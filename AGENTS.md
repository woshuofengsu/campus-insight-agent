# AGENTS.md — 项目理解与协作约定

> 本文件供 AI 编码智能体（opencode / Claude Code / Cursor 等）在接手本项目时快速理解架构与约定。改动项目前请先读这里。

## 项目定位

「社区先知 CommunityInsight」——基层治理·网格化多智能体系统，接诉即办平台。三端分离：居民端 `/resident`、网格员端 `/grid`、老年端 `/elderly`。

**核心价值主张**（答辩/评审最在意）：多智能体有**真实消息队列协作**（非伪多智能体）+ 双层防线（Verifier 校验 + Arbiter 仲裁留痕）+ **可验证**（评测集、成本记账、457 项测试）。

## 架构总览

```
前端 Vue3+Vite+NaiveUI (web/)  ──►  FastAPI 主服务 api_web.py (:8000)
                                    └─ 同时托管 Vue3 构建产物 (web/dist/)
                                    └─ JWT 鉴权 + WebSocket 实时通知 + 安全响应头
api.py (:18800)  = 扣子插件入口（独立，非主服务）
app.py  = Streamlit 备线（旧版演示，非主路线）
```

- **主服务**：`uvicorn api_web:app --port 8000`（FastAPI）
- **数据库**：SQLite（`data/community_insight.db`），schema **v41**（WAL 模式），可演进 PostgreSQL（见 `docs/scaling.md`）

## 多智能体核心（9 个声明式角色）

定义在 `agent/roles/__init__.py` 的 `AGENT_CLASSES`：

接待员(receptionist) / 报修调度(repair_dispatch) / 提案协商(proposal_collab) / 健康顾问(health_advisor) / 政策专员(policy_expert) / 通知管理员(notification_manager) / 天气守护(weather_guardian) / 网格助手(grid_assistant) / 合规审计(compliance_auditor)

协作机制（真协商，见 `agent/orchestrator.py`）：
- **黑板**（`agent/blackboard.py`）：共享上下文 + 消息队列 + 锁 + 历史（`post_message`/`get_messages`）
- **事件协商**：`process_negotiation(event)` 处理跨角色事件（天气⇄健康、报修→通知、`llm_collaboration` 通用）
- **双层防线**（每轮必过）：`agent/verifier.py`（幻觉/敏感词/手机号/诊断拦截）→ `agent/arbiter.py`（合规优先→安全→专业→转人工，决策落 `agent_logs`，`professional_domain` 字段为专业仲裁触发键）

## 常用命令

```bash
# 后端测试（457 项，全绿基线）
python -m pytest tests/ -q

# 启动主服务（最终代码；DEMO_MODE=true 可用演示账号登录）
python -m uvicorn api_web:app --host 0.0.0.0 --port 8000
# 浏览器访问 http://127.0.0.1:8000/login

# 前端构建
cd web && npm run build   # 产物 web/dist/

# 演示账号（DEMO_MODE=true）
resident: demo_resident（无密码）
grid:     demo_grid / demo123
elderly:  demo_elderly（免登录）
```

## 数据库迁移约定

- schema 版本在 `data/db_core.py`，迁移函数命名 `_m{N}_{name}`，注册进 `post` 列表（`(version, name, fn)`），幂等（`_add_column` 用 PRAGMA 检查）
- **当前版本 v41**。加列/索引/新表都走这个机制，**不要**直接 ALTER 业务代码
- 迁移脚本放 `scripts/`（照 `migrate_phone_encryption_v39.py` 模式：含 `_ensure_db()`、可回滚 `--rollback`、幂等）

## 数据安全约定（重要，评委查库会看）

- **手机号加密落库**：`data/db_repair.py` 提供 `_enc_phone()` / `_dec_phone(enc, plain)` / `_mask_phone()`（复用 `utils/crypto.get_crypto()` 单例）。**任何新表的手机号字段**必须：明文列写空 + 加密列写密文 + 读取解密。
- 已加密表：`community_issues`、`user_profile`、`emergency_contacts`、`health_consults`、`emergency_calls`。
- 留痕（`activity_log.detail`）不得含完整手机号（用 `_mask_phone`）。
- 密钥：`.env` 的 `WEB_JWT_SECRET`/`CRYPTO_KEY` 生产必配；`.env`/`*.db`/`*.db.bak`/`.coverage` 已 gitignore。

## 约束与陷阱

- **不要破坏 457 项测试**：每次改完跑 `python -m pytest tests/ -q`，必须全绿才提交。
- 测试用临时库隔离（`test_issue_phone_encryption.py` 的 `_fresh_db` fixture 模式），避免污染全局 `config.DB_PATH`。
- `stress_test.py`/`smoke_test.py` 是独立脚本（读取 `sys.argv`），**pytest 不要收集根目录脚本**（跑测试用 `tests/`）。
- `config.DEFAULT_TENANT` 为多租户默认值（演示级，仅预留字段不改查询）；`AGENT_CLASSES` 角色 id 不得随意改（有状态）。
- LLM 默认**规则优先降本**：`LLM_NEGOTIATION`/`LLM_ORCHESTRATION` 默认关，`=1` 才走真实 DeepSeek（用于答辩演示）。
- CSP `script-src 'self'` 会拦截 `?debug=1` 的 Eruda CDN（上生产需知悉）；WebSocket `/ws/notify` 用内存连接池（单机够用，多进程需 Redis）。

## 关键文件索引

| 文件 | 作用 |
|---|---|
| `api_web.py` | FastAPI 主服务：App 装配 + JWT 中间件 + 安全头 + WebSocket + SPA 托管 |
| `api_routes/` | 16 个业务路由模块（auth/agent/issues/proposals/notices/health/...）|
| `agent/orchestrator.py` | 多 Agent 编排（黑板、协商、Verifier/Arbiter 接入、转人工）|
| `agent/roles/business_agents.py` | 5 个业务角色（报修/提案/政策/健康/通知）|
| `agent/roles/auto_agents.py` | 天气守护 + 网格助手 |
| `data/db_core.py` | schema + 迁移注册（v41）|
| `web/src/views/{resident,grid,elderly}/` | 三端页面 |
| `docs/mobile-deploy.md` | 移动端部署 + 发布检查清单 |
| `docs/spec/dev-log.md` | 开发日志（最新 二十五 节为本次升级）|

## 本轮已完成的大改动（2026-08）

数据安全收口（手机号全加密）/ LLM 自主协商（`llm_negotiator.py`，默认关）/ 安全响应头 / 索引优化（v40）/ 自转率统计 / 红黑榜下钻 / NLU 方言扩充 / 多租户预留（v41）/ 舆情源框架 / WebSocket 实时通知 / 分级路由降本（`route_grade`）。详见 `docs/spec/dev-log.md` 二十五节。
