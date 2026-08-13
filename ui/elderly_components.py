# ui/elderly_components.py
"""老年关怀版专用组件 — 大字卡片、大按钮、TTS 朗读、语音输入（渐进增强）。

设计原则：全站大字（20px+）、高对比、按钮 ≥64px、避免精确控件；
语音能力（ASR/TTS）走浏览器 Web Speech API，不支持时自动降级为文字，绝不阻塞。
"""
import json

import streamlit as st


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
            background: #ffffff; border: 2px solid #e2e8f0; border-radius: 16px;
            padding: 20px; margin: 12px 0; font-size: 1.1em; line-height: 1.7;
        }
        .elderly-title { font-size: 1.6em !important; font-weight: 800; }
    </style>
    """, unsafe_allow_html=True)


def big_card(markdown_text: str, bg: str = "#ffffff", border: str = "#e2e8f0"):
    st.markdown(
        f'<div style="background:{bg};border:2px solid {border};border-radius:16px;'
        f'padding:20px;margin:12px 0;font-size:1.1em;line-height:1.7;">{markdown_text}</div>',
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


def voice_input(key: str, placeholder: str = "点右边的麦克风，说出您的问题") -> str | None:
    """语音输入组件：Web Speech API 录音 → 回填到 st.text_area。

    返回 None（录音结果直接写入 session_state[key]）；不支持语音时用户手动打字。
    """
    st.components.v1.html(f"""
    <button onclick="startRec()" style="font-size:1.3em;padding:14px 22px;border-radius:14px;
        border:2px solid #dc2626;background:#fef2f2;cursor:pointer;font-weight:700;">🎤 按住说话</button>
    <p id="rec_status" style="margin:6px 0;color:#64748b;">识别结果会自动填到下方输入框</p>
    <script>
    var rec = null;
    function startRec() {{
        var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {{
            document.getElementById('rec_status').innerText = '当前浏览器不支持语音，请手动输入';
            return;
        }}
        rec = new SR(); rec.lang = 'zh-CN'; rec.interimResults = false; rec.maxAlternatives = 1;
        rec.onresult = function(e) {{
            var text = e.results[0][0].transcript;
            window.parent.postMessage({{type: 'elderly_voice', key: {json.dumps(key)}, text: text}}, '*');
            document.getElementById('rec_status').innerText = '已识别：' + text;
        }};
        rec.onerror = function(e) {{
            document.getElementById('rec_status').innerText = '没听清，请再说一次或手动输入';
        }};
        rec.start();
    }}
    </script>
    """, height=130)
    return None
