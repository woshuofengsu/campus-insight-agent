# ui/demo_tour.py
"""🎬 竞赛演示导览 — 5幕故事线，自动引导评委体验全流程."""
import streamlit as st
from ui.components import TOKEN

# ── Tour configuration ──
TOUR_STEPS = [
    {
        "id": "welcome",
        "title": "🎬 第1幕：欢迎来到校园先知",
        "body": """
**你想扮演的角色的？**

校园先知是一个围绕 **知·报·议·督** 四字闭环设计的校园微治理 AI 平台。

- 🎓 **学生端**：感知校园动态 → 随手报修 → 提案讨论 → 数据监督
- 👨‍🏫 **教师端**：治理工作台 → 工单管理 → 提案回复 → 内容发布

接下来，我们将依次体验两端核心功能。
        """,
        "target_page": None,
        "auto_advance": False,
    },
    {
        "id": "student_pulse",
        "title": "🌊 第2幕：校园脉搏 — 感知校园动态",
        "body": """
**看看校园最近发生了什么。**

切换到「🌊 校园脉搏」页面，你可以看到：
- 🌤️ 实时天气
- 📅 校园事件日历
- 🔥 本周问题热点排行榜
- 📚 校园百科（通知、电话等）

💡 **在对话页输入「校园脉搏」**，AI 会为你播报以上所有信息。
        """,
        "target_page": "ui/pages/pulse.py",
        "auto_advance": False,
    },
    {
        "id": "student_report",
        "title": "🔧 第3幕：随手报修 — OODA 闭环核心",
        "body": """
**发现问题 → 自动上报 → 追踪进度。**

试试在对话框中输入：**「一食堂二楼空调不制冷」**

Agent 会自动：
1. 分类 → 设施维修
2. 评估 → 普通紧急度
3. 生成工单号
4. 提示追踪方式

💡 这就是 OODA 的 **报** 环节。
        """,
        "target_page": "ui/pages/home.py",
        "auto_advance": False,
        "suggested_input": "一食堂二楼空调不制冷",
    },
    {
        "id": "transparency",
        "title": "📊 第4幕：治理透明窗 — 数据的力量",
        "body": """
**切换到「📊 治理透明窗」页面。**

这里展示：
- 🏥 校园治理健康度评分
- 📈 7天问题趋势图
- 🔄 工单流转管道
- 📢 学生舆情分析
- ⚠️ 积压预警

每一项数据都来自真实上报——**知** 与 **督** 形成闭环。
        """,
        "target_page": "ui/pages/transparency.py",
        "auto_advance": False,
    },
    {
        "id": "bigscreen",
        "title": "📺 第5幕：治理指挥中心（大屏模式）",
        "body": """
**最后的 WOW 时刻！**

打开「📺 治理大屏」页面，你将看到：
- 🌑 暗色指挥中心主题
- 🔢 实时数字跳动计数器
- 🗺️ 校园问题热力分布图
- 📟 底部事件滚动播报
- 💫 KPI 卡片发光动画

💡 **加上 `?demo=1` 参数**可启用演示模式（全屏 + 模拟数据）。
        """,
        "target_page": "ui/pages/bigscreen.py",
        "auto_advance": False,
        "show_demo_hint": True,
    },
    {
        "id": "teacher",
        "title": "👨‍🏫 第6幕：教师工作台 — 管理视角",
        "body": """
**切换到教师端，看看治理的后台。**

教师端包含 4 个页面：
- 📊 **工作台**：KPI + 紧急工单一览 + 一键处理
- 📋 **工单管理**：批量操作 + 筛选 + 搜索
- 💡 **提案管理**：回复 + 采纳 + 实施
- 📢 **内容发布**：发布通知 + 创建议题

💡 **点击左下角「🔄 重新设置身份」**，选择「👨‍🏫 我是教职工」即可切换。
        """,
        "target_page": None,
        "auto_advance": False,
    },
    {
        "id": "done",
        "title": "🎉 演示完成！",
        "body": """
**校园先知 · CampusInsight Agent**

基于知·报·议·督工作流的校园微治理 AI 平台：

| 环节 | 功能 | 技术 |
|------|------|------|
| 🧠 **认知引擎** | OODA 治理工作流 + 14个工具 | LangChain + DeepSeek |
| 📊 **治理透明** | 多维健康度 + 趋势分析 | Altair + SQLite |
| 🎨 **交互设计** | 双端分离 + 响应式 | Streamlit + CSS |

**离线演示模式**：设置 `OFFLINE_MODE=true` 或 `?offline=1` 即可在无 API 环境下完整演示。

感谢观看！ 🏛️
        """,
        "target_page": None,
        "auto_advance": False,
    },
]


def render_tour_guide():
    """Render the demo tour UI — sidebar toggle + floating instruction panel."""

    # ── Sidebar: start/reset button ──
    tour_step = st.session_state.get("_tour_step", 0)

    if tour_step == 0:
        if st.sidebar.button("🎬 开始演示导览", type="primary", width="stretch",
                             help="启动竞赛演示导览，5幕自动引导"):
            st.session_state._tour_step = 1
            st.rerun()
    else:
        # Tour is active
        step_data = TOUR_STEPS[tour_step - 1]

        # ── Floating instruction panel ──
        with st.sidebar:
            st.markdown("---")
            st.markdown(
                f'<div style="background:{TOKEN["primary_bg"]};border:2px solid {TOKEN["primary_border"]};'
                f'border-radius:12px;padding:12px;margin:8px 0;">'
                f'<div style="font-size:0.7em;font-weight:700;color:{TOKEN["primary"]};'
                f'margin-bottom:4px;">🎬 演示导览 · 第{tour_step}/{len(TOUR_STEPS)}步</div>'
                f'<div style="font-size:0.8em;font-weight:600;color:{TOKEN["text"]};">'
                f'{step_data["title"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            if st.button("⏹️ 结束导览", width="stretch", key="_tour_stop"):
                st.session_state._tour_step = 0
                st.rerun()

        # ── Main area: instruction card ──
        _render_step_card(step_data, tour_step)

        # ── Suggested input ──
        if step_data.get("suggested_input"):
            st.info(f"💡 **试试输入：** `{step_data['suggested_input']}`")
            # Quick copy button
            if st.button("📋 一键填入", key="_tour_copy_input"):
                st.session_state._tour_copied = step_data["suggested_input"]
                st.rerun()

        # ── Demo hint ──
        if step_data.get("show_demo_hint"):
            st.info("💡 提示：在地址栏加 `?demo=1` 可启用全屏演示模式，加 `?offline=1` 离线运行。")

        # ── Navigation ──
        c_prev, c_next = st.columns(2)
        with c_prev:
            if tour_step > 1:
                if st.button("← 上一步", width="stretch", key="_tour_prev"):
                    st.session_state._tour_step -= 1
                    st.rerun()
        with c_next:
            if tour_step < len(TOUR_STEPS):
                if st.button("下一步 →", type="primary", width="stretch", key="_tour_next"):
                    st.session_state._tour_step += 1
                    st.rerun()

        # ── Page shortcuts ──
        target = step_data.get("target_page")
        if target:
            st.markdown("---")
            if st.button(f"📌 直接跳转到「{step_data['title'][:20]}...」页面", width="stretch"):
                st.switch_page(target)


def _render_step_card(step: dict, step_num: int):
    """Render the step instruction card in the main area."""
    progress = f"{'█' * step_num}{'░' * (len(TOUR_STEPS) - step_num)}"
    st.markdown(f"""
<div style="background:linear-gradient(135deg,{TOKEN["primary_bg"]} 0%,#f5f3ff 100%);
    border:2px solid {TOKEN["primary_border"]};
    border-radius:16px;padding:24px 28px;margin-bottom:16px;
    box-shadow:0 4px 16px rgba(79,70,229,0.1);">
    <div style="font-size:0.7em;color:{TOKEN["primary"]};font-weight:700;letter-spacing:0.1em;
        margin-bottom:4px;">{progress}</div>
    <div style="font-size:1.1em;font-weight:800;color:{TOKEN["text"]};margin-bottom:12px;">
        {step["title"]}
    </div>
    <div style="font-size:0.88em;color:{TOKEN["text_sec"]};line-height:1.7;">
        {step["body"]}
    </div>
</div>
""", unsafe_allow_html=True)
