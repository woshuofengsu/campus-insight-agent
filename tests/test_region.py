# -*- coding: utf-8 -*-
"""地区（属地）识别单测（WS1，纯函数、零 IO）。

覆盖点对应 docs/spec/地区识别落地方案.md v2 第 2 节与第 3 节：
归一化（含**复合串**「北京市海淀区」）、别名、安全默认、命中/未命中/None、级别取最具体、权重表。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import region as R  # noqa: E402


# ---------------------------------------------------------------- 归一化

def test_normalize_national_variants():
    for t in ("", "   ", "全国", "通用", "不限", "全地区"):
        assert R.normalize_area(t) == {R.NATIONAL}, t


def test_normalize_real_composite_value():
    """库里真实值「北京市海淀区」必须拆成两级 —— 否则区级条目会被当成市级。"""
    assert R.normalize_area("北京市海淀区") == {"北京市", "海淀区"}
    assert R.normalize_area("北京市") == {"北京市"}
    assert R.normalize_area("海淀区") == {"海淀区"}
    assert R.normalize_area("海淀") == {"海淀区"}
    assert R.normalize_area("北京") == {"北京市"}


def test_normalize_unknown_free_text_is_national():
    """看不懂的自由文本按全国处理（安全默认：不惩罚、不误排）。"""
    assert R.normalize_area("详见附件") == {R.NATIONAL}
    assert R.normalize_area("其他") == {R.NATIONAL}


def test_foreign_place_is_other_level():
    """看得懂的外地行政区 → 对本地用户判为 other（软降权、仍可见），而不是被当全国。"""
    r = R.resolve_region("海淀小区")
    for area in ("上海市浦东新区", "广东省深圳市南山区", "河北省"):
        boost, level = R.policy_region_boost(area, r)
        assert level == R.LEVEL_OTHER, (area, level)
        assert boost < 0, area


# ---------------------------------------------------------------- 属地解析

def test_resolve_region_hits_real_community():
    """键必须是库里真值「海淀小区」——写错键会静默失效，这条测试就是防它。"""
    r = R.resolve_region("海淀小区")
    assert r.source == "config", "应命中配置映射（未命中会回落并告警）"
    assert r.city == "北京" and r.city_id == "101010100" and r.district == "海淀区"
    assert r.label().startswith("北京市海淀区")
    assert r.cache_key() == "101010100"


def test_resolve_region_unknown_falls_back_and_warns(caplog):
    """未知社区回落全局默认（行为与现状一致），但必须**告警**，不允许静默无效。"""
    import logging
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="utils.region"):
        r = R.resolve_region("某个没配过的社区")
    assert r.source == "fallback"
    assert r.city == "北京" and r.city_id == "101010100"
    assert any("未配置属地映射" in rec.getMessage() for rec in caplog.records), \
        [rec.getMessage() for rec in caplog.records]


def test_resolve_region_none_and_empty_safe():
    for v in (None, "", "   "):
        r = R.resolve_region(v)
        assert r.city == "北京"
        assert r.chain(), "chain 至少有城市"


def test_region_chain_specific_to_broad():
    r = R.resolve_region("海淀小区")
    chain = r.chain()
    assert chain[0] == "海淀小区" and "海淀区" in chain and "北京" in chain
    # 具体 → 宽泛：区在城之前
    assert chain.index("海淀区") < chain.index("北京")


# ---------------------------------------------------------------- 匹配与级别

def test_national_covers_everyone():
    r = R.resolve_region("海淀小区")
    for area in ("", "全国", "通用", "不限"):
        assert R.policy_region_boost(area, r) == (0.0, R.LEVEL_NATIONAL)


def test_district_beats_city_and_province():
    """「北京市海淀区」同时命中市与区 → 取最具体的区级（加 1.5 而非 0.5）。

    注：直辖市里「北京市」既是省也是市，本实现按**市级**（+1.0）处理 —— 这样
    39 条「北京市」政策排在 1 条「北京市海淀区」政策之后、但仍在「全国」之前，演示效果正确。
    """
    r = R.resolve_region("海淀小区")
    assert R.policy_region_boost("北京市海淀区", r) == (R.REGION_BOOST[R.LEVEL_DISTRICT], R.LEVEL_DISTRICT)
    assert R.policy_region_boost("北京市", r) == (R.REGION_BOOST[R.LEVEL_CITY], R.LEVEL_CITY)
    assert R.policy_region_boost("海淀区", r)[1] == R.LEVEL_DISTRICT
    assert R.policy_region_boost("海淀小区", r)[1] == R.LEVEL_STREET
    assert R.policy_region_boost("本社区", r)[1] == R.LEVEL_STREET
    # 真正的省级 token（非直辖市）才走 province
    r2 = R.resolve_region("海淀小区")
    assert R.policy_region_boost("河北省", r2)[1] == R.LEVEL_OTHER


def test_foreign_area_soft_penalized_not_filtered():
    r = R.resolve_region("海淀小区")
    boost, level = R.policy_region_boost("上海市浦东新区", r)
    assert level == R.LEVEL_OTHER and boost < 0


def test_region_none_returns_zero():
    """region=None 时加分必须恒为 0 —— 这是"默认行为逐字节不变"的地基。"""
    for area in ("", "全国", "北京市", "北京市海淀区", "上海市浦东新区", "乱七八糟"):
        assert R.policy_region_boost(area, None) == (0.0, R.LEVEL_NATIONAL)


def test_levels_share_same_definition_between_two_retrievals():
    """线上（REGION_BOOST）与 Agent RRF（RRF_REGION）必须共用同一套级别定义。"""
    assert set(R.REGION_BOOST) == set(R.RRF_REGION)
    for lv, v in R.REGION_BOOST.items():
        assert (v > 0) == (R.RRF_REGION[lv] > 0), lv
    assert R.rrf_region_bonus(R.LEVEL_DISTRICT) > 0
    assert R.rrf_region_bonus(R.LEVEL_OTHER) < 0
    assert R.rrf_region_bonus("不存在的级别") == 0.0
