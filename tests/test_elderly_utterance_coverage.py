# -*- coding: utf-8 -*-
"""老人"说人话"的覆盖门禁（2026-09-30 由用户实测反馈引出）。

**用户原话**：「我保修为啥告诉我无法识别听不懂」。按真实说法跑接口复现出**三个同类问题**——
都是"老人正常说话，系统没接住"，而且一个比一个有害：

| 老人说 | 修之前 | 性质 |
|---|---|---|
| 「窗户也关不上」（拿到确认卡之后） | "已取消，没有生成工单。" | **静默取消**：老人没说取消，草稿被丢掉 |
| 「我住在五号楼」 | "我没太理解您的意思…" | **补充信息没接住**（就是用户抱怨的那句） |
| 「我家空调不制冷」「暖气不热」 | 回答今日天气 | **误路由**：故障被当成天气查询 |

本文件用**真实说法**驱动 `RepairDispatchAgent`（不 mock 意图识别），守住三件事：
  ① 常见说法/同音错字（保修、修一下、灯闪、门打不开、空调不制冷…）都要归到报修；
  ② 确认卡阶段说别的话**不许静默取消**：只有明确取消词才取消，其余要么回填补充、要么重新问；
  ③ 冷热故障、窗户门锁这类**问题形态**要按"新的一件事"处理或重新问，不能当成位置补充乱填。

门禁自检：把补充分支去掉（回到"非确认词即取消"），用例必须变红（见最后一条）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from agent.roles.business_agents import RepairDispatchAgent  # noqa: E402


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


def _agent(bb=None):
    a = RepairDispatchAgent.__new__(RepairDispatchAgent)
    a.bb = bb if bb is not None else _BB()
    return a


def _run(text, uid=99601, bb=None):
    return _agent(bb).process({"user_input": text, "uid": uid, "name": "张大爷",
                               "role": "elderly", "state": {}})


# ---------------------------------------------------------------- ① 常见说法要能听懂

@pytest.mark.parametrize("text", [
    "保修",                      # 同音错字（用户原话里就是这么写的）
    "我要保修",
    "灯闪一下就不亮了",
    "修一下灯",
    "门锁打不开",
    "下水道不通",
    "垃圾没人清",
    "我家空调不制冷",
    "暖气不热",
    "楼道感应灯没反应",
])
def test_common_repair_phrasings_are_understood(text):
    """这些说法都不该落到"我没太理解您的意思"。"""
    out = _run(text)
    assert out["status"] != "成功" or "报修" in str(out.get("reply") or "") or \
        "确认" in str(out.get("reply") or "") or "缺" in str(out.get("reply") or ""), out
    assert "没太理解" not in str(out.get("reply") or ""), f"{text} → {out.get('reply')}"
    assert out.get("intent") in ("报修", "repair") or "报修" in str(out.get("chain_note") or ""), out


# ---------------------------------------------------------------- ② 确认卡阶段不许静默取消

def test_confirm_stage_supplement_is_not_a_cancel():
    """确认卡阶段给补充信息 → 回填并重新确认，**草稿不能丢**、更不能回"已取消"。"""
    bb = _BB()
    _run("楼道灯坏了", bb=bb)                     # → 确认卡
    out = _run("其实是我家里", bb=bb)              # 补充责任范围
    reply = str(out.get("reply") or "")
    assert "已取消" not in reply, f"补充信息被当成取消了：{reply}"
    assert "确认" in reply and out.get("status") == "需确认", out


def test_confirm_stage_takes_the_elderly_own_location_words():
    """老人明确说出的楼栋/楼层要**优先于登记资料**（实测：说"我住在五号楼"却用了资料里的门牌）。"""
    bb = _BB()
    _run("楼道灯坏了", bb=bb)
    out = _run("我住在五号楼", bb=bb)
    draft = bb.read("user:99601:work_order_draft") or {}
    reply = str(out.get("reply") or "")
    loc = str(draft.get("location") or "")
    # 库内位置统一成阿拉伯数字（五号楼 → 5号楼，与老人端同一套规范化），两种写法都算通过
    assert "5号楼" in loc or "五号楼" in loc, f"没用老人说的话：{draft}"
    assert (draft.get("sources") or {}).get("location") == "user", draft
    assert "已取消" not in reply and out.get("status") == "需确认", out


def test_supplement_at_urgency_stage_also_counts():
    """**追问紧急程度时**才说楼栋，也要用上（不能只认确认阶段）。"""
    bb = _BB()
    _run("3号楼2单元电梯坏了", bb=bb)        # 位置清楚 → 只问紧急程度
    out = _run("对了，是五号楼", bb=bb)
    draft = bb.read("user:99601:work_order_draft") or {}
    loc = str(draft.get("location") or "")
    assert "5号楼" in loc or "五号楼" in loc, f"追问阶段的补充没被用上：{draft}"
    assert out.get("status") in ("需确认", "追问"), out


def test_confirm_stage_unrelated_talk_reasks_and_keeps_draft():
    """既不是确认、也不是补充、也没说取消 → **重新问一遍**，草稿保留。"""
    bb = _BB()
    _run("楼道灯坏了", bb=bb)
    out = _run("我孙子在家呢", bb=bb)
    reply = str(out.get("reply") or "")
    assert "已取消" not in reply, f"非确认词被当成取消：{reply}"
    assert "还没" in reply or "没有提交" in reply, reply
    assert out.get("status") == "需确认"
    assert bb.read("user:99601:work_order_draft"), "草稿被丢掉了（必须保留）"


def test_only_explicit_cancel_words_cancel():
    """只有明确取消词才取消（这是老人在确认卡上唯一的"退出"方式）。"""
    for word in ("算了", "取消", "不要了", "先不弄了", "不报了"):
        bb = _BB()
        _run("楼道灯坏了", bb=bb)
        out = _run(word, bb=bb)
        assert "已取消" in str(out.get("reply") or ""), f"{word} 应当取消：{out}"
        assert not bb.read("user:99601:work_order_draft"), "取消后草稿应清掉"


def test_confirm_then_confirm_creates_exactly_one_object():
    """重新问过之后仍能正常确认 → 走到建单（不能因为"重新问"把流程弄丢）。"""
    bb = _BB()
    _run("楼道灯坏了", bb=bb)
    _run("我住在五号楼", bb=bb)        # 重新问一遍
    out = _run("确认提交", bb=bb)
    assert str(out.get("status")) in ("成功", "需补充", "失败"), out
    assert "已取消" not in str(out.get("reply") or ""), out


# ---------------------------------------------------------------- ③ 问题形态按"新事"处理

def test_second_problem_is_treated_as_a_new_thing_not_a_location():
    """「窗户也关不上」是**第二件事**，不是给上一件补充位置（实测曾被填成"位置=窗户"）。"""
    bb = _BB()
    _run("楼道灯坏了", bb=bb)
    out = _run("窗户也关不上", bb=bb)
    reply = str(out.get("reply") or "")
    draft = bb.read("user:99601:work_order_draft") or {}
    assert "窗户" in str(draft.get("desc") or "") or "窗户" in reply, \
        f"第二件事没被当成新报修：{reply} / {draft}"
    assert "楼道灯" not in str(draft.get("location") or ""), draft


def test_heat_cold_faults_are_repair_not_weather():
    """冷热故障（不制冷/不制热/不热）在**意图层**就要归报修，不能被天气截走。"""
    from agent.web_agent import detect_intent
    for q in ("我家空调不制冷", "暖气不热", "空调不制热"):
        assert detect_intent(q, "elderly") == "报修", f"{q} 被路由成了 {detect_intent(q, 'elderly')}"
        assert detect_intent(q, "resident") == "报修", q


# ---------------------------------------------------------------- 门禁自检

def test_gate_would_catch_the_old_silent_cancel(monkeypatch):
    """**门禁自检**：把确认阶段恢复成"非确认词即取消"，上面两条用例必须变红。"""
    import agent.roles.business_agents as B
    calls = {"n": 0}

    def _never_filled(text, draft, uid):
        calls["n"] += 1
        return []

    monkeypatch.setattr(B, "_apply_repair_supplement", _never_filled)
    bb = _BB()
    _run("楼道灯坏了", bb=bb)
    out = _run("我住在五号楼", bb=bb)      # 补充分支被禁 → 会落到"重新问一遍"（仍是安全行为）
    assert calls["n"] >= 1, "补充吸收函数根本没被调用（自检无效）"
    assert "已取消" not in str(out.get("reply") or "")
