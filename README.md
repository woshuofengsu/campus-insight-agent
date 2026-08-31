# 🏘️ 社区先知 CommunityInsight Agent

> "京彩AI·智汇全球"首都大学生智能体OPC创新大赛 · 基层治理赛道

让每个居民都能 **知社区事、报社区修、议社区政、督社区治** 的接诉即办治理平台。

## 核心功能

### 四字闭环：知·报·议·督

| 环节 | 板块 | 能力 |
|------|------|------|
| 🌊 **知** | 社区脉搏 | 天气 + 社区事件 + 百科 + 治理热点分布 |
| 🔧 **报** | 接诉即办 | 自然语言上报 → 自动分类定级 → 生成工单 |
| 🗳️ **议** | 邻里议事 | 创建提案 + 附议 + 议题讨论 + 民意收集 |
| 📊 **督** | 社区治理看板 | 三维加权健康度 + 趋势图 + 类别明细 + 个人足迹 |

### 🧠 技术思路

用了一个类 OODA 循环（观察→定位→决策→反思→关联）的 Agent 架构，让 Agent 不只是被动回答问题，而是主动感知社区动态、自动判断用户意图、反思之前的处理结果。

- **感知**：定时扫天气、工单热点、未解决问题
- **角色切换**：根据用户说的话自动切到合适的身份（接诉/议事/数据分析/社区观察）
- **反思**：查数据库做关联分析，发现异常模式
- **兜底**：LLM 不靠谱时自动补调用，避免编造假数据

### 👥 三角色系统

- **居民端**（9 页）：对话助手、社区脉搏、接诉即办、邻里议事、社区治理看板、健康防护、消息、我的、治理大屏
- **网格员端**（6 页）：工作台、工单管理、提案管理、内容发布、数据洞察、健康管理
- **老年关怀版**（6 页）：大字极简首页、一句话上报、一键呼叫（子女/网格员/急救）、SOS 紧急求助、每日平安打卡、吃药提醒、健康档案

## 🌐 在线访问

**主入口（FastAPI + Vue3）：** 自部署后用浏览器访问 `http://<服务器IP>:8000/login`（见下「快速启动」）。

> 备用演示（旧链路，Streamlit `app.py`，:8501）不再作为主入口，仅存档参考。

> ⚠️ **数据说明**：线上为演示环境，SQLite 数据库可在部署时挂载持久卷；`DEMO_MODE=true` 且 `DEMO_AUTO_WORKER=true` 时工单由闭环机器人推进，**仅用于演示流程，不代表真实治理成效**，生产务必关闭。

## 前置依赖

```bash
# 后端
pip install -r requirements.txt
# 前端（Vue3，构建产物 web/dist/）
cd web && npm ci && npm run build && cd ..
# 配置密钥（.env，不进 git）
cp .env.example .env
# .env 必配：DEEPSEEK_API_KEY（LLM）；生产必配：WEB_JWT_SECRET / CRYPTO_KEY / CORS_ORIGINS
```

两套配置：
- **`.env.demo`**（演示姿态，`DEMO_MODE=true`，LLM 开关 `LLM_ORCHESTRATION/POLICY_LLM_RAG/RECEPTION_LLM_FALLBACK=1`）：一键演示账号 + 规则/LLM 混合。
- **`.env`**（生产姿态，`DEMO_MODE=false`，LLM 开关全为 0，强 JWT 密钥 + CORS 白名单）：关闭演示登录与 API 文档，走正式鉴权。

## 快速启动（主路线：FastAPI + Vue3）

```bash
# 启动主服务（Vue3 前端 + API，DEMO_MODE=true 可用演示账号）
python -m uvicorn api_web:app --host 0.0.0.0 --port 8000
# 浏览器访问 http://127.0.0.1:8000/login

# 演示账号（DEMO_MODE=true）
resident: demo_resident（无密码）
grid:     demo_grid / demo123
elderly:  demo_elderly（免登录）
```

> Streamlit 备线（`app.py`，:8501）为旧版演示，**非主路线**，仅作参考。

## 🛠️ 技术栈

| 层 | 用了啥 |
|----|------|
| 前端 | Vue3 + Vite + Naive UI，三端（居民/网格/老年）|
| 后端 | FastAPI（`api_web.py`，:8000），JWT 鉴权 + WebSocket + 安全响应头 |
| 多智能体 | 9 个声明式 Agent + 黑板消息队列 + 仲裁器/校验器（`agent/`）|
| 模型 | DeepSeek（deepseek-chat），默认规则优先（降本）|
| 数据库 | SQLite（schema v41，WAL），可演进 PostgreSQL |
| 移动端 | 响应式/安全区/老年大字/语音（PWA 可选）|

## 📁 项目结构

```
campus-insight-agent/
├── api_web.py              # FastAPI 主服务（JWT 中间件+安全头+WebSocket+SPA）
├── api_routes/             # 16 个业务路由模块（auth/agent/issues/proposals/...）
├── agent/                  # 多智能体（9 角色 + 黑板 + 编排 + 校验/仲裁）
├── data/                   # 数据库层（db_core.py 含 schema v41 + 迁移注册）
├── web/                    # Vue3 前端（src/views/{resident,grid,elderly}/）
├── scripts/                # 迁移 / 压测 / 演示 / 数字一致性脚本
├── tests/                  # pytest（用例数以 `python scripts/check_claims.py` 为准）
├── docs/                   # 部署 / 移动端 / 开发日志
├── api.py                  # 扣子插件入口（:18800，独立）
└── app.py                  # Streamlit 备线（旧版，非主路线）
```

## 🧪 测试

```bash
# 后端全量（改后必跑，全绿才提交；用例数见面板）
python -m pytest tests/ -q

# 数字一致性自检（打印材料应填的事实数字）
python scripts/check_claims.py

# 业务混合压测（p50/p95/p99，需先起主服务）
python scripts/benchmark_business.py

# 移动端/多智能体演示（录屏用）
python scripts/demo_collaboration.py
```

## 📊 比赛材料

- [创意说明书](docs/competition/创意说明书.md)
- [技术实现报告](docs/competition/技术实现报告.md)
- [演示脚本](docs/competition/演示脚本.md)

## 📄 许可证

MIT License
