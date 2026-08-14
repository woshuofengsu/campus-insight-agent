# agent/weekly_report.py
"""治理周报生成器 — 自动分析社区治理数据并生成结构化周报。

复用 reflector 的分析函数（z-score 异常、跨周对比、升级路径），
拼出执行摘要（LLM）、KPI 快照、异常提醒、趋势分析、解决效率、
升级路径、空间热点和复发风险。
"""

import logging
import time
from datetime import datetime

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from data.db_core import get_db

_logger = logging.getLogger("agent.weekly_report")

# 复用 reflector 的分析（延迟 import，避免模块级循环依赖）


def _run_all_analysis():
    """跑一遍 reflector 的全部分析维度，返回结构化字典。"""
    from agent.reflector import (
        _z_score_anomalies,
        _cross_time_comparison,
        _detect_upgrade_paths,
    )

    result = {
        "generated_at": datetime.now().isoformat(),
        "title": f"社区治理周报 · {datetime.now().strftime('%Y年%m月%d日')}",
    }

    try:
        with get_db() as conn:
            result["z_anomalies"] = _z_score_anomalies(conn)
            result["cross_time"] = _cross_time_comparison(conn)
            result["upgrade_paths"] = _detect_upgrade_paths(conn)

            # 总体 KPI
            total = conn.execute("SELECT COUNT(*) as c FROM community_issues").fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) as c FROM community_issues WHERE status='待处理'"
            ).fetchone()
            in_progress = conn.execute(
                "SELECT COUNT(*) as c FROM community_issues WHERE status='处理中'"
            ).fetchone()
            resolved = conn.execute(
                "SELECT COUNT(*) as c FROM community_issues WHERE status='已解决'"
            ).fetchone()
            urgent = conn.execute(
                "SELECT COUNT(*) as c FROM community_issues "
                "WHERE urgency IN ('极急','紧急') AND status != '已解决'"
            ).fetchone()
            week_new = conn.execute(
                "SELECT COUNT(*) as c FROM community_issues "
                "WHERE reported_at > date('now', '-7 days')"
            ).fetchone()
            week_resolved = conn.execute(
                "SELECT COUNT(*) as c FROM community_issues "
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

            # 本周分类明细
            cat_rows = conn.execute("""
                SELECT category, COUNT(*) as cnt
                FROM community_issues
                WHERE reported_at > date('now', '-7 days')
                GROUP BY category
                ORDER BY cnt DESC LIMIT 8
            """).fetchall()
            result["category_breakdown"] = [dict(r) for r in cat_rows]

            # 空间热点
            spatial_rows = conn.execute("""
                SELECT location, COUNT(*) as cnt,
                       SUM(CASE WHEN urgency='紧急' THEN 1 ELSE 0 END) as urgent_cnt
                FROM community_issues
                WHERE status IN ('待处理', '处理中') AND location != ''
                GROUP BY location
                ORDER BY cnt DESC LIMIT 6
            """).fetchall()
            result["spatial_hotspots"] = [dict(r) for r in spatial_rows]

            # 解决效率
            eff_rows = conn.execute("""
                SELECT category,
                       COUNT(*) AS resolved_count,
                       ROUND(AVG(julianday(resolved_at) - julianday(reported_at)), 1) AS avg_days
                FROM community_issues
                WHERE status = '已解决' AND resolved_at IS NOT NULL
                GROUP BY category
                HAVING resolved_count >= 2
                ORDER BY avg_days DESC LIMIT 6
            """).fetchall()
            result["resolution_efficiency"] = [dict(r) for r in eff_rows]

            # SLA 超时（分级口径统一走 data/db_sla.py）
            from data.db_sla import get_sla_breaches
            result["sla_overdue"] = [
                {**s, "days_open": s.get("hours_open", 0) // 24}
                for s in get_sla_breaches(limit=8)
            ]

            # 提案汇总
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

            # 健康度评分
            from data.db_health import compute_health_score
            result["health"] = compute_health_score()

    except Exception as e:
        _logger.warning("分析查询失败：%s", e)
        result["error"] = str(e)

    return result


# LLM 执行摘要

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
        _logger.debug("初始化执行摘要 LLM 客户端失败", exc_info=True)
        _EXEC_LLM = False
        return None


def _build_exec_summary_prompt(data: dict) -> str:
    """根据结构化分析数据拼执行摘要的 prompt。"""
    kpi = data.get("kpi", {})
    ct = data.get("cross_time", {})
    za = data.get("z_anomalies", [])
    up = data.get("upgrade_paths", [])
    sla = data.get("sla_overdue", [])
    cat = data.get("category_breakdown", [])
    health = data.get("health", {})
    spatial = data.get("spatial_hotspots", [])

    parts = [
        "你是社区治理周报的首席分析师。请根据以下数据撰写一份简短的执行摘要。",
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
        parts.append("## SLA 超时")
        for s in sla[:5]:
            parts.append(
                f"- #{s['id']} {s['title'][:30]} · {s.get('category','')} · "
                f"超时 {s['days_open']} 天"
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
    """让 LLM 生成执行摘要，用不了就返回空字符串。"""
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
                 "content": "你是一个社区治理数据分析师，擅长从数据中发现隐藏的模式和趋势。用简洁专业的中文回复。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.4,
        )
        elapsed = time.time() - start
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if text:
            _logger.info("执行摘要生成耗时 %.1fs", elapsed)
            return text
    except Exception as e:
        _logger.warning("执行摘要生成失败：%s", e)

    return ""


# 排版输出


def _format_report(data: dict, exec_summary: str) -> str:
    """用分析数据和执行摘要拼出完整的 markdown 周报。"""
    now = datetime.now()
    lines = [
        f"# 📊 社区治理周报",
        f"**{now.strftime('%Y年%m月%d日')}** · 社区先知 CommunityInsight 自动生成",
        "",
        "---",
        "",
    ]

    # 执行摘要
    if exec_summary:
        lines.append("## 🧠 执行摘要")
        lines.append("")
        lines.append(exec_summary)
        lines.append("")
        lines.append("---")
        lines.append("")

    # KPI 仪表盘
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

    # 跨周对比
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

    # 异常提醒
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

    # SLA 超时
    sla = data.get("sla_overdue", [])
    if sla:
        lines.append("---")
        lines.append("")
        lines.append("## ⏰ SLA 超时预警")
        lines.append("")
        lines.append("| # | 标题 | 类别 | 超时天数 |")
        lines.append("|---|------|------|----------|")
        for s in sla[:8]:
            days = s.get('days_open', 0)
            flag = "🔴" if s.get("level") == "critical" else "🟡"
            lines.append(
                f"| {flag} #{s['id']} | {s['title'][:30]} | "
                f"{s.get('category', '')} | {days} 天 |"
            )
        lines.append("")

    # 空间热点
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

    # 升级路径
    up = data.get("upgrade_paths", [])
    if up:
        lines.append("---")
        lines.append("")
        lines.append("## 治理升级路径")
        lines.append("")
        for u in up[:4]:
            has = "✅ 已有提案" if u.get('has_proposal') else "⚠️ 建议发起提案"
            lines.append(f"- **{u['category']}**：{u['issue_count']} 件待处理 → {has}")
        lines.append("")

    # 分类明细
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

    # 解决效率
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

    # 热门提案
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

    # 结尾
    lines.append("---")
    lines.append("")
    lines.append(f"*报告由 CommunityInsight 自动生成于 {now.strftime('%Y-%m-%d %H:%M')}*")
    lines.append(f"*数据来源：社区先知治理数据库 · 基于 OODA 反射器分析*")

    return "\n".join(lines)


# 对外接口


def generate_weekly_report(include_llm_summary: bool = True) -> dict:
    """生成一份完整的治理周报。

    返回字典：
        - 'data': 原始分析数据（dict）
        - 'exec_summary': LLM 生成的执行摘要（str，可能为空）
        - 'markdown': 排好版的 markdown 周报（str）
        - 'title': 带日期的周报标题
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
        "title": data.get("title", "社区治理周报"),
    }
