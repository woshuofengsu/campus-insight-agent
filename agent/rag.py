# agent/rag.py
"""社区知识库的字符 n-gram TF-IDF 检索。

纯 Python 实现，零依赖，中文文本不用 jieba 和 ML 包也能跑。
向量缓存在 SQLite 里，失败时退回关键词 LIKE 搜索。
"""

import math
import re
import sqlite3
import time
import logging
from collections import Counter

from data.db_core import get_db

_log = logging.getLogger(__name__)

# 字符 n-gram 提取

def _char_ngrams(text: str, n: int = 2) -> list[str]:
    """提取字符 n-gram，保留中文和字母数字。"""
    cleaned = re.sub(r'[^一-鿿\w]', '', text.lower())
    if len(cleaned) < n:
        return [cleaned] if cleaned else []
    return [cleaned[i:i + n] for i in range(len(cleaned) - n + 1)]


def _text_to_ngrams(text: str) -> list[str]:
    """同时抽二元组和三元组，匹配更准。"""
    bigrams = _char_ngrams(text, 2)
    trigrams = _char_ngrams(text, 3)
    return bigrams + trigrams


# TF-IDF 计算

def _compute_tf(ngrams: list[str]) -> dict[str, float]:
    """词频（原始计数 → 按文档长度归一化）。"""
    counter = Counter(ngrams)
    total = len(ngrams) or 1
    return {k: v / total for k, v in counter.items()}


def _compute_idf(doc_ngrams_list: list[list[str]]) -> dict[str, float]:
    """逆文档频率，跨所有文档算。"""
    n_docs = len(doc_ngrams_list)
    df: dict[str, int] = {}
    for ngrams in doc_ngrams_list:
        for term in set(ngrams):
            df[term] = df.get(term, 0) + 1
    return {t: math.log((n_docs + 1) / (df[t] + 1)) + 1.0 for t in df}


def _cosine_similarity(vec_a: dict[str, float],
                       vec_b: dict[str, float]) -> float:
    """两个稀疏向量（字典）的余弦相似度。"""
    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in vec_a)
    norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values())) or 1e-10
    norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values())) or 1e-10
    return dot / (norm_a * norm_b)


# 向量缓存表

def _ensure_embedding_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kb_embeddings (
            kb_id INTEGER PRIMARY KEY,
            dense_json TEXT NOT NULL DEFAULT '',
            dim INTEGER DEFAULT 0,
            provider TEXT DEFAULT '',
            ngrams_json TEXT NOT NULL DEFAULT '[]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (kb_id) REFERENCES knowledge_base(id) ON DELETE CASCADE
        )
    """)
    # 语义向量三列（dense_json/dim/provider）由 **db_core v46 迁移**统一保证（复审 P3-D：
    # 运行时裸 ALTER 会让「全新建库」与「存量升级」走两条路径）；这里的建表语句同样带上这三列，
    # 供「直接调 rag、不经 init_db」的场景（如单测）也能拿到完整表结构。
    # 若存量库由旧版本建表，升级时 init_db 的 _m46 会把缺的列补上。


# ---------------------------------------------------------------------------
# U1 混合检索：同义词扩展（零依赖，立刻见效）+ 语义向量（RRF 融合）
# ---------------------------------------------------------------------------

# 同义词表与 expand_query 统一放在 utils/text.py（data 层与 agent 层共用，避免循环导入）
from utils.text import expand_query  # noqa: E402

# RRF 融合常数（Reciprocal Rank Fusion，业界常用 60）
_RRF_K = 60
# 相关性下限：低于此分不入候选（保留升级前的 0.05 词法下限语义，避免无关条目被 RRF 排名后返回）
_SPARSE_MIN = 0.05
_DENSE_MIN = 0.15


def _rank_map(scored: list[tuple[int, float]]) -> dict[int, int]:
    """把 [(id, score)] 降序排序后转成 {id: rank(1-based)}。"""
    ordered = sorted(scored, key=lambda x: -x[1])
    return {kid: i + 1 for i, (kid, _s) in enumerate(ordered)}


def _sparse_scores(query: str, rows: list[dict]) -> list[tuple[int, float]]:
    """词法打分（n-gram TF 余弦，含同义词扩展）。"""
    import json as _json
    q_text = expand_query(query)
    query_tf = _compute_tf(_text_to_ngrams(q_text))
    out: list[tuple[int, float]] = []
    for row in rows:
        try:
            doc_ngrams = _json.loads(row["ngrams_json"]) if row.get("ngrams_json") else []
        except Exception:
            doc_ngrams = []
        if not doc_ngrams:
            doc_ngrams = _text_to_ngrams(
                f"{row.get('title', '')} {row.get('content', '')} {row.get('keywords', '')}")
        if not doc_ngrams:
            continue
        out.append((row["id"], _cosine_similarity(query_tf, _compute_tf(doc_ngrams))))
    return out


def _dense_scores(query: str, rows: list[dict]) -> list[tuple[int, float]] | None:
    """语义打分（需要 provider 可用且条目已有向量）；不可用返回 None。"""
    import json as _json
    from utils import embedding as E
    if not E.is_enabled():
        return None
    vec_rows = [(r["id"], r.get("dense_json") or "") for r in rows]
    if not any(v for _i, v in vec_rows):
        return None  # 尚未建语义索引 → 交给词法
    qv = E.embed_query(query)
    if not qv:
        return None
    out: list[tuple[int, float]] = []
    for kid, raw in vec_rows:
        if not raw:
            continue
        try:
            dv = _json.loads(raw)
        except Exception:
            continue
        out.append((kid, E.cosine(qv, dv)))
    return out or None


def search_hybrid(query: str, top_k: int = 5, category: str | None = None,
                  region=None) -> list[dict]:
    """混合检索（U1）：词法 + 语义双路召回 → RRF 融合排序。

    - 语义路不可用（未配 provider / 未建索引 / 调用失败）→ 自动只用词法（等价于升级前行为）
    - 两路都无结果 → 回退关键词 LIKE 搜索
    返回 [{id,title,content,keywords,category,score,source_route}]，score 为 RRF 分。

    属地化（地区识别 WS3）：传 `region` 后按 `applicable_area` 做**小幅**属地重排
    （RRF 以排名为本，加权限要小，只掰平近同分；级别与权重来自 `utils.region`，
    与线上 `data/db_policy` 共用同一套定义）。`region=None` → 顺序与升级前完全一致。

    ⚠️ 排序口径说明（两套并存、各有用途，勿混用）：
      - **本函数（RRF 融合）**：用于 Agent 侧上下文注入与离线评测（`scripts/rag_eval.py`），
        排序只依赖「词法/语义两路的排名」，不做业务阈值判定。
      - **线上答题**走 `data/db_policy.search_published_knowledge()`：同义词扩展的词法分
        + 语义**加性加分**（最高 +3），再与业务阈值（`get_match_threshold`）比较以决定
        「自动回答 / 弱命中转人工」——它需要可解释、可调阈值的连续分。
      - 二者共享同一批数据与 `utils.embedding`，仅融合算子不同（RRF vs 加权和）。
    """
    try:
        with get_db() as conn:
            _ensure_embedding_table(conn)
            base_sql = ("SELECT k.id, k.title, k.content, k.keywords, k.category, "
                        "k.applicable_area, "
                        "e.ngrams_json, e.dense_json "
                        "FROM knowledge_base k "
                        "LEFT JOIN kb_embeddings e ON k.id = e.kb_id")
            if category:
                rows = [dict(r) for r in conn.execute(base_sql + " WHERE k.category = ?", (category,))]
            else:
                rows = [dict(r) for r in conn.execute(base_sql)]
        if not rows:
            return _fallback_keyword_search(query, top_k, category)

        sparse = [(kid, s) for kid, s in _sparse_scores(query, rows) if s > _SPARSE_MIN]
        dense = _dense_scores(query, rows)
        if dense:
            dense = [(kid, s) for kid, s in dense if s > _DENSE_MIN] or None

        rank_sparse = _rank_map(sparse)
        rank_dense = _rank_map(dense) if dense else {}
        routes = {r["id"]: set() for r in rows}
        fused: dict[int, float] = {}
        for kid, rk in rank_sparse.items():
            fused[kid] = fused.get(kid, 0.0) + 1.0 / (_RRF_K + rk)
            routes[kid].add("sparse")
        for kid, rk in rank_dense.items():
            fused[kid] = fused.get(kid, 0.0) + 1.0 / (_RRF_K + rk)
            routes[kid].add("dense")

        if not fused:
            return _fallback_keyword_search(query, top_k, category)

        by_id = {r["id"]: r for r in rows}
        region_level: dict[int, str] = {}
        if region is not None:
            from utils.region import policy_region_boost, rrf_region_bonus
            for kid in list(fused):
                row = by_id.get(kid) or {}
                _b, level = policy_region_boost(row.get("applicable_area", ""), region)
                region_level[kid] = level
                fused[kid] += rrf_region_bonus(level)
        ordered = sorted(fused.items(), key=lambda x: -x[1])[:top_k]
        results = []
        for kid, fscore in ordered:
            r = by_id.get(kid)
            if not r:
                continue
            route = "+".join(sorted(routes.get(kid) or [])) or "sparse"
            results.append({
                "id": r["id"], "title": r["title"], "content": r["content"],
                "keywords": r["keywords"], "category": r["category"],
                "applicable_area": r.get("applicable_area") or "",
                "region_level": region_level.get(kid, "national"),
                "score": round(fscore, 6), "source_route": route,
            })
        return results or _fallback_keyword_search(query, top_k, category)
    except Exception:
        _log.debug("混合检索失败，退回关键词搜索", exc_info=True)
        return _fallback_keyword_search(query, top_k, category)


def build_dense_index(force: bool = False) -> dict:
    """为知识库条目预计算语义向量并落库（U1）。provider 不可用时返回 skipped。"""
    from utils import embedding as E
    if not E.is_enabled():
        return {"skipped": "embedding provider 未启用（EMBEDDING_PROVIDER=none 或无 key）"}
    try:
        with get_db() as conn:
            _ensure_embedding_table(conn)
            rows = [dict(r) for r in conn.execute(
                "SELECT k.id, k.title, k.content, k.keywords, e.dense_json "
                "FROM knowledge_base k LEFT JOIN kb_embeddings e ON k.id = e.kb_id")]
        todo = [r for r in rows if force or not (r.get("dense_json") or "")]
        if not todo:
            return {"indexed": len(rows), "updated": 0}
        texts = [f"{r['title']} {r['content']} {r.get('keywords') or ''}" for r in todo]
        vecs = E.embed_texts(texts)
        if vecs is None:
            return {"error": "embedding 调用失败（已自动回退词法检索）"}
        import json as _json
        provider = E.get_provider()
        for r, v in zip(todo, vecs):
            with get_db() as conn:
                _ensure_embedding_table(conn)
                conn.execute(
                    "INSERT INTO kb_embeddings (kb_id, ngrams_json, dense_json, dim, provider, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(kb_id) DO UPDATE SET dense_json=excluded.dense_json, "
                    "dim=excluded.dim, provider=excluded.provider, updated_at=CURRENT_TIMESTAMP",
                    (r["id"], _json.dumps(_text_to_ngrams(
                        f"{r['title']} {r['content']} {r.get('keywords') or ''}")),
                     _json.dumps(v), len(v), provider),
                )
                conn.commit()
        return {"indexed": len(rows), "updated": len(todo), "dim": len(vecs[0]) if vecs else 0}
    except Exception as e:  # noqa: BLE001
        _log.warning("build_dense_index 失败：%s", e, exc_info=True)
        return {"error": str(e)}


# 对外接口

def build_index(force: bool = False):
    """给知识库所有条目预计算 n-gram 向量。

    启动时或知识库内容变了之后调一次。
    force=True 表示向量已存在也强制重建。
    """
    try:
        with get_db() as conn:
            _ensure_embedding_table(conn)
            rows = conn.execute(
                "SELECT id, title, content, keywords FROM knowledge_base"
            ).fetchall()
            # 先把行都取出来再遍历（循环里 conn 会被复用）
            row_data = [dict(r) for r in rows]

        updated = 0
        for row in row_data:
            # 看有没有已建的向量
            with get_db() as conn:
                existing = conn.execute(
                    "SELECT kb_id FROM kb_embeddings WHERE kb_id = ?",
                    (row["id"],),
                ).fetchone()
            if existing and not force:
                continue

            # 用标题 + 内容 + 关键词算 n-gram
            text = f"{row['title']} {row['content']} {row.get('keywords', '')}"
            ngrams = _text_to_ngrams(text)
            ngrams_json = __import__('json').dumps(ngrams)

            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO kb_embeddings (kb_id, ngrams_json, updated_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (row["id"], ngrams_json),
                )
                conn.commit()
            updated += 1

        return {"indexed": len(row_data), "updated": updated}
    except Exception as e:
        _log.debug("build_index 失败：%s", e, exc_info=True)
        return {"error": str(e)}


# 说明：U1 起对外统一走 search_hybrid()（词法 + 语义 RRF 融合）。
# 旧的纯词法实现 semantic_search() 已无调用方，于本次清理删除；
# 如需纯词法基线对比，用 scripts/rag_eval.py --no-embedding。


def _fallback_keyword_search(query: str, top_k: int = 5,
                             category: str | None = None) -> list[dict]:
    """兜底：传统 SQL LIKE 搜索。"""
    from data.db_knowledge import search_knowledge
    results = search_knowledge(query, category) if category else search_knowledge(query)
    for r in results:
        r["score"] = 0.0
    return results[:top_k]


def get_rag_context(query: str, top_k: int = 3,
                    category: str | None = None, region=None) -> str:
    """把检索结果拼成一段上下文，注入 LLM 的 prompt。

    标准 RAG 套路：检索相关文档（U1 混合检索：词法+语义 RRF）→ 格式化成上下文 → 塞进 prompt。
    `region`：属地小幅重排（地区识别 WS3），默认 None 与升级前一致。
    """
    results = search_hybrid(query, top_k=top_k, category=category, region=region)
    if not results:
        return ""

    lines = ["以下是社区知识库中与用户问题相关的信息，请基于这些信息回答：", ""]
    for i, r in enumerate(results, 1):
        lines.append(
            f"【{i}】{r['title']}（类别：{r.get('category', '')}，"
            f"相关度：{r.get('score', 0):.2f}）\n{r['content']}\n"
        )
    lines.append("请基于以上信息准确回答用户的问题。如果信息不足以回答，请如实说明。")
    return "\n".join(lines)


def rag_search(query: str, top_k: int = 5,
               category: str | None = None, region=None) -> str:
    """把搜索结果格式化成给人看的字符串（Agent / UI 用）。

    返回 markdown 格式，直接能展示。`region`：属地小幅重排，默认 None 与升级前一致。
    """
    results = search_hybrid(query, top_k=top_k, category=category, region=region)
    if not results:
        return f"未找到与「{query}」相关的社区知识信息。"

    lines = [f"📚 **知识检索**：「{query}」— 找到 {len(results)} 条结果\n"]
    for i, r in enumerate(results, 1):
        score_bar = "█" * min(int(r.get("score", 0) * 20), 10)
        lines.append(
            f"**{i}. {r['title']}**  [{r.get('category', '')}] "
            f"`相关度 {r.get('score', 0):.2f}`\n"
            f"{r['content'][:200]}"
            f"{'...' if len(r.get('content', '')) > 200 else ''}\n"
        )
    return "\n".join(lines)
