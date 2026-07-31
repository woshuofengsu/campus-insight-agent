# agent/reflector/_insight.py
"""LLM-powered natural-language insight generation ("something the data says").

Extracted from the monolithic reflector.py. When the association engine finds
significant patterns (anomalies, trends, upgrade paths), this module generates
a human-readable interpretation via a lightweight LLM call.

The LLM insight is the key differentiator — it doesn't just dump data,
it explains WHY the pattern matters and WHAT should be done about it.
"""
import logging
import time

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

_logger = logging.getLogger("agent.reflector")

_INSIGHT_LLM = None  # lazy singleton — created on first use


# ═══════════════════════ 1. LLM client (lazy singleton) ═══════════════════════

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


# ═══════════════════════ 2. Prompt builder ═══════════════════════

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

    if za:
        level_labels = {"critical": "🔴 严重", "high": "🟠 高度", "moderate": "🟡 中度"}
        items = "\n".join(
            f"- [{level_labels.get(a['level'], a['level'])}] {a['category']}: "
            f"z={a['z_score']}, 严重度={a['severity']}/10, 紧急待处理={a.get('urgent_pending',0)}件"
            for a in za[:3]
        )
        parts.append(f"## 🔬 统计异常检测（z-score法）\n{items}\n")

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

    if up:
        items = "\n".join(
            f"- {u['category']}（{u['issue_count']}件待处理）→ {u['action']}"
            f"{' ✅' if u['has_proposal'] else ' ⚠️ 无相关提案'}"
            for u in up[:3]
        )
        parts.append(f"## 🚀 治理升级建议（报→议）\n{items}\n")

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


# ═══════════════════════ 3. LLM insight generation ═══════════════════════

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
        len(sp) >= 3
        or any(t.get("cnt", 0) >= 5 for t in tm)
        or len(rc) >= 1
        or len(an) >= 1
        or any(a["severity"] >= 5 for a in za)
        or any(not u["has_proposal"] for u in up)
        or ct.get("is_worsening", False)
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
                {
                    "role": "system",
                    "content": (
                        "你是一个有洞察力的校园治理数据分析师。用简洁的中文回复，"
                        "不超过180字。重点解读数据背后的含义和趋势，给出可操作的行动建议。"
                    ),
                },
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
        # Silent fallback — LLM insight is a bonus, not critical
        pass

    return None


# ═══════════════════════ 4. Insight text builder (LLM + structured fallback) ═══════════════════════

def build_insight_text(associations: dict, user_input: str = "") -> str:
    """Build insight text: try LLM first, fall back to structured template.

    The LLM insight provides nuanced interpretation ("what does this pattern mean?")
    while the template provides structured data display. Both are shown in the
    insight panel — LLM text first (if available), then data cards.
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

    # ── Layer 2: Z-score anomaly detection ──
    if za:
        level_icons = {"critical": "🔴", "high": "🟠", "moderate": "🟡"}
        za_items = [
            f"{level_icons.get(a['level'], '⚪')} 「{a['category']}」严重度 {a['severity']}/10 "
            f"(z={a['z_score']}，本周 {a['recent']} 件"
            + (f"，{a.get('urgent_pending',0)} 件紧急" if a.get("urgent_pending") else "")
            + ")"
            for a in za[:3]
        ]
        parts.append(f"🔬 **统计异常检测**（z-score 法）：{'；'.join(za_items)}")

    # ── Layer 3: Classic anomaly detection (ratio-based) ──
    elif an:
        an_items = [
            f"「{a['category']}」本周 {a['recent']} 件 (周均 {a['baseline_avg']}，激增 +{a['spike']})"
            for a in an[:3]
        ]
        parts.append(f"⚠️ **异常检测**：{'；'.join(an_items)}")

    # ── Layer 4: Cross-time comparison ──
    if ct:
        new_str = f"新增 {ct['new_this_week']} 件 ({ct['new_trend']})"
        resolved_str = f"解决 {ct['resolved_this_week']} 件 ({ct['resolved_trend']})"
        net_label = (
            "⚠️ 净恶化" if ct.get('is_worsening')
            else "✅ 净改善" if ct.get('is_improving')
            else "→ 持平"
        )
        parts.append(f"📅 **本周 vs 上周**：{new_str}，{resolved_str}，{net_label}")

    # ── Layer 5: Upgrade path recommendations ──
    if up:
        up_items = []
        for u in up[:3]:
            has_prop = "✅ 已有提案" if u['has_proposal'] else "⚠️ 建议发起提案"
            up_items.append(f"「{u['category']}」{u['issue_count']} 件待处理 → {has_prop}")
        parts.append(f"🚀 **治理升级路径**：{'；'.join(up_items)}")

    # ── Layer 6: Data summary — spatial ──
    if sp:
        loc_names = sorted({(r.get("location") or r.get("title", ""))[:20] for r in sp})
        titles = [r["title"] for r in sp[:5]]
        ls = "、".join(loc_names[:5]) if loc_names else "该区域"
        parts.append(
            f"📍 **空间关联**：该区域（{ls}）还有 {len(sp)} 个待处理问题，"
            f"包括：{'、'.join(titles)}"
        )

    # ── Layer 7: Data summary — temporal ──
    for t in tm:
        cat, cnt = t.get("category", ""), t.get("cnt", 0)
        parts.append(
            f"📈 **时间趋势**：近7天「{cat}」类问题新增 {cnt} 件"
            f"{'，呈上升趋势' if cnt >= 5 else ''}"
        )

    # ── Layer 8: Recurrence warning ──
    if rc:
        rts = [r["title"] for r in rc[:3]]
        parts.append(
            f"🔄 **复发预警**：类似问题曾出现过并被标记为已解决，"
            f"包括：{'、'.join(rts)}。建议关注是否存在根本性原因未解决。"
        )

    # ── Layer 9: Cross-category correlation ──
    if cr:
        cr_items = [
            f"「{c['cat_a']}」↔「{c['cat_b']}」({c['co_count']} 次共现)"
            for c in cr[:3]
        ]
        parts.append(f"🔗 **类别关联**：{'；'.join(cr_items)}")

    # ── Layer 10: Linked proposals ──
    if lp:
        lp_items = [
            f"#{p['id']} {p['title'][:25]} (👍{p['supporter_count']})"
            for p in lp[:3]
        ]
        parts.append(
            f"💡 **相关提案**：{'；'.join(lp_items)}。"
            f"这些提案正在解决同类问题，你可以关注或附议！"
        )

    # ── Layer 11: Resolution efficiency ──
    if re_:
        if len(re_) >= 2:
            worst = re_[0]
            best = re_[-1]
            parts.append(
                f"⏱️ **解决效率**：「{worst['category']}」最慢 (均 {worst['avg_days']} 天)，"
                f"「{best['category']}」最快 (均 {best['avg_days']} 天)"
            )
        else:
            item = re_[0]
            parts.append(
                f"⏱️ **解决效率**：「{item['category']}」均 {item['avg_days']} 天"
                f"（{item['resolved_count']} 件已解决）"
            )

    return "\n\n".join(parts)
