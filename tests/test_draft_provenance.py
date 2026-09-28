# -*- coding: utf-8 -*-
"""草稿归属与"旧草稿顶替新报修"（卡8 / v3 卡4，对应 v3 复核 §6-I10）。

**根因（实测复现过）**：`draft_contents` 每轮从库里回填黑板，而且草稿里没记
"它是哪场对话、从哪句话来的"。于是老人**上一件事还没确认完**又说了一件新事时，
状态机把新句子当成"对上一个问题的回答"，把新位置**合并进旧草稿** ——
确认卡里就出现了「上一件事的描述 + 这一件事的位置」的混合体，老人一确认就生成了一张错单。

本文件守住两条修法：
  ① 草稿记下来源（`source_session` / `source_text`），**回填只认同一场对话**；
  ② 新报修到来时**另起草稿**（旧草稿如实清理并在回复里说明），绝不合并。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

UID = 99401
A = "海淀小区"


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="draft_prov_"), "d.db"))
    with db_core.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
            "VALUES (?, 'u', 'resident', '测试', 1, ?)", (UID, A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


# ---------------------------------------------------------------- 出处

def test_draft_records_its_origin(fresh_db):
    """草稿要记下"哪场对话、从哪句话来"，并读得回来。"""
    from data.db_draft import load_draft, save_draft
    save_draft(UID, "work_order_draft", {"desc": "我家水管漏水了", "type": "室内"},
               step="ask_type", source_session="sess-A", source_text="我家水管漏水了")
    d = load_draft(UID, "work_order_draft")
    assert d["source_session"] == "sess-A"
    assert d["source_text"] == "我家水管漏水了"
    assert d["content"]["desc"] == "我家水管漏水了"


def test_restore_only_for_same_session(fresh_db):
    """**核心回归**：别的对话留下的草稿不回填到当前请示（否则它会冒充这件事）。"""
    from agent.orchestrator import Orchestrator
    from data.db_draft import load_draft, save_draft

    o = Orchestrator()
    # 库里先放一条"上一场对话"留下的草稿
    save_draft(UID, "work_order_draft", {"desc": "上次说的楼道灯", "type": "室内"},
               step="confirm", source_session="sess-OLD", source_text="上次说的楼道灯")
    o.run("resident", UID, "测试", "??算")   # 走一轮，触发会话初始化与草稿回填
    # 回填侧不该把旧会话的草稿塞进黑板
    key = f"user:{UID}:work_order_draft"
    val = o.bb.read(key)
    assert not (val and val.get("desc") == "上次说的楼道灯"), \
        "别的对话的草稿不该被回填成当前pending草稿"
    # 而它**没有被删掉**：仍然留在库里（可提示"上次有一条没提交的"）
    assert load_draft(UID, "work_order_draft") is not None


def test_same_session_draft_still_restores(fresh_db):
    """同场对话的草稿必须照旧回填（这是"重启后继续"的能力，别修反了）。"""
    from agent.orchestrator import Orchestrator
    from data.db_draft import save_draft

    o = Orchestrator()
    save_draft(UID, "work_order_draft", {"desc": "我家水管漏水了", "type": "室内"},
               step="ask_type", source_session=o.bb.session_id,
               source_text="我家水管漏水了")
    o.run("resident", UID, "测试", "??算")
    val = o.bb.read(f"user:{UID}:work_order_draft")
    assert val and val.get("desc") == "我家水管漏水了", "同一场对话的草稿必须能续上"


# ---------------------------------------------------------------- 新事不合并

def test_new_report_utterance_detection():
    """判断题：短回答 = 回答问题；带问题特征的句子 = 新的一件事。"""
    from agent.roles.business_agents import _is_new_repair_utterance
    assert not _is_new_repair_utterance("家里", "ask_type")
    assert not _is_new_repair_utterance("公共区域", "ask_type")
    assert not _is_new_repair_utterance("紧急", "ask_urgency")
    assert _is_new_repair_utterance("楼道灯坏了", "ask_type"), "带问题描述 → 新的一件事"
    assert _is_new_repair_utterance("我家水管漏水了，快来看看", "ask_urgency")


def test_new_report_replaces_stale_draft(fresh_db):
    """**核心回归**：上一件事还没确认完，又说一件新事 → 新草稿，且回复里说明旧草稿的去向。

    这条不是空转：把守卫关掉后实测得到 `desc='我家水管漏水了' + type='室外'` ——
    正是演示里那张"混合确认卡"（问题还是上一件事的，分类已经是这一件事的）。
    """
    from agent.orchestrator import Orchestrator
    from data.db_draft import load_draft

    o = Orchestrator()
    # 第 1 件事：家里水管漏水（会停在"追问分类"）
    r1 = o.run("resident", UID, "测试", "我家水管漏水了")
    assert r1["status"] in ("追问", "需确认"), r1
    # 还没回答，直接说第 2 件事（注意：它同时包含问题特征词）
    r2 = o.run("resident", UID, "测试", "楼道灯坏了不亮")
    draft = o.bb.read(f"user:{UID}:work_order_draft") or {}
    assert "楼道灯" in str(draft.get("desc") or ""), f"新草稿应来自新那句话：{draft}"
    assert "水管" not in str(draft.get("desc") or ""), "旧描述不得混进新草稿（这就是那类混合工单）"
    persisted = load_draft(UID, "work_order_draft")
    if persisted:
        assert "水管" not in str(persisted["content"].get("desc") or "")
