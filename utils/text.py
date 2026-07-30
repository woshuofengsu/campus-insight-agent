# utils/text.py
"""Pure text-processing utilities — zero external dependencies.

These functions are used by both the UI layer (ui/) and the agent layer (agent/).
Keeping them in a standalone module avoids circular import risks and Streamlit
exec()-context issues with ui/components.py.
"""
import re


def split_thinking(content: str) -> tuple[str, str]:
    """Split AI response into (clean_content, thinking_text).

    Handles DeepSeek-style <think>...</think> and <thinking>...</thinking> tags.
    Used by both the chat UI (home.py) and the agent engine (engine.py).
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
