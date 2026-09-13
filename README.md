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

**规则为骨、LLM 为脑、关键节点人确认**——不追求"全自主"，而是让每一步都可解释、可复算、可追责。

- **多智能体真协作**：9 个声明式角色（接待员/报修调度/提案协商/政策专员/健康顾问/天气守护/通知管理/网格助手/合规审计）通过**黑板消息队列**收发消息，能完成跨角色多轮真协商（如「高温预警 → 健康顾问评估 → 通知管理员拟稿」，全程留痕可查，非伪多智能体）
- **双层防线**：每轮输出先过 `Verifier`（幻觉 / 敏感词 / 手机号 / 医疗诊断句式拦截），再过 `Arbiter`（合规优先 → 安全 → 专业 → 转人工），仲裁决策落库可查
- **政策回答不编造**：只基于检索片段生成并校验引用下标；无材料时转人工而不是硬答
- **知识可检索**：59 条知识条目（含 40 条公开政策摘要）+ 词法/语义向量混合检索（RRF），42 条口语金标实测 **hit@1 100%**（纯词法基线 85.7%）
- **数据安全**：手机号 **AES-256-GCM 加密落库**，全库 8 张含手机号表**明文计数为 0**（`scripts/audit_phone_encryption.py` 可现场复核）
- **降本**：LLM 默认按需调用（特性开关控制），20 次真实调用实测 **¥0.0053**，记账可查

### 👥 三端系统（Vue3 三端，页面数以路由表为准）

- **居民端（14 页）**：首页、报修（含详情/新建）、邻里议事（含详情/新建）、通知、政策问答、健康防护、天气、消息中心、我的、隐私政策
- **网格员端（9 页）**：工作台（真实统计 + 红黑榜 + 满意度下钻）、工单管理、提案管理、通知管理、政策问答、天气管理、健康管理、老年关怀、消息中心
- **老年关怀端（8 页）**：大字首页（SOS 长按 + 大按钮 + 用药角标）、语音小助手、语音报修、用药提醒、听通知、紧急联系人、我的报修、政策问答
- **治理大屏（独立）**：8 张卡实时指标 + 数字差值滚动，需网格员身份访问

## 🌐 在线访问

**主入口（FastAPI + Vue3）：** 自部署后用浏览器访问 `http://<服务器IP>:8000/login`（见下「快速启动」）。

**想让评委/同学用自己手机打开（0 成本）：**

```bash
python scripts/serve_public.py     # 起服务 + 公网 HTTPS 隧道 + 刷新扫码页 + 地址进剪贴板
python scripts/probe_public.py     # 公网入口端到端探测（8 项：健康/登录页/PWA/三角色/智能体对话）
python scripts/serve_public.py --stop   # 演示结束立刻关掉公网入口
```

方案说明、电脑常开设置、5 个已知坑与安全口径：`docs/演示常开-本机方案.md`
（临时域名每次重启会变；**隧道无访问控制，拿到链接即可进入，演示完请 `--stop`**）。

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
- **`.env.demo`**（演示姿态，`DEMO_MODE=true`，LLM 开关 `LLM_ORCHESTRATION/POLICY_LLM_RAG/RECEPTION_LLM_FALLBACK=1`）：一键演示账号 + 规则/LLM 混合。**模板见 `.env.demo.example`（`cp .env.demo.example .env.demo` 后再填真实 `DEEPSEEK_API_KEY`，再 `cp .env.demo .env`）；否则 LLM 开关虽为 1 但无 key 仍会回落规则链路。** 注意：`.env.demo` 已进 `.gitignore`（避免演示密钥入库），提交模板用 `.env.demo.example`。
- **`.env`**（生产姿态，`DEMO_MODE=false`，LLM 开关全为 0，强 JWT 密钥 + CORS 白名单）：关闭演示登录与 API 文档，走正式鉴权。
- 演示前准备与两套姿态的切换步骤见 [`docs/review/演示保障清单.md`](docs/review/演示保障清单.md)（第二节"演示前 10 分钟"）。

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
| 模型 | DeepSeek（deepseek-chat），默认规则优先（降本），20 次调用实测 ¥0.0053 |
| 数据库 | SQLite（**schema v46**，WAL），版本化迁移（`_mN_` 注册表），可演进 PostgreSQL |
| 知识检索 | 词法（同义/方言扩展）+ 语义向量（text-embedding-v3, 1024 维）混合检索 + RRF 融合 |
| 质量门禁 | 582 项测试 / ruff 0 / 26 页 UI 客观审计 / 9 项演示前自检 / 检索评测（CI 门禁）|
| 移动端 | 响应式/安全区/老年大字/语音（PWA 可选）|

## 📁 项目结构

```
campus-insight-agent/
├── api_web.py              # FastAPI 主服务（JWT 中间件+安全头+WebSocket+SPA）
├── api_routes/             # 14 个业务路由模块（auth/agent/issues/proposals/…）+ 共享依赖
├── agent/                  # 多智能体（9 角色 + 黑板 + 编排 + 校验/仲裁）
├── data/                   # 数据库层（db_core.py 含 schema v46 + 迁移注册）
├── web/                    # Vue3 前端（src/views/{resident,grid,elderly}/）
├── scripts/                # 迁移 / 压测 / 演示 / 录屏 / UI 审计 / 数字一致性
├── tests/                  # pytest（用例数以 `python scripts/check_claims.py` 为准）
├── docs/                   # 部署 / 移动端 / 比赛材料 / 开发日志
├── api.py                  # 扣子插件入口（:18800，独立）
└── app.py                  # Streamlit 备线（旧版，非主路线）
```

## ✅ 质量与可验证（全部可现场复算）

| 验证项 | 命令 | 实测 |
|---|---|---|
| 功能与回归 | `python -m pytest tests/ -q` | **581 passed / 1 skipped**（可运行 582） |
| **端到端验收（真实服务）** | `python scripts/demo_acceptance.py` | **11/11 通过**（三角色登录、AI 对话、政策命中、老年天气、工作台指标、图谱反查、留痕） |
| 演示前一键自检 | `python scripts/demo_preflight.py` | **9/9 通过**（schema、手机号加密覆盖、演示账号、服务身份…） |
| UI 无障碍/一致性 | `python scripts/ui_audit.py` | **26 页/视口 × 9 类检查 0 违规**（含暗色与 1366×768 投影档） |
| 检索命中率 | `python scripts/rag_eval.py` | 混合 **hit@1 42/42 = 100%**（纯词法 85.7%） |
| 数据安全 | `python scripts/audit_phone_encryption.py` | 8 张含手机号表**明文计数 0** |
| LLM 质量与成本 | `python scripts/llm_eval.py --provider llm` | 20/20 满分，**¥0.0053 / 20 次** |
| 数字一致性 | `python scripts/check_claims.py` | 材料数字与代码实时一致 |

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

- [最终版交付说明](docs/competition/最终版交付说明.md)（**先读这份**：怎么跑、怎么验、怎么讲）
- [创意说明书（提交版）](docs/competition/创意说明书-提交版.md)
- [技术实现报告](docs/competition/技术实现报告.md)
- [演示脚本](docs/competition/演示脚本.md) · [录屏分镜与备用素材](docs/competition/答辩录屏分镜.md)

## 📄 许可证

MIT License
