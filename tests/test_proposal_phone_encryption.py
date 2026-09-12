# -*- coding: utf-8 -*-
"""提案/草稿手机号加密落库（第七轮复审 P2-A 回归）。

背景：v36 加密迁移给工单/用户/联系人/咨询/紧急呼叫都加了 `*_enc`，**唯独漏了 proposals 与两张草稿表**
（生产库实测：proposals 明文 181 条）。展示层脱敏挡不住「库被拷走」，且直接违反项目硬约定。
本文件把三件事钉死：
  1. 写路径：明文列必须写空串、真号只进 `*_enc`（g1$ 前缀 = AES-256-GCM）
  2. 读路径：解密回原值（展示层再脱敏），兼容未迁移的历史明文
  3. 迁移：存量明文回填加密 + 清空明文，且**幂等**（重复跑不重复加密、不丢数据）
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.db_core import get_db, init_db

PHONE = "13800138000"


def _fresh_db(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), f"_test_proposal_enc_{name}.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass
    init_db(path)
    return path


def _cleanup(path: str):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


def _submit(phone=PHONE):
    from data.db_proposal import submit_proposal
    pid, msg = submit_proposal(
        title="加装电梯", description="老楼上下楼不方便，建议加装电梯方便老人出行",
        category="公共设施", reporter_name="王阿姨", reporter_phone=phone, is_public=1,
    )
    assert msg == "ok", msg
    return pid


def test_proposal_phone_encrypted_on_write_and_read():
    """提交提案：明文列空、密文列 g1$、读回来仍是原号。"""
    path = _fresh_db("rw")
    try:
        pid = _submit()
        with get_db() as conn:
            row = conn.execute(
                "SELECT reporter_phone, reporter_phone_enc FROM proposals WHERE id=?", (pid,)
            ).fetchone()
        assert row["reporter_phone"] == "", "明文列必须写空串（P2-A）"
        assert row["reporter_phone_enc"].startswith("g1$"), \
            f"密文列应是 AES-256-GCM（g1$ 前缀），实际 {row['reporter_phone_enc'][:6]!r}"

        from data.db_proposal import get_proposal, view_full_phone
        p = get_proposal(pid)
        assert p["reporter_phone"] == PHONE, "读取路径必须解密回明文（供展示层脱敏）"
        assert view_full_phone(pid, actor="测试") == PHONE, "查看完整号码也要能解密"
    finally:
        _cleanup(path)


def test_proposal_phone_plaintext_count_is_zero():
    """全库断言：proposals 明文手机号计数为 0（答辩可现场自证）。"""
    path = _fresh_db("count")
    try:
        for i in range(3):
            _submit(phone=f"1380013800{i}")
        with get_db() as conn:
            n = conn.execute(
                "SELECT COUNT(*) c FROM proposals WHERE length(COALESCE(reporter_phone,''))>0"
            ).fetchone()["c"]
            enc = conn.execute(
                "SELECT COUNT(*) c FROM proposals WHERE length(COALESCE(reporter_phone_enc,''))>0"
            ).fetchone()["c"]
        assert n == 0, f"明文手机号仍有 {n} 条"
        assert enc == 3, "三条提案都应写入密文"
    finally:
        _cleanup(path)


def test_drafts_phone_encrypted():
    """两张草稿表同样加密（同类缺口，v46 一并收口）。"""
    path = _fresh_db("drafts")
    try:
        from data.db_proposal import get_draft, get_drafts, save_draft
        from data.db_repair import create_draft, get_draft as get_issue_draft

        did = save_draft(1, title="草稿", description="x" * 12, reporter_name="李叔",
                         reporter_phone=PHONE)
        with get_db() as conn:
            r = conn.execute("SELECT reporter_phone, reporter_phone_enc FROM proposal_drafts "
                             "WHERE id=?", (did,)).fetchone()
        assert r["reporter_phone"] == "" and r["reporter_phone_enc"].startswith("g1$")
        assert get_draft(did, 1)["reporter_phone"] == PHONE
        assert get_drafts(1)[0]["reporter_phone"] == PHONE

        iid = create_draft(1, "灯坏了", "公共设施", "室内", "客厅", "灯不亮", "一般",
                           reporter_name="李叔", reporter_phone=PHONE)
        with get_db() as conn:
            r2 = conn.execute("SELECT reporter_phone, reporter_phone_enc FROM issue_drafts "
                              "WHERE id=?", (iid,)).fetchone()
        assert r2["reporter_phone"] == "" and r2["reporter_phone_enc"].startswith("g1$")
        assert get_issue_draft(iid)["reporter_phone"] == PHONE
    finally:
        _cleanup(path)


def test_m46_migration_backfills_and_is_idempotent():
    """迁移回归：手工造「明文存量」→ 跑 v46 → 回填加密 + 清空明文，且重复跑不损坏。

    模拟的是生产库真实情形（v36 之前写入的 181 条明文，schema_version 已到 45）。
    """
    path = _fresh_db("migrate")
    try:
        with get_db() as conn:
            # 直接退回 v45，并插入两条明文（绕过写路径，模拟历史脏数据）
            conn.execute("UPDATE schema_version SET version=45 WHERE version=46")
            conn.execute(
                "INSERT INTO proposals (title, description, category, author, reporter_name, "
                "reporter_phone) VALUES ('旧提案','这是一条历史明文提案','其他','王阿姨','王阿姨',?)",
                (PHONE,))
            conn.execute(
                "INSERT INTO user_profile (username, role, name, phone, phone_enc) "
                "VALUES ('legacy_user','resident','老用户',?, '')", (PHONE,))
            conn.commit()

        init_db(path)                       # 重跑迁移链 → 执行 v46

        with get_db() as conn:
            p = conn.execute("SELECT reporter_phone, reporter_phone_enc FROM proposals "
                             "WHERE title='旧提案'").fetchone()
            u = conn.execute("SELECT phone, phone_enc FROM user_profile "
                             "WHERE username='legacy_user'").fetchone()
            ver = conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"]
        assert ver == 46, f"schema 版本应升到 46，实际 {ver}"
        assert p["reporter_phone"] == "", "存量明文应被清空"
        assert p["reporter_phone_enc"].startswith("g1$"), "存量明文应回填为密文"

        from utils.crypto import get_crypto
        assert get_crypto().decrypt(p["reporter_phone_enc"]) == PHONE, "回填后必须能解密回原号"
        assert u["phone"] == "" and u["phone_enc"].startswith("g1$"), "user_profile 残留明文也要收口"

        # 幂等：再跑一次不报错、数据不变
        before = p["reporter_phone_enc"]
        init_db(path)
        with get_db() as conn:
            after = conn.execute("SELECT reporter_phone_enc e FROM proposals "
                                 "WHERE title='旧提案'").fetchone()["e"]
        assert after == before, "重复迁移不应改写已有密文"
    finally:
        _cleanup(path)


def test_no_phone_gap_on_fresh_db():
    """全新建库后不允许存在「无加密列的手机号表」（用体检脚本同口径断言）。"""
    path = _fresh_db("scan")
    try:
        from scripts.audit_phone_encryption import scan_gaps
        gaps, lines = scan_gaps(path)
        assert lines, "体检脚本没扫到任何含 phone 的表，口径可能失效"
        assert not gaps, f"全新建库仍有加密缺口：{gaps}"
    finally:
        _cleanup(path)


def test_phone_columns_are_validated():
    """非法手机号仍被拒绝（加密改造不放松校验）。"""
    from data.db_proposal import submit_proposal
    path = _fresh_db("validate")
    try:
        pid, msg = submit_proposal(title="测试", description="这是一个长度足够的测试描述",
                                   category="其他", reporter_name="张三",
                                   reporter_phone="12345", is_public=1)
        assert pid == 0 and "手机号" in msg, f"非法号应被拒，实际 {pid}/{msg}"
    finally:
        _cleanup(path)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
