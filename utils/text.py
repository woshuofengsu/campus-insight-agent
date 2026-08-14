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
