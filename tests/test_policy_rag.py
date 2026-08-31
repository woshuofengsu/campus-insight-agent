# -*- coding: utf-8 -*-
"""WS3：政策真 RAG 测试。全部离线（monkeypatch policy_rag.generate），保证 457 基线行为不破坏。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

_tmp = tempfile.mkdtemp(prefix="polrag_")
config.DB_PATH = os.path.join(_tmp, "pol.db")

import pytest  # noqa: E402

from data.db_core import init_db  # noqa: E402
init_db(config.DB_PATH)


@pytest.fixture(autouse=True)
def _restore_threshold():
    """测试内 set_match_threshold(999) 会影响模块级全局，测试后还原，避免污染其它用例。"""
    import data.db_policy as dp
    old = dp._match_threshold
    yield
    dp._match_threshold = old


def _seed_knowledge(title, interp, version=1):
    from data.db_core import get_db
    from data.db_policy import set_match_threshold
    # 阈值拉高，确保任意匹配都落入「弱命中→RAG」分支（可确定测试 RAG 分支）
    set_match_threshold(999.0, actor="test")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO knowledge_base (title, summary, content, plain_interpretation, version, "
            "category, audit_status, keywords, policy_number) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (title, "", "", interp, version, "社会保障", "已发布",
             f"{title} 社区", "鲁政字〔2020〕66号"))
        conn.commit()
        return conn.execute("SELECT id FROM knowledge_base WHERE title=?", (title,)).fetchone()["id"]


def _ask(question):
    from data.db_policy import ask_question
    return ask_question(99991, question, source="测试")


def test_rag_off_keeps_low_score(monkeypatch):
    """开关关：弱命中仍走 low_score（回归，行为不变），RAG 不生效。"""
    monkeypatch.setattr("config.POLICY_LLM_RAG", False)
    monkeypatch.setattr("agent.policy_rag.POLICY_LLM_RAG", False)
    tid = _seed_knowledge("社区社保申领流程", "本社区申领方式与材料清单。")
    s = _ask("我的社保交的材料清单")
    assert s.get("matched") is False and s.get("reason") == "low_score", s
    from data.db_core import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM knowledge_base WHERE id=?", (tid,))
        conn.commit()


def test_rag_generates_and_records(monkeypatch):
    """开关开 + generate 返回合规答案：落库为已自动回答、auto_answer 含引用、cite_count+1。"""
    monkeypatch.setattr("config.POLICY_LLM_RAG", True)
    monkeypatch.setattr("agent.policy_rag.POLICY_LLM_RAG", True)
    import agent.policy_rag as pr
    monkeypatch.setattr("agent.policy_rag.generate", lambda q, results: {
        "answer": "需要您携带身份证与户口本前往社区服务站办理。",
        "cited_index": 1,
        "cited_title": results[0]["title"],
        "tokens_in": 120, "tokens_out": 40})
    tid = _seed_knowledge("社区社保申领事项", "材料清单及办理地点。")
    s = _ask("社保咋办呀")
    assert s.get("matched"), s
    assert s.get("rag") is True
    assert "参考：社区社保申领事项" in s["auto_answer"]  # 引用标题被受控拼装
    from data.db_core import get_db
    with get_db() as conn:
        row = conn.execute("SELECT status, auto_answer FROM policy_questions WHERE id=?",
                           (s["question_id"],)).fetchone()
        assert row["status"] == "已自动回答"
        assert "参考：" in row["auto_answer"]
        kb = conn.execute("SELECT cite_count FROM knowledge_base WHERE id=?", (tid,)).fetchone()
        assert kb["cite_count"] >= 1
        conn.execute("DELETE FROM policy_questions WHERE id=?", (s["question_id"],))
        conn.execute("DELETE FROM knowledge_base WHERE id=?", (tid,))
        conn.commit()


def test_rag_insufficient_falls_back(monkeypatch):
    """生成指出材料不足（INSUFFICIENT）→ 回退 low_score。"""
    monkeypatch.setattr("config.POLICY_LLM_RAG", True)
    monkeypatch.setattr("agent.policy_rag.POLICY_LLM_RAG", True)
    monkeypatch.setattr("agent.policy_rag.generate", lambda q, results: None)
    tid = _seed_knowledge("社区低保申请", "低收入家庭可申请。")
    s = _ask("低保材料清单")
    assert s.get("matched") is False and s.get("reason") == "low_score"
    from data.db_core import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM knowledge_base WHERE id=?", (tid,))
        conn.commit()


def test_rag_cited_index_out_of_range_rejected(monkeypatch):
    """真实 generate 校验：cited_index 越界（伪造引用）→ 返回 None（弃用）。"""
    monkeypatch.setattr("config.POLICY_LLM_RAG", True)
    monkeypatch.setattr("agent.policy_rag.POLICY_LLM_RAG", True)
    results = [{"title": "A", "plain_interpretation": "a", "version": 1}]
    # 造一个真实 chat 返回越界 index
    import agent.policy_rag as pr
    def _chat(*a, **k):
        return {"ok": True, "text": '{"answer":"xxx", "cited_index": 99}', "tokens_in": 1, "tokens_out": 1}
    monkeypatch.setattr("agent.llm_client.chat", _chat)
    out = pr.generate("q", results)
    assert out is None


def test_rag_cited_index_valid(monkeypatch):
    """合法 cited_index → 返回结构化结果。"""
    monkeypatch.setattr("config.POLICY_LLM_RAG", True)
    monkeypatch.setattr("agent.policy_rag.POLICY_LLM_RAG", True)
    import agent.policy_rag as pr
    results = [{"title": "A", "plain_interpretation": "a", "version": 1},
               {"title": "B", "plain_interpretation": "b", "version": 2}]
    def _chat(*a, **k):
        return {"ok": True, "text": '{"answer":"应当带身份证", "cited_index": 2}', "tokens_in": 1, "tokens_out": 1}
    monkeypatch.setattr("agent.llm_client.chat", _chat)
    out = pr.generate("q", results)
    assert out and out["cited_index"] == 2 and out["cited_title"] == "B"
