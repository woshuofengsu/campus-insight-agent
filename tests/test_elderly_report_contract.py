# -*- coding: utf-8 -*-
"""老人报修契约单测（v3 卡1）。纯规则，不需要数据库。

验收口径（来自 v3 复核的原文）：
  · `楼道灯坏了` **不许建单**（缺位置）；
  · `五号楼二层楼道灯坏了` 允许建单，位置是「5号楼二层楼道」；
  · `不是三号楼，是五号楼` 只能留**老人确认的**五号楼（未确认的纠正不得入库）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.elderly_report import (  # noqa: E402
    build_report_confirm_payload,
    extract_report_fields,
)


def test_missing_location_is_not_dispatchable():
    """施工验收：只说"楼道灯坏了"→ 缺位置，**不许建单**，并给出能听懂的追问。"""
    ok, r, ask = build_report_confirm_payload("楼道灯坏了", {})
    assert not ok, "缺位置的报修不得通过闸门（否则会生成无法派单的工单）"
    assert "location" in r["missing"]
    assert "哪个楼" in ask and "哪一层" in ask, f"追问要具体到老人能回答：{ask}"


def test_full_location_passes():
    """五号楼二层楼道灯坏了 → 位置可派单（楼栋+楼层+部位），责任范围=室外（公共区域）。"""
    ok, r, ask = build_report_confirm_payload("五号楼二层楼道灯坏了", {})
    assert ok and not ask
    loc = r["fields"]["location"]
    # 中文数字归一成阿拉伯数字（与知识图谱的楼栋口径一致）：五号楼→5号楼、二层→2层
    assert loc == "5号楼2层楼道", f"位置应含楼栋/楼层/部位：{loc}"
    assert r["fields"]["issue_type"] == "室外", "楼道属于公共区域（室外）"
    assert r["sources"]["location"] == "text"


def test_public_place_without_building_is_still_missing():
    """只说"楼道灯坏了"（没说哪栋）→ **仍然缺位置**：网格员不知道去哪个楼，等于没报。"""
    ok, r, _ask = build_report_confirm_payload("楼道灯坏了", {})
    assert not ok and "location" in r["missing"]
    # 但社区级地标（广场的路灯）本身就能定位 → 可以建单
    ok2, r2, _ = build_report_confirm_payload("广场的路灯不亮", {})
    assert ok2 and r2["fields"]["location"] == "广场"


def test_community_name_is_never_used_as_location():
    """**核心回归**：位置绝不能退化成社区名/小区名（库里 5 条 location='社区' 的工单就是这么来的）。"""
    r = extract_report_fields("小区里有点吵", {"community": "海淀小区"})
    assert r["fields"]["location"] == "", f"社区名不是可派单位置：{r['fields']['location']}"
    assert "location" in r["missing"]
    assert r["sources"]["location"] == "none"


def test_indoor_uses_profile_address_not_a_guess():
    """`我家阳台水龙头漏水了`：室内 → 房间来自原话，楼栋/单元来自**服务端资料**（并标注来源）。"""
    profile = {"building": "11号楼", "unit": "3单元301"}
    ok, r, _ = build_report_confirm_payload("我家阳台水龙头漏水了", profile)
    assert ok
    assert r["fields"]["issue_type"] == "室内"
    assert "阳台" in r["fields"]["location"] and "11号楼" in r["fields"]["location"]
    assert r["sources"]["location"] == "profile", "楼栋不是老人说的，来源必须标成资料"


def test_scope_is_asked_when_ambiguous():
    """**具体房间**与公共部位同时出现 → 不许猜责任范围，必须问（责任与费用不同）。"""
    ok, r, ask = build_report_confirm_payload("厨房漏水了，楼道也湿了", {})
    assert not ok
    assert "scope" in r["missing"]
    assert "公共" in ask or "家里" in ask


def test_generic_home_mention_does_not_hide_the_public_issue():
    """`家里老人下不来楼` 这类**泛指**不该把公共问题判成室内（实测踩到：电梯工单被判成"家里"）。"""
    ok, r, _ = build_report_confirm_payload(
        "3号楼2单元电梯又坏了，停在5楼不动了，家里老人下不来楼", {})
    assert ok, r["missing"]
    assert r["fields"]["issue_type"] == "室外", "报的是电梯（公共部位）"
    loc = r["fields"]["location"]
    assert loc.startswith("3号楼2单元") and "电梯" in loc, f"位置应指到楼栋+单元+电梯：{loc}"


def test_home_only_issue_uses_profile_address_and_asks_nothing():
    """只说"我家水管漏水了"（没说房间）：用**登记地址**定位（不是猜），可正常上报。"""
    ok, r, _ = build_report_confirm_payload("我家水管漏水了", {"building": "3号楼", "unit": "2单元501"})
    assert ok
    assert r["fields"]["issue_type"] == "室内"
    assert r["fields"]["location"].startswith("3号楼2单元501")
    assert r["sources"]["location"] == "profile"

def test_user_confirmed_values_win_and_are_marked_user():
    """老人补充/确认的值优先，且来源标成 user（未确认的系统建议不算事实）。"""
    ok, r, _ = build_report_confirm_payload(
        "楼道灯坏了", {}, confirmed_location="5号楼二层楼道", confirmed_scope="室外",
        confirmed_urgency="中等")
    assert ok
    assert r["fields"]["location"] == "5号楼二层楼道"
    assert r["fields"]["issue_type"] == "室外"
    assert r["fields"]["urgency"] == "中等"
    assert r["sources"]["location"] == "user"
    assert r["sources"]["issue_type"] == "user"
    assert r["sources"]["urgency"] == "user"


def test_correction_only_applies_what_the_user_confirmed():
    """`不是三号楼，是五号楼`：原话里有两个楼栋 → 只有**老人确认的**那个能入库。"""
    text = "不是三号楼，是五号楼，楼道灯坏了"
    auto = extract_report_fields(text, {})
    assert "3号楼" in auto["suggestion"]["location"], \
        "原话里确实提到了三号楼（系统不该自作主张删掉，而要交给老人确认）"
    ok, r, _ = build_report_confirm_payload(text, {}, confirmed_location="5号楼楼道")
    assert ok and r["fields"]["location"] == "5号楼楼道", "入库值必须是老人确认后的值"
    assert r["sources"]["location"] == "user"


def test_urgent_words_are_suggested_but_need_confirmation():
    """危险词自动建议「紧急」，但字段来源是 suggestion（仍可由老人改）。"""
    r = extract_report_fields("厨房燃气味很大", {"building": "3号楼", "unit": "2单元501"})
    assert r["fields"]["urgency"] == "紧急"
    assert r["sources"]["urgency"] == "suggestion"


def test_same_input_gives_same_task_object():
    """同一输入重复运行 → 一致的任务对象（v2 卡10 的可复现要求）。"""
    a = extract_report_fields("五号楼二层楼道灯坏了", {"building": "11号楼"})
    b = extract_report_fields("五号楼二层楼道灯坏了", {"building": "11号楼"})
    assert a == b


def test_short_description_is_rejected():
    """太短不建单（避免"灯"这种建出一张没人看得懂的单）。"""
    ok, _r, ask = build_report_confirm_payload("灯", {})
    assert not ok and ask
