# data/db_kb_metrics.py
"""知识库健康度（U3）：让 RAG 可量化、可证伪。

指标口径：
  - 查询总数 / 命中数 / 命中率（matched=1 占比）
  - 平均最佳匹配分、检索路线分布（lexical / hybrid）
  - **零命中问题 top N**（未命中问题按文本聚合，直接指出知识库缺口）
  - 知识库规模与主题分布（已发布条数 / 分类分布 / 90 天内到期提醒数）

数据来源：`kb_query_log`（v43，记录每次检索尝试，含未命中）。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)


def get_kb_health(days: int = 7, top_n: int = 10, tenant: str | None = None) -> dict:
    """知识库健康度（近 days 天）。任何异常都返回零值结构，不影响页面。

    多租户（Codex 评审 I1）：**居民提问的聚合只算本社区**——
    `kb_query_log` 存的是居民问题原文，原来"零命中问题榜"把所有社区的问题聚合在一起，
    等于让每个社区的网格员都能读到别社区居民问了什么。知识库本身（`knowledge_base`）
    是**跨社区共享**的公开语料，其规模/分类统计保持全局。
    `tenant` 传空串 → 只返回零值结构（fail-closed，不回落到"统计全部"）。
    """
    out = {
        "days": days, "queries": 0, "hits": 0, "hit_rate": 0.0,
        "avg_score": 0.0, "retrieval": {}, "zero_hit_top": [],
        "kb_published": 0, "kb_total": 0, "by_category": {},
        "expiring_soon": 0, "embedding": {},
    }
    try:
        from utils.embedding import describe
        out["embedding"] = describe()
    except Exception:
        pass
    from utils.tenant import normalize_tenant
    scope = normalize_tenant(tenant) if tenant is not None else None
    if tenant is not None and not scope:
        return out          # 身份没有合法社区 → 不返回别社区的问题聚合
    # 社区过滤：kb_query_log 没有租户列，按其归属用户所在社区筛（子查询，避免 N 次往返）
    _scope_sql, _scope_args = "", []
    if scope:
        _scope_sql = (" AND user_id IN (SELECT id FROM user_profile WHERE community=?)")
        _scope_args = [scope]
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c, SUM(CASE WHEN matched=1 THEN 1 ELSE 0 END) h, "
                "AVG(CASE WHEN matched=1 THEN top_score ELSE NULL END) s "
                "FROM kb_query_log WHERE created_at >= datetime('now', ?)" + _scope_sql,
                [f"-{days} days"] + _scope_args).fetchone()
            out["queries"] = row["c"] or 0
            out["hits"] = row["h"] or 0
            out["hit_rate"] = round(out["hits"] * 100.0 / out["queries"], 1) if out["queries"] else 0.0
            out["avg_score"] = round(row["s"], 2) if row["s"] else 0.0

            for r in conn.execute(
                "SELECT retrieval, COUNT(*) c FROM kb_query_log "
                "WHERE created_at >= datetime('now', ?)" + _scope_sql + " GROUP BY retrieval",
                [f"-{days} days"] + _scope_args):
                out["retrieval"][r["retrieval"] or "unknown"] = r["c"]

            # 零命中问题 top N（未命中的问题按原文聚合，指出知识库缺口）
            for r in conn.execute(
                "SELECT question, COUNT(*) c, MAX(top_score) s FROM kb_query_log "
                "WHERE matched=0 AND created_at >= datetime('now', ?)" + _scope_sql +
                " GROUP BY question ORDER BY c DESC, s DESC LIMIT ?",
                [f"-{days} days"] + _scope_args + [top_n]):
                out["zero_hit_top"].append({
                    "question": r["question"], "count": r["c"],
                    "best_score": round(r["s"], 2) if r["s"] else 0.0})

            out["kb_total"] = conn.execute(
                "SELECT COUNT(*) c FROM knowledge_base").fetchone()["c"] or 0
            out["kb_published"] = conn.execute(
                "SELECT COUNT(*) c FROM knowledge_base WHERE audit_status='已发布'").fetchone()["c"] or 0
            for r in conn.execute(
                "SELECT category, COUNT(*) c FROM knowledge_base "
                "WHERE audit_status='已发布' GROUP BY category ORDER BY c DESC"):
                out["by_category"][r["category"] or "未分类"] = r["c"]
            out["expiring_soon"] = conn.execute(
                "SELECT COUNT(*) c FROM knowledge_base WHERE audit_status='已发布' "
                "AND expire_date != '' AND expire_date <= date('now','localtime','+90 days')"
            ).fetchone()["c"] or 0
    except Exception:
        _log.warning("get_kb_health 统计失败", exc_info=True)
    return out


def log_kb_query(user_id: int | None, question: str, matched: bool, reason: str = "",
                 top_score: float = 0.0, top_kb_id: int | None = None,
                 retrieval: str = "", role: str = "resident") -> None:
    """记录一次知识库检索尝试（U3）。失败只记日志，绝不影响业务主流程。

    合规：`question` 是自由文本（居民可能顺口说出手机号），落库前**必须掩码**
    （`utils.text.mask_phones`）——与「全表手机号加密 + 留痕不含完整手机号」既定口径一致。
    """
    safe_q = (question or "")[:200]
    try:
        from utils.text import mask_phones
        safe_q = mask_phones(safe_q)
    except Exception:
        # ⚠️ **隐私类处理必须 fail-closed**（任务卡 5）：原来这里是 `pass` ——
        # 掩码组件一坏，**原文（可能含居民顺口说出的手机号）照样落库**，
        # 等于"脱敏失败时放行"，正是本项目最忌讳的口径（安全校验破了要拒绝，不许放行）。
        # 现在：掩码失败 → **不留原文**（只留一个明确的占位符），并打 warning 让人知道有东西丢了。
        _log.warning("手机号掩码失败 → 本次问题文本不落库（fail-closed，避免明文手机号入 kb_query_log）",
                     exc_info=True)
        safe_q = "[脱敏失败，文本已丢弃]"
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO kb_query_log (user_id, role, question, matched, reason, "
                "top_score, top_kb_id, retrieval) VALUES (?,?,?,?,?,?,?,?)",
                (user_id, role, safe_q, 1 if matched else 0, reason or "",
                 float(top_score or 0), top_kb_id, retrieval or ""),
            )
            conn.commit()
    except Exception:
        _log.debug("记录知识库查询日志失败（已忽略）", exc_info=True)


def clean_kb_query_log(days: int = 90) -> int:
    """清理超期查询日志（调度器调用）。返回删除条数。"""
    try:
        with get_db() as conn:
            cur = conn.execute(
                f"DELETE FROM kb_query_log WHERE created_at < datetime('now', '-{days} days')")
            conn.commit()
            return cur.rowcount
    except Exception:
        _log.warning("清理知识库查询日志失败", exc_info=True)
        return 0
