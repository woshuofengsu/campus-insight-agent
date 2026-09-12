# -*- coding: utf-8 -*-
"""U3 知识库健康度测试：查询日志记录 / 命中率与零命中统计 / 端点权限 / 清理。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from data import db_core


@pytest.fixture()
def fresh_db():
    """每个用例独立临时库（隔离，避免其它测试文件共享 config.DB_PATH）。"""
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="kb_metrics_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "kb.db"))
    yield
    db_core._DB_PATH = orig


def test_kb_query_log_and_health(fresh_db):
    """命中/未命中都记日志 → 健康度给出命中率、零命中 top、检索路线分布。"""
    from data.db_kb_metrics import get_kb_health, log_kb_query
    log_kb_query(1, "医保怎么报销", True, reason="ok", top_score=5.02,
                 top_kb_id=1, retrieval="hybrid")
    log_kb_query(1, "医保怎么报销", True, reason="ok", top_score=4.8, top_kb_id=1, retrieval="hybrid")
    log_kb_query(2, "火星移民政策", False, reason="no_knowledge", top_score=0.0, retrieval="lexical")
    log_kb_query(2, "火星移民政策", False, reason="no_knowledge", top_score=0.0, retrieval="lexical")
    h = get_kb_health(days=7)
    assert h["queries"] == 4 and h["hits"] == 2
    assert h["hit_rate"] == 50.0
    assert h["avg_score"] > 0
    assert h["retrieval"].get("hybrid") == 2 and h["retrieval"].get("lexical") == 2
    # 零命中问题 top：同一问题出现 2 次应排在首位
    assert h["zero_hit_top"], "应有零命中问题"
    assert h["zero_hit_top"][0]["question"] == "火星移民政策"
    assert h["zero_hit_top"][0]["count"] == 2
    assert "embedding" in h


def test_kb_health_empty_is_safe(fresh_db):
    """无任何查询记录时不得报错，命中率为 0。"""
    from data.db_kb_metrics import get_kb_health
    h = get_kb_health(days=7)
    assert h["queries"] == 0 and h["hit_rate"] == 0.0 and h["zero_hit_top"] == []


def test_kb_health_counts_knowledge_scale(fresh_db):
    """知识库规模与分类分布来自 knowledge_base（已发布）。"""
    from data.db_policy import create_knowledge
    from data.db_core import get_db
    from data.db_kb_metrics import get_kb_health
    kid, err = create_knowledge(
        title="测试政策条目", category="社保医保",
        plain_interpretation="用于统计测试。", source="公开政策",
        keywords="测试,统计", effective_date="2024-01-01", actor="测试")
    assert kid and not err, err
    with get_db() as conn:
        conn.execute("UPDATE knowledge_base SET audit_status='已发布' WHERE id=?", (kid,))
        conn.commit()
    h = get_kb_health(days=7)
    assert h["kb_published"] >= 1
    assert h["by_category"].get("社保医保", 0) >= 1


def test_kb_query_log_masks_phone(fresh_db):
    """合规：问题文本里的手机号落库前必须掩码（不得存完整手机号）。"""
    from data.db_kb_metrics import log_kb_query
    from data.db_core import get_db
    log_kb_query(1, "我家电话是13812345678，漏水了找谁", True)
    with get_db() as conn:
        row = conn.execute("SELECT question FROM kb_query_log ORDER BY id DESC LIMIT 1").fetchone()
    q = row["question"]
    assert "13812345678" not in q, f"完整手机号不得落库：{q}"
    assert "138****5678" in q, f"应掩码为 138****5678：{q}"
    # 非手机号数字串不受影响（如工单号）
    log_kb_query(1, "工单 WO00012345 进度", True)
    with get_db() as conn:
        row = conn.execute("SELECT question FROM kb_query_log ORDER BY id DESC LIMIT 1").fetchone()
    assert "WO00012345" in row["question"]


def test_mask_phones_util():
    """utils.text.mask_phones：掩码手机号、保留工单号、空值安全。"""
    from utils.text import mask_phones
    assert mask_phones("联系13900001111") == "联系139****1111"
    assert mask_phones("工单号 WO12345678901") == "工单号 WO12345678901"  # 非 1[3-9] 开头
    assert mask_phones("") == ""
    assert mask_phones("13812345678 和 15987654321") == "138****5678 和 159****4321"


def test_rag_eval_reports_hit_at_1(fresh_db):
    """评测输出应同时给 top-k 命中率与 hit@1（Top-1 正确率）。"""
    from scripts.rag_eval import run
    r = run(topk=3, no_embedding=True)
    assert "hit1_rate" in r and "hit1" in r
    assert 0 <= r["hit1_rate"] <= 100
    assert r["hit1"] <= r["hits"], "hit@1 不可能多于 top-k 命中数"


def test_clean_kb_query_log(fresh_db):
    """清理函数可运行（90 天保留）。"""
    from data.db_kb_metrics import clean_kb_query_log, log_kb_query
    log_kb_query(1, "测试问题", True)
    n = clean_kb_query_log(days=90)
    assert n >= 0  # 新记录不应被清理


def test_kb_health_endpoint_grid_only(client):
    """端点：grid 可查、居民 403。"""
    r = client.post("/api/web/auth/demo", json={"role": "resident"})
    rh = {"Authorization": f"Bearer {r.json()['data']['token']}"}
    r = client.get("/api/web/agent/kb-health", headers=rh)
    assert r.status_code == 400 and r.json()["code"] == 1003
    g = client.post("/api/web/auth/demo", json={"role": "grid"})
    gh = {"Authorization": f"Bearer {g.json()['data']['token']}"}
    r = client.get("/api/web/agent/kb-health", headers=gh)
    assert r.status_code == 200 and r.json()["success"]
    d = r.json()["data"]
    for k in ("queries", "hit_rate", "zero_hit_top", "kb_published", "by_category"):
        assert k in d


@pytest.fixture(scope="module")
def client():
    """端点测试用 TestClient（与 test_agent 同模式，模块级）。"""
    from fastapi.testclient import TestClient
    import api_web
    with TestClient(api_web.app) as c:
        yield c
