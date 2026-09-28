# -*- coding: utf-8 -*-
"""「上次没提交的草稿」——续接与只给自己看（卡8 收尾 / §6-I10）。

**背景**：为了不让旧草稿顶替新报修，回填只认同一场对话；但草稿**不能因此消失**：
老人上次没提交完就走了，回来时要能看到并能续上。这里守住两件事：
  ① 显式续接：用户说「继续上次」才续（**系统不替他猜**哪条草稿该复活）；
  ② 草稿只给本人看：接口按服务端身份的 uid 查，别人查不到（草稿里是居民原话，可能含电话住址）。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

UID = 99901
OTHER = 99902
A = "海淀小区"


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="resume_"), "r.db"))
    with db_core.get_db() as conn:
        for uid in (UID, OTHER):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, 'resident', ?, 1, ?)", (uid, f"u{uid}", f"n{uid}", A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _req(uid=UID):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": "resident", "name": "测试", "community": A,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _ok(res):
    if isinstance(res, dict):
        return res
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8"))


# ---------------------------------------------------------------- 只给自己看

def test_drafts_endpoint_only_returns_mine(fresh_db):
    """草稿接口只回自己的（草稿里有居民原话，绝不能让别人查到）。"""
    from api_routes.agent import agent_drafts
    from data.db_draft import save_draft
    save_draft(UID, "work_order_draft", {"desc": "我家阳台漏水了", "type": "室内"},
               step="ask_type", source_session="s1", source_text="我家阳台漏水了")
    save_draft(OTHER, "work_order_draft", {"desc": "别人家的卫生间堵了", "type": "室内"},
               step="ask_type", source_session="s2", source_text="别人家的卫生间堵了")
    mine = _ok(agent_drafts(_req(UID)))["data"]
    assert len(mine) == 1 and "我家阳台漏水了" in mine[0]["summary"]
    assert all("别人家" not in d["summary"] for d in mine), "不能看到别人的草稿"


def test_drafts_endpoint_needs_login(fresh_db):
    from api_routes.agent import agent_drafts
    req = SimpleNamespace(state=SimpleNamespace(user={}), query_params={},
                          client=SimpleNamespace(host="127.0.0.1"))
    assert _ok(agent_drafts(req))["success"] is False


def test_drafts_endpoint_does_not_leak_raw_fields(fresh_db):
    """只回"是什么"，不回原始字段明细（减少暴露面）。"""
    from api_routes.agent import agent_drafts
    from data.db_draft import save_draft
    save_draft(UID, "work_order_draft",
               {"desc": "我家水管漏水", "type": "室内", "phone": "13800001234"},
               step="ask_type", source_session="s", source_text="我家水管漏水")
    row = _ok(agent_drafts(_req(UID)))["data"][0]
    assert "phone" not in row and "content" not in row
    assert set(row) <= {"draft_type", "summary", "step", "updated_at"}


# ---------------------------------------------------------------- 续接

def test_resume_restores_draft_from_another_session(fresh_db):
    """**核心**：上一场对话留下的草稿，用户说「继续上次」→ 能续上并进入确认步骤。"""
    from agent.orchestrator import Orchestrator
    from data.db_draft import save_draft

    save_draft(UID, "work_order_draft",
               {"desc": "我家阳台水管漏水了", "type": "室内", "urgency": "一般"},
               step="confirm", source_session="上一场对话", source_text="我家阳台水管漏水了")
    o = Orchestrator()
    out = o.run("resident", UID, "测试", "继续上次")
    assert out["status"] == "需确认", out
    assert "阳台水管" in out["reply"]
    draft = o.bb.read(f"user:{UID}:work_order_draft")
    assert draft and "阳台水管" in str(draft.get("desc"))


def test_resume_says_so_when_nothing_to_resume(fresh_db):
    """没有草稿就如实说没有，而不是编一条出来。"""
    from agent.orchestrator import Orchestrator
    out = Orchestrator().run("resident", UID, "测试", "继续上次")
    assert "没有" in out["reply"] and out["status"] != "成功"


def test_resume_reassigns_session_so_it_survives_next_turn(fresh_db):
    """续接后要把草稿归属改到**当前会话**，否则下一轮又被判成"别的对话的草稿"。"""
    from agent.orchestrator import Orchestrator
    from data.db_draft import load_draft, save_draft

    save_draft(UID, "work_order_draft", {"desc": "楼道灯坏了", "type": "室外"},
               step="confirm", source_session="旧会话", source_text="楼道灯坏了")
    o = Orchestrator()
    o.run("resident", UID, "测试", "继续上次")
    assert load_draft(UID, "work_order_draft")["source_session"] == o.bb.session_id
    # 再开一个新编排器（模拟重启/换会话）时也能回填，因为归属已是当前会话
    o2 = Orchestrator(session_id=o.bb.session_id)
    o2.run("resident", UID, "测试", "??")
    assert (o2.bb.read(f"user:{UID}:work_order_draft") or {}).get("desc") == "楼道灯坏了"


def test_resume_does_not_fire_on_normal_message(fresh_db):
    """正常说话不该触发续接（只有明确说「继续上次」才续）。"""
    from agent.orchestrator import Orchestrator
    from data.db_draft import save_draft
    save_draft(UID, "work_order_draft", {"desc": "旧的水管问题", "type": "室内"},
               step="confirm", source_session="旧会话", source_text="旧的水管问题")
    o = Orchestrator()
    out = o.run("resident", UID, "测试", "今天天气怎么样")
    assert "旧的水管问题" not in out["reply"], "正常提问不该把旧草稿翻出来"
