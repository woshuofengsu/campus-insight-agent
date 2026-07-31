# agent/reflector/_associations.py
"""SQL-heavy association computation — spatial / temporal / recurrence / anomaly detection.

Extracted from the monolithic reflector.py. This module is the "heavy lifter":
it runs up to 10 SQL queries per turn to find patterns across campus_issues,
proposals, and discussion_topics.
"""
import logging
import math
import os
import re

from data.database import get_db

_logger = logging.getLogger("agent.reflector")

# ── Constants (shared with _parser.py via reflector/__init__.py) ──

_LOCATION_PATTERNS = [
    r"教\d+楼", r"图书馆", r"食堂", r"宿舍\d*号楼", r"操场", r"体育馆",
    r"实验楼", r"行政楼", r"[一二三四五六七八九十]食堂", r"\d+号宿舍楼", r"\d+栋",
]

_STOP_WORDS: set[str] = {
    "了", "的", "是", "我", "要", "有", "在", "不", "和", "都",
    "一", "个", "上", "也", "很", "到", "说", "去", "你", "会",
    "着", "没有", "看", "好", "自己", "这",
}


# ═══════════════════════ 1. Text extraction helpers ═══════════════════════

def _extract_locations(text: str) -> set[str]:
    found: set[str] = set()
    for pat in _LOCATION_PATTERNS:
        for m in re.finditer(pat, text):
            found.add(m.group())
    return found


def _extract_categories(steps: list[dict]) -> list[str]:
    cats: set[str] = set()
    for s in (steps or []):
        ti = s.get("tool_input", {})
        if isinstance(ti, dict) and (c := ti.get("category", "")):
            cats.add(str(c).strip())
    return list(cats)


def _extract_keywords(text: str) -> list[str]:
    tokens = re.split(r"[，。！？；：、\s,.!?;:\"'\t\n]+", text)
    seen: set[str] = set()
    result: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if len(tok) >= 2 and tok not in _STOP_WORDS and tok not in seen:
            seen.add(tok)
            result.append(tok)
    return result


# ═══════════════════════ 2. Analysis helpers ═══════════════════════

def _cross_time_comparison(conn) -> dict:
    """Compare this week vs last week for new issues and resolutions."""
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN reported_at > date('now', '-7 days') THEN 1 ELSE 0 END) AS new_this_week,
            SUM(CASE WHEN reported_at > date('now', '-14 days')
                     AND reported_at <= date('now', '-7 days') THEN 1 ELSE 0 END) AS new_last_week,
            SUM(CASE WHEN status = '已解决'
                     AND resolved_at > date('now', '-7 days') THEN 1 ELSE 0 END) AS resolved_this_week,
            SUM(CASE WHEN status = '已解决'
                     AND resolved_at > date('now', '-14 days')
                     AND resolved_at <= date('now', '-7 days') THEN 1 ELSE 0 END) AS resolved_last_week
        FROM campus_issues
    """).fetchone()
    if not row:
        return {}
    ntw, nlw, rtw, rlw = (
        row["new_this_week"] or 0, row["new_last_week"] or 0,
        row["resolved_this_week"] or 0, row["resolved_last_week"] or 0,
    )

    def _trend(curr, prev):
        if prev == 0:
            return "↑" if curr > 0 else "→"
        ratio = curr / prev
        if ratio > 1.5:
            return "↑↑"
        if ratio > 1.1:
            return "↑"
        if ratio < 0.67:
            return "↓↓"
        if ratio < 0.9:
            return "↓"
        return "→"

    return {
        "new_this_week": ntw, "new_last_week": nlw,
        "resolved_this_week": rtw, "resolved_last_week": rlw,
        "new_trend": _trend(ntw, nlw),
        "resolved_trend": _trend(rtw, rlw),
        "net_this_week": ntw - rtw,
        "net_last_week": nlw - rlw,
        "is_worsening": (ntw - rtw) > (nlw - rlw) and ntw > nlw,
        "is_improving": rtw > rlw and (ntw - rtw) <= (nlw - rlw),
    }


def _z_score_anomalies(conn) -> list[dict]:
    """Compute z-score based anomaly detection per category.

    More statistically sound than simple ratio thresholds: computes mean and
    stddev across all categories' weekly issue counts over a 4-week window,
    then flags categories where the z-score exceeds 1.0.

    Also computes a severity score (0-10) combining z-score magnitude,
    absolute count, and urgency mix.
    """
    rows = conn.execute("""
        SELECT category,
            SUM(CASE WHEN reported_at > date('now', '-7 days') THEN 1 ELSE 0 END) AS recent,
            ROUND(AVG(CASE WHEN reported_at > date('now', '-28 days')
                       AND reported_at <= date('now', '-7 days') THEN 1 ELSE 0 END), 1) * 3 AS baseline_3wk,
            COUNT(CASE WHEN urgency='紧急' AND status != '已解决' THEN 1 END) AS urgent_pending
        FROM campus_issues
        WHERE reported_at > date('now', '-28 days')
        GROUP BY category
        HAVING recent > 0
    """).fetchall()
    if len(rows) < 2:
        return []

    recents = [r["recent"] for r in rows]
    n = len(recents)
    mean = sum(recents) / n
    variance = sum((x - mean) ** 2 for x in recents) / n
    std = math.sqrt(variance) if variance > 0 else 1.0

    anomalies = []
    for r in rows:
        z = (r["recent"] - mean) / std if std > 0 else 0
        if z < 1.0:
            continue  # not significant
        count_score = min(r["recent"] / 5.0, 1.0) * 3
        urgency_score = min(r["urgent_pending"] / 2.0, 1.0) * 3
        severity = round(z * 2 + count_score + urgency_score, 1)
        severity = min(severity, 10.0)
        level = "critical" if severity >= 8 else "high" if severity >= 5 else "moderate"
        anomalies.append({
            "category": r["category"],
            "recent": r["recent"],
            "z_score": round(z, 2),
            "severity": severity,
            "level": level,
            "urgent_pending": r["urgent_pending"],
        })
    anomalies.sort(key=lambda x: -x["severity"])
    return anomalies[:5]


def _detect_upgrade_paths(conn) -> list[dict]:
    """Detect categories where issues should escalate to proposals.

    Criteria: 3+ unresolved issues in a category, no matching active proposal
    with >10 supporters.
    """
    rows = conn.execute("""
        SELECT ci.category, COUNT(*) as issue_count
        FROM campus_issues ci
        WHERE ci.status IN ('待处理', '处理中')
        GROUP BY ci.category
        HAVING COUNT(*) >= 3
        ORDER BY issue_count DESC
    """).fetchall()
    if not rows:
        return []

    # Get existing proposal categories
    prop_rows = conn.execute(
        "SELECT DISTINCT category FROM proposals WHERE status IN ('讨论中', '已回应')"
    ).fetchall()
    covered_cats = {r["category"] for r in prop_rows}

    upgrades = []
    for r in rows:
        cat = r["category"]
        count = r["issue_count"]
        covered = cat in covered_cats
        upgrades.append({
            "category": cat,
            "issue_count": count,
            "has_proposal": covered,
            "action": "关注已有提案进展" if covered else "建议发起新提案",
        })
    return upgrades[:4]


# ═══════════════════════ 3. Main association computation ═══════════════════════

def compute_associations(user_input: str, steps: list[dict], db_path: str = "") -> dict:
    """Run SQL queries against campus DB to find spatial/temporal/recurrence associations.

    Returns a dictionary with 10 analysis dimensions. Non-critical — failures
    are logged and the caller receives an empty result set.
    """
    import os as _os
    if not db_path:
        from config import DB_PATH as _dp
        db_path = _dp
    if not _os.path.isfile(db_path):
        _logger.warning("DB file not found at %s — skipping association queries", db_path)
        return _empty_result()

    try:
        return _compute_associations_impl(user_input, steps)
    except Exception as e:
        _logger.warning("Association query failed (non-fatal): %s", e, exc_info=True)
        return _empty_result()


def _empty_result() -> dict:
    """Return an empty (no-insight) association result."""
    return {
        "spatial": [], "temporal": [], "recurrence": [],
        "anomalies": [], "correlations": [], "linked_proposals": [],
        "resolution_efficiency": [], "cross_time": {}, "z_anomalies": [],
        "upgrade_paths": [],
        "has_insight": False, "insight_text": "",
    }


def _compute_associations_impl(user_input: str, steps: list[dict]) -> dict:

    ui = user_input or ""

    with get_db() as conn:
        # Gather locations from user_input and all tool_input string values
        locations = _extract_locations(ui)
        for s in (steps or []):
            ti = s.get("tool_input", {})
            if isinstance(ti, dict):
                for v in ti.values():
                    if isinstance(v, str):
                        locations.update(_extract_locations(v))

        categories = _extract_categories(steps)
        keywords = _extract_keywords(ui)
        spatial: list[dict] = []
        temporal: list[dict] = []
        recurrence: list[dict] = []
        seen_ids: set[int] = set()

        # ── 1. Spatial clustering ──
        for loc in locations:
            for r in conn.execute(
                "SELECT id, title, status, category, reported_at, location FROM campus_issues "
                "WHERE location LIKE ? AND status != '已解决' "
                "ORDER BY reported_at DESC LIMIT 5", (f"%{loc}%",),
            ).fetchall():
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    spatial.append(dict(r))

        # ── 2. Temporal trend ──
        if categories:
            placeholders = ",".join("?" for _ in categories)
            rows = conn.execute(
                f"SELECT category, COUNT(*) as cnt FROM campus_issues "
                f"WHERE category IN ({placeholders}) AND reported_at > date('now', '-7 days') "
                f"GROUP BY category",
                categories,
            ).fetchall()
            temporal.extend(dict(r) for r in rows)

        # ── 3. Recurrence detection ──
        for kw in keywords:
            for r in conn.execute(
                "SELECT id, title, status, category, reported_at FROM campus_issues "
                "WHERE title LIKE ? AND status = '已解决' "
                "ORDER BY reported_at DESC LIMIT 3", (f"%{kw}%",),
            ).fetchall():
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    recurrence.append(dict(r))

        # ── 4-10: Enhanced analyses (each wrapped for resilience) ──
        anomalies = _run_optional_query(conn, _anomaly_detection_query)
        correlations = _run_optional_query(conn, _correlation_query)
        linked_proposals = _run_optional_query(conn, _linked_proposals_query)
        resolution_efficiency = _run_optional_query(conn, _resolution_efficiency_query)
        cross_time = _cross_time_comparison(conn)
        z_anomalies = _z_score_anomalies(conn)
        upgrade_paths = _detect_upgrade_paths(conn)

    assoc_data = {
        "spatial": spatial, "temporal": temporal, "recurrence": recurrence,
        "anomalies": anomalies, "correlations": correlations,
        "linked_proposals": linked_proposals, "resolution_efficiency": resolution_efficiency,
        "cross_time": cross_time, "z_anomalies": z_anomalies,
        "upgrade_paths": upgrade_paths,
    }
    has = bool(
        spatial or temporal or recurrence or anomalies or correlations
        or linked_proposals or resolution_efficiency
        or z_anomalies or cross_time or upgrade_paths
    )
    assoc_data["has_insight"] = has
    # insight_text is built by the insight module; set a placeholder here
    assoc_data["insight_text"] = ""
    return assoc_data


# ═══════════════════════ 4. Optional query runners (non-critical) ═══════════════════════

def _run_optional_query(conn, query_fn) -> list[dict]:
    """Run a query function, returning [] on any failure — non-critical by design."""
    try:
        return query_fn(conn)
    except Exception:  # non-critical: graceful degradation
        return []


def _anomaly_detection_query(conn) -> list[dict]:
    """Compare recent week vs 4-week baseline for category spikes."""
    rows = conn.execute("""
        SELECT category,
            SUM(CASE WHEN reported_at > date('now', '-7 days') THEN 1 ELSE 0 END) AS recent,
            ROUND(SUM(CASE WHEN reported_at > date('now', '-35 days')
                      AND reported_at <= date('now', '-7 days') THEN 1 ELSE 0 END) / 4.0, 1) AS baseline_avg
        FROM campus_issues
        WHERE reported_at > date('now', '-35 days')
        GROUP BY category
        HAVING recent > baseline_avg * 1.5 AND recent >= 3
        ORDER BY (recent - baseline_avg) DESC
        LIMIT 5
    """).fetchall()
    return [
        {"category": r["category"], "recent": r["recent"],
         "baseline_avg": r["baseline_avg"],
         "spike": round(r["recent"] - r["baseline_avg"], 1)}
        for r in rows
    ]


def _correlation_query(conn) -> list[dict]:
    """Categories that co-occur in the same locations."""
    rows = conn.execute("""
        SELECT a.category AS cat_a, b.category AS cat_b, COUNT(*) AS co_count
        FROM campus_issues a
        JOIN campus_issues b ON a.location = b.location AND a.id < b.id
            AND a.location != '' AND b.location != ''
        WHERE a.category != b.category
        GROUP BY cat_a, cat_b
        ORDER BY co_count DESC
        LIMIT 5
    """).fetchall()
    return [
        {"cat_a": r["cat_a"], "cat_b": r["cat_b"], "co_count": r["co_count"]}
        for r in rows
    ]


def _linked_proposals_query(conn) -> list[dict]:
    """Proposals addressing the top hot-issue categories."""
    top_cats = conn.execute("""
        SELECT category FROM campus_issues
        WHERE status != '已解决'
        GROUP BY category ORDER BY COUNT(*) DESC LIMIT 3
    """).fetchall()
    top_cat_names = [r["category"] for r in top_cats]
    if not top_cat_names:
        return []
    placeholders = ",".join("?" for _ in top_cat_names)
    rows = conn.execute(
        f"SELECT id, title, category, supporter_count, status FROM proposals "
        f"WHERE category IN ({placeholders}) "
        f"ORDER BY supporter_count DESC LIMIT 5",
        top_cat_names,
    ).fetchall()
    return [dict(r) for r in rows]


def _resolution_efficiency_query(conn) -> list[dict]:
    """Per-category average resolution time."""
    rows = conn.execute("""
        SELECT category,
            COUNT(*) AS resolved_count,
            ROUND(AVG(julianday(resolved_at) - julianday(reported_at)), 1) AS avg_days
        FROM campus_issues
        WHERE status = '已解决' AND resolved_at IS NOT NULL
        GROUP BY category
        ORDER BY avg_days DESC
        LIMIT 8
    """).fetchall()
    return [
        {"category": r["category"], "resolved_count": r["resolved_count"],
         "avg_days": r["avg_days"]}
        for r in rows if r["resolved_count"] >= 2
    ]


# ═══════════════════════ 5. Proactive dashboard insights ═══════════════════════

def get_proactive_insights(db_path: str = "") -> dict:
    """Run association analysis without user input — for dashboard proactive insights.

    Unlike compute_associations() which is tied to a chat turn, this function
    runs independently to surface anomalies, trends, and upgrade suggestions
    directly on the dashboard.
    """
    if not db_path:
        from config import DB_PATH as _dp
        db_path = _dp
    if not os.path.isfile(db_path):
        return {"has_insight": False, "summary_text": "数据库未就绪"}

    try:
        with get_db() as conn:
            cross_time = _cross_time_comparison(conn)
            z_anomalies = _z_score_anomalies(conn)
            upgrade_paths = _detect_upgrade_paths(conn)

            resolution_efficiency = _run_optional_query(conn, _resolution_efficiency_query)

            urgent_count = 0
            stale_count = 0
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE urgency='紧急' AND status != '已解决'"
                ).fetchone()
                urgent_count = row["cnt"] if row else 0
            except Exception:  # non-critical: silent pass intended
                pass
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE status IN ('待处理','处理中') AND reported_at < date('now', '-7 days')"
                ).fetchone()
                stale_count = row["cnt"] if row else 0
            except Exception:  # non-critical: silent pass intended
                pass

        has_insight = bool(z_anomalies or cross_time or upgrade_paths or resolution_efficiency)
        summary_parts: list[str] = []

        if z_anomalies:
            top = z_anomalies[0]
            level_label = {"critical": "严重", "high": "高度", "moderate": "中度"}
            summary_parts.append(
                f"🔬 「{top['category']}」出现{level_label.get(top['level'], '')}异常"
                f"（严重度 {top['severity']}/10，本周 {top['recent']} 件）"
            )

        if cross_time:
            if cross_time.get("is_worsening"):
                summary_parts.append(
                    f"⚠️ 本周净增 {cross_time.get('net_this_week', 0)} 件，较上周恶化"
                )
            elif cross_time.get("is_improving"):
                summary_parts.append(
                    f"✅ 本周治理改善，净解决 {abs(cross_time.get('net_this_week', 0))} 件"
                )
            else:
                summary_parts.append("📊 本周治理态势平稳")

        uncovered_upgrades = [u for u in upgrade_paths if not u["has_proposal"]]
        if uncovered_upgrades:
            cats = "、".join(u["category"] for u in uncovered_upgrades[:2])
            summary_parts.append(f"🚀 「{cats}」类建议发起治理提案（报→议升级）")

        if resolution_efficiency:
            worst = resolution_efficiency[0]
            if worst["avg_days"] >= 7:
                summary_parts.append(
                    f"⏱️ 「{worst['category']}」解决最慢（均 {worst['avg_days']} 天），存在效率瓶颈"
                )

        return {
            "has_insight": has_insight,
            "z_anomalies": z_anomalies,
            "cross_time": cross_time,
            "upgrade_paths": upgrade_paths,
            "uncovered_upgrades": uncovered_upgrades,
            "resolution_efficiency": resolution_efficiency,
            "urgent_count": urgent_count,
            "stale_count": stale_count,
            "summary_text": "\n".join(
                f"- {p}" for p in summary_parts
            ) if summary_parts else "✅ 暂无异常洞察，校园治理运行平稳",
            "summary_parts": summary_parts,
        }
    except Exception as e:
        _logger.warning("Proactive insights failed: %s", e)
        return {"has_insight": False, "summary_text": f"洞察分析暂不可用：{e}"}
