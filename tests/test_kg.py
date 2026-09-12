# -*- coding: utf-8 -*-
"""U6 轻量知识图谱测试：规则抽取 / 建图幂等 / 实体反查 / 规模统计 / 端点权限。

全部用例走 `fresh_db`（临时库）——**不碰生产库** data/community_insight.db。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from data import db_core


@pytest.fixture()
def fresh_db():
    """每个用例独立临时库（隔离，避免污染 config.DB_PATH 与生产库）。"""
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="kg_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "kg.db"))
    yield
    db_core._DB_PATH = orig


def _add_issue(title, location="", description="", category="设施维修"):
    """直接写一条工单（只写 title/category/location/description，不涉及手机号列）。"""
    from data.db_core import get_db
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO community_issues (title, category, location, description) VALUES (?,?,?,?)",
            (title, category, location, description))
        conn.commit()
        return cur.lastrowid


def _add_knowledge(title, content, keywords="", category="养老服务", audit_status="已发布"):
    """写一条知识库条目（audit_status 默认已发布，便于抽取）。"""
    from data.db_core import get_db
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_base (title, content, keywords, category, audit_status, source) "
            "VALUES (?,?,?,?,?, '测试来源')",
            (title, content, keywords, category, audit_status))
        conn.commit()
        return cur.lastrowid


# ------------------------------------------------------------ 1. 规则抽取

def test_extract_building(fresh_db):
    """楼栋：阿拉伯/中文数字都识别，并归一成「N号楼」；「二楼」这类楼层不算楼栋。"""
    from data.db_kg import extract_entities
    assert extract_entities("3号楼2单元电梯困人")["building"] == ["3号楼"]
    assert extract_entities("四号楼顶漏水")["building"] == ["4号楼"]      # 中文数字归一
    assert extract_entities("12号楼前电动车飞线充电")["building"] == ["12号楼"]
    assert extract_entities("二楼水龙头漏水")["building"] == []           # 楼层不是楼栋
    assert extract_entities("3号楼和5号楼都停水")["building"] == ["3号楼", "5号楼"]


def test_extract_facility(fresh_db):
    """设施：同义说法归一到同一实体；「加装电梯」是政策事项，不重复出设施「电梯」。"""
    from data.db_kg import extract_entities
    assert extract_entities("电梯坏了")["facility"] == ["电梯"]
    assert extract_entities("货梯异响")["facility"] == ["电梯"]           # 同义归一
    assert extract_entities("楼道灯不亮")["facility"] == ["路灯"]
    assert extract_entities("下水道堵塞")["facility"] == ["水管"]
    e = extract_entities("居民希望加装电梯")
    assert e["topic"] == ["加装电梯"] and e["facility"] == []             # 最长匹配优先


def test_extract_group_and_topic(fresh_db):
    """人群：更长的人群名优先（独居老人 不会再出一个「老人」）；政策事项与人群各归各类。"""
    from data.db_kg import extract_entities
    e = extract_entities("11号楼独居老人三天未出门")
    assert e["group"] == ["独居老人"] and e["building"] == ["11号楼"]
    assert extract_entities("高龄老人可申请高龄津贴")["group"] == ["高龄老人"]
    assert extract_entities("高龄老人可申请高龄津贴")["topic"] == ["高龄津贴"]
    assert extract_entities("残疾人家庭申请低保户认定")["group"] == ["残疾人", "低保户"]


def test_extract_empty_is_safe(fresh_db):
    """无实体时各类型返回空列表（不得报错、不得瞎猜）。"""
    from data.db_kg import extract_entities
    empty = {"building": [], "facility": [], "group": [], "topic": []}
    assert extract_entities("今天天气不错") == empty
    assert extract_entities("") == empty
    assert extract_entities(None) == empty


# ------------------------------------------------------------ 2. 建图（幂等）

def test_build_graph_idempotent(fresh_db):
    """连续建图两次：实体/关系/引用数完全一致（不得翻倍、不得留下重复边）。"""
    from data.db_kg import build_graph, graph_stats
    _add_issue("3号楼电梯故障停运", location="3号楼2单元", description="电梯异响后停运，老人上下楼困难")
    _add_issue("3号楼水管漏水", location="3号楼", description="厨房下水道漏水")
    _add_knowledge("加装电梯政策解读", "4-12号楼居民关注的加装电梯流程与费用分摊", keywords="加装电梯,老旧小区")
    first = build_graph(limit=100)
    second = build_graph(limit=100)
    assert first["entities"] == second["entities"] > 0
    assert first["relations"] == second["relations"] > 0
    assert first["mentions"] == second["mentions"] > 0
    st = graph_stats()
    assert st["entities"] == first["entities"]
    assert st["relations"] == first["relations"]
    with db_core.get_db() as conn:
        n_ent = conn.execute("SELECT COUNT(*) c FROM kg_entity").fetchone()["c"]
        n_rel = conn.execute("SELECT COUNT(*) c FROM kg_relation").fetchone()["c"]
        dup = conn.execute(
            "SELECT COUNT(*) c FROM (SELECT src_id, rel, dst_id FROM kg_relation "
            "GROUP BY src_id, rel, dst_id HAVING COUNT(*) > 1)").fetchone()["c"]
    assert n_ent == first["entities"] and n_rel == first["relations"]
    assert dup == 0, "同一 (src, rel, dst) 不得出现重复边"


# ------------------------------------------------------------ 3. 实体反查（核心价值）

def test_query_entity_returns_issue_and_knowledge(fresh_db):
    """「电梯」：同时查出含电梯的工单与含电梯的政策（这就是图谱的价值）。"""
    from data.db_kg import build_graph, query_entity
    _add_issue("3号楼电梯故障停运", location="3号楼2单元", description="电梯停运，高层老人出行困难",
               category="设施维修")
    _add_knowledge("电梯年度检修与维保口径", "电梯维保单位每月巡检一次，故障停运需 24 小时内响应。",
                   keywords="电梯,检修", category="公共设施")
    build_graph(limit=100)
    r = query_entity("电梯")
    assert r["found"] and r["match_mode"] == "single"
    assert any("电梯" in i["title"] for i in r["related_issues"])
    assert any("电梯" in k["title"] for k in r["related_knowledge"])
    # 关联实体：楼栋（3号楼）与工单类别（设施维修）都应在
    names = {e["name"] for e in r["related_entities"]}
    assert "3号楼" in names and "设施维修" in names
    assert "电梯" in r["summary"] and r["summary"].count("工单") >= 1
    # 查不到的实体：不编造，给提示
    miss = query_entity("火星移民")
    assert miss["found"] is False and miss["hint"]


def test_query_entity_compound_intersection(fresh_db):
    """「3号楼电梯」复合查询取交集：只返回同时提到 3号楼 与 电梯 的工单。"""
    from data.db_kg import build_graph, query_entity
    _add_issue("3号楼电梯故障停运", location="3号楼", description="电梯停运")
    _add_issue("5号楼电梯异响", location="5号楼", description="电梯异响")
    _add_issue("3号楼水管漏水", location="3号楼", description="水管漏水")
    build_graph(limit=100)
    r = query_entity("3号楼电梯")
    assert r["found"] and r["match_mode"] == "all"
    titles = [i["title"] for i in r["related_issues"]]
    assert any("3号楼电梯" in t for t in titles)
    assert not any("5号楼" in t for t in titles), "交集查询不应带出 5号楼 的工单"
    assert not any("水管" in t for t in titles), "交集查询不应带出同楼栋的其它问题"
    # 子串扩展：查「老人」应能带出更具体的人群实体（独居老人）
    _add_issue("11号楼独居老人需要助餐", location="11号楼", description="独居老人行动不便", category="社区事务")
    build_graph(limit=100)
    r2 = query_entity("老人")
    assert r2["found"]
    assert {e["name"] for e in r2["entities"]} >= {"独居老人"}
    assert any("独居老人" in i["title"] for i in r2["related_issues"])


def test_query_entity_empty_graph_is_honest(fresh_db):
    """未建图时如实返回空 + 提示（不假装查到了数据）。"""
    from data.db_kg import graph_stats, query_entity
    st = graph_stats()
    assert st["entities"] == 0 and st["relations"] == 0
    r = query_entity("电梯")
    assert r["found"] is False
    assert "尚未构建" in r["hint"]
    assert r["related_issues"] == [] and r["related_knowledge"] == []


# ------------------------------------------------------------ 4. 规模统计

def test_graph_stats_structure(fresh_db):
    """统计结构：实体/关系/引用数 + 类型分布 + 关系分布 + top 实体 + 工单覆盖率。"""
    from data.db_kg import build_graph, graph_stats
    _add_issue("3号楼电梯故障", location="3号楼", description="电梯停运", category="设施维修")
    _add_issue("楼道堆物堵塞消防通道", location="3号楼2单元楼道", description="杂物堆积",
               category="安全隐患")
    _add_knowledge("高龄津贴申领指南", "高龄老人可申领高龄津贴，需携带身份证到社区办理。",
                   keywords="高龄津贴", category="养老服务")
    build_graph(limit=100)
    st = graph_stats()
    for key in ("entities", "relations", "mentions", "by_type", "by_rel", "by_ref_type",
                "top_entities", "built_at", "coverage", "entity_types", "rel_types"):
        assert key in st, f"统计缺字段 {key}"
    assert st["entities"] >= 4 and st["relations"] >= 3
    assert "building" in st["by_type"] and "facility" in st["by_type"]
    assert st["by_rel"].get("has_facility", 0) >= 1
    assert st["by_rel"].get("related_issue", 0) >= 1
    assert st["by_ref_type"].get("issue", 0) >= 1
    assert st["top_entities"] and "degree" in st["top_entities"][0]
    assert st["built_at"], "应记录建图时间"
    assert st["coverage"]["issues_total"] == 2
    assert st["coverage"]["issues_covered"] == 2
    assert st["coverage"]["issue_coverage"] == 100.0


# ------------------------------------------------------------ 5. 端点权限

@pytest.fixture(scope="module")
def client():
    """端点测试用 TestClient（与 test_kb_metrics 同模式，模块级）。"""
    from fastapi.testclient import TestClient
    import api_web
    with TestClient(api_web.app) as c:
        yield c


def test_kg_endpoints_permission(fresh_db, client):
    """端点：居民一律 1003 无权限；grid 200（且全程只写临时库）。"""
    from api_routes.deps import make_token
    _add_issue("3号楼电梯故障停运", location="3号楼2单元", description="电梯停运", category="设施维修")
    rh = {"Authorization": f"Bearer {make_token(9001, 'resident', '测试居民')}"}
    gh = {"Authorization": f"Bearer {make_token(9002, 'grid', '测试网格员')}"}

    # 居民：三个端点全部拒绝
    assert client.get("/api/web/agent/kg/stats", headers=rh).json()["code"] == 1003
    assert client.get("/api/web/agent/kg/entity?name=电梯", headers=rh).json()["code"] == 1003
    assert client.post("/api/web/agent/kg/rebuild", headers=rh).json()["code"] == 1003

    # grid：重建 → 统计 → 查询
    r = client.post("/api/web/agent/kg/rebuild?limit=100", headers=gh)
    assert r.status_code == 200 and r.json()["success"]
    assert r.json()["data"]["entities"] >= 2

    r = client.get("/api/web/agent/kg/stats", headers=gh)
    assert r.status_code == 200 and r.json()["success"]
    assert r.json()["data"]["entities"] >= 2

    r = client.get("/api/web/agent/kg/entity?name=电梯", headers=gh)
    assert r.status_code == 200 and r.json()["success"]
    data = r.json()["data"]
    assert data["found"] and data["related_issues"]
    assert "3号楼电梯故障停运" in data["related_issues"][0]["title"]

    # 缺参数：明确报错而不是查全表
    assert client.get("/api/web/agent/kg/entity", headers=gh).json()["code"] == 1003

    # 隔离证明：本用例写的是临时库，不是生产库 data/community_insight.db
    import config
    assert db_core._DB_PATH != config.DB_PATH
