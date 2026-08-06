# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **学生（Student）**：日常查看校园动态（天气、活动、百科）、上报问题（设施报修、环境问题）、提交提案（校园改进建议）、查看治理透明度
- **教师/职工（Teacher/Staff）**：管理工作台查看全局 KPI、处理工单（分派、标记解决）、回复提案、发布通知和校园内容、查看数据洞察和周报

## Product Purpose

校园先知（CampusInsight）是一个校园基层治理平台。学生自下而上发现问题并上报，Agent（16 个工具 + OODA 治理工作流）自动分类、关联分析，教师自上而下高效处理，系统每周自动生成治理周报。闭环：感知 → 上报 → 分析 → 处理 → 反馈。

## Positioning

**不是 ChatGPT 套壳**。是一个拥有真实 Agent 架构的治理工具：16 个可被 Agent 自主调用的工具、OODA（Observe-Orient-Decide-Act-Reflect）治理工作流、TF-IDF 语义搜索、z-score 异常检测、跨周趋势对比。99% 的学生作品止步于聊天机器人——这是一个完整的工作流闭环。

## Operating Context

- 大学校园日常运营场景
- 比赛演示环境（需要 5 分钟内展示核心价值）
- 评委背景：技术 + 产品，看重创新深度和交互体验
- 模拟数据（非真实生产数据）

## Capabilities and Constraints

**能力：**
- 双角色系统（学生 9 页 + 教师 6 页）
- Agent 16 工具自动发现与调用
- OODA 治理工作流推理可视化
- 语义搜索（字符 n-gram TF-IDF，零依赖）
- z-score 异常检测 + 跨周趋势分析
- 治理周报一键生成
- 和风天气实时集成
- 亮色/暗色双主题
- 治理大屏（动画 KPI + 热力图）

**约束：**
- Streamlit 1.59.2 框架限制（CSS 注入能力有限）
- 8 月 15 日比赛截止
- 无云端部署（仅本地运行）
- DeepSeek API 单模型依赖

**未决定：**
- 是否添加拍照报修（多模态）
- 是否部署到 Streamlit Cloud

## Brand Commitments

- 名称：校园先知 · CampusInsight
- 口号：知报议督（感知 · 上报 · 协商 · 监督）
- 主色调：indigo (#4f46e5) / purple (#7c3aed)
- 体验目标：专业严谨（企业级可靠性）+ 青春活力（校园生活气息），两者同等重要
- 风格参考：Linear 的工具感 + 中国大学校园的美学元素
- 语言：简体中文

## Evidence on Hand

- 完整可运行应用（~65 文件，~16,000 行 Python）
- 16 个 Agent 工具全部注册并运行
- RAG 索引 9 条知识库条目
- 模拟工单、提案、天气数据
- `/docs/superpowers/specs/` 下的设计文档

## Product Principles

1. **治理闭环而非聊天**：每个功能服务于「发现→上报→处理→反馈」闭环，不堆砌技术噱头
2. **技术是手段不是目的**：Agent 推理链可视化，让评委看到技术深度而非黑盒
3. **双角色真正分工**：教师端是管理后台（效率优先），学生端是参与工具（易用优先）
4. **数据驱动决策**：周报、异常检测、趋势分析不是装饰，是可操作的治理洞察
5. **比赛级打磨**：5 分钟演示内呈现完整闭环 + 技术亮点 + 视觉品质

## Accessibility & Inclusion

- 亮色/暗色双主题支持
- 响应式布局（桌面 / 平板 / 手机）
- 中文字体优化（PingFang SC, Microsoft YaHei）
