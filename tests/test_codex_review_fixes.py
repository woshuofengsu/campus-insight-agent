# -*- coding: utf-8 -*-
"""Codex 评审发现的缺陷 —— 修复回归测试（F1 / F3 / I3 / I4 / REL-04）。

来源：`docs/review/Codex-项目评审与规划.md`（Codex 通读项目后给出的评审报告）。
本文件只覆盖**本轮已修**的几条，每条都先复现问题再断言修复后的行为，
避免"改了但没测"和"以后又被改回去"。

隔离写法同 `tests/test_tenant_isolation.py`（临时库 + teardown 还原 + 清租户缓存）。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
GRID_A = 96511
GRID_B = 96512
RES_A = 96501
ELDER_A = 96521      # A 社区老人
ELDER_B = 96522      # B 社区老人


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="codex_review_")
    path = os.path.join(tmp, "cr.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, com in ((GRID_A, "grid", "A网格", A), (GRID_B, "grid", "B网格", B),
                                     (RES_A, "resident", "A居民", A),
                                     (ELDER_A, "elderly", "A老人", A),
                                     (ELDER_B, "elderly", "B老人", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


def _req(uid, role, community):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"{community}{role}", "community": community,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


# ---------------- F1：老人名单 / 健康记录必须按社区 ----------------

def test_manage_elders_lists_only_own_community():
    """原实现只筛 role/is_active → A 社区网格员能列出**全平台**老人（含姓名与社区）。"""
    from api_routes.elderly import web_manage_elders
    res = web_manage_elders(_req(GRID_A, "grid", A))
    assert res.get("success"), res
    names = [r["name"] for r in res["data"]]
    ids = [r["id"] for r in res["data"]]
    assert "A老人" in names and ELDER_A in ids
    assert "B老人" not in names, "A 社区网格员不该看到 B 社区老人（Codex 评审 F1）"
    assert ELDER_B not in ids


def test_manage_elders_empty_tenant_returns_nothing():
    """身份解析不出社区（库里也没社区）→ 空列表（fail-closed），不许回落成"列全部"。"""
    from api_routes.elderly import web_manage_elders
    ghost = 96599
    with db_core.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                     "VALUES (?, ?, 'grid', '无社区网格', 1, '')", (ghost, f"u{ghost}"))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    res = web_manage_elders(_req(ghost, "grid", ""))
    assert res.get("success") and res["data"] == []


def test_manage_vitals_denies_cross_community():
    """原实现只校验 grid 角色 + 传入 uid → 可读别的社区老人的健康记录。"""
    from api_routes.elderly import web_manage_vitals
    from data.db_vitals import add_vital
    add_vital(ELDER_B, "血压", sys_=150, dia=95, note="测试")

    ok = web_manage_vitals(_req(GRID_A, "grid", A), uid=ELDER_A, limit=5)
    assert ok.get("success"), "本社区老人应可读"
    bad = web_manage_vitals(_req(GRID_A, "grid", A), uid=ELDER_B, limit=5)
    # 失败走 `_fail` → JSONResponse，不是 dict
    assert not isinstance(bad, dict), "跨社区健康记录必须被拒（Codex 评审 F1）"
    import json as _json
    assert _json.loads(bytes(bad.body).decode("utf-8"))["success"] is False


# ---------------- F3：转人工失败不许说"已转接" ----------------

def _transfer(orchestrator, ctx, result, reason):
    """调用真实签名：`_transfer_to_human(self, ctx, result, reason)`。"""
    return type(orchestrator)._transfer_to_human(orchestrator, ctx, result, reason)


def test_handoff_failure_does_not_claim_transfer(monkeypatch):
    """建包失败时原来照样回复"已为您转接工作人员"——一个失败案例就能推翻"有人工兜底"。"""
    import data.db_agent as dba
    from agent.orchestrator import Orchestrator

    def boom(*_a, **_k):
        raise RuntimeError("模拟建包失败")

    monkeypatch.setattr(dba, "create_handoff", boom)
    o = Orchestrator(session_id="test-handoff-fail")      # 真编排器（含 agents/黑板）
    result = {"reply": "我先帮您看看。", "intent": "其他", "status": "转人工"}
    out = _transfer(o, {"uid": RES_A, "name": "A居民", "role": "resident",
                        "user_input": "我要找人处理"}, result, "需要人工")
    assert "已为您转接" not in out["reply"], "建包失败时不能说已转接（Codex 评审 F3）"
    assert out["status"] != "transferred_to_human"
    assert out["handoff_id"] is None
    assert ("没转接成功" in out["reply"]) or ("没有" in out["reply"])


def test_handoff_success_still_claims_transfer(monkeypatch):
    """成功分支的措辞不能被误改（这是现场演示要展示的能力）。"""
    import data.db_agent as dba
    from agent.orchestrator import Orchestrator

    monkeypatch.setattr(dba, "create_handoff", lambda *a, **k: 4242)
    o = Orchestrator(session_id="test-handoff-ok")
    result = {"reply": "我先帮您看看。", "intent": "其他", "status": "转人工"}
    out = _transfer(o, {"uid": RES_A, "name": "A居民", "role": "resident",
                        "user_input": "我要找人处理"}, result, "需要人工")
    assert "已为您转接工作人员" in out["reply"]
    assert out["status"] == "transferred_to_human"
    assert out["handoff_id"] == 4242


# ---------------- I3：没建草稿就不要说"已生成草稿" ----------------

def test_notification_agent_does_not_claim_draft_created():
    """`process_negotiation` 只返回建议文本，没有真的创建通知草稿对象。"""
    from agent.roles.business_agents import NotificationManagerAgent
    a = NotificationManagerAgent.__new__(NotificationManagerAgent)
    for ev, kw in (("extreme_weather", {}), ("safety_hazard", {"hazard": "燃气泄漏"})):
        out = a.process_negotiation({"payload": {"event": ev, **kw}})
        assert out, f"{ev} 应返回内容"
        assert "已生成" not in out["reply"], f"{ev}：没建草稿就不能说已生成（Codex 评审 I3）"
        assert "建议生成" in out["reply"]


# ---------------- I4：网格助手查人工待办必须带租户 ----------------

def test_grid_assistant_handoff_query_passes_tenant(monkeypatch):
    """我上一轮把 list_handoffs 改成 fail-closed（不传 tenant 抛错），
    网格助手这条调用漏了参数 → 用户只会看到"服务暂不可用"（Codex 评审 I4）。"""
    import data.db_agent as dba
    from agent.roles import auto_agents as aa

    seen: list = []

    def fake_list_handoffs(status="", limit=50, tenant=None):
        seen.append(tenant)
        return []

    monkeypatch.setattr(dba, "list_handoffs", fake_list_handoffs)
    agent = aa.GridAssistantAgent.__new__(aa.GridAssistantAgent)
    agent._reply = lambda *a, **k: {"reply": a[0] if a else "", "status": "成功"}
    agent.process({"user_input": "有哪些人工待办处理包？", "uid": GRID_A, "name": "A网格", "state": {}})
    assert seen and all(t == A for t in seen), \
        f"网格助手查询人工待办必须传**本社区**租户，实际 {seen}"


# ---------------- REL-04：PIPL 导出必须按各表正确的用户列 ----------------

def test_export_uses_reporter_id_for_issues_and_proposals():
    """community_issues / proposals 的归属列是 reporter_id；按 user_id 查会报错并被静默吞掉，
    导致导出里少了居民自己的工单与提案。"""
    from api_routes.auth import me_export
    from data.db_repair import submit_issue
    from data.db_proposal import submit_proposal
    import json as _json

    submit_issue(title="导出用例工单", category="公共设施", issue_type="室内", location="1号楼",
                 description="描述内容足够长", urgency="一般", reporter_name="A居民",
                 reporter_phone="13800002001", reporter_id=RES_A)
    submit_proposal(title="导出用例提案", description="这是一段足够长的提案描述内容",
                    category="公共设施", reporter_name="A居民",
                    reporter_phone="13800002002", is_public=1, reporter_id=RES_A)

    resp = me_export(_req(RES_A, "resident", A))
    body = _json.loads(bytes(resp.body).decode("utf-8"))
    assert "export_incomplete" not in body, f"导出不应有失败表：{body.get('export_incomplete')}"
    assert any("导出用例工单" in (r.get("title") or "") for r in body["community_issues"]), \
        "居民的工单必须出现在自己的导出里"
    assert any("导出用例提案" in (r.get("title") or "") for r in body["proposals"]), \
        "居民的提案必须出现在自己的导出里"
