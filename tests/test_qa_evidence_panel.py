# -*- coding: utf-8 -*-
"""证据面板门禁（外部评审第十一轮建议："每个回答显示来源、社区、时间、是否自动回答"）。

**为什么要这条门禁**：前端 `resident/QA.vue` 早就写了 `data-evidence-card` 那块 UI 与样式，
但接口**从来没有返回 `knowledge` 字段** —— 于是那块面板永远不显示（本项目典型的
"前后端字段没对齐"：代码在、看着像做了、实际是死的，页面审计也抓不到，因为不报错）。

本文件守住三件事：
  ① `/qa/ask` 命中时**必须**回 `knowledge`（标题/来源/版本/生效期/适用地区/原文/检索姿态）；
  ② 这些字段必须来自**数据库真行**（不是模型复述）—— 逐字段与库里的那条比对；
  ③ 未命中/弱证据/敏感时，必须回"为什么没自动回答"（reason + 说明），前端才有得显示。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
UID = 99501


@pytest.fixture()
def fresh_db():
    import tempfile
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="evidence_")
    path = os.path.join(tmp, "e.db")
    db_core._DB_PATH = ""
    db_core.init_db(path)
    with db_core.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community, "
            "phone_enc) VALUES (?, 'demo_x', 'resident', '王阿姨', 1, ?, '')", (UID, A))
        # 造一条"已发布且生效中"的知识，字段写全，便于逐字段比对
        conn.execute(
            "INSERT INTO knowledge_base (category, title, content, keywords, audit_status, source, "
            "effective_date, expire_date, version, publisher, policy_number, applicable_area, "
            "plain_interpretation, attachment) VALUES (?,?,?,?, '已发布', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("社区规定", "测试用楼道堆物规定", "楼道不得堆放杂物。", "楼道,堆物,杂物",
             "北京市人民政府", "2026-01-01", "2027-12-31", 3, "北京市人民政府",
             "京政发〔2026〕1 号", "北京市", "楼道里不能堆放杂物，影响消防通道。",
             "https://example.com/policy.pdf"))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield path
    db_core._DB_PATH = orig
    clear_cache()


def _req(community=A, uid=UID):
    return SimpleNamespace(
        state=SimpleNamespace(user={"uid": uid, "role": "resident", "name": "王阿姨",
                                     "community": community}),
        query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _ask(question, community=A):
    from api_routes.policy import AskQuestion, web_qa_ask
    res = web_qa_ask(AskQuestion(question=question), _req(community))
    body = res if isinstance(res, dict) else __import__("json").loads(bytes(res.body).decode())
    return body.get("data") or {}


def test_hit_returns_evidence_fields_from_database(fresh_db):
    """命中时 `/qa/ask` 必须回 `knowledge`，且逐字段等于库里那条（不是模型复述）。"""
    d = _ask("楼道里能不能堆东西")
    assert d.get("matched") is True, d
    k = d.get("knowledge")
    assert k, "接口没有返回 knowledge —— 前端那块证据面板是死的（历史真实故障）"
    row = None
    with db_core.get_db() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_base WHERE audit_status='已发布' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row, "前置失败：库里没有已发布条目"
    assert k["id"] == row["id"]
    assert k["title"] == row["title"], "标题必须来自数据库真行"
    assert k["version"] == (row["version"] or 1)
    assert k["source"] == (row["source"] or "")
    assert k["publisher"] == (row["publisher"] or "")
    assert k["policy_number"] == (row["policy_number"] or "")
    assert k["effective_date"] == (row["effective_date"] or "")
    assert k["expire_date"] == (row["expire_date"] or "")
    assert k["applicable_area"] == (row["applicable_area"] or "")
    assert k["attachment"] == (row["attachment"] or "")
    assert k["retrieval"] in ("lexical", "hybrid", ""), k


def test_hit_explains_why_it_could_answer(fresh_db):
    """还要给出"凭什么答这一条"：匹配度 + 属地级别 + 适用地区。"""
    d = _ask("楼道里能不能堆东西")
    assert d.get("score") is not None, "没有匹配度，前端没法显示判定过程"
    assert d.get("region_level"), "没有属地级别（national/city/district/community/other）"
    assert d.get("applicable_area"), "没有适用地区"
    assert d.get("region_label"), "没有说明'按哪个社区优先'"


def test_miss_explains_why_not_answered(fresh_db):
    """没有依据/弱证据时，要回"为什么没自动回答"，前端才显示得出来。"""
    d = _ask("我想申请个专利，流程怎么走")
    assert d.get("matched") is False
    assert d.get("reason"), d
    assert d.get("manual_text"), d
    assert "knowledge" not in d or not d["knowledge"], "没回答却给了依据，会误导"


def test_sensitive_goes_to_human_with_reason(fresh_db):
    """敏感/医疗/法律必须转人工，并给理由（reason=manual）。"""
    d = _ask("我头疼该吃什么药")
    assert d.get("matched") is False and d.get("reason") == "manual", d


def test_evidence_card_is_not_dead_ui():
    """**门禁自检**：前端确实在等 `result.knowledge`，接口确实给了 —— 两边对齐。

    这条防的是"以后有人把 knowledge 从接口里删掉/改名"，那会重演"面板静默消失"。
    """
    import io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vue = io.open(os.path.join(root, "web", "src", "views", "resident", "QA.vue"),
                  encoding="utf-8").read()
    assert "result.knowledge" in vue and "data-evidence-card" in vue, \
        "前端证据面板没了？那这条门禁要跟着改（别让它变成空跑）"
    py = io.open(os.path.join(root, "api_routes", "policy.py"), encoding="utf-8").read()
    assert '"knowledge": {' in py, "接口又没返回 knowledge 了 —— 证据面板会静默消失"
