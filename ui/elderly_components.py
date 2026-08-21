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

# TTS 朗读自定义组件（v2：支持音量、5 分钟重试、失败回传通知负责人）
_TTS_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "static", "elderly_tts")
_tts_component = components.declare_component("elderly_tts", path=_TTS_COMPONENT_DIR)


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


def tts_speak(text: str, label: str = "🔊 朗读", volume: float | None = None):
    """朗读文本（浏览器 SpeechSynthesis，渐进增强）。

    - volume：音量（0~2，按老人设置传入；默认从 session `_tts_volume` 读，缺省 1.0）
    - 失败自动重试 3 次、每次间隔 5 分钟（spec）；最终失败回传 "__TTS_FAIL__"，
      由调用方留痕并通知负责人「提醒发送失败」。
    """
    if volume is None:
        try:
            volume = float(st.session_state.get("_tts_volume", 1.0))
        except (TypeError, ValueError):
            volume = 1.0
    try:
        with open(os.path.join(_TTS_COMPONENT_DIR, "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("{{{TEXT_JSON}}}", json.dumps(text, ensure_ascii=False))
        html = html.replace("{{{VOLUME_JSON}}}", str(float(volume)))
        result = _tts_component(html=html, key=f"tts_{abs(hash(text)) % 10**9}", default="")
        if result == "__TTS_FAIL__":
            try:
                from data.db_notifications import log_activity, log_exception
                log_activity("系统", "老年端语音播报失败", "tts", module="老年端",
                             detail=f"播报内容：{text[:60]}（重试 3 次失败，已通知负责人）")
                log_exception("老年端", f"语音播报失败（3 次重试后）：{text[:60]}")
                from data.db_user import list_users
                for u in list_users(role="grid"):
                    from data.db_notifications import create_notification
                    create_notification(u["id"], "tts", "⚠️ 老年端语音播报失败",
                                        "语音朗读重试 3 次仍失败，请提醒老人查看文字内容。")
            except Exception:
                pass
    except Exception:
        # 组件不可用时降级为普通朗读按钮（HTML 内联，兼容旧行为）
        text_js = json.dumps(text, ensure_ascii=False)
        st.components.v1.html(f"""
        <button onclick="speak()" style="font-size:1.2em;padding:14px 22px;border-radius:14px;
            border:2px solid #4f46e5;background:#eef2ff;cursor:pointer;font-weight:700;">{label}</button>
        <div id="tts_msg" style="font-size:1em;color:#b91c1c;margin-top:6px;"></div>
        <script>
        function speak() {{
            if (!('speechSynthesis' in window)) {{
                document.getElementById('tts_msg').textContent = '当前浏览器不支持语音朗读，请查看文字';
                return;
            }}
            var u = new SpeechSynthesisUtterance({text_js});
            u.lang = 'zh-CN'; u.rate = 0.9; u.volume = {float(volume)};
            u.onerror = function() {{
                document.getElementById('tts_msg').textContent = '语音播放失败，请查看文字';
            }};
            speechSynthesis.cancel();
            speechSynthesis.speak(u);
        }}
        </script>
        """, height=96)


def voice_input(key: str | None = None) -> str | None:
    """语音输入组件：Web Speech API 录音 → 通过双向组件把识别文本回传给 Python。

    返回识别文本（或 None 表示未识别/不支持）；调用方把返回值回填到输入框。
    """
    try:
        value = _voice_input_component(key=key, default=None)
        return value if isinstance(value, str) and value.strip() else None
    except Exception:
        return None
