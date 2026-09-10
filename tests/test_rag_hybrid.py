# -*- coding: utf-8 -*-
"""U1 混合检索测试：同义词扩展 / 词法降级 / 语义向量加分 / RRF 融合 / 评测脚本。

设计要点（可证伪）：
  - provider=none（默认）时必须与升级前行为一致（纯词法，不报错）
  - provider 可用时词法 + 语义双路融合，结果带 source_route 标记
  - 任何 embedding 失败都降级，不抛异常
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from data import db_core


@pytest.fixture()
def fresh_db():
    """每个用例在临时库上运行；teardown 恢复 db_core 全局路径。"""
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="rag_hybrid_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "rag.db"))
    yield
    db_core._DB_PATH = orig


def _seed_knowledge():
    """造两条已发布条目：一条讲「增设电梯」，一条讲「垃圾分类」。

    注意：category 必须属于 POLICY_CATEGORIES（社保医保/养老服务/住房保障/办事指引/社区规定）。
    """
    from data.db_policy import create_knowledge
    from data.db_core import get_db
    k1, e1 = create_knowledge(
        title="既有多层住宅增设电梯实施办法", category="住房保障",
        plain_interpretation="老楼加装电梯需本单元业主协商一致，费用按楼层分摊。",
        source="公开政策", keywords="增设电梯,加装电梯,费用分摊", effective_date="2020-01-01",
        content="既有多层住宅增设电梯应当经本单元业主依法协商，费用分摊方案由业主约定。",
        actor="测试")
    k2, e2 = create_knowledge(
        title="生活垃圾分类管理要求", category="社区规定",
        plain_interpretation="生活垃圾需按四分类投放，定时定点清运。",
        source="公开政策", keywords="垃圾分类,清运,垃圾桶", effective_date="2020-05-01",
        content="生活垃圾分为厨余垃圾、可回收物、有害垃圾、其他垃圾四类。", actor="测试")
    assert not e1 and not e2, (e1, e2)
    with get_db() as conn:
        conn.execute("UPDATE knowledge_base SET audit_status='已发布' WHERE id IN (?,?)", (k1, k2))
        conn.commit()
    return k1, k2


# ---------- 同义词扩展（零依赖，立刻生效） ----------

def test_expand_query_maps_colloquial_to_policy_terms():
    from utils.text import expand_query
    out = expand_query("老楼装电梯怎么申请")
    assert "增设电梯" in out and "加装电梯" in out     # 口语 → 政策书面语
    assert out.startswith("老楼装电梯怎么申请")        # 只加词不改词
    # 无命中则原样返回
    assert expand_query("今天天气不错") == "今天天气不错"
    # 不重复追加已存在的词
    out2 = expand_query("加装电梯费用怎么分摊")
    assert out2.count("加装电梯") == 1


def test_synonym_expansion_improves_recall(fresh_db):
    """口语查询（老楼装电梯）应能召回标题含「增设电梯」的条目。"""
    _seed_knowledge()
    from data.db_policy import search_published_knowledge
    results = search_published_knowledge("老楼装电梯怎么申请", top_k=3)
    assert results, "同义词扩展后应有召回结果"
    assert "电梯" in (results[0]["title"] or "")


# ---------- 混合检索（provider 默认关闭 → 纯词法，行为与升级前一致） ----------

def test_search_hybrid_lexical_by_default(fresh_db):
    _seed_knowledge()
    from agent.rag import search_hybrid
    from utils.embedding import is_enabled
    assert is_enabled() is False, "默认应为 none（无 provider 无 key）"
    results = search_hybrid("垃圾分类怎么投", top_k=3)
    assert results, "词法路径应有结果"
    assert results[0]["source_route"] == "sparse"
    assert "垃圾" in results[0]["title"]


def test_search_hybrid_no_result_falls_back_to_keyword(fresh_db):
    """无向量索引时仍能工作（走词法），完全不匹配时返回空而不报错。"""
    _seed_knowledge()
    from agent.rag import search_hybrid
    assert search_hybrid("完全不相关的火星移民政策", top_k=3) == []


def test_dense_boost_empty_when_disabled(fresh_db):
    _seed_knowledge()
    from data.db_policy import _dense_boost
    assert _dense_boost("电梯", []) == {}
    from data.db_core import get_db
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM knowledge_base")]
    assert _dense_boost("电梯", rows) == {}


# ---------- 语义向量加分（注入假向量验证融合路径） ----------

def test_dense_boost_with_injected_vectors(fresh_db, monkeypatch):
    """注入假向量 + 启用 provider → 语义分生效、路线标记为 hybrid。"""
    k1, k2 = _seed_knowledge()
    from agent.rag import _ensure_embedding_table
    from data.db_core import get_db
    import json
    # 构造：k2（垃圾分类）语义向量与查询向量高度一致，k1 相反 → 语义应把 k2 顶上来
    with get_db() as conn:
        _ensure_embedding_table(conn)
        conn.execute("INSERT OR REPLACE INTO kb_embeddings (kb_id, ngrams_json, dense_json, dim, provider) "
                     "VALUES (?, '[]', ?, 3, 'fake')", (k1, json.dumps([0.0, 0.0, 1.0])))
        conn.execute("INSERT OR REPLACE INTO kb_embeddings (kb_id, ngrams_json, dense_json, dim, provider) "
                     "VALUES (?, '[]', ?, 3, 'fake')", (k2, json.dumps([1.0, 0.0, 0.0])))
        conn.commit()

    from utils import embedding as E
    monkeypatch.setattr(E, "is_enabled", lambda: True)
    monkeypatch.setattr(E, "embed_query", lambda q: [1.0, 0.0, 0.0])
    monkeypatch.setattr(E, "get_provider", lambda: "fake")
    monkeypatch.setattr(E, "get_model", lambda: "fake-3d")

    from data.db_policy import search_published_knowledge, _dense_boost
    from data.db_core import get_db as _g
    with _g() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM knowledge_base")]
    boost = _dense_boost("随便问", rows)
    assert boost.get(k2, 0) > boost.get(k1, 1)          # 语义分：k2 高于 k1
    results = search_published_knowledge("随便问", top_k=2)
    assert results and results[0]["retrieval"] == "hybrid"


def test_gdr_hybrid_route_label(fresh_db, monkeypatch):
    """agent.rag.search_hybrid 在语义可用时给出 sparse+dense 路线标记。"""
    k1, k2 = _seed_knowledge()
    from agent.rag import _ensure_embedding_table, search_hybrid
    from data.db_core import get_db
    import json
    with get_db() as conn:
        _ensure_embedding_table(conn)
        conn.execute("INSERT OR REPLACE INTO kb_embeddings (kb_id, ngrams_json, dense_json, dim, provider) "
                     "VALUES (?, '[]', ?, 3, 'fake')", (k1, json.dumps([1.0, 0.0, 0.0])))
        conn.execute("INSERT OR REPLACE INTO kb_embeddings (kb_id, ngrams_json, dense_json, dim, provider) "
                     "VALUES (?, '[]', ?, 3, 'fake')", (k2, json.dumps([0.0, 1.0, 0.0])))
        conn.commit()
    from utils import embedding as E
    monkeypatch.setattr(E, "is_enabled", lambda: True)
    monkeypatch.setattr(E, "embed_query", lambda q: [1.0, 0.0, 0.0])
    results = search_hybrid("电梯", top_k=2)
    assert results
    assert "dense" in results[0]["source_route"]


# ---------- embedding 不可用时必须优雅降级 ----------

def test_embedding_disabled_returns_none(monkeypatch):
    from utils import embedding as E
    monkeypatch.setattr(E, "get_provider", lambda: "none")
    monkeypatch.setattr(E, "get_api_key", lambda: "")
    assert E.is_enabled() is False
    assert E.embed_texts(["x"]) is None
    assert E.embed_query("x") is None
    assert E.cosine([], []) == 0.0


def test_embedding_failure_degrades(monkeypatch):
    """provider 声称可用但请求失败 → embed_texts 返回 None（不抛异常）。"""
    from utils import embedding as E
    monkeypatch.setattr(E, "get_provider", lambda: "bailian")
    monkeypatch.setattr(E, "get_api_key", lambda: "fake-key")
    monkeypatch.setattr(E, "_post_batch", lambda texts: None)
    assert E.is_enabled() is True
    assert E.embed_texts(["x"]) is None


def test_embedding_cache_hit(monkeypatch):
    """查询向量应命中进程内缓存（不重复计费）。"""
    from utils import embedding as E
    calls = {"n": 0}

    def fake_post(texts):
        calls["n"] += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(E, "get_provider", lambda: "bailian")
    monkeypatch.setattr(E, "get_api_key", lambda: "fake-key")
    monkeypatch.setattr(E, "_post_batch", fake_post)
    E._QUERY_CACHE.clear()
    assert E.embed_query("同一个问题") == [0.1, 0.2, 0.3]
    assert E.embed_query("同一个问题") == [0.1, 0.2, 0.3]
    assert calls["n"] == 1, "第二次应命中缓存"


# ---------- 评测脚本 ----------

def test_rag_eval_runs(fresh_db):
    """rag_eval 能跑通并返回命中率（golden 集非空）。"""
    from scripts.rag_eval import load_golden, run
    cases = load_golden()
    assert len(cases) >= 20, "RAG golden 集应不少于 20 条"
    r = run(topk=3)
    assert r["cases"] == len(cases)
    assert 0 <= r["hit_rate"] <= 100
    assert "embedding" in r and "provider" in r["embedding"]
