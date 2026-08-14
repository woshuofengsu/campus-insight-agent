# agent/reflector/_insight.py
"""用 LLM 把关联数据生成洞察。

关联引擎找到显著模式（异常、趋势、升级路径）时，
这个模块用一次轻量 LLM 调用生成人话解读。
"""
import logging
import time

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

_logger = logging.getLogger("agent.reflector")

_INSIGHT_LLM = None  # 懒加载单例——第一次用的时候才建


# 1. LLM 客户端（懒加载单例）

def _get_insight_llm():
    """懒初始化一个轻量 LLM 客户端，专门生成洞察。

    和主 Agent 的 LLM 分开——只做事后分析用。
    没配 API key 就返回 None。
    """
    global _INSIGHT_LLM
    if _INSIGHT_LLM is not None:
        return _INSIGHT_LLM
    if not DEEPSEEK_API_KEY:
        _INSIGHT_LLM = False  # 哨兵值：试过了，但没有
        return None
    try:
        from openai import OpenAI
        _INSIGHT_LLM = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        return _INSIGHT_LLM
    except Exception:
        _logger.debug("初始化洞察 LLM 客户端失败", exc_info=True)
        _INSIGHT_LLM = False
        return None


# 2. Prompt 组装

def _build_insight_prompt(associations: dict, user_input: str) -> str:
    """给 LLM 洞察生成器拼一个聚焦的 prompt。

    现在包含：跨周对比、带严重度的 z-score 异常、升级路径建议、
    解决效率数据。
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

    parts = ["你是一位社区治理数据分析师。以下是根据用户消息自动发现的关联数据：", ""]

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
        "- 语气像一个有洞察力的社区治理分析师，看到别人看不到的模式",
        "- 给出 1-2 条最具体、最可操作的下一步建议",
        "- 纯文本，不用 markdown，不用 emoji 前缀",
    ])

    return "\n".join(parts)


# 3. LLM 洞察生成

def _generate_llm_insight(associations: dict, user_input: str) -> str | None:
    """试着生成一条有深度的 LLM 洞察，不行/失败就返回 None。

    只在关联足够显著值得分析时才调。
    阈值加强过：z 异常严重度 ≥5、有未覆盖类别的升级路径、
    跨周恶化趋势，或者经典触发条件。
    """
    sp = associations.get("spatial", [])
    tm = associations.get("temporal", [])
    rc = associations.get("recurrence", [])
    an = associations.get("anomalies", [])
    za = associations.get("z_anomalies", [])
    up = associations.get("upgrade_paths", [])
    ct = associations.get("cross_time", {})

    # 加强后的显著度阈值
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
                        "你是一个有洞察力的社区治理数据分析师。用简洁的中文回复，"
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
            _logger.info("LLM 洞察生成耗时 %.1fs（%d 字）", elapsed, len(text))
            return text
    except Exception:
        # 静默兜底——LLM 洞察是加分项，不是必须的
        _logger.debug("LLM 洞察生成失败", exc_info=True)
        pass

    return None


# 4. 洞察文本组装（LLM + 结构化兜底）

def build_insight_text(associations: dict, user_input: str = "") -> str:
    """组装洞察文本：先试 LLM，不行就用结构化模板。

    LLM 洞察负责解释"这个模式说明什么"，模板负责摆数据。
    两者都显示在洞察面板——LLM 文本在前（有的话），数据卡片在后。
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

    # 第 1 层：LLM 解读（回答"为什么"）
    llm_insight = _generate_llm_insight(associations, user_input)
    if llm_insight:
        parts.append(f"🧠 **深度解读**：{llm_insight}")

    # 第 2 层：z-score 异常检测
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

    # 第 3 层：经典异常检测（比例法）
    elif an:
        an_items = [
            f"「{a['category']}」本周 {a['recent']} 件 (周均 {a['baseline_avg']}，激增 +{a['spike']})"
            for a in an[:3]
        ]
        parts.append(f"⚠️ **异常检测**：{'；'.join(an_items)}")

    # 第 4 层：跨周对比
    if ct:
        new_str = f"新增 {ct['new_this_week']} 件 ({ct['new_trend']})"
        resolved_str = f"解决 {ct['resolved_this_week']} 件 ({ct['resolved_trend']})"
        net_label = (
            "⚠️ 净恶化" if ct.get('is_worsening')
            else "✅ 净改善" if ct.get('is_improving')
            else "→ 持平"
        )
        parts.append(f"📅 **本周 vs 上周**：{new_str}，{resolved_str}，{net_label}")

    # 第 5 层：升级路径建议
    if up:
        up_items = []
        for u in up[:3]:
            has_prop = "✅ 已有提案" if u['has_proposal'] else "⚠️ 建议发起提案"
            up_items.append(f"「{u['category']}」{u['issue_count']} 件待处理 → {has_prop}")
        parts.append(f"🚀 **治理升级路径**：{'；'.join(up_items)}")

    # 第 6 层：数据摘要——空间
    if sp:
        loc_names = sorted({(r.get("location") or r.get("title", ""))[:20] for r in sp})
        titles = [r["title"] for r in sp[:5]]
        ls = "、".join(loc_names[:5]) if loc_names else "该区域"
        parts.append(
            f"📍 **空间关联**：该区域（{ls}）还有 {len(sp)} 个待处理问题，"
            f"包括：{'、'.join(titles)}"
        )

    # 第 7 层：数据摘要——时间
    for t in tm:
        cat, cnt = t.get("category", ""), t.get("cnt", 0)
        parts.append(
            f"📈 **时间趋势**：近7天「{cat}」类问题新增 {cnt} 件"
            f"{'，呈上升趋势' if cnt >= 5 else ''}"
        )

    # 第 8 层：复发预警
    if rc:
        rts = [r["title"] for r in rc[:3]]
        parts.append(
            f"🔄 **复发预警**：类似问题曾出现过并被标记为已解决，"
            f"包括：{'、'.join(rts)}。建议关注是否存在根本性原因未解决。"
        )

    # 第 9 层：跨类别关联
    if cr:
        cr_items = [
            f"「{c['cat_a']}」↔「{c['cat_b']}」({c['co_count']} 次共现)"
            for c in cr[:3]
        ]
        parts.append(f"🔗 **类别关联**：{'；'.join(cr_items)}")

    # 第 10 层：相关提案
    if lp:
        lp_items = [
            f"#{p['id']} {p['title'][:25]} (👍{p['supporter_count']})"
            for p in lp[:3]
        ]
        parts.append(
            f"💡 **相关提案**：{'；'.join(lp_items)}。"
            f"这些提案正在解决同类问题，你可以关注或附议！"
        )

    # 第 11 层：解决效率
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
