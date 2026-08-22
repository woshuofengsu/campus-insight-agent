# agent/roles/receptionist.py
"""社区接待员：统一入口。意图识别、纠错确认、情绪安抚、礼貌回复、帮助/自我介绍、路由。
"""
from agent import web_agent as A
from agent.roles.base import BaseAgent

# 中文意图 → 路由 key（与 roles/config.py ROUTE_MAP 对应）
INTENT_KEY_MAP = {
    "报修": "repair",
    "撤回引导": "withdraw",  # 独立处理：不建报修草稿
    "提案": "proposal",
    "政策问答": "policy",
    "通知查询": "notification",
    "天气查询": "weather",
    "身体不适": "health",
    "联系社区": "community",
    "待办提醒": "grid", "导出数据": "grid", "统计查询": "grid",
    "搜索资料": "grid", "页面跳转": "grid",
}


class ReceptionistAgent(BaseAgent):
    key = "receptionist"
    name = "社区接待员"
    icon = "👤"
    role_desc = "统一入口：意图识别、追问引导、情绪安抚、纠错确认、路由分发"
    audience = "居民/老人"
    human_stop = "意图不明确时转人工"
    tools_whitelist = ["意图识别", "纠错", "情绪识别", "路由"]

    # ---- 快捷回复 ----

    def _polite(self):
        return "不客气，有需要随时找我。"

    def _intro(self):
        return "我是社区小助手，可以帮您报修、查政策、看天气、看通知，也可以帮您联系社区。"

    def _help(self, role):
        entries = "、".join(A.quick_entries(role))
        return f"我可以帮您：{entries}。直接对我说就行，或点击下方快捷按钮。"

    def process(self, ctx: dict) -> dict:
        text = (ctx.get("user_input") or "").strip()[:200]
        role = ctx.get("role") or "resident"

        # 礼貌 / 自我介绍 / 使用帮助
        if A.detect_polite(text):
            return self._reply(self._polite(), intent="礼貌回复", chain_note="识别到礼貌用语")
        if "你是谁" in text or "你叫什么" in text:
            return self._reply(self._intro(), intent="自我介绍", chain_note="自我介绍")
        if A.detect_intent(text, role) == "使用帮助":
            return self._reply(self._help(role), intent="使用帮助", chain_note="展示功能介绍")

        # 纠错确认（先展示确认再继续；否认保留原文）
        pc = ctx["state"].get("pending_correct")
        if pc:
            ctx["state"].pop("pending_correct")
            text = pc["corrected"] if text in ("对", "确认", "是的", "确定", "对，提交") else pc["original"]
            ctx["user_input"] = text

        # 用户主动要求转人工（T6：转人工/人工客服/找真人）
        if any(k in text for k in ("转人工", "人工客服", "找真人", "人工处理", "叫工作人员", "真人帮我")):
            ctx["state"]["user_requested_human"] = True
            return self._reply("", status="routed", intent="handoff", done=False,
                               chain_note="用户主动要求转人工")

        corrected = A.correct_text(text)
        if corrected and corrected != text:
            ctx["state"]["pending_correct"] = {"original": text, "corrected": corrected}
            return self._reply(f"您说的是「{corrected}」吗？", status="需确认", intent="纠正确认",
                               actions=[{"type": "buttons", "options": ["对", "不是"]}],
                               chain_note="检测到错别字，先请用户确认")

        # 紧急语义 / 情绪
        ctx["state"]["urgent"] = A.detect_emergency(text)
        emotion = A.detect_emotion(text)

        # 意图识别（多意图取第一个主要意图；紧急语义默认联想报修）
        intent = A.detect_intent(text, role)
        if not intent:
            if ctx["state"].get("urgent"):
                intent = "repair"
            elif A.detect_go_out(text):
                return self._reply("需要帮您查天气吗？", intent="出行联想",
                                   actions=[{"type": "buttons", "options": ["查今天天气", "不用了"]}],
                                   chain_note="出行场景联想")
            elif emotion:
                return self._reply("我理解您的着急，马上为您处理。请告诉我具体的问题，比如是漏水、灯坏还是其他。",
                                   intent="情绪安抚",
                                   actions=[{"type": "buttons", "options": ["报修", "提案", "政策问答", "查天气"]}],
                                   chain_note="先安抚再引导")
            else:
                return self._reply(A.unknown_reply(role), intent="未知意图",
                                   actions=[{"type": "buttons", "options": A.quick_entries(role)}],
                                   chain_note="未识别意图，展示快捷入口")

        # 接待员落意图到黑板，交 Orchestrator 路由
        self._write("user_input", text)
        intent_key = INTENT_KEY_MAP.get(intent, "receptionist")
        self._write("user_intent", intent_key)
        self._write("user_context", {
            "role": role, "uid": ctx.get("uid"), "name": ctx.get("name"),
            "text": text, "intent_cn": intent,
        })
        return self._reply("", status="routed", intent=intent_key, done=False,
                           chain_note=f"识别为「{intent}」，路由中")
