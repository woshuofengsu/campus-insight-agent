# -*- coding: utf-8 -*-
"""已知边界⑥收口：自由文本 PII 脱敏（手机号 / 身份证）。

两层测试：
1. 纯函数层：`utils/pii.scrub_text` 的边界（误伤与漏检都要挡住）；
2. 落库层：居民手写在工单/提案/健康咨询正文里的号码，**入库时就必须是打码的**，
   同时结构化手机号列的加密链路不受影响（两条路不能互相顶掉）。

隔离说明：每个用例在临时库上跑，teardown 恢复 `db_core._DB_PATH`（同
`tests/test_issue_phone_encryption.py` 的写法，避免污染同进程其他测试）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402
from utils.pii import mask_phone, scrub_text  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    """整个模块共用一个临时库（每个用例建库会让本文件跑 30 秒以上，拖慢全量门禁）。"""
    _orig = db_core._DB_PATH
    _tmp = tempfile.mkdtemp(prefix="pii_scrub_")
    _path = os.path.join(_tmp, "pii_scrub.db")
    db_core._DB_PATH = ""
    if os.path.exists(_path):
        os.unlink(_path)
    db_core.init_db(_path)
    yield
    db_core._DB_PATH = _orig


# ---------------- 1. 纯函数层 ----------------

def test_phone_masked_in_sentence():
    out, hits = scrub_text("我电话 13800138000，随时可以联系")
    assert hits == 1
    assert "13800138000" not in out
    assert "138****8000" in out


def test_multiple_phones_counted():
    out, hits = scrub_text("我的 13800138000，我儿子的 13900139000")
    assert hits == 2
    assert "13800138000" not in out and "13900139000" not in out


def test_id_card_masked():
    out, hits = scrub_text("身份证 110113200604194512 已上传")
    assert hits == 1
    assert "110113200604194512" not in out
    assert "110113********4512" in out


def test_phone_and_id_together():
    out, hits = scrub_text("电话13800138000 身份证110113200604194512")
    assert hits == 2
    assert "138****8000" in out and "110113********4512" in out


def test_already_masked_not_touched():
    out, hits = scrub_text("已有脱敏号 138****8000")
    assert hits == 0
    assert out == "已有脱敏号 138****8000"


def test_non_phone_11_digits_untouched():
    # 订单号/工单号这类长数字不是手机号，不能被误伤
    out, hits = scrub_text("订单号 20000000000 已生成")
    assert hits == 0
    assert "20000000000" in out


def test_short_number_untouched():
    out, hits = scrub_text("门牌号 12345，电话 88886666")
    assert hits == 0
    assert out == "门牌号 12345，电话 88886666"


def test_phone_inside_longer_digits_untouched():
    # 20 位数字里嵌着 11 位手机号形态：不算手机号，避免把长串切掉一段
    out, hits = scrub_text("流水号 13800138000123456789")
    assert hits == 0
    assert out == "流水号 13800138000123456789"


def test_empty_and_non_str():
    assert scrub_text("") == ("", 0)
    assert scrub_text(None) == (None, 0)
    assert scrub_text(12345) == (12345, 0)


def test_mask_phone_format_matches_project():
    # 与 data/db_repair._mask_phone 同格式（项目里两处口径必须一致）
    from data.db_repair import _mask_phone
    assert mask_phone("13800138000") == _mask_phone("13800138000") == "138****8000"


# ---------------- 2. 落库层 ----------------

def test_issue_description_scrubbed_on_write():
    from data.db_core import get_db
    from data.db_repair import submit_issue

    iid, _ = submit_issue(
        title="家里漏水，我电话13800138000", category="室内", issue_type="室内",
        location="3号楼", description="水管漏水，联系我 13900139000",
        urgency="一般", reporter_name="张三", reporter_phone="13800001111",
        reporter_id=1,
    )
    with get_db() as conn:
        row = conn.execute(
            "SELECT title, description, reporter_phone, reporter_phone_enc "
            "FROM community_issues WHERE id=?", (iid,)).fetchone()
    assert "13800138000" not in row["title"]
    assert "13900139000" not in row["description"]
    assert "138****8000" in row["title"]
    assert "139****9000" in row["description"]
    # 结构化手机号列仍走加密链路：明文列留空、密文列可解回原文
    assert row["reporter_phone"] == ""
    assert row["reporter_phone_enc"]
    from data.db_repair import _dec_phone
    assert _dec_phone(row["reporter_phone_enc"]) == "13800001111"


def test_proposal_and_consult_scrubbed_on_write():
    from data.db_core import get_db
    from data.db_health_content import submit_consult
    from data.db_proposal import submit_proposal

    pid, _msg = submit_proposal(title="加装充电桩（我电话13800138000）",
                                description="欢迎联系 13900139000 讨论",
                                category="公共设施", reporter_name="李四",
                                reporter_phone="13700002222", is_public=1, reporter_id=2)
    assert pid > 0, f"提案创建失败：{_msg}"

    cid, status, _code = submit_consult(
        user_id=2, name="王五", phone="13700007777", consult_type="健康知识",
        content="最近血压有点高，想问问日常要注意什么，我的电话 13600136000")
    assert cid > 0, f"健康咨询创建失败：{status}"

    with get_db() as conn:
        p = conn.execute("SELECT title, description FROM proposals WHERE id=?",
                         (pid,)).fetchone()
        c = conn.execute("SELECT content FROM health_consults WHERE id=?",
                         (cid,)).fetchone()
    assert p is not None and c is not None
    assert "13800138000" not in p["title"] and "13900139000" not in p["description"]
    assert "13600136000" not in c["content"]
    assert "136****6000" in c["content"]
