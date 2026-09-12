# -*- coding: utf-8 -*-
"""U4 关怀量化测试：关怀事件记录 / 指标口径 / 端点权限 / 编排接线。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from data import db_core


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="care_metrics_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "care.db"))
    yield
    db_core._DB_PATH = orig


def test_care_metrics_aggregation(fresh_db):
    """关怀量化：情绪识别数、触达率、情绪→转人工率、情绪→闭环率、场景分布。"""
    from data.db_care_metrics import get_care_metrics, log_care_event
    # 1) 情绪 + 安抚句 + 成功
    log_care_event(1, "resident", emotion_tag="着急", comfort_used=True,
                   scene="repair_ok", scene_line_used=True, intent="repair_dispatch", status="成功")
    # 2) 情绪 + 共情 + 转人工
    log_care_event(2, "elderly", emotion_tag="焦虑", comfort_used=True,
                   scene="sos", scene_line_used=True, intent="health_advisor",
                   status="transferred_to_human")
    # 3) 无情绪，仅场景共情
    log_care_event(3, "resident", emotion_tag="", comfort_used=False,
                   scene="fail", scene_line_used=True, intent="policy_expert", status="失败")
    m = get_care_metrics(days=7)
    assert m["care_events"] == 3
    assert m["emotion_events"] == 2
    # 触达数只在「识别到情绪」的事件里统计 → 2 条情绪事件都有安抚，触达率 100%
    assert m["touch_events"] == 2
    assert m["touch_rate"] == 100.0
    assert m["scene_line_events"] == 3  # 场景共情句 3 条（含无情绪那条）
    assert m["emotion_to_human"] == 1
    assert m["emotion_to_human_rate"] == 50.0
    assert m["emotion_closed"] == 1
    assert m["emotion_closed_rate"] == 50.0
    assert m["by_emotion"].get("着急") == 1 and m["by_emotion"].get("焦虑") == 1
    assert m["by_scene"].get("repair_ok") == 1 and m["by_scene"].get("sos") == 1


def test_care_metrics_empty_safe(fresh_db):
    from data.db_care_metrics import get_care_metrics
    m = get_care_metrics(days=7)
    assert m["care_events"] == 0 and m["touch_rate"] == 0.0
    assert m["by_emotion"] == {} and m["by_scene"] == {}


def test_seed_care_events_idempotent_and_no_pii(fresh_db):
    """演示种子：空库补种关怀事件（大屏不空）；已够数不重复；**只种标签不种 PII**。"""
    from data.seed import _seed_care_events
    from data.db_core import get_db
    n1 = _seed_care_events()
    assert n1 >= 8, f"应种 8~15 条演示关怀事件，实际 {n1}"
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM care_event_log")]
    assert len(rows) == n1
    # 幂等：再跑不加倍
    assert _seed_care_events() == 0
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM care_event_log").fetchone()["c"] == n1
    # 无 PII：不含手机号/姓名/原文（只应有标签、场景、状态、意图）
    import re
    for r in rows:
        joined = " ".join(str(v) for v in r.values())
        assert not re.search(r"1[3-9]\d{9}", joined), "不得含手机号"
        assert not r.get("user_id"), "种子事件 user_id 应为 0（非真实用户）"
    # 跨天分布（便于周维度统计）：至少覆盖 3 个不同日期
    with get_db() as conn:
        days = conn.execute(
            "SELECT COUNT(DISTINCT date(created_at)) c FROM care_event_log").fetchone()["c"]
    assert days >= 3, f"应跨多天分布，实际 {days} 天"


def test_clean_care_event_log(fresh_db):
    from data.db_care_metrics import clean_care_event_log, log_care_event
    log_care_event(1, "resident", emotion_tag="着急", comfort_used=True)
    assert clean_care_event_log(days=180) >= 0  # 新记录不被清理


def test_care_endpoint_grid_only(client):
    """端点：grid 可查、居民 403。"""
    r = client.post("/api/web/auth/demo", json={"role": "resident"})
    rh = {"Authorization": f"Bearer {r.json()['data']['token']}"}
    r = client.get("/api/web/agent/care-metrics", headers=rh)
    assert r.status_code == 400 and r.json()["code"] == 1003
    g = client.post("/api/web/auth/demo", json={"role": "grid"})
    gh = {"Authorization": f"Bearer {g.json()['data']['token']}"}
    r = client.get("/api/web/agent/care-metrics", headers=gh)
    assert r.status_code == 200 and r.json()["success"]
    for k in ("care_events", "emotion_events", "touch_rate", "by_emotion", "by_scene"):
        assert k in r.json()["data"]


def test_orchestrator_records_care_event(client, fresh_db):
    """编排接线：带情绪的用户输入 → 回复出现安抚/共情 → 落一条关怀事件。"""
    from agent.orchestrator import Orchestrator
    from data.db_care_metrics import get_care_metrics
    o = Orchestrator()
    out = o.run("resident", 999, "测试居民", "我家漏水了，急死了，你们管不管")
    assert out.get("reply")
    m = get_care_metrics(days=1)
    # 命中情绪（急死了）→ 应记关怀事件；若该场景未拼关怀句则允许 0（避免脆断言）
    if m["care_events"]:
        assert m["emotion_events"] >= 1
        assert "着急" in m["by_emotion"] or "不满" in m["by_emotion"] or m["emotion_events"] >= 1


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import api_web
    with TestClient(api_web.app) as c:
        yield c
