# -*- coding: utf-8 -*-
"""人工处理包工作台（卡11 / v3 卡7）：**从"能看到包"到"能办完"**。

**背景**：原来 `agent_handoffs` 只有「待处理 → 已处理」一步，网格端看得到包却办不了事 ——
谁领的、向居民补问了什么、回复了什么、为什么关闭，全都没有记录；
居民那边也收不到任何回音。本文件守住四件事：
  ① 领取：**只能一个人领**，别人再领要明确报出"已经被谁领了"（不能静默覆盖）；
  ② 补问 / 回复：必填文本，状态机只允许在正确状态下执行，并**真的通知到居民**；
  ③ 关闭：必须写关闭说明（居民看得到的处理结果）；
  ④ 越权：跨社区、非网格员一律拒绝。
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
RESIDENT_A = 99701
GRID_A = 99711
GRID_A2 = 99712
GRID_B = 99713


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="handoff_"), "h.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((RESIDENT_A, "resident", "A居民", A),
                                     (GRID_A, "grid", "A网格甲", A),
                                     (GRID_A2, "grid", "A网格乙", A),
                                     (GRID_B, "grid", "B网格", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _req(uid, role="grid", com=A):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"n{uid}", "community": com,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _new_handoff(reason="居民问的医保报销没答上"):
    from data.db_agent import create_handoff
    return create_handoff("sess-1", RESIDENT_A, "resident", "policy",
                          reason, {"original_input": "医保怎么报销", "reply": "需要人工"})


def _row(hid):
    with db_core.get_db() as conn:
        r = conn.execute("SELECT * FROM agent_handoffs WHERE id=?", (hid,)).fetchone()
    return dict(r) if r else {}


def _denied(res) -> bool:
    if isinstance(res, dict):
        return not res.get("success")
    import json as _json
    return not _json.loads(bytes(res.body).decode("utf-8")).get("success")


def _err(res) -> str:
    if isinstance(res, dict):
        return res.get("error") or ""
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8")).get("error") or ""


def _call(hid, action, text="", req=None):
    from api_routes.agent import HandoffAction, agent_handoff_action
    return agent_handoff_action(hid, HandoffAction(action=action, text=text),
                                req or _req(GRID_A))


def _notifs(uid):
    with db_core.get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY id", (uid,)).fetchall()]


# ---------------------------------------------------------------- 领取

def test_claim_marks_who_and_when(fresh_db):
    hid = _new_handoff()
    assert not _denied(_call(hid, "claim")), "本社区网格员应能领取"
    row = _row(hid)
    assert row["status"] == "已领取"
    assert row["assignee_id"] == GRID_A and row["assignee_name"]
    assert row["claimed_at"], "领取时间要留痕（居民/负责人都会问「谁什么时候接的」）"


def test_second_claim_is_refused_with_name(fresh_db):
    """**不许静默抢单**：别人再领要明确说"已经被谁领了"。"""
    hid = _new_handoff()
    _call(hid, "claim", req=_req(GRID_A))
    res = _call(hid, "claim", req=_req(GRID_A2))
    assert _denied(res)
    assert "领取" in _err(res) and _row(hid)["assignee_id"] == GRID_A


def test_cross_community_claim_denied(fresh_db):
    hid = _new_handoff()
    res = _call(hid, "claim", req=_req(GRID_B, com=B))
    assert _denied(res), "别的社区不能领本社区的处理包"
    assert _row(hid)["status"] == "待处理"


def test_resident_cannot_claim(fresh_db):
    hid = _new_handoff()
    res = _call(hid, "claim", req=_req(RESIDENT_A, role="resident"))
    assert _denied(res), "居民不能领处理包（这是负责人端的能力）"


# ---------------------------------------------------------------- 补问 / 回复

def test_ask_requires_claim_and_text(fresh_db):
    hid = _new_handoff()
    assert _denied(_call(hid, "ask", "请问您的医保卡号是多少")), "未领取就补问应被拒"
    _call(hid, "claim")
    assert _denied(_call(hid, "ask", "  ")), "补问内容不能为空"
    res = _call(hid, "ask", "请问您的医保卡号是多少")
    assert not _denied(res), _err(res)
    row = _row(hid)
    assert row["status"] == "等居民补充" and row["ask_back"] and row["asked_at"]


def test_ask_notifies_the_resident(fresh_db):
    """补问要**真的通知到居民**（否则居民永远不知道要补什么）。"""
    hid = _new_handoff()
    _call(hid, "claim")
    _call(hid, "ask", "请问您的医保卡号是多少")
    msgs = _notifs(RESIDENT_A)
    assert any("医保卡号" in (m.get("content") or "") for m in msgs), f"居民没收到补问：{msgs}"


def test_reply_transitions_and_notifies(fresh_db):
    hid = _new_handoff()
    _call(hid, "claim")
    res = _call(hid, "reply", "已帮您查到：带身份证和医保卡到社区服务站办理即可")
    assert not _denied(res), _err(res)
    row = _row(hid)
    assert row["status"] == "已回复" and row["replied_at"] and row["reply"]
    assert any("医保卡" in (m.get("content") or "") for m in _notifs(RESIDENT_A)), "回复要通知居民"


def test_cannot_reply_twice(fresh_db):
    """已回复过就直接关闭，不能反复回复（状态机要挡住，不能悄悄覆盖上一条回复）。"""
    hid = _new_handoff()
    _call(hid, "claim")
    _call(hid, "reply", "第一次回复：请带身份证来社区")
    res = _call(hid, "reply", "第二次回复：另一套说法")
    assert _denied(res)
    assert _row(hid)["reply"] == "第一次回复：请带身份证来社区"


def test_ask_after_claim_then_reply_from_asking(fresh_db):
    """等居民补充期间也可以直接回复（居民可能没回、但负责人已经查到答案）。"""
    hid = _new_handoff()
    _call(hid, "claim")
    _call(hid, "ask", "请补充卡号")
    res = _call(hid, "reply", "已按身份证查到，办理方式是…")
    assert not _denied(res), _err(res)
    assert _row(hid)["status"] == "已回复"


# ---------------------------------------------------------------- 关闭

def test_close_requires_note_and_finishes(fresh_db):
    hid = _new_handoff()
    _call(hid, "claim")
    assert _denied(_call(hid, "close", "")), "关闭必须写说明（居民看得到的处理结果）"
    res = _call(hid, "close", "已电话告知居民办理流程，居民确认理解。")
    assert not _denied(res), _err(res)
    row = _row(hid)
    assert row["status"] == "已处理" and row["close_note"] and row["closed_at"]


def test_close_after_finish_is_refused(fresh_db):
    hid = _new_handoff()
    _call(hid, "claim")
    _call(hid, "close", "办结")
    res = _call(hid, "close", "再关一次")
    assert _denied(res) and "关闭" in _err(res)


def test_claim_finished_package_refused(fresh_db):
    hid = _new_handoff()
    _call(hid, "claim")
    _call(hid, "close", "办结")
    assert _denied(_call(hid, "claim", req=_req(GRID_A2)))


# ---------------------------------------------------------------- 留痕与列表

def test_transitions_are_logged(fresh_db):
    """每一步都要能在活动留痕里查到（评委/负责人复算时看的就是这个）。"""
    hid = _new_handoff()
    _call(hid, "claim")
    _call(hid, "reply", "已答复")
    _call(hid, "close", "居民确认办结")
    with db_core.get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT action, actor, after_value FROM activity_log "
            "WHERE target_type='agent_handoff' AND target_id=? ORDER BY id", (hid,)).fetchall()]
    actions = [r["action"] for r in rows]
    assert "领取人工处理包" in actions and "回复居民" in actions and "办结人工处理包" in actions
    assert all(r["actor"] for r in rows), "每条留痕都要有操作人"


def test_list_shows_workbench_fields(fresh_db):
    """列表接口要带上工作台需要的字段（谁领的 / 补问 / 回复 / 关闭说明）。"""
    from api_routes.agent import agent_handoffs
    hid = _new_handoff()
    _call(hid, "claim")
    _call(hid, "ask", "请补充卡号")
    rows = agent_handoffs(_req(GRID_A))["data"]
    row = next(r for r in rows if r["id"] == hid)
    assert row["assignee_name"] and row["ask_back"] and row["original_input"]
