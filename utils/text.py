# utils/text.py
"""纯文本处理工具，不依赖任何第三方库。

UI 层（ui/）和 agent 层（agent/）都在用。单独拆出来是为了避免循环 import，
也躲开 Streamlit 对 ui/components.py 的 exec() 上下文问题。
"""
import re


def split_thinking(content: str) -> tuple[str, str]:
    """把 AI 回复拆成（正文, 思考过程）两部分。

    处理 DeepSeek 风格的 <think>...</think> 和 <thinking>...</thinking> 标签。
    聊天页（home.py）和 agent 引擎（engine.py）都在用。
    """
    thinking_parts: list[str] = []
    cleaned = content

    _t1, _t2 = "<think>", "</think>"
    for match in reversed(list(re.finditer(re.escape(_t1) + r'(.*?)' + re.escape(_t2), cleaned, re.DOTALL))):
        thinking_parts.append(match.group(0))
        cleaned = cleaned[:match.start()] + cleaned[match.end():]

    _t3, _t4 = "<thinking", "</thinking>"
    for match in reversed(list(re.finditer(
        re.escape(_t3) + r'[^>]*>' + r'(.*?)' + re.escape(_t4),
        cleaned, re.DOTALL | re.IGNORECASE,
    ))):
        thinking_parts.append(match.group(1).strip())
        cleaned = cleaned[:match.start()] + cleaned[match.end():]

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    thinking = "\n\n---\n\n".join(reversed(thinking_parts)) if thinking_parts else ""
    return cleaned, thinking


# ---- 敏感词检测（通知/内容发布前拦截，spec 05/04：涉政治、暴力、诈骗、隐私等）----

_SENSITIVE_WORDS = [
    # 涉政/违法（演示用最小集，可扩展）
    "共产党", "习近平", "习主席", "法轮功", "台独", "藏独", "疆独", "港独",
    "颠覆国家", "恐怖", "爆炸物", "枪支弹药",
    # 诈骗/隐私
    "转账给我", "打钱到", "汇款账号", "银行卡号", "身份证号", "密码发我",
    # 辱骂/色情
    "傻逼", "妈的", "操你", "妓女", "嫖娼", "赌博",
]


def check_sensitive(text: str) -> tuple[bool, str]:
    """敏感词检测：返回 (是否含敏感词, 命中的敏感词)。"""
    text = text or ""
    for w in _SENSITIVE_WORDS:
        if w and w in text:
            return True, w
    return False, ""
