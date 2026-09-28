# -*- coding: utf-8 -*-
"""字段来源与追问策略（卡10）：**只追问必要信息**、字段来源可解释、同输入同结果。

**背景**：报修调度原来无论用户说了什么，都先问"是您家里还是公共区域？"再问"是紧急情况吗？"
—— 用户明明说了"3号楼2单元电梯坏了"，位置和责任范围都在句子里，还是被问两遍。
本文件守住：
  ① 已经说清的信息**不再问**（问得更少是改进，不是放水）；
  ② 拿不准的**必须问**（不许替用户拍板责任范围）；
  ③ 确认卡上标出**位置是从哪来的**（您说的 / 您的登记资料）；
  ④ 同一句话重复跑，得到**一致的任务对象**（可复现）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from agent.roles.business_agents import RepairDispatchAgent, _extract_repair_fields  # noqa: E402


class _BB(dict):
    """最小黑板替身：够 RepairDispatchAgent 读写草稿与状态。"""

    def read(self, key):
        return self.get(key)

    def write(self, key, val, source="", lock=True):
        self[key] = val

    def unlock(self, key):
        pass

    def post_message(self, *a, **k):
        return None

    def get_messages(self, *a, **k):
        return []


def _agent():
    a = RepairDispatchAgent.__new__(RepairDispatchAgent)
    a.bb = _BB()
    return a


PROFILE_UID = None   # 不查库：走"没有资料"的分支（更严格）


# ---------------------------------------------------------------- 抽取

def test_extract_finds_location_and_scope():
    r = _extract_repair_fields("3号楼2单元电梯坏了", PROFILE_UID)
    assert r["location"].startswith("3号楼2单元") and "电梯" in r["location"]
    assert r["type"] == "室外"
    assert r["sources"]["location"] == "text"


def test_extract_refuses_to_guess_when_vague():
    """只说"灯坏了"→ 位置与责任范围都给不出结论（放进 missing），必须继续问。"""
    r = _extract_repair_fields("灯坏了", PROFILE_UID)
    assert r["location"] == "" and r["type"] == ""
    assert set(r["missing"]) >= {"location", "scope"}


def test_extract_is_deterministic():
    a = _extract_repair_fields("3号楼2单元电梯坏了", PROFILE_UID)
    b = _extract_repair_fields("3号楼2单元电梯坏了", PROFILE_UID)
    assert a == b, "同一句话重复跑必须得到一致的任务对象"


# ---------------------------------------------------------------- 追问策略（端到端走一遍 agent）

def _run(text, uid=88801, role="resident", bb=None):
    a = _agent()
    if bb is not None:
        a.bb = bb
    return a.process({"user_input": text, "uid": uid, "name": "测试", "role": role,
                      "state": {}})


def test_full_location_skips_the_category_question():
    """位置与责任范围都在句子里 → **只问紧急程度**（旧行为会问两遍）。"""
    out = _run("3号楼2单元电梯坏了")
    assert out["status"] == "追问"
    assert "紧急" in out["reply"], out["reply"]
    assert "公共区域" not in out["reply"], f"不该再问家里/公共：{out['reply']}"


def test_vague_still_asks_the_necessary_question():
    """说不清就照旧问 —— **不许替用户拍板**责任范围。"""
    out = _run("灯坏了")
    assert out["status"] == "追问" and "家里" in out["reply"], out["reply"]


def test_confirm_card_shows_location_source():
    """确认卡要标出位置**从哪来**（"您说的" / "您的登记资料"），用户才能核对。"""
    bb = _BB()
    _run("3号楼2单元电梯坏了", bb=bb)
    out = _run("紧急", bb=bb)
    assert out["status"] == "需确认"
    assert "位置：" in out["reply"] and "电梯" in out["reply"]
    assert ("来自您说的话" in out["reply"]) or ("来自您的登记资料" in out["reply"])


def test_draft_keeps_field_sources():
    """草稿里要留下每个字段的来源（未确认的不算业务事实，来源要可追溯）。"""
    bb = _BB()
    _run("3号楼2单元电梯坏了", uid=88802, bb=bb)
    draft = bb.read("user:88802:work_order_draft")
    assert draft and draft.get("sources", {}).get("location") == "text"
    assert draft.get("location", "").startswith("3号楼2单元")


def test_ambiguous_scope_still_asks_even_with_location():
    """有位置但责任范围有歧义（家里和公共都提到）→ 仍要问责任范围。"""
    out = _run("厨房漏水了，楼道也湿了")
    assert out["status"] == "追问"
    assert ("家里" in out["reply"]) or ("公共" in out["reply"]), out["reply"]


@pytest.mark.parametrize("text,expect_ask", [
    ("3号楼2单元电梯坏了", False),     # 位置+责任范围都清楚 → 不问分类
    ("我家厨房水管漏水了", False),     # 室内 + 房间 → 不问分类
    ("灯坏了", True),                  # 什么都没说清 → 要问
])
def test_question_count_matches_information_given(text, expect_ask):
    out = _run(text)
    asked_category = "公共区域" in out["reply"]
    assert asked_category == expect_ask, f"{text} → {out['reply']}"
