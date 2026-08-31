# -*- coding: utf-8 -*-
"""LLM 自主协商决策器（P1-1）：LLM 判断是否需跨角色联动并输出结构化决策。

设计原则：
- 默认关闭（LLM_ORCHESTRATION=1 才启用），规则引擎为主干不受影响
- LLM 只输出结构化 JSON 决策（是否联动/联动谁/一句话理由），不直接面向用户
- 决策落 agent_logs 留痕；产出过 Verifier 才生效（BLOCK → 回退规则流程）
"""
import json
import os
import time
import urllib.request

_CANDIDATES = ("health_advisor", "weather_guardian", "notification_manager",
               "policy_expert", "repair_dispatch", "proposal_collab")


def decide_collaboration(user_input: str, intent: str) -> dict:
    """返回 {need: bool, target: str|None, reason: str}。未启用/异常 → {need: False}。"""
    if os.getenv("LLM_ORCHESTRATION", "0") != "1":
        return {"need": False, "target": None, "reason": "disabled"}
    try:
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
    except Exception:
        return {"need": False, "target": None, "reason": "no_config"}
    if not DEEPSEEK_API_KEY:
        return {"need": False, "target": None, "reason": "no_key"}
    start = time.time()
    try:
        payload = {
            "model": DEEPSEEK_MODEL or "deepseek-chat",
            "messages": [
                {"role": "system", "content":
                 "你是社区多智能体系统的编排决策器。判断用户诉求是否需要联动其他角色协同处理。"
                 "只输出 JSON：{\"need\": true/false, \"target\": \"角色key\", \"reason\": \"一句话\"}。"
                 f"可选角色：{'、'.join(_CANDIDATES)}。仅在诉求明显跨角色时才 need=true。"},
                {"role": "user", "content": f"意图：{intent}\n诉求：{user_input}"},
            ],
            "max_tokens": 80, "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{(DEEPSEEK_BASE_URL or 'https://api.deepseek.com/v1').rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        text = out.get("choices", [{}])[0].get("message", {}).get("content") or "{}"
        decision = json.loads(text)
        decision.setdefault("need", False)
        if decision.get("target") not in _CANDIDATES:
            decision["target"] = None
            decision["need"] = False
        try:
            from data.db_llm_usage import record_usage
            usage = out.get("usage", {})
            record_usage("自主协商决策", int(usage.get("prompt_tokens", 0)),
                         int(usage.get("completion_tokens", 0)),
                         duration_ms=int((time.time() - start) * 1000),
                         input_preview=user_input[:30])
        except Exception:
            pass
        return decision
    except Exception:
        return {"need": False, "target": None, "reason": "error"}


# =====================================================================
# P3-1：分级路由判定（规则优先降本）—— 供答辩演示与单测，不改现有调用
# =====================================================================

# 规则引擎可确定性命中的诉求特征词（无需 LLM）
_RULE_HIT_WORDS = ("报修", "漏水", "灯", "坏了", "堵", "提案", "政策", "医保", "天气",
                   "温度", "下雨", "通知", "社区电话", "联系社区", "怎么用", "帮助")


def route_grade(user_input: str, intent: str = "") -> dict:
    """显式分级：判定该诉求走「规则引擎」（0 成本）还是「LLM」（按需）。

    返回 {grade: "rule"|"llm", reason: str, rule_hits: [...]}。
    仅在固定词命中且意图明确时判为 rule；否则 llm（保守，宁多调用不误判）。
    说明：Web 端现状即「规则优先」，本函数把该策略显式化、可测试。
    """
    text = user_input or ""
    hits = [w for w in _RULE_HIT_WORDS if w in text]
    # 有明确业务词命中 + 已有意图 → 规则可覆盖
    if hits and intent:
        return {"grade": "rule", "reason": f"命中规则词 {hits}，不由 LLM 处理", "rule_hits": hits}
    # 无明确业务词 → 需 LLM 理解
    if not hits:
        return {"grade": "llm", "reason": "无明确规则词，需 LLM 理解", "rule_hits": []}
    # 有词但意图未定（模糊）→ 保守走 LLM
    return {"grade": "llm", "reason": f"命中规则词 {hits} 但意图未明，保守走 LLM", "rule_hits": hits}
