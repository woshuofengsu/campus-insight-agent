# app.py
"""社区先知 CommunityInsight Agent — Streamlit 多页面入口."""
import sys
import os

# 把项目根目录加进路径，不然 import 找不到模块
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from ui.session_state import SS
import altair as alt
from config import DEEPSEEK_API_KEY, OFFLINE_MODE

# 全局图表配色，个别图表可以在 configure_altair() 里覆盖
@alt.theme.register("community", enable=True)
def _alt_theme():
    return alt.theme.ThemeConfig({
        "background": "transparent",
        "view": {"stroke": "transparent"},
        "axis": {
            "gridColor": "rgba(0,0,0,0.06)", "domainColor": "rgba(0,0,0,0.10)",
            "tickColor": "rgba(0,0,0,0.10)", "labelColor": "#64748b",
            "titleColor": "#475569", "labelFontSize": 11, "titleFontSize": 12,
        },
        "bar": {"color": "#4f46e5"},
        "line": {"strokeWidth": 2, "color": "#4f46e5"},
        "point": {"filled": True, "size": 50, "color": "#4f46e5"},
})
from ui.session import init_session
from ui.onboarding import render_onboarding
from ui.login import render_login
from ui.theme import inject_theme_css, apply_theme_at_startup, apply_native_theme
from ui.notify import check_and_notify
from agent.rag import build_index


def main():
    # 原生主题必须在 set_page_config 之前设置，这个顺序对 baseweb 很关键
    apply_theme_at_startup()

    # 页面配置——侧边栏只在登录后展开
    # 设完马上再调 apply_native_theme() 保住暗色模式，
    # 不然 st.set_page_config() 会把 config.toml 里的配置重置掉。
    st.set_page_config(
        page_title="社区先知 · CommunityInsight",
        page_icon="🏘️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 原生主题覆盖，每次 set_page_config 之后都得跟着调一次
    apply_native_theme()

    # 全局 CSS
    from ui.css import inject_global_css, inject_sidebar_force_css
    inject_global_css()
    inject_theme_css()
    inject_sidebar_force_css()

    # 校验 .env，离线演示模式就跳过
    is_offline = OFFLINE_MODE
    try:
        qp = st.query_params.get("offline")
        if qp and str(qp).lower() in ("1", "true", "yes"):
            is_offline = True
    except Exception:
        pass  # 有的 Streamlit 版本没有 query_params，不重要，忽略

    if not DEEPSEEK_API_KEY and not is_offline:
        st.warning(
            "⚠️ 未检测到 DeepSeek API Key，已自动切换到**离线演示模式**。\n\n"
            "部分功能（自动分类、反思分析）将使用离线规则替代。"
        )
        st.caption("复制 `.env.example` 为 `.env` 并填入 API Key 即可启用完整智能对话能力。")
        is_offline = True
        st.session_state._force_offline = True

    # 初始化会话（DB + Agent + 记忆）
    try:
        agent, memory = init_session()
    except Exception as e:
        st.error(f"😅 系统初始化失败：{e}\n请检查 .env 中的 API Key 是否正确。")
        st.stop()

    # 后台调度器（守护线程，自动任务幂等，失败不影响主流程）
    try:
        from scripts.scheduler import ensure_scheduler_started
        ensure_scheduler_started(interval=60)
    except Exception:
        pass  # 调度器不是必须的，别卡住启动

    # 建 RAG 索引（不阻塞启动，建过就跳过）
    try:
        build_index(force=False)
    except Exception:
        pass  # RAG 不是必须的，别卡住启动

    # 登录门槛
    if SS.login_user_id not in st.session_state:
        render_login()
        return

    # 新人引导（只有新用户会走）
    if not memory.is_onboarding_done():
        render_onboarding(memory)
        return

    # 实时通知检查（toast 弹窗）
    check_and_notify()

    # 多页面导航
    profile = memory.get_user_profile()
    if profile is None:
        profile = {}
    role = profile.get("role", "resident")

    # 家属绑定模式：绑定了老人的家属可进入老年端（以老人身份免登录操作，spec 06）
    if role != "elderly" and profile.get("id"):
        try:
            from data.db_user import get_bound_elderly
            _elder = get_bound_elderly(profile["id"])
            if _elder:
                role = "elderly"
                st.session_state["_elderly_uid"] = _elder["id"]
                st.session_state["_elderly_name"] = _elder.get("name") or "大爷/阿姨"
        except Exception:
            pass

    if role == "grid":
        nav = st.navigation([
            st.Page("ui/pages_grid/dashboard.py", title="工作台", icon=":material/dashboard:", default=True),
            st.Page("ui/pages_grid/issues_mgmt.py", title="工单管理", icon=":material/assignment:"),
            st.Page("ui/pages_grid/proposals_mgmt.py", title="提案管理", icon=":material/lightbulb:"),
            st.Page("ui/pages_grid/notices_mgmt.py", title="通知管理", icon=":material/campaign:"),
            st.Page("ui/pages_grid/policy_mgmt.py", title="政策问答管理", icon=":material/quiz:"),
            st.Page("ui/pages_grid/weather_mgmt.py", title="天气管理", icon=":material/cloud:"),
            st.Page("ui/pages_grid/content_mgmt.py", title="内容发布", icon=":material/campaign:"),
            st.Page("ui/pages_grid/insights.py", title="数据洞察", icon=":material/insights:"),
            st.Page("ui/pages_grid/health_mgmt.py", title="健康管理", icon=":material/health_and_safety:"),
            st.Page("ui/pages_grid/elderly_care_mgmt.py", title="老年关怀管理", icon=":material/elderly:"),
        ])
    elif role == "elderly":
        nav = st.navigation([
            st.Page("ui/pages_elderly/home.py", title="🏠 首页", icon=":material/home:", default=True),
            st.Page("ui/pages_elderly/report.py", title="🗣️ 一句话上报", icon=":material/mic:"),
            st.Page("ui/pages_elderly/progress.py", title="📋 我的工单", icon=":material/assignment:"),
            st.Page("ui/pages_elderly/notify.py", title="🔊 听通知", icon=":material/notifications:"),
            st.Page("ui/pages_elderly/health.py", title="🏥 我的健康", icon=":material/health_and_safety:"),
            st.Page("ui/pages_elderly/meds.py", title="💊 吃药提醒", icon=":material/medication:"),
        ])
    else:
        # 居民端信息架构：按四字闭环「知·报·议·督」排序（核心任务靠前），
        # 个人/消息居中，低频（健康防护/治理大屏）靠后。
        nav = st.navigation([
            # 核心四件套：知·报·议·督
            st.Page("ui/pages/home.py", title="对话", icon=":material/chat:", default=True),
            st.Page("ui/pages/pulse.py", title="社区脉搏", icon=":material/waves:"),
            st.Page("ui/pages/weather.py", title="天气", icon=":material/cloud:"),
            st.Page("ui/pages/issues.py", title="接诉即办", icon=":material/build:"),
            st.Page("ui/pages/voice.py", title="邻里议事", icon=":material/forum:"),
            st.Page("ui/pages/transparency.py", title="社区治理看板", icon=":material/bar_chart:"),
            st.Page("ui/pages/policy.py", title="政策问答", icon=":material/quiz:"),
            # 个人与消息
            st.Page("ui/pages/mine.py", title="我的", icon=":material/person:"),
            st.Page("ui/pages/notifications.py", title="消息", icon=":material/notifications:"),
            # 低频功能
            st.Page("ui/pages/health.py", title="健康防护", icon=":material/health_and_safety:"),
            st.Page("ui/pages/bigscreen.py", title="治理大屏", icon=":material/tv:"),
        ])

    # 侧边栏（老人端全屏没侧边栏，页面里大字导航 + 紧急联系）
    if role != "elderly":
        with st.sidebar:
            from ui.sidebar import render_sidebar
            render_sidebar(profile, role)

    nav.run()


if __name__ == "__main__":
    main()
