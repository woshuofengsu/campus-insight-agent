# 🏛️ 校园先知 CampusInsight Agent

> "京彩AI·智汇全球"首都大学生智能体OPC创新大赛 · 基层治理赛道

让每个学生都能 **知校园事、报校园修、议校园政、督校园治** 的校园微治理平台。

## ✨ 核心功能

### 四字闭环：知·报·议·督

| 环节 | 板块 | 能力 |
|------|------|------|
| 🌊 **知** | 校园脉搏 | 天气 + 校园事件 + 百科 + 治理热点分布 |
| 🔧 **报** | 随手报修 | 自然语言上报 → 自动分类定级 → 生成工单 |
| 🗳️ **议** | 有话说 | 创建提案 + 附议 + 议题讨论 + 民意收集 |
| 📊 **督** | 治理透明窗 | 三维加权健康度 + 趋势图 + 类别明细 + 个人足迹 |

### 🧠 技术思路

用了一个类 OODA 循环（观察→定位→决策→反思→关联）的 Agent 架构，让 Agent 不只是被动回答问题，而是主动感知校园动态、自动判断用户意图、反思之前的处理结果。

- **感知**：定时扫天气、工单热点、未解决问题
- **角色切换**：根据用户说的话自动切到合适的身份（报修/议事/数据分析/校园观察）
- **反思**：查数据库做关联分析，发现异常模式
- **兜底**：LLM 不靠谱时自动补调用，避免编造假数据

### 👥 双角色系统

- **学生端**（9 页）：对话、校园脉搏、随手报修、有话说、治理透明窗、健康防护、消息、我的、治理大屏
- **教师端**（6 页）：工作台、工单管理、提案管理、内容发布、数据洞察、健康管理

## 🚀 快速启动

**推荐方式：双击 [`start.bat`](start.bat)**（自动杀旧进程、检查依赖、打开浏览器）

```bash
# 或手动：
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env 填入：
#   DEEPSEEK_API_KEY=sk-xxx  （必填）
#   HEFENG_API_KEY=xxx        （可选，天气 API）

# 3. 启动应用（首次自动初始化数据库 + 种子数据）
streamlit run app.py
# 或双击 start.bat
```

**大屏演示模式**（无需数据库）：
```
streamlit run app.py
# 然后访问: http://localhost:8501/?demo=1&page=bigscreen
```

## 🛠️ 技术栈

Streamlit + LangChain + DeepSeek + SQLite + Altair，跑在 Streamlit Cloud 上。

| 层 | 用了啥 |
|----|------|
| 界面 | Streamlit 多页面，学生/教师双角色导航 |
| Agent | LangChain Agent + 自定义 OODA 循环 |
| 模型 | DeepSeek (deepseek-chat) |
| 数据库 | SQLite WAL 模式，15 张表 |
| 可视化 | Altair，自适应亮色/暗色模式 |
| 天气 | 和风天气 API，挂了自动用模拟数据 |

## 📁 项目结构

```
campus-insight-agent/
├── app.py              # 入口，路由 + 全局样式
├── agent/              # 治理工作流（OODA 循环、提示词、反射器）
├── tools/              # 16 个工具函数（自动发现）
├── perception/         # 感知模块（天气、热点监控）
├── data/               # 数据库层
├── ui/                 # 前端
│   ├── pages/          #   学生端 9 页
│   └── pages_teacher/  #   教师端 6 页
├── tests/              # 测试
└── docs/               # 比赛文档
```

## 🧪 测试

```bash
# 全量验证（309 项）
python tests/test_verify_all.py

# Ablation 评估（性能基准 + 组件对比）
python tests/test_ablation.py
python tests/test_ablation.py --output ablation_report.md
```

## 📊 比赛材料

- [创意说明书](docs/competition/创意说明书.md)
- [技术实现报告](docs/competition/技术实现报告.md)
- [演示脚本](docs/competition/演示脚本.md)

## 📄 许可证

MIT License
