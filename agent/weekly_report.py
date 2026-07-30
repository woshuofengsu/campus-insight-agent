# agent/weekly_report.py
"""AI 治理周报生成器 — 自动分析校园治理数据并生成结构化周报。

Design:
  - Reuses reflector.py's analysis functions (z-score, cross-time, upgrade paths)
    to avoid duplicating SQL logic.
  - Compiles a multi-section report: executive summary (LLM), KPI snapshot,
    anomaly alerts, trend analysis, resolution efficiency, upgrade paths,
    spatial hotspots, recurrence risks.
  - LLM-powered executive summary that synthesizes all findings into
    natural-language insights and action recommendations.
  - Returns a markdown string suitable for display in the teacher insights page,
    the bigscreen page, or as an exported report.

Usage:
    from agent.weekly_report import generate_weekly_report
    report = generate_weekly_report()  # dict with sections + markdown
"""

import logging
import time
from datetime import datetime

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from data.db_core import get_db

_logger = logging.getLogger("agent.weekly_report")

# ── Reuse reflector analysis (imports deferred to avoid circular deps at module level) ──


def _run_all_analysis():
    """Run all reflector analysis dimensions. Returns structured dict."""
    from agent.reflector import (
        _z_score_anomalies,
        _cross_time_comparison,
        _detect_upgrade_paths,
    )

    result = {
        "generated_at": datetime.now().isoformat(),
        "title": f"校园治理周报 · {datetime.now().strftime('%Y年%m月%d日')}",
    }

    try:
        with get_db() as conn:
            result["z_anomalies"] = _z_score_anomalies(conn)
            result["cross_time"] = _cross_time_comparison(conn)
            result["upgrade_paths"] = _detect_upgrade_paths(conn)

            # ── Overall KPIs ──
            total = conn.execute("SELECT COUNT(*) as c FROM campus_issues").fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) as c FROM campus_issues WHERE status='待处理'"
            ).fetchone()
            in_progress = conn.execute(
                "SELECT COUNT(*) as c FROM campus_issues WHERE status='处理中'"
            ).fetchone()
            resolved = conn.execute(
                "SELECT COUNT(*) as c FROM campus_issues WHERE status='已解决'"
            ).fetchone()
            urgent = conn.execute(
                "SELECT COUNT(*) as c FROM campus_issues "
                "WHERE urgency='紧急' AND status != '已解决'"
            ).fetchone()
            week_new = conn.execute(
                "SELECT COUNT(*) as c FROM campus_issues "
                "WHERE reported_at > date('now', '-7 days')"
            ).fetchone()
            week_resolved = conn.execute(
                "SELECT COUNT(*) as c FROM campus_issues "
                "WHERE status='已解决' AND resolved_at > date('now', '-7 days')"
            ).fetchone()

            result["kpi"] = {
                "total": total["c"] if total else 0,
                "pending": pending["c"] if pending else 0,
                "in_progress": in_progress["c"] if in_progress else 0,
                "resolved": resolved["c"] if resolved else 0,
                "urgent": urgent["c"] if urgent else 0,
                "week_new": week_new["c"] if week_new else 0,
                "week_resolved": week_resolved["c"] if week_resolved else 0,
                "resolution_rate": round(
                    resolved["c"] / max(total["c"], 1) * 100, 1
                ) if total and resolved else 0,
            }

            # ── Category breakdown (this week) ──
            cat_rows = conn.execute("""
                SELECT category, COUNT(*) as cnt
                FROM campus_issues
                WHERE reported_at > date('now', '-7 days')
                GROUP BY category
                ORDER BY cnt DESC LIMIT 8
            """).fetchall()
            result["category_breakdown"] = [dict(r) for r in cat_rows]

            # ── Spatial hotspots ──
            spatial_rows = conn.execute("""
                SELECT location, COUNT(*) as cnt,
                       SUM(CASE WHEN urgency='紧急' THEN 1 ELSE 0 END) as urgent_cnt
                FROM campus_issues
                WHERE status IN ('待处理', '处理中') AND location != ''
                GROUP BY location
                ORDER BY cnt DESC LIMIT 6
            """).fetchall()
            result["spatial_hotspots"] = [dict(r) for r in spatial_rows]

            # ── Resolution efficiency ──
            eff_rows = conn.execute("""
                SELECT category,
                       COUNT(*) AS resolved_count,
                       ROUND(AVG(julianday(resolved_at) - julianday(reported_at)), 1) AS avg_days
                FROM campus_issues
                WHERE status = '已解决' AND resolved_at IS NOT NULL
                GROUP BY category
                HAVING resolved_count >= 2
                ORDER BY avg_days DESC LIMIT 6
            """).fetchall()
            result["resolution_efficiency"] = [dict(r) for r in eff_rows]

            # ── SLA overdue (pending > 7 days) ──
            sla_rows = conn.execute("""
                SELECT id, title, category, reported_at,
                       CAST(julianday('now') - julianday(reported_at) AS INTEGER) AS days_open
                FROM campus_issues
                WHERE status IN ('待处理', '处理中')
                  AND reported_at < date('now', '-7 days')
                ORDER BY days_open DESC LIMIT 8
            """).fetchall()
            result["sla_overdue"] = [dict(r) for r in sla_rows]

            # ── Proposals summary ──
            prop_total = conn.execute("SELECT COUNT(*) as c FROM proposals").fetchone()
            prop_active = conn.execute(
                "SELECT COUNT(*) as c FROM proposals WHERE status='讨论中'"
            ).fetchone()
            prop_implemented = conn.execute(
                "SELECT COUNT(*) as c FROM proposals WHERE status='已实施'"
            ).fetchone()
            top_props = conn.execute(
                "SELECT id, title, category, supporter_count, status "
                "FROM proposals ORDER BY supporter_count DESC LIMIT 5"
            ).fetchall()

            result["proposals_summary"] = {
                "total": prop_total["c"] if prop_total else 0,
                "active": prop_active["c"] if prop_active else 0,
                "implemented": prop_implemented["c"] if prop_implemented else 0,
                "top": [dict(r) for r in top_props],
            }

            # ── Health score ──
            from data.db_health import compute_health_score
            result["health"] = compute_health_score()

    except Exception as e:
        _logger.warning("Analysis query failed: %s", e)
        result["error"] = str(e)

    return result


# ── LLM Executive Summary ──

_EXEC_LLM = None


def _get_llm():
    global _EXEC_LLM
    if _EXEC_LLM is not None:
        return _EXEC_LLM
    if not DEEPSEEK_API_KEY:
        _EXEC_LLM = False
        return None
    try:
        from openai import OpenAI
        _EXEC_LLM = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        return _EXEC_LLM
    except Exception:
        _EXEC_LLM = False
        return None


def _build_exec_summary_prompt(data: dict) -> str:
    """Build the executive summary prompt from structured analysis data."""
    kpi = data.get("kpi", {})
    ct = data.get("cross_time", {})
    za = data.get("z_anomalies", [])
    up = data.get("upgrade_paths", [])
    sla = data.get("sla_overdue", [])
    cat = data.get("category_breakdown", [])
    health = data.get("health", {})
    spatial = data.get("spatial_hotspots", [])

    parts = [
        "你是校园治理周报的首席分析师。请根据以下数据撰写一份简短的执行摘要。",
        "",
        "## 本周KPI",
        f"- 总工单: {kpi.get('total', 0)} | 待处理: {kpi.get('pending', 0)} | "
        f"处理中: {kpi.get('in_progress', 0)} | 已解决: {kpi.get('resolved', 0)}",
        f"- 紧急待处理: {kpi.get('urgent', 0)} | 本周新增: {kpi.get('week_new', 0)} | "
        f"本周解决: {kpi.get('week_resolved', 0)} | 解决率: {kpi.get('resolution_rate', 0)}%",
        f"- 治理健康度: {health.get('score', 'N/A')} 分 / {health.get('grade', 'N/A')}",
        "",
    ]

    if ct:
        parts.append("## 跨周趋势")
        parts.append(
            f"- 新增: 本周 {ct.get('new_this_week', '?')} vs 上周 {ct.get('new_last_week', '?')} "
            f"({ct.get('new_trend', '→')})"
        )
        parts.append(
            f"- 解决: 本周 {ct.get('resolved_this_week', '?')} vs 上周 {ct.get('resolved_last_week', '?')} "
            f"({ct.get('resolved_trend', '→')})"
        )
        net = "恶化" if ct.get('is_worsening') else "改善" if ct.get('is_improving') else "平稳"
        parts.append(f"- 净趋势: {net}")
        parts.append("")

    if za:
        level_cn = {"critical": "严重", "high": "高度", "moderate": "中度"}
        parts.append("## 统计异常（z-score）")
        for a in za[:5]:
            parts.append(
                f"- [{level_cn.get(a['level'], a['level'])}] {a['category']}: "
                f"z={a['z_score']}, 严重度={a['severity']}/10"
            )
        parts.append("")

    if sla:
        parts.append("## SLA 逾期")
        for s in sla[:5]:
            parts.append(
                f"- #{s['id']} {s['title'][:30]} · {s.get('category','')} · "
                f"逾期 {s['days_open']} 天"
            )
        parts.append("")

    if up:
        parts.append("## 治理升级建议")
        for u in up[:4]:
            parts.append(
                f"- {u['category']}: {u['issue_count']}件待处理 → {u['action']}"
                f"{' (已有提案)' if u.get('has_proposal') else ' (无相关提案)'}"
            )
        parts.append("")

    if spatial:
        parts.append("## 空间热点")
        for s in spatial[:5]:
            parts.append(
                f"- {s['location']}: {s['cnt']}件待处理"
                f"{' (紧急' + str(s['urgent_cnt']) + '件)' if s.get('urgent_cnt') else ''}"
            )
        parts.append("")

    parts.extend([
        "",
        "请用 200-300 字撰写执行摘要，包含：",
        "1. 本周整体态势（一句话概括）",
        "2. 1-2 个最值得关注的问题/异常",
        "3. 1-2 条具体的、可操作的行动建议",
        "",
        "要求：",
        "- 语气专业但不沉闷，像一个有洞察力的数据分析师",
        "- 明确指出需要立即处理的事项",
        "- 纯文本，不用 markdown 格式",
        "- 不要重复列举数字，要解读趋势和原因",
    ])

    return "\n".join(parts)


def _generate_exec_summary(data: dict) -> str:
    """Generate LLM-powered executive summary. Returns empty string if unavailable."""
    client = _get_llm()
    if not client:
        return ""

    prompt = _build_exec_summary_prompt(data)
    try:
        start = time.time()
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system",
                 "content": "你是一个校园治理数据分析师，擅长从数据中发现隐藏的模式和趋势。用简洁专业的中文回复。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.4,
        )
        elapsed = time.time() - start
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if text:
            _logger.info("Executive summary generated in %.1fs", elapsed)
            return text
    except Exception as e:
        _logger.warning("Executive summary generation failed: %s", e)

    return ""


# ── Formatting ──


def _format_report(data: dict, exec_summary: str) -> str:
    """Build the full markdown report from analysis data + executive summary."""
    now = datetime.now()
    lines = [
        f"# 📊 校园治理周报",
        f"**{now.strftime('%Y年%m月%d日')}** · 校园先知 CampusInsight 自动生成",
        "",
        "---",
        "",
    ]

    # ── Executive Summary ──
    if exec_summary:
        lines.append("## 🧠 执行摘要")
        lines.append("")
        lines.append(exec_summary)
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── KPI Dashboard ──
    kpi = data.get("kpi", {})
    health = data.get("health", {})
    lines.append("## 📈 KPI 仪表盘")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 📝 总工单 | {kpi.get('total', 0)} |")
    lines.append(f"| ⏳ 待处理 | {kpi.get('pending', 0)} |")
    lines.append(f"| 🔄 处理中 | {kpi.get('in_progress', 0)} |")
    lines.append(f"| ✅ 已解决 | {kpi.get('resolved', 0)} |")
    lines.append(f"| 🔥 紧急未解决 | {kpi.get('urgent', 0)} |")
    lines.append(f"| 📥 本周新增 | {kpi.get('week_new', 0)} |")
    lines.append(f"| 📤 本周解决 | {kpi.get('week_resolved', 0)} |")
    lines.append(f"| 📊 解决率 | {kpi.get('resolution_rate', 0)}% |")
    lines.append(f"| 🏥 治理健康度 | {health.get('score', 'N/A')} 分 · {health.get('grade', 'N/A')} |")
    lines.append("")

    # ── Cross-time comparison ──
    ct = data.get("cross_time", {})
    if ct:
        lines.append("---")
        lines.append("")
        lines.append("## 📅 跨周趋势对比")
        lines.append("")
        new_t = ct.get('new_trend', '→')
        res_t = ct.get('resolved_trend', '→')
        net_label = "⚠️ 净恶化" if ct.get('is_worsening') else "✅ 净改善" if ct.get('is_improving') else "→ 持平"
        lines.append(f"| 维度 | 本周 | 上周 | 趋势 |")
        lines.append(f"|------|------|------|------|")
        lines.append(f"| 新增工单 | {ct.get('new_this_week', '?')} | {ct.get('new_last_week', '?')} | {new_t} |")
        lines.append(f"| 解决工单 | {ct.get('resolved_this_week', '?')} | {ct.get('resolved_last_week', '?')} | {res_t} |")
        lines.append(f"| 净变化 | {ct.get('net_this_week', '?')} | {ct.get('net_last_week', '?')} | {net_label} |")
        lines.append("")

    # ── Anomaly alerts ──
    za = data.get("z_anomalies", [])
    if za:
        lines.append("---")
        lines.append("")
        lines.append("## 🔬 统计异常检测")
        lines.append("")
        level_icons = {"critical": "🔴", "high": "🟠", "moderate": "🟡"}
        for a in za[:5]:
            icon = level_icons.get(a['level'], '⚪')
            lines.append(
                f"- {icon} **{a['category']}**：z-score {a['z_score']}，"
                f"严重度 {a['severity']}/10，本周 {a['recent']} 件"
                f"{'，其中 ' + str(a.get('urgent_pending', 0)) + ' 件紧急' if a.get('urgent_pending') else ''}"
            )
        lines.append("")

    # ── SLA Overdue ──
    sla = data.get("sla_overdue", [])
    if sla:
        lines.append("---")
        lines.append("")
        lines.append("## ⏰ SLA 逾期预警")
        lines.append("")
        lines.append("| # | 标题 | 类别 | 逾期天数 |")
        lines.append("|---|------|------|----------|")
        for s in sla[:8]:
            days = s.get('days_open', 0)
            flag = "🔴" if days >= 14 else "🟠" if days >= 10 else "🟡"
            lines.append(
                f"| {flag} #{s['id']} | {s['title'][:30]} | "
                f"{s.get('category', '')} | {days} 天 |"
            )
        lines.append("")

    # ── Spatial hotspots ──
    spatial = data.get("spatial_hotspots", [])
    if spatial:
        lines.append("---")
        lines.append("")
        lines.append("## 🗺️ 空间热点")
        lines.append("")
        for s in spatial[:6]:
            urgent_str = f"（含紧急 {s['urgent_cnt']} 件）" if s.get('urgent_cnt') else ""
            lines.append(f"- **{s['location']}**：{s['cnt']} 件待处理 {urgent_str}")
        lines.append("")

    # ── Upgrade paths ──
    up = data.get("upgrade_paths", [])
    if up:
        lines.append("---")
        lines.append("")
        lines.append("## 🚀 治理升级路径")
        lines.append("")
        for u in up[:4]:
            has = "✅ 已有提案" if u.get('has_proposal') else "⚠️ 建议发起提案"
            lines.append(f"- **{u['category']}**：{u['issue_count']} 件待处理 → {has}")
        lines.append("")

    # ── Category breakdown ──
    cat = data.get("category_breakdown", [])
    if cat:
        lines.append("---")
        lines.append("")
        lines.append("## 📊 本周工单分类")
        lines.append("")
        lines.append("| 类别 | 数量 |")
        lines.append("|------|------|")
        for c in cat[:8]:
            lines.append(f"| {c['category']} | {c['cnt']} |")
        lines.append("")

    # ── Resolution efficiency ──
    eff = data.get("resolution_efficiency", [])
    if eff:
        lines.append("---")
        lines.append("")
        lines.append("## ⏱️ 解决效率排名")
        lines.append("")
        lines.append("| 类别 | 已解决数 | 平均天数 |")
        lines.append("|------|----------|----------|")
        for e in eff[:6]:
            flag = "🐢" if e['avg_days'] >= 5 else "🐇" if e['avg_days'] <= 2 else ""
            lines.append(f"| {flag} {e['category']} | {e['resolved_count']} | {e['avg_days']} 天 |")
        lines.append("")

    # ── Top proposals ──
    props = data.get("proposals_summary", {})
    top = props.get("top", [])
    if top:
        lines.append("---")
        lines.append("")
        lines.append("## 💡 热门提案")
        lines.append("")
        for p in top[:5]:
            status_icon = {"讨论中": "💬", "已回应": "📝", "已采纳": "✅", "已实施": "🎉"}.get(p['status'], "")
            lines.append(f"- {status_icon} **{p['title'][:30]}** · 👍{p['supporter_count']} · {p['status']}")
        lines.append("")

    # ── Footer ──
    lines.append("---")
    lines.append("")
    lines.append(f"*报告由 CampusInsight AI 自动生成于 {now.strftime('%Y-%m-%d %H:%M')}*")
    lines.append(f"*数据来源：校园先知治理数据库 · 基于 OODA 反射器 + LLM 深度分析*")

    return "\n".join(lines)


# ── Public API ──


def generate_weekly_report(include_llm_summary: bool = True) -> dict:
    """Generate a complete AI governance weekly report.

    Returns a dict with:
        - 'data': the raw analysis data (dict)
        - 'exec_summary': LLM-generated executive summary (str, may be empty)
        - 'markdown': formatted markdown report (str)
        - 'title': report title with date
    """
    data = _run_all_analysis()

    exec_summary = ""
    if include_llm_summary:
        exec_summary = _generate_exec_summary(data)

    markdown = _format_report(data, exec_summary)

    return {
        "data": data,
        "exec_summary": exec_summary,
        "markdown": markdown,
        "title": data.get("title", "校园治理周报"),
    }
