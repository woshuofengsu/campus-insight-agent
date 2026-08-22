# data/db_llm_usage.py
"""LLM 用量统计（P2-05，适配项目：Web 端 Agent 为规则引擎零 LLM 调用，此表记录 engine.py LLM 链路用量，
证明「规则优先」降本；同时支持任何 LLM 调用点记账）。"""
import logging

from data.database import get_db

_log = logging.getLogger(__name__)

# 演示单价（元/千 token）：输入便宜、输出贵（DeepSeek 级）
_PRICE_IN = 0.001
_PRICE_OUT = 0.002

_CACHE = {}


def record_usage(module: str, tokens_in: int, tokens_out: int,
                 duration_ms: int = 0, cache_hit: bool = False,
                 input_preview: str = "") -> int:
    """记录一次 LLM 调用（或缓存命中）。"""
    cost = (tokens_in * _PRICE_IN + tokens_out * _PRICE_OUT) / 1000.0
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO llm_usage (module, tokens_in, tokens_out, cost_yuan, duration_ms, "
            "cache_hit, input_preview) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (module, int(tokens_in), int(tokens_out), round(cost, 4),
             int(duration_ms), 1 if cache_hit else 0, (input_preview or "")[:80]),
        )
        conn.commit()
        return cur.lastrowid


def record_cache_hit(module: str, input_preview: str = "") -> int:
    """缓存命中记账（不消耗 token，用于展示缓存有效性）。"""
    return record_usage(module, 0, 0, duration_ms=0, cache_hit=True, input_preview=input_preview)


def get_usage_summary(days: int = 7) -> dict:
    """近 N 天用量汇总（调用数/token/费用/缓存命中）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) calls, SUM(tokens_in) tin, SUM(tokens_out) tout, "
            "SUM(cost_yuan) cost, SUM(cache_hit) hits "
            "FROM llm_usage WHERE created_at >= datetime('now', ? || ' days')",
            (f"-{days}",),
        ).fetchone()
        return {
            "days": days,
            "calls": row["calls"] or 0,
            "tokens_in": row["tin"] or 0,
            "tokens_out": row["tout"] or 0,
            "cost_yuan": round(row["cost"] or 0, 4),
            "cache_hits": row["hits"] or 0,
        }


def get_usage_trend(days: int = 7) -> list[dict]:
    """近 N 天按日调用/费用趋势。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DATE(created_at, 'localtime') d, COUNT(*) calls, SUM(cost_yuan) cost "
            "FROM llm_usage WHERE created_at >= datetime('now', ? || ' days') "
            "GROUP BY d ORDER BY d", (f"-{days}",),
        ).fetchall()
        return [{"day": r["d"], "calls": r["calls"], "cost": round(r["cost"] or 0, 4)} for r in rows]
