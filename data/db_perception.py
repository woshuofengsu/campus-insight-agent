# data/db_perception.py
"""🧠 背景感知模块 — 定期扫描社区数据，生成感知洞察.

触发机制:
  - 任意用户访问任意页面 → init_session() → 检查距上次扫描是否超过阈值
  - 超过阈值 → 自动执行感知扫描 → 结果存入 perception_log
  - 感知结果在「社区脉搏」页和网格员「工作台」展示

感知管线:
  1. 趋势分析 — 本周 vs 上周工单量/分类对比
  2. 异常检测 — 某分类/地点突然激增
  3. 积压预警 — 超期未处理工单
  4. 舆情快照 — 近期反馈情绪分布
"""
import json
import logging
from datetime import datetime, timedelta
from data.db_core import get_db

_log = logging.getLogger(__name__)

# ── 默认扫描间隔（分钟）──
DEFAULT_SCAN_INTERVAL_MINUTES = 30

# ── 异常检测阈值 ──
ANOMALY_SPIKE_RATIO = 2.5    # 某分类当日新增 > 日均 × 2.5 → 异常
ANOMALY_MIN_COUNT = 3        # 至少达到此数量才触发异常
# SLA 超期口径已收敛到 data/db_sla.py（极急6h / 紧急24h / 普通72h），
# 此处不再维护独立的 SLA_WARNING_DAYS / SLA_CRITICAL_DAYS 常量。


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _n_days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def get_perception_status() -> dict:
    """返回扫描状态: 上次扫描时间、是否需要重新扫描."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT run_at FROM perception_log ORDER BY run_at DESC LIMIT 1"
        ).fetchone()

    if not row:
        return {
            "last_run": None,
            "last_run_display": "从未扫描",
            "due": True,
            "minutes_since": None,
        }

    last_run = row["run_at"]
    try:
        last_dt = datetime.strptime(last_run[:19], "%Y-%m-%d %H:%M")
        elapsed = (datetime.now() - last_dt).total_seconds() / 60
    except (ValueError, TypeError):
        return {"last_run": last_run, "last_run_display": str(last_run)[:16],
                "due": True, "minutes_since": None}

    return {
        "last_run": last_run,
        "last_run_display": str(last_run)[:16],
        "due": elapsed >= DEFAULT_SCAN_INTERVAL_MINUTES,
        "minutes_since": round(elapsed),
    }


def run_perception_scan(threshold_minutes: int = DEFAULT_SCAN_INTERVAL_MINUTES,
                         force: bool = False) -> dict | None:
    """如距上次扫描超过阈值，执行一次感知扫描。返回感知报告或 None（不需要扫描时）。

    调用位置: ui/session.py init_session() — 任何页面加载都会触发检查。
    """
    status = get_perception_status()

    if not force and not status["due"]:
        return None  # 不需要扫描

    return _do_perception_scan(trigger="auto")


def _do_perception_scan(trigger: str = "auto") -> dict:
    """执行完整的感知扫描管线，结果持久化到 perception_log。"""
    now_str = _now()
    today_str = _today()
    week_ago = _n_days_ago(7)

    with get_db() as conn:
        # -- 1. 基础数据采集 --
        total = conn.execute("SELECT COUNT(*) as cnt FROM community_issues").fetchone()["cnt"]
        pending = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues WHERE status IN ('待处理','处理中')"
        ).fetchone()["cnt"]
        today_new = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues WHERE date(reported_at) = ?", (today_str,)
        ).fetchone()["cnt"]
        today_resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues WHERE status='已解决' AND date(resolved_at) = ?",
            (today_str,),
        ).fetchone()["cnt"]

        # -- 2. 趋势分析 — 本周 vs 上周 --
        this_week_new = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues WHERE date(reported_at) >= ?",
            (week_ago,),
        ).fetchone()["cnt"]
        this_week_resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues "
            "WHERE status='已解决' AND date(resolved_at) >= ?",
            (week_ago,),
        ).fetchone()["cnt"]

        # 上周同期 (14天前到7天前)
        two_weeks_ago = _n_days_ago(14)
        last_week_new = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues "
            "WHERE date(reported_at) >= ? AND date(reported_at) < ?",
            (two_weeks_ago, week_ago),
        ).fetchone()["cnt"]
        last_week_resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues "
            "WHERE status='已解决' AND date(resolved_at) >= ? AND date(resolved_at) < ?",
            (two_weeks_ago, week_ago),
        ).fetchone()["cnt"]

        # 趋势方向
        if this_week_new > last_week_new * 1.3:
            trend = "rising"
            trend_label = "上升"
        elif this_week_new < last_week_new * 0.7:
            trend = "declining"
            trend_label = "下降"
        else:
            trend = "stable"
            trend_label = "平稳"

        resolution_rate = round(this_week_resolved / max(1, this_week_new) * 100)

        # -- 3. 异常检测 — 分类/地点激增 --
        anomalies: list[dict] = []

        # 3a. 分类激增检测：今日各分类 vs 近7天日均
        today_cats = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM community_issues "
            "WHERE date(reported_at) = ? GROUP BY category",
            (today_str,),
        ).fetchall()

        for row in today_cats:
            cat = row["category"]
            today_cnt = row["cnt"]
            # 近7天该分类日均
            week_total = conn.execute(
                "SELECT COUNT(*) as cnt FROM community_issues "
                "WHERE category = ? AND date(reported_at) >= ? AND date(reported_at) < ?",
                (cat, week_ago, today_str),
            ).fetchone()["cnt"]
            avg_daily = week_total / max(1, 6)  # exclude today

            if today_cnt >= ANOMALY_MIN_COUNT and today_cnt > avg_daily * ANOMALY_SPIKE_RATIO:
                anomalies.append({
                    "type": "category_spike",
                    "category": cat,
                    "today_count": today_cnt,
                    "avg_daily": round(avg_daily, 1),
                    "message": f"「{cat}」分类今日激增至 {today_cnt} 件（日均 {avg_daily:.1f} 件）",
                    "level": "warning",
                })

        # 3b. 地点激增
        today_locs = conn.execute(
            "SELECT location, COUNT(*) as cnt FROM community_issues "
            "WHERE date(reported_at) = ? AND location != '' GROUP BY location",
            (today_str,),
        ).fetchall()

        for row in today_locs:
            loc = row["location"]
            today_cnt = row["cnt"]
            if today_cnt >= ANOMALY_MIN_COUNT:
                week_total = conn.execute(
                    "SELECT COUNT(*) as cnt FROM community_issues "
                    "WHERE location = ? AND date(reported_at) >= ? AND date(reported_at) < ?",
                    (loc, week_ago, today_str),
                ).fetchone()["cnt"]
                avg_daily = week_total / max(1, 6)
                if today_cnt > avg_daily * ANOMALY_SPIKE_RATIO:
                    anomalies.append({
                        "type": "location_spike",
                        "location": loc,
                        "today_count": today_cnt,
                        "avg_daily": round(avg_daily, 1),
                        "message": f"「{loc}」今日上报激增至 {today_cnt} 件（日均 {avg_daily:.1f} 件）",
                        "level": "warning",
                    })

        # -- 4. 积压预警 — SLA 超期工单（分级口径统一走 data/db_sla.py）--
        from data.db_sla import get_sla_summary
        _sla = get_sla_summary()
        overdue_critical = _sla["critical_overdue"]   # 极急/紧急 超时
        overdue_warning = _sla["normal_overdue"]      # 普通 超时

        if overdue_critical > 0:
            anomalies.append({
                "type": "sla_critical",
                "count": overdue_critical,
                "message": f"{overdue_critical} 件紧急工单已超时未处理",
                "level": "critical",
            })
        elif overdue_warning > 2:
            anomalies.append({
                "type": "sla_warning",
                "count": overdue_warning,
                "message": f"{overdue_warning} 件普通工单已超时未处理",
                "level": "warning",
            })

        # -- 5. 舆情快照 — 近期反馈情绪 --
        sentiment_rows = conn.execute(
            "SELECT sentiment, COUNT(*) as cnt FROM feedback_items "
            "WHERE created_at >= ? GROUP BY sentiment",
            (week_ago,),
        ).fetchall()
        sentiment_dist = {r["sentiment"]: r["cnt"] for r in sentiment_rows}
        pos = sentiment_dist.get("正面", 0)
        neg = sentiment_dist.get("负面", 0)
        neu = sentiment_dist.get("中性", 0)
        total_fb = pos + neg + neu
        sentiment_ratio = round(pos / max(1, total_fb) * 100) if total_fb else 50

        # -- 6. 提案动态 --
        proposals_active = conn.execute(
            "SELECT COUNT(*) as cnt FROM proposals WHERE status='讨论中'"
        ).fetchone()["cnt"]
        proposals_new = conn.execute(
            "SELECT COUNT(*) as cnt FROM proposals WHERE date(created_at) >= ?",
            (week_ago,),
        ).fetchone()["cnt"]

        # -- 7. 生成综合摘要 --
        key_findings: list[str] = []

        # Trend finding
        if trend == "rising":
            key_findings.append(
                f"📈 近7天新增工单 {this_week_new} 件，较上周（{last_week_new} 件）明显上升"
            )
        elif trend == "declining":
            key_findings.append(
                f"📉 近7天新增工单 {this_week_new} 件，较上周（{last_week_new} 件）下降，社区运转改善"
            )
        else:
            key_findings.append(
                f"📊 近7天新增工单 {this_week_new} 件，与上周持平，社区运转平稳"
            )

        if resolution_rate >= 70:
            key_findings.append(f"✅ 近7天解决率 {resolution_rate}%，处理效率良好")
        elif resolution_rate < 40:
            key_findings.append(f"⚠️ 近7天解决率仅 {resolution_rate}%，需关注处理效率")

        if pending > 10:
            key_findings.append(f"⏳ 当前 {pending} 件工单待处理")

        if proposals_new > 0:
            key_findings.append(f"💡 近7天新增 {proposals_new} 件提案，{proposals_active} 件讨论中")

        if total_fb > 0:
            mood = "积极" if sentiment_ratio >= 60 else "一般" if sentiment_ratio >= 40 else "需要关注"
            key_findings.append(f"💬 近7天居民反馈情绪：{mood}（正面率 {sentiment_ratio}%）")

        # Anomaly findings
        for a in anomalies:
            key_findings.append(f"{'🔴' if a['level'] == 'critical' else '🟡'} {a['message']}")

        # Overall summary (1-line)
        if not anomalies and trend in ("stable", "declining"):
            overall = f"🌿 社区运转正常 · {today_new} 件新增 · 解决率 {resolution_rate}%"
        elif anomalies:
            crits = [a for a in anomalies if a["level"] == "critical"]
            if crits:
                overall = f"🚨 {crits[0]['message'][:40]} · 共 {len(anomalies)} 项需关注"
            else:
                overall = f"⚠️ {len(anomalies)} 项异常需关注 · 社区基本正常"
        else:
            overall = f"📊 社区运转平稳 · {today_new} 件新增 · 待处理 {pending} 件"

        # -- 8. 持久化 --
        details = {
            "this_week_new": this_week_new,
            "this_week_resolved": this_week_resolved,
            "last_week_new": last_week_new,
            "last_week_resolved": last_week_resolved,
            "resolution_rate": resolution_rate,
            "trend_label": trend_label,
            "sentiment_distribution": sentiment_dist,
            "sentiment_ratio": sentiment_ratio,
            "overdue_warning": overdue_warning,
            "overdue_critical": overdue_critical,
            "proposals_active": proposals_active,
            "proposals_new": proposals_new,
        }

        conn.execute(
            "INSERT INTO perception_log (run_at, trigger, overall_summary, trend_direction, "
            "anomaly_count, key_findings, details_json, issues_total, issues_pending, "
            "issues_new_today) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now_str, trigger, overall, trend, len(anomalies),
             json.dumps(key_findings, ensure_ascii=False),
             json.dumps(details, ensure_ascii=False),
             total, pending, today_new),
        )
        conn.commit()

        # -- 9. 记录到活动日志 --
        try:
            from data.db_notifications import log_activity
            log_activity(
                "系统感知", "定时扫描",
                target_type="perception",
                detail=f"发现 {len(anomalies)} 项异常 · {today_new} 件新增工单",
            )
        except Exception:  # best-effort, skip
            _log.debug("Failed to log activity for perception scan", exc_info=True)
            pass

    result = {
        "run_at": now_str,
        "trigger": trigger,
        "overall_summary": overall,
        "trend_direction": trend,
        "trend_label": trend_label,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "key_findings": key_findings,
        "details": details,
        "issues_total": total,
        "issues_pending": pending,
        "issues_new_today": today_new,
    }

    _log.info("Perception scan complete: %s", overall)
    return result


def get_latest_perception() -> dict | None:
    """获取最近一次感知扫描结果."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM perception_log ORDER BY run_at DESC LIMIT 1"
        ).fetchone()

    if not row:
        return None

    r = dict(row)
    # 反序列化 JSON 字段
    for field in ("key_findings", "details_json"):
        raw = r.get(field, "[]")
        if isinstance(raw, str):
            try:
                r[field.replace("_json", "")] = json.loads(raw)
            except json.JSONDecodeError:
                r[field.replace("_json", "")] = []

    # details_json → details
    if "details_json" in r and "details" not in r:
        try:
            r["details"] = json.loads(r["details_json"]) if isinstance(r["details_json"], str) else r["details_json"]
        except json.JSONDecodeError:
            r["details"] = {}

    if "key_findings" not in r:
        r["key_findings"] = []

    # 计算距离上次扫描的时间
    run_at = r.get("run_at", "")
    if run_at:
        try:
            run_dt = datetime.strptime(str(run_at)[:19], "%Y-%m-%d %H:%M")
            r["minutes_ago"] = round((datetime.now() - run_dt).total_seconds() / 60)
        except (ValueError, TypeError):
            r["minutes_ago"] = None

    return r


def get_perception_history(limit: int = 10) -> list[dict]:
    """获取历史感知记录."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, run_at, trigger, overall_summary, trend_direction, "
            "anomaly_count, issues_total, issues_pending, issues_new_today "
            "FROM perception_log ORDER BY run_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def force_perception_scan() -> dict:
    """手动触发一次感知扫描（从 UI 按钮调用）."""
    return _do_perception_scan(trigger="manual")
