# 变更日志

> 社区先知 CommunityInsight Agent —— 治理闭环 + 优化方案落地 + 老年关怀版
>
> 日期：2026-08-13　测试基线：**328 passed, 7 subtests passed**（`pytest -q`）

本日志记录本轮「全都做」迭代对系统的改动。改动原则：**内部标识不动**（表 `campus_issues`、字段 `school/grade/major/student_id`、角色 `student/teacher`、工具 `get_campus_pulse/get_school_policy`、路由 `/api/campus-pulse`、DB `campus_insight.db`、类 `CampusAgent` 均保留），只改用户可见文案与数据口径。

---

## 完整审查优化（全库扫描 + 一致性收尾）

> 对全库做一次完整审查：残留标识 / 文档一致性 / 配置键名 / 孤儿文件 / 测试清单。全程 `pytest` 全绿（328 passed）。

### 清理
- 删除孤儿文件：已删模块的 `.pyc`（`db_academic`、`models`、`query_campus_issues`、`query_campus_pulse`）+ 测试残留 DB（`tests/_test_semantics_anon.db`、`tests/unit/_test_audit_pending.db`）。
- 确认 `.gitignore` 已覆盖 `__pycache__/`、`*.pyc`、`*.db`、`.env`、`dist/`。

### 文档一致性
- `PRODUCT.md`：`99% 的学生作品` → `99% 的参赛作品`。
- `install.bat`：`demo_student/demo_teacher` → `demo_resident/demo_grid`，并补 `demo_elderly`。
- `.env.example`：补 `demo_elderly` 说明；社区配置键名从 `CAMPUS_*` 迁到 `COMMUNITY_*`。
- `docs/DEPLOY.md`：Secrets 示例与 `.env` 示例的 `CAMPUS_CITY/API_KEY` → `COMMUNITY_*`。

### 配置键名迁移（campus → community，向后兼容）
- `config.py`：`CAMPUS_CITY/CITY_ID/DISTRICT/BG_IMAGE/API_KEY` → `COMMUNITY_*`，旧键名仍作 `_secret` fallback（老 `.env` 不破坏）。
- `tools/query_weather.py`：4 处 `CAMPUS_CITY/DISTRICT/CITY_ID` → `COMMUNITY_*`。
- `api.py`：`CAMPUS_API_KEY` → `COMMUNITY_API_KEY`（中间件 + 告警文案）。

### 其他
- `data/database.py` docstring 补全 submodule 清单（含 `db_sla`/`db_memory`/`db_elderly` 说明）。
- `tests/test_verify_all.py` 模块编译清单核对为 53 模块，数量准确。

### 刻意保留（非缺陷）
- `data/db_core.py` 里的密码盐 `campus-insight-salt-2026` 与 v1/v2/v4 迁移中的旧名（`campus_issues`/`student_id`/`school`…）为迁移与密码校验所需，保留。
- `ui/components.py` 的 `CAT_LABEL` 旧校园分类兼容 shim 保留（§10.8）。
- `HANDOFF.md`、`CHANGELOG.md` 历史段落、`docs/competition/迁移日志-社区版.md` 为历史记录（含 `pages_teacher`/`demo_student` 等当时名），不篡改。

---

## 老年关怀版（elderly 角色，大字极简 + 安全闭环）

> 依据 `docs/ELDERLY_MODE_PLAN.md`（v2，含独居老人视角补充）实施。全程 `pytest` 全绿（328 passed）。

### 角色与入口
- 新增第三个角色 `elderly`：`app.py` 的 `st.navigation` 加 elderly 页面组（6 页），elderly 全屏无侧边栏（页面内大字导航 + 退出）。
- `ui/login.py` 第三个演示入口「👴 老年关怀版」；`ui/onboarding.py` 角色选择三列 + elderly 大字设置向导（子女电话/独居标记）。
- `data/seed.py` 新增 `demo_elderly`（张大爷，11号楼3单元301，沿用 seed 独居老人叙事）+ `_seed_elderly_profile`（高血压/降压药/子女电话）；`seed_all` 改为「已有数据也确保 demo 账号 + 老年档案存在（幂等）」。

### 数据层（迁移 v9/v10）
- `data/db_core.py` 迁移框架升到 v10：`_m9_create_elderly_profile`（健康/用药/联系人/独居/`last_active_at`）+ `_m10_create_sos_log`。
- 新模块 `data/db_elderly.py`：档案 CRUD、`touch_active`/`get_inactive_elders`/`notify_inactive_elders`（平安打卡 + 24h 无人应答检测 + 24h 去重通知）、`sos_request`/`get_pending_sos`/`mark_sos_done`、`due_reminders`（±30min 窗口）、`get_care_reminders`（天气/健康风险/助餐/防诈）。

### 页面（ui/pages_elderly/ + ui/elderly_components.py）
- `home.py`：大字主入口 + **SOS 二次确认（防误触）** + 一键呼叫（子女置顶/网格员/物业/急救）+ 到点用药置顶 + 关怀提醒 + 功能大按钮。
- `report.py`：语音（Web Speech API，iframe 内识别显示）+ 大字文字上报，复用语义路由 `route_intent` + `report_issue`，结果 TTS 朗读。
- `progress.py`（大字工单）、`notify.py`（通知 + TTS 朗读）、`health.py`（紧急信息卡 + 血压记录 + 子女电话 + 家属协助录入）、`meds.py`（用药 + 「我已吃」确认 + 设置）。
- `ui/elderly_components.py`：大字 CSS（20px + 64px 按钮 + 高对比）、`big_card`、`tts_speak`、`voice_input`。

### 安全闭环（独居老人核心）
- `perception/monitor.py` 新增 `_check_elderly_safety()`：超 24h 未互动 → 站内通知网格员（去重）。
- `ui/pages_grid/dashboard.py` 新增「👴 老年关怀」区块：待处理 SOS + 超时未互动老人列表。
- SOS 流程：按下 → 确认 → `sos_request` + `broadcast_notification` 通知网格员 → 网格员可「已处理」。

### 按推荐决策落实
- 健康档案仅本人可看，网格员只看「照顾注意事项」（紧急信息卡不暴露完整病历）；用药只站内通知 + TTS（无短信/电话）；独立子女端本期未做（通知 + 网格员关怀块覆盖）；血压/血糖大字手录 + 近 7 次趋势（无设备对接）。

### 测试
- 新增 `tests/test_elderly.py`（4 个：档案 CRUD / 用药触发窗口 / 平安打卡 / SOS 闭环）。
- `test_verify_all.py` 模块编译清单升到 53 模块（新增 `data.db_elderly`）。

### 关键新增文件
`data/db_elderly.py`、`ui/elderly_components.py`、`ui/pages_elderly/{home,report,progress,notify,health,meds}.py`、`tests/test_elderly.py`、`docs/ELDERLY_MODE_PLAN.md`

---

## 优化方案落地（三视角锐评后的 P0/P1/P2 迭代）

> 依据 `docs/OPTIMIZATION_PLAN.md` 实施：拆雷（P0）+ 修体验断点（P1）+ 提升 Agent 竞争力（P1-4/P2）。全程 `pytest` 全绿（324 passed）。

### P0 拆雷（现场翻车风险清零）

- **P0-1 角色权限隔离**：`ui/sidebar.py` 的「切换账号」下拉改为仅 `DEMO_MODE` 开启时显示（`config.py` 新增 `DEMO_MODE`，默认关闭）；新增 `ui/guard.py` 的 `require_role("grid")` 页面守卫，6 个网格员页全部接入；`api.py` 无 key 时一次性 warning 日志；`.env.example` 补 `DEMO_MODE` 说明与演示账号名。
- **P0-2 匿名闭环修复**：`data/db_governance.py` 新增 `get_my_anonymous_issues(reporter_id)`（按 reporter_id 查，兼容旧 `author='匿名'`），`ui/pages/mine.py` 新增「我的匿名工单」区块——匿名居民现在能追踪自己的工单且不泄露身份。
- **P0-3 DB 迁移框架化**：`data/db_core.py` 重写 `init_db()` 为版本化迁移——`schema_version` + `schema_migrations` 表，有序 `_m1.._m8` 迁移步，**失败即抛错不再吞异常**（幂等靠 PRAGMA 检查而非 try/except）。已验证新库/旧 campus 库/重复 init 三路径。

### P1 修体验断点

- **P1-1 assignee_id**：`community_issues` 加 `assignee_id` 列（迁移 v6）；`update_issue_status(assignee_id=)`、`auto_dispatch` 按用户 ID 派单并 `create_notification` 通知被派单网格员；`issues_mgmt.py` 「我的待办」优先按 assignee_id 过滤（同名不串单），手动指派也反查 id。
- **P1-2 SLA 升级两档**：`data/db_sla.py` 新增 `_escalation_expr`（极急12h/紧急48h/普通144h）、`escalate_overdue_issues()`（幂等标记 `escalated_at` + 邮件通知）、`get_escalated_issues()`；`perception/monitor.py` 新增 `_check_escalation`；`dashboard.py` 新增「⏫ SLA 升级工单」区块。
- **P1-3 满意度复核**：`set_satisfaction` 不满意不再直接重开，而是置为「待复核」；新增 `review_dissatisfaction(reopen)` 供网格员确认重开/驳回；居民端「我的」页展示待复核状态；工单管理加「待复核」筛选 + 复核按钮。堵住居民单方面刷单。
- **P1-4 Agent 核心（竞争力）**：新增 `agent/router.py`（意图→工具语义路由，关键词优先 + LLM 兜底 + 置信度）与 `agent/verifier.py`（回复中 #编号回查 DB 的幻觉校验）；接入 `engine._orient`（建议工具注入）与 `engine._reflect`（4.6 事实校验）。
- **P1-5 老年可用性**：`sidebar.py` 新增「紧急联系」一键拨打（tel: 网格员/物业）+「大字」模式（放大根字号）。
- **P1-6 处理进度透明**：`ui/components.py` 的 `issue_row` 卡片展示责任网格员。

### P2 竞争力深化 + 工程收尾

- **P2-1 自主规划**：新增 `agent/planner.py`（Plan-and-Execute 轻量版，规则模板 + LLM 步骤计划），`_orient` 注入「建议步骤计划」。
- **P2-2 多 Agent 协作 + event_memory**：新增 `agent/workers.py`（Observer/Dispatcher/Auditor 聚合）与 `data/db_memory.py`（跨会话事件记忆）；`report_issue`/`set_satisfaction` 记事件，`_orient` 注入「你最近…」个性化上下文。
- **P2-3 评测体系**：新增 `agent/eval/eval_suite.py`（15 个意图路由场景 + 幻觉编号校验），`python -m agent.eval.eval_suite` 可跑，当前关键词路由命中率 100%、幻觉检出率 100%。
- **P2-4 测试重构/死代码清理**：新增 `pytest.ini` 抑制 `PytestReturnNotNoneWarning`；删除死代码 `db_core.resolve_author()`、整个 `data/models.py`（无调用者）、`data/test_teacher.db`、`streamlit_errors.log`；`test_verify_all.py` 模块编译清单更新为 52 模块（新增 router/verifier/planner/workers/db_memory 等）。
- **P2-5 UI 收尾**：`login.py` 注册表单补「小区」必填；`mine.py` 影响力从游戏化等级（钻石/黄金/白银）改为治理化表述（"你推动的社区改变"）；邮件发送可观测已确认存在。

### 关键新增文件

`agent/router.py`、`agent/verifier.py`、`agent/planner.py`、`agent/workers.py`、`agent/eval/eval_suite.py`、`data/db_dispatch.py`、`data/db_memory.py`、`ui/guard.py`、`pytest.ini`、`docs/OPTIMIZATION_PLAN.md`

---

## 换皮收尾（全量命名迁移 + 战线二三）

> 本轮迭代把上一轮「内部标识不动」的原则升级为**全量命名迁移**：残留的校园标识（字段/死代码/文档）全部迁到社区命名，并落地两条加分战线与语义兜底测试。

### ③ 字段重命名（student_id/school/grade/major → resident_id/community/building/unit）
- `user_profile` 四字段全量改名：`student_id→resident_id`、`school→community`、`grade→building`、`major→unit`。
- **`grade` 双语义陷阱已避开**：健康度等级（优/良/需改进）的 `grade` 全部保留不动，只改用户画像字段上下文。
- `data/db_core.py` 的 `init_db()` 内置幂等迁移：`ALTER TABLE user_profile RENAME COLUMN` 四连（先于 ADD COLUMN 执行），旧库平滑升级，数据零丢失。
- 同步改动：`db_user.py`（SELECT/INSERT/UPDATE）、`db_governance.py` `_resolve_author`、`db_notifications.py`（`resident_id` 匹配）、`models.py`、`seed.py`、`agent/helpers.py`、`agent/prompt.py`、`ui/components.py`、`ui/sidebar.py`、`ui/login.py`、`ui/onboarding.py`、`ui/pages/mine.py`、`ui/pages_grid/*`、`api.py`（`ChatRequest.resident_id`）。

### ④ 诚实披露（docs/TECHNICAL.md）
- 新增「演进说明与命名对照（诚实披露）」章节，附旧→新命名对照表 + `init_db()` 幂等迁移说明。
- 修正文中残留的 `CampusAgent` / `get_campus_pulse` / `campus_issues` / 测试总数。

### ⑤ 战线二：主动发现 + 主动派单
- 新增 `data/db_dispatch.py`：`CATEGORY_DEPT_MAP`（类别→责任部门）+ `auto_dispatch()` + `discover_and_dispatch()`。
- 感知引擎 `perception/monitor.py` 新增 `_check_auto_dispatch()`：Observe 阶段自动扫描未派单开放工单，按类别派给对应部门网格员（极急/紧急优先）。

### ⑥ 战线三：匿名哈希 + 满意度透传原因
- 匿名上报身份哈希化：`data/db_governance.py` 新增 `anonymized_author()`（稳定伪名「匿名居民#hash8」），`report_issue(anonymous=True)` 存伪名而非明文身份，`reporter_id` 仍单独留存供闭环通知。
- 满意度透传原因：`community_issues` 新增 `satisfaction_reason` 列，`set_satisfaction(..., reason=...)` 透传「不满意原因」；居民端「我的」页可填原因，网格员工作台可查看近期不满意反馈。

### ⑦ 语义兜底测试（tests/test_semantics.py，5 个）
- SLA 时区（新工单不误判超时，回归 +8h bug）、分级边界（极急 6h/紧急 24h/普通 72h）、满意度闭环（不满意重开 + 重新解决重置）、匿名（伪名稳定且不泄露身份 + 后台保留 reporter_id）。

### ⑨ 死代码清理（db_academic 校园教务残留）
- 删除 `data/db_academic.py`（courses/exams/events/club_activities 无调用者），同步移除 `db_core.py` 四张 CREATE TABLE、`database.py` re-export、`models.py` 四个 dataclass、`test_verify_all.py` 模块编译项。
- 顺带清理 `data/db_health_alerts.py` 密度模型里的「exam periods / 中文大学 / class schedule / dorms」等校园注释与变量名（改为「季节高峰 / 通勤节奏 / 单元楼」），行为不变。

### 文档一致性
- `安装说明.md`：`demo_student/demo_teacher` → `demo_resident/demo_grid`。
- `README.md`：`pages_teacher/` → `pages_grid/`。
- `docs/COZE_INTEGRATION.md`：`/api/campus-pulse` → `/api/community-pulse`、`get_campus_pulse` → `get_community_pulse`、`campus_insight.db` → `community_insight.db`。

---

## P0 —— 数据正确性 & 治理闭环

### P0-1　分类系统统一 + 上报人字段落地
- 分类/紧急度判定收敛到 `_llm_classify(title, description)`（关键词兜底），全系统单一真相源。
- `report_issue` 工具补齐 `reporter_id`，工单与上报人建立真实归属关系。
- 救活 `suggested_category`，让 LLM 建议分类真正落库并参与展示。

### P0-2　SLA 分级（核心，替换全部硬编码 stale/urgent）
- **新增 `data/db_sla.py` 作为 SLA 单一真相源**：
  - `SLA_HOURS = {"极急": 6, "紧急": 24, "普通": 72}`（小时级口径）。
  - `get_sla_breaches(limit)` → 返回 `hours_open` / `level`（`critical`=极急/紧急超时，`overdue`=普通超时）。
  - `get_sla_summary()` → `{urgent_pending, critical_overdue, normal_overdue, total_overdue}`。
- **全量替换 8 处硬编码「>7 天 / 紧急积压」口径**，统一改走 `db_sla`：
  - `agent/reflector/_associations.py`、`agent/governance_audit.py`、`agent/closed_loop.py`、`api.py`、`data/db_perception.py`、`ui/pages_teacher/insights.py`、`ui/pages/transparency.py`、`agent/weekly_report.py`。
- `data/db_perception.py` 删除旧 `SLA_WARNING_DAYS / SLA_CRITICAL_DAYS` 常量，指向 `db_sla`。

### P0-3　满意度 / 确认闭环
- `data/database.py`：`set_satisfaction(issue_id, value, reopen_on_dissatisfied=True)` + `get_satisfaction_stats()`。
- 居民端 `ui/pages/mine.py`：已解决工单渲染 👍满意 / 👎不满意 按钮；👎 自动重新打开工单，形成真实闭环。

### P0-4　网格员工作台「我的待办」优先
- `ui/pages_teacher/issues_mgmt.py`：新增「👷 我的待办」开关，按当前登录网格员姓名过滤 `assignee`，今日待办排前。

### P0-5　匿名上报 + 通知定向
- 上报支持匿名；通知按 `reporter_id` 定向送达，不再全量广播。

---

## P1 —— 一致性 & 可用性

### P1-1　同事件聚合去重
- 报告时子串去重已存在，本轮确认并纳入口径说明（非重复建设）。

### P1-2　真派单
- 工单 `assignee` 字段已存在；本轮补齐网格员侧「我的待办」入口，派单链路闭环。

### P1-3　口径面板（方法论披露）
- `ui/components.py` 新增 `methodology_panel()`（expander），诚实披露分类 / SLA / 异常检测 / 满意度 / 隐私口径，引用 `SLA_HOURS`。
- 接入 `ui/pages_teacher/dashboard.py`、`ui/pages_teacher/insights.py`。

### P1-4　时区统一（今日边界）
- 时间戳存 UTC（`CURRENT_TIMESTAMP`），`julianday()` 差值本就时区无关（正确）。
- 修正「今日」边界缺失本地时区的站点：`date(col) = date('now','localtime')` → `date(col, 'localtime') = date('now','localtime')`。
  - `data/db_governance.py`、`data/db_notifications.py`（×3）、`ui/pages_teacher/issues_mgmt.py`。

### P1-5　首开不空 + 空态 CTA
- `ui/pages/mine.py`：空态补「🔧 去上报诉求」「💬 去发起提案」按钮（`st.switch_page`），首开不再空屏（seed 已覆盖首开数据）。

---

## P2 —— 加分项

### P2-1　周报按钮（已存在，SLA 统一）
- 周报入口已存在；本轮将周报的逾期统计改走 `get_sla_breaches()`。

### P2-2　意见情绪聚合（已存在）
- `get_feedback_stats()` + 感知舆情已覆盖，本轮确认无需重建。

### P2-3　邮件通知（QQ SMTP）
- `config.py`：新增 `SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_TO`（经 `_secret()` 读取）。
- **新增 `data/email_notify.py`**：`is_configured()` + `send_email()`，`smtplib.SMTP_SSL` 最佳努力，失败静默记录日志、返回 `False`，永不阻塞主流程。
- `ui/pages_teacher/insights.py`：周报生成后新增「📧 发送到邮箱」按钮。
- **凭据只进 `.env`（已 gitignore）**；`.env.example` 只放占位说明，不含真实授权码。

---

## 审查修复（本轮 Review 发现并修复的 Bug / 口径残留）

1. **`ui/pages_teacher/insights.py` 明细表 Bug**：Row 5「SLA 超时明细」仍引用 `o.get("days_open")`，但 `get_sla_breaches()` 返回的是 `hours_open`，导致全部行显示 `?`。已改为 `hours = o.get("hours_open", 0)`，`time_str = f"{hours//24} 天" / f"{hours} 小时"`，图标改用 `o.get("level") == "critical"`。
2. **「超过 7 天」硬编码残留**：
   - `agent/governance_audit.py`：`⚠️ 积压 X 件超过7天未处理` → `⚠️ 积压 X 件超时未处理`（含 docstring）。
   - `ui/pages_teacher/insights.py`：`已逾期超过 7 天未解决` → `已超时未解决`。
3. **`agent/weekly_report.py` 周报口径统一**：
   - 「SLA 逾期 / 逾期 X 天」→「SLA 超时 / 超时 X 天」。
   - 表格预警图标由硬编码 `days>=14/10` 阈值改为读 `s.get("level") == "critical"`（与 db_sla 口径一致）。

---

4. **`data/db_sla.py` 时区偏移 Bug（严重，本轮审查发现）**：`julianday('now','localtime')` 与 UTC 存储的 `reported_at`（`CURRENT_TIMESTAMP`）混用，导致所有工单 `hours_open` 系统性 +8 小时（实测旧写法 `8.0h` vs 正确 `0.0h`）。极急工单 6 小时 SLA 会被**立即误判超时**。已全部改为 `julianday('now')`（与 UTC 存储同源比较）。
5. **满意度闭环缺口**：居民点「不满意」重开工单后，`satisfaction` 仍残留「不满意」，网格员再次解决后居民无法再次评价、且旧评价被重复计入统计。已在 `update_issue_status` 的「已解决」分支加 `satisfaction = ''` 重置。
6. **日志兜底遗漏**：`get_satisfaction_stats` 缺 try/except + logging，与 `get_sla_summary` 等 get 函数不一致，DB 异常会致 dashboard 崩溃。已补 try/except + `_log.warning`。

---

## 已知的刻意保留（非缺陷）

- `ui/pages_teacher/issues_mgmt.py` 的 `_compute_days()`（Python 端「已开启 X 天」工龄展示，阈值 3/7/14 用于着色）是**展示层工龄启发式**，与 `db_sla` 的「紧急度 × 小时」SLA 超时判定是两回事，保留不变。
- `> date('now', '-7 days')` 类「近 7 天趋势窗口」是时间窗口，非 SLA 阈值，保留不变。

---

## 验证

- `python -m pytest -q` → **318 passed, 7 warnings, 7 subtests passed**（约 38–43s）。
- 每批改动后均跑全量回归，基线一致，无破坏。
- 敏感项复核：`.env`（含真实 `DEEPSEEK_API_KEY` / `HEFENG_API_KEY` / `SMTP_*`）仍在 `.gitignore` 内，不打包、不提交。
