# AGENTS.md — 项目理解与协作约定

> 本文件供 AI 编码智能体（opencode / Claude Code / Cursor 等）在接手本项目时快速理解架构与约定。改动项目前请先读这里。

## 项目定位

「社区先知 CommunityInsight」——基层治理·网格化多智能体系统，接诉即办平台。三端分离：居民端 `/resident`、网格员端 `/grid`、老年端 `/elderly`。

**核心价值主张**（答辩/评审最在意）：多智能体有**真实消息队列协作**（非伪多智能体）+ 双层防线（Verifier 校验 + Arbiter 仲裁留痕）+ **可验证**（评测集、成本记账、634 项测试 + UI 客观审计 + 演示前自检，全部可现场复算）。

## 架构总览

```
前端 Vue3+Vite+NaiveUI (web/)  ──►  FastAPI 主服务 api_web.py (:8000)
                                    └─ 同时托管 Vue3 构建产物 (web/dist/)
                                    └─ JWT 鉴权 + WebSocket 实时通知 + 安全响应头
api.py (:18800)  = 扣子插件入口（独立，非主服务）
app.py  = Streamlit 备线（旧版演示，非主路线）
```

- **主服务**：`uvicorn api_web:app --port 8000`（FastAPI）
- **数据库**：SQLite（`data/community_insight.db`），schema **v46**（WAL 模式），可演进 PostgreSQL（见 `docs/scaling.md`）

## 多智能体核心（9 个声明式角色）

定义在 `agent/roles/__init__.py` 的 `AGENT_CLASSES`：

接待员(receptionist) / 报修调度(repair_dispatch) / 提案协商(proposal_collab) / 健康顾问(health_advisor) / 政策专员(policy_expert) / 通知管理员(notification_manager) / 天气守护(weather_guardian) / 网格助手(grid_assistant) / 合规审计(compliance_auditor)

协作机制（真协商，见 `agent/orchestrator.py`）：
- **黑板**（`agent/blackboard.py`）：共享上下文 + 消息队列 + 锁 + 历史（`post_message`/`get_messages`）
- **事件协商**：`process_negotiation(event)` 处理跨角色事件（天气⇄健康、报修→通知、`llm_collaboration` 通用）
- **双层防线**（每轮必过）：`agent/verifier.py`（幻觉/敏感词/手机号/诊断拦截）→ `agent/arbiter.py`（合规优先→安全→专业→转人工，决策落 `agent_logs`，`professional_domain` 字段为专业仲裁触发键）

## 常用命令

```bash
# 后端测试（可运行 634 项：633 通过 + 1 需外部服务跳过，全绿基线）
python -m pytest tests/ -q

# 启动主服务（最终代码；DEMO_MODE=true 可用演示账号登录）
python -m uvicorn api_web:app --host 0.0.0.0 --port 8000
# 浏览器访问 http://127.0.0.1:8000/login

# 前端构建
cd web && npm run build   # 产物 web/dist/

# 演示账号（DEMO_MODE=true）
resident: demo_resident（无密码，海淀小区）· demo_resident_cy / demo123（朝阳试点社区，属地化对比用）
grid:     demo_grid / demo123
elderly:  demo_elderly（免登录）
```

## 数据库迁移约定

- schema 版本在 `data/db_core.py`，迁移函数命名 `_m{N}_{name}`，注册进 `post` 列表（`(version, name, fn)`），幂等（`_add_column` 用 PRAGMA 检查）
- **当前版本 v46**。加列/索引/新表都走这个机制，**禁止**在业务代码里运行时 ALTER（v46 已把历史遗留的运行时补列全部收回迁移链）
- 迁移脚本放 `scripts/`（照 `migrate_phone_encryption_v39.py` 模式：含 `_ensure_db()`、可回滚 `--rollback`、幂等）
- **D12（评审建议）**：`data/db_policy.proposal/elderly_care/health_content/weather/notice` 各 800–1240 行，**比赛期不做大重构**；答辩后按 read/write 拆分（纯计算抽 `data/_*_logic.py` + 单测），其结构写入 WS11

## 数据安全约定（重要，评委查库会看）

- **手机号加密落库**：`data/db_repair.py` 提供 `_enc_phone()` / `_dec_phone(enc, plain)` / `_mask_phone()`（复用 `utils/crypto.get_crypto()` 单例）。**任何新表的手机号字段**必须：明文列写空 + 加密列写密文 + 读取解密。
- 已加密表（**v46 起全覆盖**）：`community_issues`、`user_profile`、`emergency_contacts`、`health_consults`、
  `emergency_calls`、`proposals`、`proposal_drafts`、`issue_drafts`。
- **新增含手机号的表后必跑** `python scripts/audit_phone_encryption.py`：要求「有 `*_enc` 兄弟列 + 明文计数 0」，
  并加进 `_mN_` 迁移做存量回填（只在加密成功时清空明文）。`demo_preflight` 第 8 项会现场核对。
- 留痕（`activity_log.detail`）不得含完整手机号（用 `_mask_phone`）。
- 密钥：`.env` 的 `WEB_JWT_SECRET`/`CRYPTO_KEY` 生产必配；`.env`/`*.db`/`*.db.bak`/`.coverage` 已 gitignore。

## 约束与陷阱

- **不要破坏这 634 项测试**（633 通过 + 1 需外部服务跳过）：每次改完跑 `python -m pytest tests/ -q`，必须全绿才提交；另跑 `python scripts/demo_preflight.py --fast`（9 项自检）与 `python scripts/ui_audit.py`（全站 34 个路由页 / 54 个页面视口 UI 客观审计）。
- 测试用临时库隔离（`test_issue_phone_encryption.py` 的 `_fresh_db` fixture 模式），避免污染全局 `config.DB_PATH`。
- `stress_test.py`/`smoke_test.py` 是独立脚本（读取 `sys.argv`），**pytest 不要收集根目录脚本**（跑测试用 `tests/`）。
- `config.DEFAULT_TENANT` 为多租户默认值（演示级，仅预留字段不改查询）；`AGENT_CLASSES` 角色 id 不得随意改（有状态）。
- LLM 默认**规则优先降本**：代码默认 `LLM_NEGOTIATION`/`LLM_ORCHESTRATION`/`POLICY_LLM_RAG`/`RECEPTION_LLM_FALLBACK` 全关；
  **使用姿态**（`.env` / `.env.demo`）可全开——本机 `.env` 已全开，实测每轮对话约 **+0.9 秒 / +¥0.0002**。
  改 `.env` 后**必须重启服务**才生效（否则你测的是旧姿态）。
- **测试必须姿态无关**：依赖 LLM/演示开关的测试要显式 `monkeypatch.setenv/delenv` 钉住姿态，
  否则本机一开开关就会**真打网络**并造成假失败（本轮实测踩到 2 条）。
- **记账不许静默丢账**：`agent/llm_client._record` 失败会懒初始化重试并 warning（有子进程回归测试守着）；
  新增 LLM 调用点后确认 `llm_usage` 真有记录。
- 密钥姿态：`CRYPTO_KEY`/`WEB_JWT_SECRET` 在 **`DEMO_MODE=false` 且缺失或是仓库占位值时拒绝启动**（fail-closed）；
  演示姿态允许但会告警；`demo_preflight` 姿态行会显示"加密密钥=自定义/默认"。
- **改完 `web/src` 必须先 `cd web && npm run build` 再审计/演示**（复审 F4）：`web/dist` 不进 git，
  改完不 build 的话 `ui_audit`/`mobile_audit`/演示测的都是**旧包**，会得出"修了但没生效/没修也报绿"的假结论。
  两个审计脚本已内置 dist 新鲜度闸：落后于源码直接红字退出。
- 语义文字色**一律用亮/暗成对令牌**（`--ink-*`、`--st-*-ink`、`--primary-ink`、`--danger-solid`/`--success-ink`），
  **不要在内联样式里写死 hex**：写死色在暗色下不跟着换，`ui_audit` 会抓（第九轮抓到 6 处这类问题）。
- **禁止静默吞异常**（本轮新增门禁）：`except` 块里必须 `_log.warning(...)` 或抛出；
  尤其**绝不能"吞掉异常后返回成功"**（`tests/test_silent_exceptions.py` 会红）。
  分诊工具：`python scripts/audit_silent_exceptions.py`（HIGH/MID 基线只减不增）；
  安全/隐私类校验（敏感词、脱敏、权限）一律 **fail-closed**——组件坏了要拒绝，不许放行。
- **属地化（地区识别）统一口径**：所有"按地区"的能力都必须走 `utils/region.py`（`resolve_region` /
  `policy_region_boost` / `normalize_area`），**不要各写一份**。三条硬规则：
  ① **属地只影响"选谁"，绝不影响"能不能自动回答"**（政策阈值永远只看 `base_score`；选答规则 =
     「达标候选中优先**属地适用**者，一个都没有才回落到达标的跨区条目」——早期"只看 top1"会把本来能答的变成转人工，
     而"只看 final 排序第一条"又会让**朝阳居民被海淀区文件回答**（跨区只扣 0.5，压不过主题分差距，live 实测 final
     12.14 vs 10.16）；跨区兜底时正文必须标注「该依据的适用地区是…」，见 `format_knowledge_answer`）；
  ② `applicable_area` 写「全国 / 北京市 / 北京市海淀区 / 社区名」；社区名必须与 `user_profile.community`
     真值一致并登记进 `config.REGION_BY_COMMUNITY`（未命中会 warning + 回落全局默认，不许静默失效）；
  ③ 天气缓存键统一用 **adcode**，且 `get_daily_advice` 的每日缓存 action 必须带 key（否则跨社区串味）。
  三端（居民 / 老年 / Agent 文本链路）**必须同批接入**，别只改居民端（同场演示口径会不一致）。
- CSP `script-src 'self'` **禁止内联脚本**：调试入口已改为同源外部文件 `web/public/debug.js`（`?debug=1` 生效），
  不要再往 `index.html` 里写内联 `<script>`（会在每个页面报 CSP 错、评委开 DevTools 就能看到）。
  WebSocket `/ws/notify` 用内存连接池（单机够用，多进程需 Redis）。

## 关键文件索引

| 文件 | 作用 |
|---|---|
| `api_web.py` | FastAPI 主服务：App 装配 + JWT 中间件 + 安全头 + WebSocket + SPA 托管 |
| `api_routes/` | 14 个业务路由模块 + 共享依赖（auth/agent/issues/proposals/notices/health/...）|
| `agent/orchestrator.py` | 多 Agent 编排（黑板、协商、Verifier/Arbiter 接入、转人工）|
| `agent/roles/business_agents.py` | 5 个业务角色（报修/提案/政策/健康/通知）|
| `agent/roles/auto_agents.py` | 天气守护 + 网格助手 |
| `data/db_core.py` | schema + 迁移注册（**v46**）|
| `web/src/views/{resident,grid,elderly}/` | 三端页面 |
| `docs/mobile-deploy.md` | 移动端部署 + 发布检查清单 |
| `scripts/serve_public.py` | **本机常开一键工具**：起服务（默认只绑 127.0.0.1）+ 公网 HTTPS 隧道 + 抓新域名 + 刷新扫码页（`--status` / `--stop` / `--lan` / `--autostart`）|
| `scripts/probe_public.py` | **公网入口端到端探测**（健康/登录页/PWA/三角色/智能体对话，8 项；含 DNS 绕行）|
| `scripts/net_probe.py` | DNS 兜底：UDP/53 问公共 DNS + 本进程改写解析 + IP/SNI 直连校验（校园 DNS 会对新隧道域名返回 NXDOMAIN）|
| `docs/演示常开-本机方案.md` | 0 成本公网演示方案：命令、自启、6 个已知坑、安全口径、成本对照 |
| `docs/spec/dev-log.md` | 开发日志（**最新 四十八 节**：地区识别属地化全量落地 WS1–WS8）|
| `utils/region.py` | **属地解析统一入口**：`Region`/`normalize_area`/`resolve_region`/`policy_region_boost` + 级别与权重常量（政策与 RAG 共用）|
| `docs/spec/地区识别落地方案.md` | 属地化方案 **v2 定稿**（含 v1 的 7 处偏差记录，勿照 v1 实施）|
| `tests/test_silent_exceptions.py` | 静默吞异常门禁：「静默假成功」必须为 0 + HIGH/MID 基线只减不增（工具 `scripts/audit_silent_exceptions.py`）|
| `tests/test_claims_consistency.py` | 材料口径门禁：过时表述 / 测试数口径 / **PWA 只能宣称"可安装"、不得宣称离线能力** / 消融供数冒烟项白名单 |
| `tests/test_creative_proposal_template.py` | **提交件模板门禁**：`创意说明书-提交版.md` 必须守住官方模板 28 个标题、三.3/三.4 模板要点、项目概述 ≤300 字（中文字与去空白字符两种口径）、五.2 四项自评勾选、附件 1–5 条、参赛方向只勾基层治理 |

## 已完成的大改动（截至最终版）

- **P0/P1 收口**：数据安全（手机号全加密 + 脱敏 + 审计留痕）/ LLM 自主协商（`llm_negotiator.py`，默认关）/ 安全响应头 /
  索引优化（v40）/ 自转率统计 / 红黑榜下钻 / NLU 方言扩充 / 多租户预留（v41）/ 舆情源框架 / WebSocket 实时通知 / 分级路由降本
- **竞品对标升级 U1–U7**：混合检索（词法+语义 RRF）/ 真实政策语料 40 条 / 知识库健康度观测 / 关怀量化 / 演示前自检 /
  轻量知识图谱 / 数据层演进路径（见 dev-log 二十七～三十四节）
- **视觉系统 v2 + 客观 UI 审计**：设计令牌重建、三端差异化、暗色达标、无障碍达标，
  `scripts/ui_audit.py` **全站 34 个路由页 / 54 个页面视口 × 9 类检查 0 违规**（见 dev-log 三十五～三十六、四十三节）
- **第七轮复审收口**：v46 手机号加密全量补齐（提案/草稿/user_profile 残留）/ 运行时裸 ALTER 收回迁移链 /
  utcnow 弃用清理 / 异常文案脱敏 / 录屏素材（见 dev-log 三十七～三十八节）

- **地区识别/属地化落地**：政策按行政区划属地优先（线上加性分 + Agent RRF 重排双口径）、天气按社区城市
  （三端一致、缓存键 adcode）、知识库新增「适用地区」、金标 48 条含 6 条属地用例（属地 Top-1 4/4）
  （见 dev-log 四十八节 + `docs/spec/地区识别落地方案.md` v2）

详见 `docs/spec/dev-log.md`（最新 **四十八** 节）。
