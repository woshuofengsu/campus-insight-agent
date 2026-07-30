# agent/reflector.py
"""Post-response association reasoning engine ("反射器").

After the main agent (LangChain AgentExecutor) finishes running, the reflector:
  1. Parses intermediate steps into structured reasoning phases.
  2. Computes spatial / temporal / recurrence associations via SQL queries.
  3. Runs enhanced anomaly detection (z-score + moving average + severity scoring).
  4. Detects cross-time trends (this week vs last week) with significance indicators.
  5. Detects governance upgrade paths (报→议 escalation triggers).
  6. Generates LLM-powered natural-language insight when associations are significant.
  7. Enriches the raw response with association insights.

The LLM insight is the key differentiator — it doesn't just dump data,
it explains WHY the pattern matters and WHAT should be done about it.
"""
import logging, math, os, re, time
from config import DB_PATH, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

_logger = logging.getLogger("agent.reflector")

_STOP_WORDS: set[str] = {"了","的","是","我","要","有","在","不","和","都","一","个","上","也","很","到","说","去","你","会","着","没有","看","好","自己","这"}
_PHASE_ICONS = {"observe": "🔍", "orient": "⚡", "decide": "🗳️", "act": "🔧", "reflect": "🌤️"}
_LOCATION_PATTERNS = [r"教\d+楼", r"图书馆", r"食堂", r"宿舍\d*号楼", r"操场", r"体育馆", r"实验楼", r"行政楼", r"[一二三四五六七八九十]食堂", r"\d+号宿舍楼", r"\d+栋"]


# ═══════════════════════ 1. Step parsing ═══════════════════════

def _normalize_tool_input(tool_input) -> dict:
    """Ensure tool_input is a dict, regardless of what LangChain passes.

    StructuredTools always pass dicts, but plain @tool functions may pass
    strings, numbers, or None. Normalize so downstream code can safely
    use .get() and string formatting.
    """
    if tool_input is None:
        return {}
    if isinstance(tool_input, dict):
        return tool_input
    if isinstance(tool_input, str):
        return {"input": tool_input}
    # Number, list, or other — wrap for safe display
    return {"value": tool_input}


def parse_intermediate_steps(intermediate_steps: list) -> list[dict]:
    """Convert LangChain intermediate_steps (list[tuple[AgentAction, str]]) to structured steps."""
    if not intermediate_steps:
        return []
    steps: list[dict] = []
    for action, observation in intermediate_steps:
        tool_name = getattr(action, "tool", "unknown")
        tool_input = _normalize_tool_input(getattr(action, "tool_input", None))
        obs_raw = str(observation) if observation else ""
        obs_str = obs_raw[:200] + ("..." if len(obs_raw) > 200 else "")
        t = tool_name.lower()
        phase = "observe" if any(k in t for k in ("query","get_","pulse","weather")) else "act"
        steps.append({
            "phase": phase, "icon": _PHASE_ICONS.get(phase, "🔧"),
            "tool_name": tool_name, "tool_input": tool_input,
            "tool_output": obs_str,
            "summary": _summarize_step(tool_name, tool_input),
        })
    return steps


# ═══════════════════════ 2. Step summarisation ═══════════════════════

def _summarize_step(tool_name: str, tool_input: dict) -> str:
    """Generate a one-line human-readable Chinese summary of a tool call.

    Uses a dispatch table keyed by exact tool name for robustness.
    The 12 known tools are the ones auto-discovered from tools/.
    """
    ti = tool_input or {}

    # ── Exact-match dispatch (ordered by tool category) ──
    handlers = {
        # 报 — issue reporting
        "report_issue":    lambda: f"上报问题：{str(ti.get('title',''))[:30]} → {ti.get('category','')}",
        "query_issues":    lambda: f"查询工单：{ti.get('category','') or '全部'} {ti.get('status','') or '全部'}",
        # 知 — observation
        "get_campus_pulse":      lambda: "获取校园脉搏快照",
        "get_governance_stats":  lambda: "查询治理统计数据",
        "get_weather":           lambda: "查询天气信息",
        "query_knowledge":       lambda: f"语义搜索校园百科：{str(ti.get('query',''))[:30]}",
        "get_school_policy":     lambda: f"检索校规政策：{str(ti.get('topic',''))[:30]}",
        # 议 — proposals & discussion
        "create_proposal":   lambda: f"创建提案：{str(ti.get('title',''))[:30]}",
        "support_proposal":  lambda: f"附议提案 #{ti.get('proposal_id','?')}",
        "get_proposals":     lambda: "查询提案列表",
        "get_topics":        lambda: "查询讨论议题",
        "get_topic_detail":  lambda: f"查看议题 #{ti.get('topic_id','?')} 详情",
        "express_opinion":   lambda: "发表议题意见",
        "collect_feedback":  lambda: "收集校园意见",
    }

    handler = handlers.get(tool_name)
    if handler:
        return handler()
    return f"调用 {tool_name}"


# ═══════════════════════ 3. Association helpers ═══════════════════════

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
            seen.add(tok); result.append(tok)
    return result


# ═══════════════════════ 4. Enhanced analysis helpers ═══════════════════════

def _cross_time_comparison(conn) -> dict:
    """Compare this week vs last week for new issues and resolutions.

    Returns a dict with trend data suitable for insight generation.
    Computes: new issues this week, new last week, resolved this week,
    resolved last week, and direction indicators.
    """
    try:
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
        ntw, nlw, rtw, rlw = row["new_this_week"] or 0, row["new_last_week"] or 0, row["resolved_this_week"] or 0, row["resolved_last_week"] or 0

        def _trend(curr, prev):
            if prev == 0:
                return "↑" if curr > 0 else "→"
            ratio = curr / prev
            if ratio > 1.5: return "↑↑"
            if ratio > 1.1: return "↑"
            if ratio < 0.67: return "↓↓"
            if ratio < 0.9: return "↓"
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
    except Exception:
        return {}


def _z_score_anomalies(conn) -> list[dict]:
    """Compute z-score based anomaly detection per category.

    More statistically sound than simple ratio thresholds: computes mean and
    stddev across all categories' weekly issue counts over a 4-week window,
    then flags categories where the z-score exceeds 1.5.

    Also computes a severity score (0-10) combining z-score magnitude,
    absolute count, and urgency mix.
    """
    try:
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
            # Severity score: z-score (0-4) + count factor (0-3) + urgency factor (0-3)
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
    except Exception:
        return []


def _detect_upgrade_paths(conn) -> list[dict]:
    """Detect categories where issues should escalate to proposals.

    Criteria: 3+ unresolved issues in a category, no matching active proposal
    with >10 supporters. Returns upgrade suggestions with the category name
    and issue count.
    """
    try:
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
    except Exception:
        return []


# ═══════════════════════ 5. Compute associations ═══════════════════════

def compute_associations(user_input: str, steps: list[dict]) -> dict:
    """Run SQL queries against campus DB to find spatial/temporal/recurrence associations.

    Enhanced with 4 additional analysis dimensions:
      5. Anomaly detection — category spikes vs historical baseline
      6. Cross-category correlation — categories that co-occur in same locations
      7. Issue-proposal linking — proposals addressing hot issue categories
      8. Resolution efficiency — per-category avg resolution time
    """
    if not os.path.isfile(DB_PATH):
        _logger.warning("DB file not found at %s — skipping association queries", DB_PATH)
        return {"spatial": [], "temporal": [], "recurrence": [],
                "anomalies": [], "correlations": [], "linked_proposals": [],
                "resolution_efficiency": [], "cross_time": {}, "z_anomalies": [],
                "upgrade_paths": [],
                "has_insight": False, "insight_text": ""}

    try:
        from data.database import get_db
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
            spatial: list[dict] = []; temporal: list[dict] = []; recurrence: list[dict] = []
            anomalies: list[dict] = []; correlations: list[dict] = []
            linked_proposals: list[dict] = []; resolution_efficiency: list[dict] = []
            seen_ids: set[int] = set()

            # ── 1. Spatial clustering ──
            for loc in locations:
                for r in conn.execute(
                    "SELECT id, title, status, category, reported_at, location FROM campus_issues "
                    "WHERE location LIKE ? AND status != '已解决' "
                    "ORDER BY reported_at DESC LIMIT 5", (f"%{loc}%",),
                ).fetchall():
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"]); spatial.append(dict(r))

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
                        seen_ids.add(r["id"]); recurrence.append(dict(r))

            # ── 4. Anomaly detection — compare recent week vs 4-week baseline ──
            try:
                anom_rows = conn.execute("""
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
                anomalies = [
                    {"category": r["category"], "recent": r["recent"],
                     "baseline_avg": r["baseline_avg"],
                     "spike": round(r["recent"] - r["baseline_avg"], 1)}
                    for r in anom_rows
                ]
            except Exception:
                pass

            # ── 5. Cross-category correlation — categories that co-occur in locations ──
            try:
                corr_rows = conn.execute("""
                    SELECT a.category AS cat_a, b.category AS cat_b, COUNT(*) AS co_count
                    FROM campus_issues a
                    JOIN campus_issues b ON a.location = b.location AND a.id < b.id
                        AND a.location != '' AND b.location != ''
                    WHERE a.category != b.category
                    GROUP BY cat_a, cat_b
                    ORDER BY co_count DESC
                    LIMIT 5
                """).fetchall()
                correlations = [
                    {"cat_a": r["cat_a"], "cat_b": r["cat_b"], "co_count": r["co_count"]}
                    for r in corr_rows
                ]
            except Exception:
                pass

            # ── 6. Issue-Proposal linking — proposals addressing hot categories ──
            try:
                top_cats = conn.execute("""
                    SELECT category FROM campus_issues
                    WHERE status != '已解决'
                    GROUP BY category ORDER BY COUNT(*) DESC LIMIT 3
                """).fetchall()
                top_cat_names = [r["category"] for r in top_cats]
                if top_cat_names:
                    cat_placeholders = ",".join("?" for _ in top_cat_names)
                    prop_rows = conn.execute(
                        f"SELECT id, title, category, supporter_count, status FROM proposals "
                        f"WHERE category IN ({cat_placeholders}) "
                        f"ORDER BY supporter_count DESC LIMIT 5",
                        top_cat_names,
                    ).fetchall()
                    linked_proposals = [dict(r) for r in prop_rows]
            except Exception:
                pass

            # ── 7. Resolution efficiency by category ──
            try:
                eff_rows = conn.execute("""
                    SELECT category,
                        COUNT(*) AS resolved_count,
                        ROUND(AVG(julianday(resolved_at) - julianday(reported_at)), 1) AS avg_days
                    FROM campus_issues
                    WHERE status = '已解决' AND resolved_at IS NOT NULL
                    GROUP BY category
                    ORDER BY avg_days DESC
                    LIMIT 8
                """).fetchall()
                resolution_efficiency = [
                    {"category": r["category"], "resolved_count": r["resolved_count"],
                     "avg_days": r["avg_days"]}
                    for r in eff_rows if r["resolved_count"] >= 2
                ]
            except Exception:
                pass

            # ── 8. Cross-time comparison (this week vs last week) ──
            cross_time = _cross_time_comparison(conn)

            # ── 9. Z-score anomaly detection ──
            z_anomalies = _z_score_anomalies(conn)

            # ── 10. Upgrade path detection (报→议 escalation) ──
            upgrade_paths = _detect_upgrade_paths(conn)

        assoc_data = {
            "spatial": spatial, "temporal": temporal, "recurrence": recurrence,
            "anomalies": anomalies, "correlations": correlations,
            "linked_proposals": linked_proposals, "resolution_efficiency": resolution_efficiency,
            "cross_time": cross_time, "z_anomalies": z_anomalies,
            "upgrade_paths": upgrade_paths,
        }
        has = bool(spatial or temporal or recurrence or anomalies or correlations
                   or linked_proposals or resolution_efficiency
                   or z_anomalies or cross_time or upgrade_paths)
        assoc_data["has_insight"] = has
        assoc_data["insight_text"] = _build_insight_text(assoc_data, user_input=ui)
        return assoc_data

    except Exception as e:
        _logger.warning("Association query failed (non-fatal): %s", e, exc_info=True)
        return {"spatial": [], "temporal": [], "recurrence": [],
                "anomalies": [], "correlations": [], "linked_proposals": [],
                "resolution_efficiency": [], "cross_time": {}, "z_anomalies": [],
                "upgrade_paths": [],
                "has_insight": False, "insight_text": ""}


# ═══════════════════════ 5. LLM-powered insight generation ═══════════════════════

_INSIGHT_LLM = None  # lazy singleton — created on first use


def _get_insight_llm():
    """Lazy-init a lightweight LLM client for insight generation.

    Separate from the main agent's LLM — only used for post-hoc analysis.
    Returns None if API key is not configured.
    """
    global _INSIGHT_LLM
    if _INSIGHT_LLM is not None:
        return _INSIGHT_LLM
    if not DEEPSEEK_API_KEY:
        _INSIGHT_LLM = False  # sentinel: tried but not available
        return None
    try:
        from openai import OpenAI
        _INSIGHT_LLM = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        return _INSIGHT_LLM
    except Exception:
        _INSIGHT_LLM = False
        return None


def _build_insight_prompt(associations: dict, user_input: str) -> str:
    """Build a focused prompt for the LLM insight generator.

    Now includes: cross-time comparison, z-score anomalies with severity,
    upgrade path suggestions, and resolution efficiency data.
    """
    sp = associations.get("spatial", [])
    tm = associations.get("temporal", [])
    rc = associations.get("recurrence", [])
    an = associations.get("anomalies", [])
    lp = associations.get("linked_proposals", [])
    ct = associations.get("cross_time", {})
    za = associations.get("z_anomalies", [])
    up = associations.get("upgrade_paths", [])
    re_ = associations.get("resolution_efficiency", [])

    parts = ["你是一位校园治理数据分析师。以下是根据用户消息自动发现的关联数据：", ""]

    if sp:
        items = "\n".join(
            f"- #{r['id']} {r['title']} [{r.get('status','')}] ({r.get('category','')})"
            for r in sp[:5]
        )
        parts.append(f"## 同区域待处理问题（{len(sp)} 个）\n{items}\n")

    if tm:
        items = "\n".join(
            f"- {t['category']}: 近7天新增 {t['cnt']} 件"
            for t in tm
        )
        parts.append(f"## 近期趋势\n{items}\n")

    if an:
        items = "\n".join(
            f"- {a['category']}: 本周 {a['recent']} 件 vs 周均 {a['baseline_avg']} 件 (激增 +{a['spike']})"
            for a in an[:3]
        )
        parts.append(f"## ⚠️ 异常检测 — 类别激增预警\n{items}\n")

    # ── NEW: Z-score anomalies with severity ──
    if za:
        level_labels = {"critical": "🔴 严重", "high": "🟠 高度", "moderate": "🟡 中度"}
        items = "\n".join(
            f"- [{level_labels.get(a['level'], a['level'])}] {a['category']}: "
            f"z={a['z_score']}, 严重度={a['severity']}/10, 紧急待处理={a.get('urgent_pending',0)}件"
            for a in za[:3]
        )
        parts.append(f"## 🔬 统计异常检测（z-score法）\n{items}\n")

    # ── NEW: Cross-time comparison ──
    if ct:
        parts.append(
            f"## 📅 跨周对比\n"
            f"- 本周新增 {ct.get('new_this_week',0)} 件 ({ct.get('new_trend','→')}) vs "
            f"上周 {ct.get('new_last_week',0)} 件\n"
            f"- 本周解决 {ct.get('resolved_this_week',0)} 件 ({ct.get('resolved_trend','→')}) vs "
            f"上周 {ct.get('resolved_last_week',0)} 件\n"
            f"- 净变化: {'恶化' if ct.get('is_worsening') else '改善' if ct.get('is_improving') else '平稳'}\n"
        )

    if lp:
        items = "\n".join(
            f"- #{p['id']} {p['title'][:30]} · 👍{p['supporter_count']} · {p['status']}"
            for p in lp[:3]
        )
        parts.append(f"## 💡 关联提案（同类别热门提案）\n{items}\n")

    if rc:
        items = "\n".join(
            f"- #{r['id']} {r['title']} (曾标记为已解决)"
            for r in rc[:3]
        )
        parts.append(f"## 复发预警（{len(rc)} 个）\n{items}\n")

    # ── NEW: Upgrade path suggestions ──
    if up:
        items = "\n".join(
            f"- {u['category']}（{u['issue_count']}件待处理）→ {u['action']}"
            f"{' ✅' if u['has_proposal'] else ' ⚠️ 无相关提案'}"
            for u in up[:3]
        )
        parts.append(f"## 🚀 治理升级建议（报→议）\n{items}\n")

    # ── NEW: Resolution efficiency ──
    if re_ and len(re_) >= 2:
        worst = re_[0]
        best = re_[-1]
        parts.append(
            f"## ⏱️ 解决效率\n"
            f"- 最慢: 「{worst['category']}」均 {worst['avg_days']} 天\n"
            f"- 最快: 「{best['category']}」均 {best['avg_days']} 天\n"
        )

    parts.extend([
        f"用户原始消息：{user_input[:200]}",
        "",
        "请用 2-4 句话进行深度解读（控制在 180 字以内）：",
        "1. 如果有 z-score 异常（严重度>=5），指出最值得关注的类别、可能原因和趋势预测",
        "2. 如果有跨周对比数据，结合趋势方向判断问题是在恶化还是改善",
        "3. 如果有同区域多问题或复发，指出系统性风险",
        "4. 如果有治理升级建议，明确建议用户采取什么行动",
        "5. 如果有解决效率数据，指出瓶颈类别",
        "",
        "要求：",
        "- 不要重复列举数据（数据已在上方展示），要解读其深层含义",
        "- 语气像一个有洞察力的校园治理分析师，看到别人看不到的模式",
        "- 给出 1-2 条最具体、最可操作的下一步建议",
        "- 纯文本，不用 markdown，不用 emoji 前缀",
    ])

    return "\n".join(parts)


def _generate_llm_insight(associations: dict, user_input: str) -> str | None:
    """Try to generate a nuanced LLM insight. Returns None if unavailable/fails.

    Only called when associations are significant enough to warrant analysis.
    Enhanced threshold: z-anomalies with severity >= 5, upgrade paths with
    uncovered categories, cross-time worsening trends, or classic triggers.
    """
    sp = associations.get("spatial", [])
    tm = associations.get("temporal", [])
    rc = associations.get("recurrence", [])
    an = associations.get("anomalies", [])
    za = associations.get("z_anomalies", [])
    up = associations.get("upgrade_paths", [])
    ct = associations.get("cross_time", {})

    # Enhanced significance threshold
    significant = (
        len(sp) >= 3 or
        any(t.get("cnt", 0) >= 5 for t in tm) or
        len(rc) >= 1 or
        len(an) >= 1 or
        any(a["severity"] >= 5 for a in za) or
        any(not u["has_proposal"] for u in up) or
        ct.get("is_worsening", False)
    )
    if not significant:
        return None

    client = _get_insight_llm()
    if not client:
        return None

    prompt = _build_insight_prompt(associations, user_input)

    try:
        start = time.time()
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个有洞察力的校园治理数据分析师。用简洁的中文回复，不超过180字。重点解读数据背后的含义和趋势，给出可操作的行动建议。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.4,
        )
        elapsed = time.time() - start
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if text:
            _logger.info("LLM insight generated in %.1fs (%d chars)", elapsed, len(text))
            return text
    except Exception:
        pass  # Silent fallback — LLM insight is a bonus, not critical

    return None


def _build_insight_text(associations: dict, user_input: str = "") -> str:
    """Build insight text: try LLM first, fall back to structured template.

    The LLM insight provides nuanced interpretation ("what does this pattern mean?")
    while the template provides structured data display. Both are shown in the
    insight panel — LLM text first (if available), then data cards.

    Enhanced with: cross-time comparison, z-score anomalies with severity levels,
    upgrade path recommendations, and trend direction indicators.
    """
    parts: list[str] = []
    sp = associations.get("spatial", [])
    tm = associations.get("temporal", [])
    rc = associations.get("recurrence", [])
    an = associations.get("anomalies", [])
    cr = associations.get("correlations", [])
    lp = associations.get("linked_proposals", [])
    re_ = associations.get("resolution_efficiency", [])
    ct = associations.get("cross_time", {})
    za = associations.get("z_anomalies", [])
    up = associations.get("upgrade_paths", [])

    # ── Layer 1: LLM interpretation (the "why") ──
    llm_insight = _generate_llm_insight(associations, user_input)
    if llm_insight:
        parts.append(f"🧠 **AI 深度解读**：{llm_insight}")

    # ── Layer 2: Z-score anomaly detection (statistically rigorous, highest priority) ──
    if za:
        level_icons = {"critical": "🔴", "high": "🟠", "moderate": "🟡"}
        za_items = [
            f"{level_icons.get(a['level'], '⚪')} 「{a['category']}」严重度 {a['severity']}/10 "
            f"(z={a['z_score']}，本周 {a['recent']} 件"
            + (f"，{a.get('urgent_pending',0)} 件紧急" if a.get('urgent_pending') else "")
            + ")"
            for a in za[:3]
        ]
        parts.append(f"🔬 **统计异常检测**（z-score 法）：{'；'.join(za_items)}")

    # ── Layer 3: Classic anomaly detection (ratio-based, complementary) ──
    elif an:
        an_items = [f"「{a['category']}」本周 {a['recent']} 件 (周均 {a['baseline_avg']}，激增 +{a['spike']})" for a in an[:3]]
        parts.append(f"⚠️ **异常检测**：{'；'.join(an_items)}")

    # ── Layer 4: Cross-time comparison ──
    if ct:
        new_str = f"新增 {ct['new_this_week']} 件 ({ct['new_trend']})"
        resolved_str = f"解决 {ct['resolved_this_week']} 件 ({ct['resolved_trend']})"
        net_label = "⚠️ 净恶化" if ct.get('is_worsening') else "✅ 净改善" if ct.get('is_improving') else "→ 持平"
        parts.append(f"📅 **本周 vs 上周**：{new_str}，{resolved_str}，{net_label}")

    # ── Layer 5: Upgrade path recommendations ──
    if up:
        up_items = []
        for u in up[:3]:
            action = u['action']
            has_prop = "✅ 已有提案" if u['has_proposal'] else "⚠️ 建议发起提案"
            up_items.append(f"「{u['category']}」{u['issue_count']} 件待处理 → {has_prop}")
        parts.append(f"🚀 **治理升级路径**：{'；'.join(up_items)}")

    # ── Layer 6: Data summary (the "what") ──
    if sp:
        loc_names = sorted({(r.get("location") or r.get("title", ""))[:20] for r in sp})
        titles = [r["title"] for r in sp[:5]]
        ls = "、".join(loc_names[:5]) if loc_names else "该区域"
        parts.append(f"📍 **空间关联**：该区域（{ls}）还有 {len(sp)} 个待处理问题，包括：{'、'.join(titles)}")

    for t in tm:
        cat, cnt = t.get("category", ""), t.get("cnt", 0)
        parts.append(f"📈 **时间趋势**：近7天「{cat}」类问题新增 {cnt} 件{'，呈上升趋势' if cnt >= 5 else ''}")

    if rc:
        rts = [r["title"] for r in rc[:3]]
        parts.append(f"🔄 **复发预警**：类似问题曾出现过并被标记为已解决，包括：{'、'.join(rts)}。建议关注是否存在根本性原因未解决。")

    # ── Layer 7: Cross-category correlation ──
    if cr:
        cr_items = [f"「{c['cat_a']}」↔「{c['cat_b']}」({c['co_count']} 次共现)" for c in cr[:3]]
        parts.append(f"🔗 **类别关联**：{'；'.join(cr_items)}")

    # ── Layer 8: Linked proposals ──
    if lp:
        lp_items = [f"#{p['id']} {p['title'][:25]} (👍{p['supporter_count']})" for p in lp[:3]]
        parts.append(f"💡 **相关提案**：{'；'.join(lp_items)}。这些提案正在解决同类问题，你可以关注或附议！")

    # ── Layer 9: Resolution efficiency ──
    if re_:
        if len(re_) >= 2:
            worst = re_[0]  # sorted by avg_days DESC, worst first
            best = re_[-1]  # best (fastest)
            parts.append(f"⏱️ **解决效率**：「{worst['category']}」最慢 (均 {worst['avg_days']} 天)，「{best['category']}」最快 (均 {best['avg_days']} 天)")
        else:
            item = re_[0]
            parts.append(f"⏱️ **解决效率**：「{item['category']}」均 {item['avg_days']} 天（{item['resolved_count']} 件已解决）")

    return "\n\n".join(parts)


# ═══════════════════════ 6. Enrich response ═══════════════════════

def enrich_response(raw_response: str, associations: dict) -> str:
    """Append association insights to the agent's response if meaningful.

    Only skips when the response already contains our exact insight header
    (prevents double-appending on re-processing). All other cases: append —
    the insight contains DB-derived data the LLM couldn't possibly know.
    """
    if not associations.get("has_insight"):
        return raw_response or ""
    insight = associations.get("insight_text", "")
    if not insight:
        return raw_response or ""
    if "智能关联分析" in (raw_response or ""):
        return raw_response or ""
    return f"{raw_response}\n\n---\n\n💡 **智能关联分析**（AI 自动发现）：\n\n{insight}"


# ═══════════════════════ 7. Text-action parsing (fallback when LLM doesn't call tools) ═══════════════════════

# Patterns that indicate the agent performed an action in its text response,
# even when LangChain didn't capture a formal tool call.
# Token that stops at spaces, Chinese punctuation, and line breaks
_TK = r"[^\s，。；！？\n]+"

_TEXT_ACTION_PATTERNS: list[tuple[str, str, str]] = [
    # (regex pattern, icon, phase)
    # Order matters: more specific patterns first to prevent sub-pattern shadowing
    (rf"已(为你|为你)?生成工单\s*[#＃]?\s*{_TK}", "⚡", "act"),
    (rf"工单\s*[#＃]\s*{_TK}", "⚡", "act"),
    (r"(上报|报修|创建).{0,10}(工单|问题)", "⚡", "act"),
    (r"(已上报|已报修|已提交)", "⚡", "act"),
    (r"(查询|正在查|检索).{0,10}(工单|问题|数据|提案|议题|报修)", "🔍", "observe"),
    (r"校园脉搏", "🌊", "observe"),
    (r"治理(统计|数据|快照|健康)", "📊", "observe"),
    (r"天气", "🌤️", "observe"),
    (r"(创建|发起).{0,10}(提案|议题)", "🗳️", "act"),
    (r"(附议|支持).{0,10}提案", "🗳️", "act"),
    (r"(\d+)人附议", "🗳️", "observe"),
    (r"已采纳|已实施|已回应", "✅", "act"),
]


def _parse_text_actions(raw_response: str) -> list[dict]:
    """Extract pseudo-steps from the agent's text response.

    When DeepSeek generates action descriptions inline (e.g. "已为你生成工单 #42")
    instead of formally calling tools via LangChain, this parser recovers those
    actions so the reasoning chain isn't empty.

    Returns a list of step dicts compatible with parse_intermediate_steps output.
    """
    steps: list[dict] = []
    covered_ranges: list[tuple[int, int]] = []  # for overlap dedup

    def _has_overlap(start: int, end: int) -> bool:
        for cs, ce in covered_ranges:
            if start < ce and end > cs:  # intervals overlap
                return True
        return False

    for pattern, icon, phase in _TEXT_ACTION_PATTERNS:
        for m in re.finditer(pattern, raw_response):
            start, end = m.start(), m.end()
            if _has_overlap(start, end):
                continue  # skip — already covered by a higher-priority pattern
            covered_ranges.append((start, end))
            match_text = m.group(0)[:60]
            steps.append({
                "phase": phase,
                "icon": icon,
                "tool_name": "",
                "tool_input": {},
                "tool_output": match_text,
                "summary": f"AI 执行：{match_text}",
            })

    # Sort by position in text (natural reading order)
    steps.sort(key=lambda s: raw_response.find(s["tool_output"]))
    return steps


# ═══════════════════════ 7.5 Trivial-input gate ═══════════════════════

# Messages that don't warrant 10+ SQL queries for association analysis
_TRIVIAL_PATTERNS: set[str] = {
    "你好", "您好", "hi", "hello", "嗨", "早", "早上好", "下午好", "晚上好",
    "谢谢", "感谢", "thanks", "thank you", "3q",
    "好的", "嗯", "哦", "行", "可以", "ok", "okay", "好滴", "好",
    "哈哈", "嘿嘿", "呵呵", "嘻嘻", "lol",
    "再见", "拜拜", "bye", "88", "回头见", "改天聊",
    "在吗", "在不在", "有人吗", "在不",
    "没事", "没什么", "没啥", "随便看看", "逛逛",
    "你是谁", "你叫什么", "介绍一下", "介绍一下你自己",
}


def _is_trivial_input(user_input: str) -> bool:
    """Return True if the input is generic small-talk that shouldn't trigger
    the heavy association analysis pipeline."""
    cleaned = user_input.strip().lower().rstrip("。！？!?.,，")
    if len(cleaned) <= 2:
        return True
    if cleaned in _TRIVIAL_PATTERNS:
        return True
    # Greeting-only pattern: "你好呀", "嗨~", etc.
    if re.match(r"^(你好|您好|hi|hello|嗨|早|谢谢|感谢|thanks|bye|再见|拜拜)[!！~～呀啊]*$", cleaned):
        return True
    return False


# ═══════════════════════ 8. Proactive dashboard insights ═══════════════════════

def get_proactive_insights() -> dict:
    """Run association analysis without user input — for dashboard proactive insights.

    Unlike compute_associations() which is tied to a chat turn, this function
    runs independently to surface anomalies, trends, and upgrade suggestions
    directly on the dashboard. This is the "wow moment" — the AI agent
    proactively telling users what they should know.
    """
    if not os.path.isfile(DB_PATH):
        return {"has_insight": False, "summary_text": "数据库未就绪"}

    try:
        from data.database import get_db

        with get_db() as conn:
            cross_time = _cross_time_comparison(conn)
            z_anomalies = _z_score_anomalies(conn)
            upgrade_paths = _detect_upgrade_paths(conn)

            resolution_efficiency: list[dict] = []
            try:
                eff_rows = conn.execute("""
                    SELECT category,
                        COUNT(*) AS resolved_count,
                        ROUND(AVG(julianday(resolved_at) - julianday(reported_at)), 1) AS avg_days
                    FROM campus_issues
                    WHERE status = '已解决' AND resolved_at IS NOT NULL
                    GROUP BY category
                    ORDER BY avg_days DESC
                    LIMIT 5
                """).fetchall()
                resolution_efficiency = [
                    {"category": r["category"], "resolved_count": r["resolved_count"],
                     "avg_days": r["avg_days"]}
                    for r in eff_rows if r["resolved_count"] >= 2
                ]
            except Exception:
                pass

            urgent_count = 0
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE urgency='紧急' AND status != '已解决'"
                ).fetchone()
                urgent_count = row["cnt"] if row else 0
            except Exception:
                pass

            stale_count = 0
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE status IN ('待处理','处理中') AND reported_at < date('now', '-7 days')"
                ).fetchone()
                stale_count = row["cnt"] if row else 0
            except Exception:
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
            "summary_text": "\n".join(f"- {p}" for p in summary_parts) if summary_parts else "✅ 暂无异常洞察，校园治理运行平稳",
            "summary_parts": summary_parts,
        }
    except Exception as e:
        _logger.warning("Proactive insights failed: %s", e)
        return {"has_insight": False, "summary_text": f"洞察分析暂不可用：{e}"}


# ═══════════════════════ 9. Main entry point ═══════════════════════

def build_reasoning_chain(intermediate_steps: list, raw_response: str,
                          user_input: str) -> dict:
    """Main entry point: parse steps, compute associations, enrich response.

    Strategy:
    1. Try LangChain intermediate_steps (formal tool calls) first.
    2. If empty, fall back to text-action parsing (pattern-matching in response).
    3. Append a final "reflect" step for the agent's text answer.
    """
    raw, ui = raw_response or "", user_input or ""
    steps = parse_intermediate_steps(intermediate_steps)

    # Fallback: if no formal tool calls captured, parse the text response
    if not steps and raw.strip():
        steps = _parse_text_actions(raw)

    # Append a final step for the agent's text response (the "reflect" phase)
    if raw.strip():
        steps.append({
            "phase": "reflect",
            "icon": "💬",
            "tool_name": "",
            "tool_input": {},
            "tool_output": raw[:200] + ("..." if len(raw) > 200 else ""),
            "summary": f"生成回复（{len(raw)} 字）",
        })

    # ── Trivial-input gate: skip heavy association analysis for small-talk ──
    if _is_trivial_input(ui) and not intermediate_steps:
        # No tool calls + trivial input → return minimal chain, skip 10+ SQL queries
        return {"steps": steps, "associations": {"has_insight": False},
                "raw_response": raw, "enriched_response": raw}

    assoc = compute_associations(ui, steps)
    return {"steps": steps, "associations": assoc, "raw_response": raw,
            "enriched_response": enrich_response(raw, assoc)}
