# AGENTS.md — 项目理解与协作约定

> 本文件供 AI 编码智能体（opencode / Claude Code / Cursor 等）在接手本项目时快速理解架构与约定。改动项目前请先读这里。

## 项目定位

「社区先知 CommunityInsight」——基层治理·网格化多智能体系统，接诉即办平台。三端分离：居民端 `/resident`、网格员端 `/grid`、老年端 `/elderly`。

**核心价值主张**（答辩/评审最在意）：多智能体有**真实消息队列协作**（非伪多智能体）+ 双层防线（Verifier 校验 + Arbiter 仲裁留痕）+ **可验证**（评测集、成本记账、1169 项测试 + UI 客观审计 + 演示前自检，全部可现场复算）。

## 架构总览

```
前端 Vue3+Vite+NaiveUI (web/)  ──►  FastAPI 主服务 api_web.py (:8000)
                                    └─ 同时托管 Vue3 构建产物 (web/dist/)
                                    └─ JWT 鉴权 + WebSocket 实时通知 + 安全响应头
api.py (:18800)  = 扣子插件入口（独立，非主服务）
app.py  = Streamlit 备线（旧版演示，非主路线）
```

- **主服务**：`uvicorn api_web:app --port 8000`（FastAPI）
- **数据库**：SQLite（`data/community_insight.db`），schema **v54**（WAL 模式），可演进 PostgreSQL（见 `docs/scaling.md`）

## 多智能体核心（9 个声明式角色）

定义在 `agent/roles/__init__.py` 的 `AGENT_CLASSES`：

接待员(receptionist) / 报修调度(repair_dispatch) / 提案协商(proposal_collab) / 健康顾问(health_advisor) / 政策专员(policy_expert) / 通知管理员(notification_manager) / 天气守护(weather_guardian) / 网格助手(grid_assistant) / 合规审计(compliance_auditor)

协作机制（真协商，见 `agent/orchestrator.py`）：
- **黑板**（`agent/blackboard.py`）：共享上下文 + 消息队列 + 锁 + 历史（`post_message`/`get_messages`）
- **事件协商**：`process_negotiation(event)` 处理跨角色事件（天气⇄健康、报修→通知、`llm_collaboration` 通用）
- **双层防线**（每轮必过）：`agent/verifier.py`（幻觉/敏感词/手机号/诊断拦截）→ `agent/arbiter.py`（合规优先→安全→专业→转人工，决策落 `agent_logs`，`professional_domain` 字段为专业仲裁触发键）

## 常用命令

```bash
# 后端测试（可运行 1169 项：1168 通过 + 1 需外部服务跳过，全绿基线）
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
- **当前版本 v54**（v47 = 老年健康记录 `elderly_vitals` + 历史血压回填；v52 = 工单字段来源与处置归类；
  **v53 = `community_issues.is_demo` 演示数据标记**；**v54 = 服务台地基** —
  `submission_channel` / `operator_user_id` / `operator_role` / `station_id` / `consent_status` /
  `issue_code` + 号段表 `issue_code_seq`）。加列/索引/新表都走这个机制，
  **禁止**在业务代码里运行时 ALTER（v46 已把历史遗留的运行时补列全部收回迁移链）
- **加迁移后要同步文档数字**：`python scripts/sync_schema_numbers.py`（把各份材料里的
  `schema vN` / `N 个迁移` 一次改到当前值，**历史基线块内一字不动**）→ 再跑 `check_claims.py` 复核。
  以前没有这个入口，每次加迁移都得手改十几处、漏一处只有门禁才报
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

- **不要破坏这 1169 项测试**（1168 通过 + 1 需外部服务跳过）：每次改完跑 `python -m pytest tests/ -q`，必须全绿才提交；另跑 `python scripts/demo_preflight.py --fast`（9 项自检）与 `python scripts/ui_audit.py`（全站 38 个路由页 / 62 个页面视口 UI 客观审计）。
- ⚠️ **跑全量 `pytest tests/` 前先停掉本机服务**（2026-09-24 实测踩到）：`uvicorn api_web:app` 正在运行时，
  `tests/e2e/test_demo_scenarios.py` 有 2 个用例会因数据库状态冲突报 `no such table: community_issues`
  （表现为"单跑过、全量挂"）；停掉服务后同一套代码 **660 全绿**。反之 **UI 审计脚本（`ui_audit`/`mobile_audit`）需要服务在跑**。
  两条命令的"服务开/关"要求正好相反，别搞混。
- 测试用临时库隔离（`test_issue_phone_encryption.py` 的 `_fresh_db` fixture 模式），避免污染全局 `config.DB_PATH`。
- `stress_test.py`/`smoke_test.py` 是独立脚本（读取 `sys.argv`），**pytest 不要收集根目录脚本**（跑测试用 `tests/`）。
- **多租户（v48 起真隔离；v49 草稿归属与幂等；v50 人工待办工作台；v51 通知补发队列）**：租户键 = **社区名**（`user_profile.community`）。**四条硬规则**：
  ① **写入侧必须落租户**——社区范围数据的 INSERT 后要调 `utils.tenant.stamp_tenant(conn, 表, 新行id, 归属人id)`
     （无归属人的行用 `stamp_tenant_value(conn, 表, 行id, 租户)`）。
     v41 的教训：只加列+回填、业务从不写入 → 租户为空、隔离静默失效；
     **B6 又扫出 6 处漏盖章**，后果不是"看见别人的"而是**自己人也看不见**（转人工处理包/关怀事件/
     天气巡查任务/政务上报工单全被读取侧的 fail-closed 过滤掉）→ 由 `tests/test_tenant_write_side.py` 静态守着；
  ② **读取侧 fail-closed**——跨用户列表/聚合函数必须显式传 `tenant=`（走 `utils.tenant.tenant_clause`）：
     合法社区名 → `AND tenant_id=?`；**空串 → 返回空集**；两者都没给（也没给 `reporter_id/user_id` 自身范围）
     → **抛 ValueError**，绝不悄悄查全库；
  ③ **按 id 直取必须过闸门**——详情/操作接口是"按 id 直取单行"，没有 WHERE 可加，
     只校验角色就会出现"列表看不见、换个 id 就看见"（B6 实测：朝阳网格员读到海淀工单全文）。
     这类路由一律调 `api_routes.deps._same_tenant(request, 表, 行id)`（内部走
     `utils.tenant.row_in_tenant`，表名白名单 + 全分支 fail-closed）；
     它**不替代**自身范围校验（居民看自己的单仍要 `reporter_id == uid`，两者是"与"）。
     新增按-id 路由忘了带闸门 → `tests/test_tenant_idor_sweep.py` 直接红（豁免要写理由）；
  ④ **租户只从服务端身份来**（`api_routes/deps._tenant(request)`，源自 JWT 的 `community`），
     绝不接受前端传的 tenant/community 作为过滤依据；
  ⑤ **配置（`settings` 表）也要按租户分键**——裸键 = 全局默认，`键@社区` = 社区专属；
     一律走 `data/db_settings.py`（`get_setting`/`set_setting`/`get_setting_json`/`set_setting_json`），
     读取顺序 **社区专属 → 全局 → 代码默认**，**写入只写社区键**（别去改全局）。
     ⚠️ **别把配置缓存在模块级变量里再被 setter 改写**：那是跨租户串味的根源
     （B7 前的 `_match_threshold` / `_LINKAGE_THRESHOLDS` 就是这样，朝阳改阈值会连带改掉海淀）；
     另外**配置项必须接到真正做判定的地方**——只改"配置页读数"而不改判定点，就是本项目最忌讳的
     "做了但不生效"（天气联动原来连社区维度都没有，B7 已让定时任务按社区逐个判定）。
     系统级定时任务（没有"当前用户"）要"按社区各跑一遍"时，用 `utils.tenant.all_tenants()` 枚举社区；
  ⑥ **拿不到 `Request` 的代码要用请求级租户上下文**——Agent 工具（`tools/*.py`）、引擎这类
     普通函数没有 FastAPI 的 `Request`，**不许**用 `default_community()` 兜底（那等于"永远看成默认社区"，
     朝阳用户会看到海淀的数据，而且泄漏发生在**对话文本**里、页面审计抓不到）。
     入口处用 `with utils.tenant.tenant_context(租户):` 显式声明（`/agent/chat` 按 JWT、
     插件入口显式声明单社区口径），工具用 `tools/_ctx.py::tool_tenant()` 读；
     **取不到就返回空串**，由工具给出"无法确定所在社区"的明确提示。
     ⚠️ 备线的 `ui/_tenant.current_tenant()` 拿不到会话会回落默认社区，工具**不要**用它，
     要用严格版 `session_tenant_or_empty()`（实测踩到过：用它等于工具没隔离）。
     上下文用 `contextvars` 不用模块级全局（全局变量并发会串味）。
  ⑦ **收件人有统一入口，且"通知"与"读取"口径必须分开**——凡是"社区里发生的事要通知负责人"，
     一律走 `data.db_user.managers_of(tenant)`（内部 fail-closed：非法/空社区返回空表），
     不要**再**写 `list_users(role="grid")` 裸广播（项目里曾有 19 处，会把 A 社区老人的健康读数
     投给 B 社区网格员）。但通知**取不到合法社区时要回退为"全体负责人 + `_log.warning`"**，
     **不能** fail-closed——静默漏发比跨社区多发更难发现（SOS 尤其如此）。
     读取类（列表/下拉/分派候选）反过来：走 `tenant_clause`，空社区给空集、不传租户抛 `ValueError`
     （例：`data.db_kg.query_entity(name, tenant=...)`、`db_health_content.list_consult_handlers(tenant)`）。
     受 `tests/test_recipient_scope_ratchet.py` 棘轮约束：新增裸收件人写法直接红；
     有意保留的"无社区归属回退"必须登记在它的 `BASELINE` 并写明理由。
  `config.DEFAULT_COMMUNITY` 是历史/无归属数据的归档社区（`DEFAULT_TENANT` 是 v41 旧口径的行政区值，仅兼容保留）；
  Streamlit 备线在入口 `app.py` 调 `install_tenant_defaults()` 统一注入（见 `ui/_tenant.py`）。
- LLM 默认**规则优先降本**：代码默认 `LLM_NEGOTIATION`/`LLM_ORCHESTRATION`/`POLICY_LLM_RAG`/`RECEPTION_LLM_FALLBACK` 全关；
  **使用姿态**（`.env` / `.env.demo`）可全开——本机 `.env` 已全开，实测每轮对话约 **+0.9 秒 / +¥0.0002**。
  改 `.env` 后**必须重启服务**才生效（否则你测的是旧姿态）。
- **测试必须姿态无关**：依赖 LLM/演示开关的测试要显式 `monkeypatch.setenv/delenv` 钉住姿态，
  否则本机一开开关就会**真打网络**并造成假失败（本轮实测踩到 2 条）。
- **记账不许静默丢账**：`agent/llm_client._record` 失败会懒初始化重试并 warning（有子进程回归测试守着）；
  新增 LLM 调用点后确认 `llm_usage` 真有记录。
- 密钥姿态：`CRYPTO_KEY`/`WEB_JWT_SECRET` 在 **`DEMO_MODE=false` 且缺失或是仓库占位值时拒绝启动**（fail-closed）；
  演示姿态允许但会告警；`demo_preflight` 姿态行会显示"加密密钥=自定义/默认"。
- **演示行为一律"默认跟随 `DEMO_MODE`"，不许恒为开**（2026-10-06 空库演练抓到的真洞，见 dev-log 六十八）：
  `SEED_DEMO_DATA`（灌演示账号/演示数据）与 `DEMO_AUTO_WORKER`（自动替网格员推进工单）
  原来都恒为 `true`，于是**生产姿态的空库第一次启动就长出了 6 个演示账号**
  （2 个密码是 `demo123`，而密码登录是正常路径）+ 38 条虚构工单 —— 与部署手册红线**直接矛盾**。
  新增任何"演示专用行为"时：默认值写成 `"true" if DEMO_MODE else "false"`，
  并在 `deploy/.env.production.example` 里**显式写出**（`tests/test_prod_empty_init.py` 会核对模板）。
  生产空库不灌种子后，"第一个账号"走 `python scripts/bootstrap_admin.py`（见 `docs/deploy/生产部署手册.md` §4）。
- **观察期（打完 `pilot-ui-v1` 之后）跑 `python scripts/freeze_check.py`**：它对着冻结标签逐字比对
  老年端界面（页面/布局/语音与 SOS/图标/样式表/全局样式），改了就是红。要动界面 → 回退、或打新标签重新冻结、
  或在它的 `ALLOW` 里登记理由（**不要**用 ALLOW 长期豁免整目录，那等于把门禁关掉）。
  **`pilot-v1` → `pilot-ui-v1` 的切换**（2026-10-06）：界面重设计必然改老年端界面，而观察**尚未开始**，
  所以按脚本给的路径第 ② 条"打新标签重新冻结"，把 `FREEZE_REF` 换成 `pilot-ui-v1`。
- **视觉系统 v3「社区服务站」**（见 `docs/ui/UI重设计-交付说明.md` + dev-log 六十九）：
  渐变/发光/无限动画/keyframes **全部为 0**，`scripts/ui_style_audit.py` 以棘轮守着（只减不增）；
  新增任何"演示专用"特效前先想清楚——**审美要求已经变成可复算的数字**，加回去会直接红。
  ⚠️ 还有一个**血的教训**：删 `style.css` 里的 CSS 变量前，先跑 `ui_style_audit.py`
  看有没有页面还在 `var(--它)`——`.vue` 里的 `background:var(--x)` 在变量被删后会**整条失效**
  （表现是白字白底），而 `ui_audit` 的对比度检查**遇到祖先有渐变就跳过**，以前这类缺陷是被渐变挡住的。
- **改完 `web/src` 必须先 `cd web && npm run build` 再审计/演示**（复审 F4）：`web/dist` 不进 git，
  改完不 build 的话 `ui_audit`/`mobile_audit`/演示测的都是**旧包**，会得出"修了但没生效/没修也报绿"的假结论。
  两个审计脚本已内置 dist 新鲜度闸：落后于源码直接红字退出。
- 语义文字色**一律用亮/暗成对令牌**（`--ink-*`、`--st-*-ink`、`--primary-ink`、`--danger-solid`/`--success-ink`），
  **不要在内联样式里写死 hex**：写死色在暗色下不跟着换，`ui_audit` 会抓（第九轮抓到 6 处这类问题）。
- **界面图形一律用 `<EIcon name="…"/>`，禁止 emoji 当图标**（2026-09-29 全站换掉 557 处）：
  emoji 是各厂商字形（大小/配色/有无都不同），`ui_audit` 与 `mobile_audit` 都测不出"字形不确定"。
  ⚠️ **连注释里也不行**：`tests/test_no_emoji_ui.py` 会扫 `web/src/**` 的 `.vue/.js/.ts` **逐行**，
  注释里的 `⚠️` 一样报红（**这条我已经踩中两次**：`Dashboard.vue`、`AgentChat.vue`）——
  在 `web/src` 里写注释请直接用中文（"注意："），唯一豁免是 `utils/weatherIcon.js`（它按 emoji 选图标，
  是**输入匹配**而不是渲染）。
  图标在 `web/src/config/icons.js`（语义命名，不够就加一个）；写死的名字与配置里的 `icon: '…'`
  必须是表里真实存在的名字（写错只会静默显示成「更多」图标）→ `tests/test_no_emoji_ui.py` 会红。
  天气图标用 `utils/weatherIcon.js` 由**文字**选图标（后端仍返回 emoji 字段，但界面不再直接渲染它）。
- **禁止静默吞异常**（本轮新增门禁）：`except` 块里必须 `_log.warning(...)` 或抛出；
  尤其**绝不能"吞掉异常后返回成功"**（`tests/test_silent_exceptions.py` 会红）。
  分诊工具：`python scripts/audit_silent_exceptions.py`（HIGH/MID 基线只减不增）；
  安全/隐私类校验（敏感词、脱敏、权限）一律 **fail-closed**——组件坏了要拒绝，不许放行。
- **新增写路由要能被卡 7 闸门认出来**（`tests/test_write_route_gate.py`，实测踩到）：
  它对 `POST/PUT/PATCH/DELETE` 一律按"写操作"审，要求**角色 + 范围**检查痕迹，否则要登记理由。
  ⚠️ **纯计算却用 POST 的路由**（例：服务台的 `/extract` 要把一整段原话放进请求体）
  会**误判成裸写接口** → 正确做法是登记进它的 `_EXTRA_ALLOWED` **并写明"不落库"的理由**，
  **不要**套 `@write_route`（那等于谎称自己在写库），也不要为了躲门禁把接口改成 GET。
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
| `api_routes/` | 15 个业务路由模块 + 共享依赖（auth/agent/issues/proposals/notices/health/service_desk/...）|
| `agent/orchestrator.py` | 多 Agent 编排（黑板、协商、Verifier/Arbiter 接入、转人工）|
| `agent/roles/business_agents.py` | 5 个业务角色（报修/提案/政策/健康/通知）|
| `agent/roles/auto_agents.py` | 天气守护 + 网格助手 |
| `data/db_core.py` | schema + 迁移注册（**v54**）|
| `data/db_issue_code.py` | **对外事项编号 + 工作人员查询**（编号与内部 id 解耦；姓名/手机后四位/楼栋/时间/编号五路查；结果脱敏）|
| `api_routes/service_desk.py` | **服务台模式**（阶段 2）：共享设备代录——操作人/当事人**分开落库**、授权依据必填、跨社区拒绝、走查居民按操作人社区补章 |
| `web/src/views/ServiceDesk.vue` | 服务台四步页（办理方式+授权 → 当事人 → 内容 → 完成），**独立入口 `/service-desk`**，不进老年端导航 |
| `deploy/` | 部署骨架：compose（app + Caddy + 可选 PG + 独立备份容器）· 两阶段 Dockerfile（镜像内构建前端）· `docs/deploy/生产部署手册.md` |
| `scripts/backup_db.py` · `scripts/restore_drill.py` | 备份（快照 + sha256/表行数清单）与**恢复演练**（恢复到临时目录后 6 项校验；实测 0.02 秒） |
| `scripts/empty_db_drill.py` | **空库初始化演练**（生产红线）：三种姿态各建一套空库 → 生产姿态必须 0 演示账号/0 数据、缺密钥必须拒绝启动、**演示库文件不得被改动** |
| `scripts/bootstrap_admin.py` | **首个负责人账号引导**（空库不灌种子后怎么登进去）：强制 ≥12 位密码 · 拒绝 `demo` 前缀 · 社区名（租户键）必填 |
| `scripts/freeze_check.py` | **观察期界面冻结校验**：把老年端界面与冻结标签（现为 **`pilot-ui-v1`**）逐字比对，改了就是红（"观察期间不改界面"不能只靠记性） |
| `scripts/pilot_freeze_check.py` | **试点冻结门禁**：路由 / 各端页面 / Agent 角色 / 表 / schema / 路由模块 + **老年端 6 个入口、3 个主要动作、2 个求助入口** 全都不许变（多一个少一个都红）——"不再加功能"由机器守 |
| `scripts/staging_drill.py` | **staging 环境演练**（本机真跑）：独立库 + 独立密钥 + 独立账号 + 独立端口；验「演示账号在预发登不上」「写进去只落预发」「跨密钥解不开」 |
| `docs/eval/pilot-冻结清单.md` | **试点冻结清单**：冻了什么 / 怎么验 / **唯一合法解冻路径** / 还没做的（真人项） |
| `docs/eval/试点-运营规则确认单.md` | **试点前必须与社区填完的 9 条运营规则**（谁接单 / 谁关单 / 响应时限 / 通知失败怎么办 / 谁代办 / 哪些转人工 / 数据保存多久 / 谁能看完整手机号）——每条都标了"系统在哪配" |
| `scripts/sync_schema_numbers.py` | 加迁移后**一键同步**各份材料里的 `schema vN / N 个迁移`（历史基线块内不动）|
| `scripts/seed_category_demo.py` | 对照清单的**演示数据**准备（走真实链路造 + `--mark-existing` 补 `is_demo`；脚本自称"是演示数据"）|
| `web/public/device-check.html` | **真机自查页**：在真机上打开即测出浏览器/语音/播报/拨号能力并生成可粘贴报告（配合 `docs/eval/真机验证记录.md`）|
| `web/src/views/{resident,grid,elderly}/` | 三端页面 |
| `docs/mobile-deploy.md` | 移动端部署 + 发布检查清单 |
| `scripts/serve_public.py` | **本机常开一键工具**：起服务（默认只绑 127.0.0.1）+ 公网 HTTPS 隧道 + 抓新域名 + 刷新扫码页（`--status` / `--stop` / `--lan` / `--autostart`）|
| `scripts/probe_public.py` | **公网入口端到端探测**（健康/登录页/PWA/三角色/智能体对话，8 项；含 DNS 绕行）|
| `scripts/net_probe.py` | DNS 兜底：UDP/53 问公共 DNS + 本进程改写解析 + IP/SNI 直连校验（校园 DNS 会对新隧道域名返回 NXDOMAIN）|
| `docs/演示常开-本机方案.md` | 0 成本公网演示方案：命令、自启、6 个已知坑、安全口径、成本对照 |
| `docs/spec/dev-log.md` | 开发日志（**最新 七十 节**：试点冻结 + 环境真演练 / 六十九：前端「社区服务站」重设计）|
| `docs/ui/UI重设计-交付说明.md` | **视觉系统 v3 交付说明**：令牌变更表 · 各端改了什么 · 多宽度检查结果 · 已知问题 · `pilot-ui-v1` 冻结说明 |
| `scripts/ui_style_audit.py` | **「AI 展示感」客观审计**（棘轮只减不增）：渐变/发光/无限动画/keyframes/内联 hex/**未定义 CSS 变量**/老年端技术术语 |
| `scripts/ui_baseline_capture.py` | **UI 基线/对照截图**（`--out` 换目录）：25 页 × 5 档宽度 + 老年端确认卡，并记录路由/导航/按钮文字/溢出 |
| `scripts/journey_check.py` | **浏览器旅程**（发布门槛，9 条 / 89 项：v2 §14 八条 + 服务台代录一条）：页面真点击 + 接口 + 库内事实三处对账 |
| `scripts/grid_gov_check.py` | **治理侧两项对账**（29 项）：情景模拟器 + 人工修正对照清单，页面/接口/库内三处同一个数 |
| `data/db_governance_sim.py` | **治理情景模拟器**（只读）：样本量×增长率 → 工时 → 折算人手；**算不出来就明说**（不给人手数、不拿默认值硬算）|
| `tests/test_governance_sim.py` | 模拟器门禁（19 例）：只读 / 租户 fail-closed / 配置按社区分键 / 样本不足 / **标签必须是「情景估算」** |
| `tests/test_category_corrections.py` | **系统建议 vs 人工最终**门禁（12 例）：两列语义必须分开 / 覆盖率必报 / 无留痕的改动要露头 |
| `docs/eval/elderly-user-study-v1.md` | 真实老人观察**方案与空表**（执行只能由人做；文首写明"尚未开展"）|
| `tests/test_report_idempotency.py` | 报修幂等门禁（含**真双线程并发**用例：同编号并发只建一张单）|
| `utils/region.py` | **属地解析统一入口**：`Region`/`normalize_area`/`resolve_region`/`policy_region_boost` + 级别与权重常量（政策与 RAG 共用）|
| `docs/spec/地区识别落地方案.md` | 属地化方案 **v2 定稿**（含 v1 的 7 处偏差记录，勿照 v1 实施）|
| `tests/test_silent_exceptions.py` | 静默吞异常门禁：「静默假成功」必须为 0 + HIGH/MID 基线只减不增（工具 `scripts/audit_silent_exceptions.py`）|
| `tests/test_claims_consistency.py` | 材料口径门禁：过时表述 / 测试数口径 / **PWA 只能宣称"可安装"、不得宣称离线能力** / 消融供数冒烟项白名单 |
| `tests/test_no_markdown_bold_in_ui.py` | **界面文案门禁**：Vue 模板里（注释除外）不许出现 Markdown 粗体 `**…**`——它会被**原样显示**，而 `ui_audit`/`mobile_audit` 都测不出 |
| `tests/test_creative_proposal_template.py` | **提交件模板门禁**：`创意说明书-提交版.md` 必须守住官方模板 28 个标题、三.3/三.4 模板要点、项目概述 ≤300 字（中文字与去空白字符两种口径）、五.2 四项自评勾选、附件 1–5 条、参赛方向只勾基层治理 |

## 已完成的大改动（截至最终版）

- **P0/P1 收口**：数据安全（手机号全加密 + 脱敏 + 审计留痕）/ LLM 自主协商（`llm_negotiator.py`，默认关）/ 安全响应头 /
  索引优化（v40）/ 自转率统计 / 红黑榜下钻 / NLU 方言扩充 / 多租户预留（v41）/ 舆情源框架 / WebSocket 实时通知 / 分级路由降本
- **竞品对标升级 U1–U7**：混合检索（词法+语义 RRF）/ 真实政策语料 40 条 / 知识库健康度观测 / 关怀量化 / 演示前自检 /
  轻量知识图谱 / 数据层演进路径（见 dev-log 二十七～三十四节）
- **视觉系统 v2 + 客观 UI 审计**：设计令牌重建、三端差异化、暗色达标、无障碍达标，
  `scripts/ui_audit.py` **全站 38 个路由页 / 62 个页面视口 × 9 类检查 0 违规**（见 dev-log 三十五～三十六、四十三节）
- **第七轮复审收口**：v46 手机号加密全量补齐（提案/草稿/user_profile 残留）/ 运行时裸 ALTER 收回迁移链 /
  utcnow 弃用清理 / 异常文案脱敏 / 录屏素材（见 dev-log 三十七～三十八节）

- **地区识别/属地化落地**：政策按行政区划属地优先（线上加性分 + Agent RRF 重排双口径）、天气按社区城市
  （三端一致、缓存键 adcode）、知识库新增「适用地区」、金标 48 条含 6 条属地用例（属地 Top-1 4/4）
  （见 dev-log 四十八节 + `docs/spec/地区识别落地方案.md` v2）

- **多租户真隔离 → 配置隔离（B5–B7）**：租户键=社区名；写入侧盖章 / 读取侧 fail-closed /
  按-id 闸门 / 配置按社区分键 / Agent 工具用请求级租户上下文；收件人统一走 `managers_of(tenant)`
  （通知类**不做** fail-closed，理由见 dev-log 五十五～五十七节）
- **首批八条浏览器旅程（卡12）**：新增 `scripts/journey_check.py`（**现 9 条旅程 / 89 项检查**；
  交付时 8 条 / 58 项 → 63 项 → 阶段 2 加服务台代录一条后 89 项），
  每条同时验**页面真点击 / 接口返回 / 库内事实**；当场抓到两个真 bug（老人缺位置补充后**提交不了**、
  连点两下**建出两张工单**）并各自补了回归测试（见 dev-log 五十八节）
- **提交前最后一批（2026-09-29 深夜，v4 第 2/3 批收尾）**：居民端政策问答**依据面板**（含决策元数据 + 门禁）·
  语义文字色一律换 `-ink` 成对令牌（`ui_audit` 抓到方案详情 2.31:1）· 对抗集 **21 → 60 条**（四类各 15，
  3 条未达标项登记在台账 §7.1，不调参掩盖）（见 dev-log **五十九** 节）
- **全站去 emoji（557 处 → 0，单色线性图标体系；首轮按码位扫 539，端到端复核又补出 ⏱️↩️▶️⏸️ 一类 18）**：`web/src/config/icons.js`（122 个语义图标，含少量别名）+
  `components/EIcon.vue` 全站通用 + `utils/weatherIcon.js`（天气图标改由文字选图标，后端数据没动）；
  门禁 `tests/test_no_emoji_ui.py`（0 emoji / 图标名必须存在 / 必须 currentColor 与 aria-hidden / 扫描器自检）
  （见 dev-log **六十** 节）
- **计划内欠账清账（2026-09-29 深夜，v4 §6 B 栏清空）**：`senior_manager_ids` **前端入口**（天气管理页 +
  按社区分键、只收本社区负责人）· 通知创建/操作**接幂等键**（前端统一 `utils/idemToken.js`；
  编号不合规要告警，别静默不幂等）· **重复报修率 + 转人工原因分布**（`/agent/governance-metrics`，
  工作台"治理指标"卡）· **字段来源落库 + 同类处置画像**（迁移 **v52**、`/issues/{id}/field-sources`、
  `/issues/knowledge`；样本 <5 标注"样本不足"）（见 dev-log **六十一** 节）
- **收敛方案第 3–7 阶段（2026-09-29）**：冻结观察版 `elderly-observation-v1`（先跑绿再冻）·
  真实老人观察**准备件**（`docs/eval/` 四份，全是空表 + 「尚未开展」）·
  **治理情景模拟器**（只读，公式透明，**算不出来就明说**：未配置人均可用工时 → 不给人手数）·
  **补 `suggested_category` 写入侧**（`category` 会被人工改、`suggested_category` 保留系统原值）·
  **人工修正对照清单**（`/issues/category-corrections`，**覆盖率必须与一致率一起看**，
  无留痕的改动要露头，明确「不用于模型训练」）（见 dev-log **六十三** 节）
- **外部复核三点核实与门禁盲区修复（见 dev-log 六十四）**：判据从"只认 `HTTP 路由 N`"扩到
  `N 条路由` / `N 张业务表`（**提交件用的正是后者**，原先漏检 4 处）；**pytest 不可用时 `check_claims` 直接失败**；
  历史基线与当前值用 `<!-- baseline:historical -->` 分开写；`sync_test_count` 变历史感知（不再篡改历史）；
  "覆盖率不得写成准确率"变成门禁
- **"能做的"全部收口（见 dev-log 六十五）**：真实 DeepSeek 兼容 **3/3**、LLM 评分 **3/3**、语料指纹复核一致
  （材料里"真实模型链路未跑"已改正）· 迁移 **v53 `is_demo`** 让**演示数据可辨认**（面板四条免责 +
  已标记/未标记分开报）· `/device-check.html` **真机自查页** + `docs/eval/真机验证记录.md`（未开展）·
  `docs/eval/社区试点方案-v1.md`（未开展）· `scripts/sync_schema_numbers.py`（加迁移后一键同步材料数字）·
  修掉一处**数据相关**的对比度缺陷（草稿提示 4.43:1 → 新令牌 `--primary-light-ink`）

- **服务台线收口（阶段 1A + 2，见 dev-log 六十六～六十七）**：`deploy/`（Compose + Caddy + 独立备份容器 +
  生产部署手册，**Compose 未真实构建运行**）· 备份/恢复演练**真跑通过**（恢复 0.02 秒）· 迁移 **v54**
  （渠道 / 操作人-当事人分离 / 服务点 / 授权依据 / **对外事项编号** + 号段表）·
  `data/db_issue_code.py`（五路查 + 脱敏 + 只认后四位）· `/service-desk` **独立四步页**（共享设备收尾、抽取只给建议）·
  浏览器旅程 **第 9 条**（63 → 89 项，顺手修掉旅程 8 的空断言）· 新门禁 `tests/test_no_markdown_bold_in_ui.py`

- **观察期保障包（阶段 2 之后，见 dev-log 六十八）**：**空库初始化演练** `scripts/empty_db_drill.py`
  第一次跑就抓到**生产安全洞**——生产姿态的空库启动后自动长出 6 个演示账号（2 个密码 `demo123`）
  + 38 条虚构工单，与部署手册红线矛盾 → 修法：`SEED_DEMO_DATA`/`DEMO_AUTO_WORKER` **默认跟随 `DEMO_MODE`**
  + `scripts/bootstrap_admin.py`（空库第一个账号）+ `COMMUNITY_DB_PATH`（staging/生产分库）·
  **观察期界面冻结校验** `scripts/freeze_check.py`（对着 `pilot-v1` 逐字比老年端界面）·
  **真机自查页门禁** `tests/test_device_check_page.py` · 静态资源目录（`web/public`）纳入 emoji 与文案门禁

- **前端「社区服务站」重设计（v3，见 dev-log 六十九 + `docs/ui/UI重设计-交付说明.md`）**：
  三端 + 登录页 + 大屏按任务书重做视觉与信息层级：品牌色换稳重蓝绿（`#2D5BFF`→`#1B6B5A`）·
  圆角 12px 封顶 · **整层删除 v2 动效**（渐变/发光/星光粒子/呼吸环/毛玻璃/波浪入场/渐变流动/图标弹跳）·
  老年端首页三层 + 确认卡六件事优先（技术细节折叠）+ 进度页改事项编号 ·
  居民端首页「我要办事/查看进度/问社区问题」+ 问答结论优先与依据折叠 ·
  网格端第一层「待研判/待处理/待回访/已完成」+ 展开区左信息右操作 + 分析详情折叠 ·
  登录页与问答去内部技术名词 · 删掉无人使用的 `components/CountUp.vue` ·
  新增 `scripts/ui_style_audit.py`（棘轮）与 `scripts/ui_baseline_capture.py`（基线/对照截图）·
  冻结标签 **`pilot-ui-v1`**（观察必须在本版上进行）

- **试点期纪律（2026-10-06 起，见 dev-log 七十）**：**不再加功能**——路由/页面/Agent/表/schema
  由 `scripts/pilot_freeze_check.py` 与 `tests/test_pilot_freeze.py` 守着（多一个少一个都红）；
  界面由 `scripts/freeze_check.py` 对着 `pilot-ui-v1` 守着。
  改任何东西都要走 `docs/eval/pilot-冻结清单.md` 的**唯一合法解冻路径**（写理由 → 跑齐门禁 → **重新打标签**，
  观察数据只与同一标签内部可比）。环境侧的"预发与演示分离"由 `scripts/staging_drill.py` 真跑验证（15 项）。
  与社区一起填的 9 条运营规则在 `docs/eval/试点-运营规则确认单.md`——**没填完不开试点**。
  ⚠️ 数字口径：`docs/eval/pilot-v1-基线.md` 是 **`pilot-v1` 时代的历史基线**（数字用
  `baseline:historical` 标记夹着，保留当时事实不再更新），**当前值只看 `docs/eval/pilot-冻结清单.md`**；
  写材料时别把两份里的用例数/页数混用。

详见 `docs/spec/dev-log.md`（最新 **七十** 节）。
