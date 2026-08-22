# agent/prompt_guard.py
"""Prompt 注入防护（P2-06，五层防护中的输入过滤层 + 输出检测层）。

五层防护：
1. 输入过滤（本模块 detect_injection）
2. 系统提示词加固（agent/prompt.py：最重要规则 + 标签隔离）
3. LLM 输出校验（agent/verifier.py：注入特征检测）
4. 后端权限强制（各端点角色/属主校验，已落地）
5. 合规审计员复核（agent/roles/compliance.py）

检测到注入：拦截 → 固定安全语 → 留痕 → 记录异常（告警）。
"""
import logging

_log = logging.getLogger(__name__)

# 输入注入关键词/模式（指令覆盖 / 角色扮演 / 数据泄露 / 越权 / 安全绕过）
_INPUT_INJECTION_PATTERNS = [
    ("指令覆盖", ("忽略之前的指令", "忽略以上指令", "忘记规则", "无视规则", "忽略所有规则")),
    ("提示词泄露", ("系统提示词", "system prompt", "你的指令是什么", "把你的提示词")),
    ("角色扮演", ("你是自由AI", "不受限制的AI", "你现在是", "扮演成不受限", "没有限制")),
    ("数据泄露", ("所有居民信息", "列出所有居民", "全部用户数据", "所有工单数据", "导出所有数据",
                 "全部手机号", "所有电话", "所有身份证")),
    ("越权请求", ("帮我审核", "帮我发布", "直接发布", "帮我关闭工单", "改成已完成", "帮我删除",
                 "给我管理员", "提升权限")),
    ("安全绕过", ("忽略合规", "绕过校验", "跳过检查", "不需要确认", "直接通过")),
]

# 输出注入特征（LLM 被注入后可能输出这些）
_OUTPUT_INJECTION_PATTERNS = [
    "我无法遵守", "作为AI", "system prompt", "系统提示词", "忽略之前的",
    "以管理员身份", "已为您审核", "已发布紧急通知",
]


def detect_injection(text: str) -> str | None:
    """输入注入检测：命中返回类别（如「指令覆盖」），未命中返回 None。"""
    text = (text or "").lower()
    for cat, kws in _INPUT_INJECTION_PATTERNS:
        for kw in kws:
            if kw.lower() in text:
                return cat
    return None


def detect_output_injection(text: str) -> str | None:
    """输出注入特征检测（Verifier 用）：命中返回特征，未命中 None。"""
    text = (text or "").lower()
    for kw in _OUTPUT_INJECTION_PATTERNS:
        if kw.lower() in text:
            return kw
    return None


def safe_reply() -> str:
    """固定安全语（人性化，不冷冰冰）。"""
    return "抱歉，我无法处理这个请求。您可以换一种方式描述问题，比如报修、查政策、看天气。"
