# ui/icons.py
"""图标规范 — 功能图标统一用 Material Symbols（内联 SVG），emoji 仅作情感装饰。

Streamlit 的 st.Page 支持 Material 前缀图标（app.py 导航已用），但 st.button /
st.markdown 页面内不渲染 Material 前缀。这里提供 material_icon() 用内联 SVG
桥接，供页面内功能按钮/卡片使用。

规范：
  - 功能识别（导航/按钮/状态）→ material_icon() 或 st.Page 的 :material:*。
  - emoji → 仅问候语、成功/告警的情感点缀，不作为功能识别的唯一标识。
"""
import html as _html

# 常用 Material Symbols 的 path 数据（精简子集，按需扩充）
_ICON_PATHS = {
    "report": "M8 16h8v2H8v-2zm0-4h8v2H8v-2zm0-4h8v2H8V8zm11.6 6.9l-1.4-1.4L19.6 12l-1.4-1.5 1.4-1.4L21 10.5 19.6 12z",
    "call": "M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.5.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.2.2 2.4.6 3.5.1.3 0 .7-.2 1l-2.3 2.3z",
    "health": "M12 21s-6-4.4-9-8.5C1 9.7 2.5 6 6 6c2.2 0 3.6 1.2 4.5 2.5C11.4 7.2 12.8 6 15 6c3.5 0 5 3.7 3 6.5-3 4.1-9 8.5-9 8.5z",
    "list": "M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z",
}


def material_icon(name: str, size: int = 24, color: str = "currentColor") -> str:
    """返回 Material Symbol 的内联 SVG，查不到就返回空串。"""
    path = _ICON_PATHS.get(name)
    if not path:
        return ""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="{_html.escape(color)}" '
        f'style="vertical-align:middle;flex-shrink:0;" aria-hidden="true">'
        f'<path d="{path}"/></svg>'
    )
