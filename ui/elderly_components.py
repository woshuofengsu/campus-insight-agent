# ui/elderly_components.py
"""老年关怀版专用组件 — 大字卡片、大按钮、TTS 朗读、语音输入（渐进增强）。

设计原则：全站大字（20px+）、高对比、按钮 ≥64px、避免精确控件；
语音能力（ASR/TTS）走浏览器 Web Speech API，不支持时自动降级为文字，绝不阻塞。
"""
import json
import os

import streamlit as st
import streamlit.components.v1 as components

# 语音输入自定义组件（双向回传识别文本）
_VOICE_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "static", "voice_input")
_voice_input_component = components.declare_component("voice_input", path=_VOICE_COMPONENT_DIR)


def inject_elderly_css():
    """注入老年关怀版全局大字 + 高对比样式。"""
    st.markdown("""
    <style>
        /* 老年关怀版：全站大字 + 高对比 */
        .stApp { font-size: 20px !important; }
        .stButton button, .stDownloadButton button {
            min-height: 64px !important;
            font-size: 1.25em !important;
            font-weight: 700 !important;
            border-radius: 16px !important;
        }
        .stTextInput input, .stTextArea textarea { font-size: 1.2em !important; }
        .elderly-card {
            background: #ffffff; border: 2px solid #334155; border-radius: 16px;
            padding: 20px; margin: 12px 0; font-size: 1.1em; line-height: 1.7;
            color: #000000;
        }
        .elderly-title { font-size: 1.6em !important; font-weight: 800; color: #000000; }
    </style>
    """, unsafe_allow_html=True)


def big_card(markdown_text: str, bg: str = "#ffffff", border: str = "#334155"):
    st.markdown(
        f'<div style="background:{bg};border:2px solid {border};border-radius:16px;'
        f'padding:20px;margin:12px 0;font-size:1.1em;line-height:1.7;color:#000000;">{markdown_text}</div>',
        unsafe_allow_html=True,
    )


def big_button(label: str, key: str, primary: bool = True, on_click=None, args=None):
    return st.button(
        label, key=key, type="primary" if primary else "secondary",
        on_click=on_click, args=args, width="stretch",
    )


def tts_speak(text: str, label: str = "🔊 朗读"):
    """朗读文本（浏览器 SpeechSynthesis，渐进增强）。"""
    text_js = json.dumps(text, ensure_ascii=False)
    st.components.v1.html(f"""
    <button onclick="speak()" style="font-size:1.2em;padding:14px 22px;border-radius:14px;
        border:2px solid #4f46e5;background:#eef2ff;cursor:pointer;font-weight:700;">{label}</button>
    <script>
    function speak() {{
        if ('speechSynthesis' in window) {{
            var u = new SpeechSynthesisUtterance({text_js});
            u.lang = 'zh-CN'; u.rate = 0.9;
            speechSynthesis.cancel(); speechSynthesis.speak(u);
        }} else {{
            alert('当前浏览器不支持语音朗读');
        }}
    }}
    </script>
    """, height=64)


def voice_input(key: str | None = None) -> str | None:
    """语音输入组件：Web Speech API 录音 → 通过双向组件把识别文本回传给 Python。

    返回识别文本（或 None 表示未识别/不支持）；调用方把返回值回填到输入框。
    """
    try:
        value = _voice_input_component(key=key, default=None)
        return value if isinstance(value, str) and value.strip() else None
    except Exception:
        return None
