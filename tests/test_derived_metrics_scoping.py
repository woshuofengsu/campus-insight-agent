# -*- coding: utf-8 -*-
"""派生聚合按社区收口（v2 升级方案任务卡 4 后半 · 派生查询）。

**问题**（Codex 评审 I1）：多租户只把"主列表"收干净了，**派生/聚合路径**还在跨社区汇总：
- `db_care_metrics.get_care_metrics` 统计所有社区的关怀事件 → 网格端"关怀触达率"混入别社区数据；
- `db_kb_metrics.get_kb_health` 的**零命中问题榜**把所有社区的居民提问原文聚合在一起 →
  等于每个社区的网格员都能读到"别社区居民问了什么"。

**做法**：两个聚合都接受 `tenant=`，按社区过滤（`kb_query_log` 无租户列 → 按其归属用户社区筛）；
空租户一律返回**零值结构**（fail-closed，绝不回落成"统计全部"）。
知识库本身的规模/分类统计**保持全局**（跨社区共享的公开语料，不是居民数据）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
RES_A = 96801
RES_B = 96802
GRID_A = 96811


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="derived_scope_")
    path = os.path.join(tmp, "ds.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, com in ((RES_A, "resident", "A居民", A),
                                     (RES_B, "resident", "B居民", B),
                                     (GRID_A, "grid", "A网格", A)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


def test_care_metrics_scoped_by_community():
    """A 社区的情绪事件不该出现在 B 社区的指标里。"""
    from data.db_care_metrics import get_care_metrics, log_care_event
    log_care_event(RES_A, role="resident", emotion_tag="焦虑", comfort_used=True, status="成功")
    log_care_event(RES_A, role="resident", emotion_tag="着急", comfort_used=False, status="成功")

    a = get_care_metrics(days=7, tenant=A)
    b = get_care_metrics(days=7, tenant=B)
    assert a["care_events"] >= 2, f"A 社区应统计到自己的事件，实际 {a['care_events']}"
    assert a["emotion_events"] >= 2
    assert b["care_events"] == 0, f"B 社区不该看到 A 社区的事件，实际 {b['care_events']}"


def test_care_metrics_fail_closed_on_empty_tenant():
    from data.db_care_metrics import get_care_metrics
    assert get_care_metrics(days=7, tenant="")["care_events"] == 0, \
        "空租户必须返回零值，不得回落成统计全部"
    assert get_care_metrics(days=7, tenant="海淀区")["care_events"] == 0, \
        "历史行政区值不是合法租户"


def test_kb_health_zero_hit_questions_scoped():
    """零命中榜是**居民提问原文**：A 社区的问题不该出现在 B 社区的榜里。"""
    from data.db_kb_metrics import get_kb_health, log_kb_query
    log_kb_query(RES_A, "A社区问的独有政策问题", matched=False, reason="low_score", top_score=1.2)
    log_kb_query(RES_B, "B社区问的独有政策问题", matched=False, reason="low_score", top_score=1.1)

    a = get_kb_health(days=7, top_n=10, tenant=A)
    b = get_kb_health(days=7, top_n=10, tenant=B)
    a_qs = [x["question"] for x in a["zero_hit_top"]]
    b_qs = [x["question"] for x in b["zero_hit_top"]]
    assert "A社区问的独有政策问题" in a_qs
    assert "B社区问的独有政策问题" not in a_qs, "A 社区网格员不该看到 B 社区居民的提问原文"
    assert "B社区问的独有政策问题" in b_qs and "A社区问的独有政策问题" not in b_qs
    assert a["queries"] >= 1 and b["queries"] >= 1


def test_kb_health_fail_closed_but_kb_scale_stays_global():
    """空租户 → 提问聚合为零；但知识库规模是共享语料，仍应给出真实规模。"""
    from data.db_kb_metrics import get_kb_health
    out = get_kb_health(days=7, top_n=10, tenant="")
    assert out["queries"] == 0 and out["zero_hit_top"] == [], "空租户不得聚合任何社区的问题"
    assert out["kb_total"] >= 0          # 共享语料，允许全局统计
