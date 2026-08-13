# 社区先知 CommunityInsight Agent — 全面优化方案

> 依据：上一轮「大师 / 居民 / 网格员」三视角锐评（2026-08-13）。
> 目标：拆掉会翻车的雷 + 修好体验断点 + 把 Agent 从「规则驱动的工具调用器」升级为「能规划、能反思、能协作的治理 Agent」。
> 原则：**先拆雷，再修体验，竞争力专项按 P1 核心做深**。所有改动保持 `pytest` 全绿为底线。

---

## 0. 优化总纲（优先级速览）

| 类别 | 动作 | 翻车风险 | 优先级 |
|---|---|---|---|
| A 拆雷 | 角色权限隔离（切换账号/网格员页/API 鉴权） | 🔴 现场翻车 | P0 |
| A 拆雷 | 匿名上报闭环断裂（自己找不到自己的工单） | 🔴 现场露馅 | P0 |
| A 拆雷 | DB 迁移无版本号、吞异常 | 🟠 换机器/现场重建出中间态 | P0 |
| B 体验 | assignee 姓名弱主键、派单无通知、SLA 无升级 | 🟠 权责不清 | P1 |
| B 体验 | 满意度无复核、邮件静默失败、老人可用性 | 🟡 体验断点 | P1 |
| C 竞争力 | Agent 语义路由 / 自主规划 / 事实校验 / 多 Agent / 评测体系 | ⭐ 答辩胜负手 | **P1 重点** |
| D 工程 | 死代码清理、测试分层、异常策略、中间层收敛 | 🟡 长期债务 | P2 |

---

## 1. 技术架构与工程治理（AICG 大师视角）

### 1.1 DB 迁移框架化（P0）
- **现状**：`data/db_core.py` 的 `init_db()` 是"无版本号迁移流水线"，RENAME TABLE / RENAME COLUMN×4 / ADD COLUMN×N / role UPDATE 全部 `try/except: pass` 吞异常。跑两次没事、中途失败没人知道、库处于什么版本靠猜。
- **方案**：
  1. 新增 `schema_version` 表（`version INTEGER`），`init_db()` 开头读取当前版本。
  2. 把现有迁移重写为有序 `MIGRATIONS: list[tuple[int, str, callable]]`，每步独立函数 + 独立事务。
  3. 迁移**失败即抛错**（不再吞），日志输出失败步与原因；首次启动失败给出可读指引。
  4. 新增 `schema_migrations` 日志表记录已执行步骤（时间/名称），便于排查。
  5. 数据迁移与 schema 迁移同框架（`RENAME COLUMN`、role UPDATE 都纳入版本步）。
- **文件**：`data/db_core.py`
- **验收**：① 全新库 ② 带旧 campus 库 ③ 模拟中途失败——三条路径各有测试；迁移幂等（重复 init 版本号不变）；`pytest` 全绿。

### 1.2 死代码与仓库垃圾清理（P2）
- 清理清单（先 grep 确认零调用再删）：
  - `db_core.resolve_author()`（定义着、re-export 着、无调用者；`db_governance.py` 的 import 也未用）。
  - `data/models.py` 剩余死类（`UserProfile`/`KnowledgeItem` 若全库 grep 无引用则随 db_academic 一起收敛）。
  - `data/test_teacher.db`、根目录 `streamlit_errors.log`、`tests/` 下残留 `_test_*.db`。
  - 测试里 `_login_user_profile` 死 fixture。
- **验收**：grep `student|teacher|db_academic|resolve_author(` 在非迁移/非 shim 上下文零残留；`pytest` 全绿。

### 1.3 测试分层重构（P2）
- **现状**：`test_ablation.py` 的 `test_*` 函数 `return dict`，每次跑都刷 `PytestReturnNotNoneWarning`（冒烟脚本冒充单测）；大量断言"异常被吞掉返回默认值"，掩盖错误路径行为。
- **方案**：
  1. `test_ablation.py` 改为真正 `assert` 或在文件头 `@pytest.mark.smoke` 标记并从默认收集剔除。
  2. 新增**行为断言**用例：对关键写路径（report_issue / set_satisfaction / update_issue_status / auto_dispatch），断言"返回值、DB 状态、通知记录"三者一致。
  3. 错误路径测试从"断言不崩"升级为"断言返回结构 + 日志级别"。
- **验收**：`pytest -q` 无 `PytestReturnNotNoneWarning`；写路径行为用例 ≥ 10 条。

### 1.4 安全与权限隔离（P0，最大翻车点）
- **切换账号漏洞**：`ui/sidebar.py` 登录后渲染「切换账号」下拉，`list_users()` 全量列出，**任何用户一键切到网格员**。
  - **方案**：删除该下拉，或改为仅 `DEMO_MODE=true`（`config.py` 读 `.env`/环境变量）时显示；默认关闭。账号切换只保留"退出→重新登录"。
- **RBAC 页面守卫**：`app.py` 的 `st.navigation` 加角色过滤；grid 页面入口加 `if role != "grid": st.error + st.stop()` 统一守卫函数（`ui/guard.py`）。
- **API 鉴权**：`api.py` 已有中间件但 `CAMPUS_API_KEY` 默认空 = 全公开。方案：部署文档强制设置；`ngrok_backup.bat` 加提示"公网暴露需先配置 API Key"；README 安全章节。
- **验收**：居民登录后访问 `/grid/*` 页面被拦截；无 key 调 `/api/chat` 返回 401；`DEMO_MODE=false` 时侧边栏无切换账号。

### 1.5 中间层收敛（P2）
- `data/database.py` 99 行纯 re-export，IDE 跳转多一层。方案：保留兼容层但**新代码直接 import 子模块**（`data.db_governance` / `data.db_sla` / `data.db_dispatch`），并清理已无调用者的 re-export。
- **验收**：grep 确认新增代码无 `from data.database import`（仅存量兼容）。

### 1.6 异常策略分级（P1）
- 写路径（report/update/satisfaction/派单）异常必须可见：`st.error` 或 `logging.error`，禁止静默。
- 读路径（统计/健康分）降级可保留 `_log.warning` + 返回空结构。
- **验收**：审计关键写函数无裸 `except: pass`；异常有明确日志级别与上下文。

---

## 2. 居民体验与信任（居民视角）

### 2.1 匿名上报闭环修复（P0）
- **现状**：匿名上报 `author` 存伪名 `匿名居民#hash8`，而「我的」页用真实身份 `resolve_author(profile)` 匹配 → **匿名居民自己看不到自己的工单**。
- **方案**：
  1. `data/db_governance.py` 新增 `get_my_anonymous_issues(reporter_id, limit)`（按 `reporter_id` 查，不暴露 author）。
  2. `ui/pages/mine.py` 新增「匿名工单」页签/区块：仅当当前用户存在 `reporter_id` 匹配的匿名工单时展示，状态流转（待处理/处理中/已解决/满意度）与普通工单一致。
  3. 通知中心已按 `reporter_id` 定向，保持不动。
- **验收**：匿名上报 → 「我的-匿名工单」可见、状态可追踪、可评价；隐私不泄露（他人看不到）。

### 2.2 激励体系治理化（P2）
- 保留"贡献统计 + 影响力积分"，弱化"💎钻石治理者/🥇黄金守卫者"游戏化等级文案，改为「贡献记录 + 你推动的社区改变」列表（如"你上报的 X 已解决，惠及 N 户"）。
- **验收**：页面文案更新，无排行榜式措辞。

### 2.3 老年可用性（P1）
- ① 语音输入：`ui/pages/voice.py` 增加浏览器 Web Speech API 录音→文本（渐进增强，无 ASR 时回退键盘）；② 大字模式开关（`ui/theme.py` 字号 token 放大档）；③ 楼栋/单元校验改"选填 + 智能识别"（`agent/helpers.extract_location` 已能提取，弱化 `validate_location` 硬拦截）；④ 工单/页面加"一键拨打网格员 62319876 / 物业 62310086"（seed 已有号码）。
- **验收**：居民核心路径（上报/查工单/评价）3 次点击可达；语音入口降级可用。

### 2.4 注册语义修正（P1）
- `ui/login.py` 注册表单：**小区（community）必填**，楼栋/单元选填；`create_user` 字段语义已修正（上一轮已把楼栋→building、单元→unit）。
- **验收**：注册后 `profile.community` 非空；旧注册用户（community 空）不强制补录、Agent 提示补填。

### 2.5 处理进度透明（P1）
- 工单卡片（`ui/components.issue_card`）展示：`assignee`（由谁处理）+ 处理时间线（上报→处理中→已解决 节点）+ 满意度状态。
- **验收**：居民端工单可见"责任网格员 + 处理阶段"。

---

## 3. 网格员效率与权责（网格员视角）

### 3.1 assignee 弱主键 → assignee_id（P1）
- **现状**：`_my_name = profile.get("name")` 比对 `assignee` 字符串，**同名网格员串单**。
- **方案**：`community_issues` 新增 `assignee_id INTEGER`；`update_issue_status(..., assignee_id=)` / `auto_dispatch` 按 ID 写；「我的待办」按 `assignee_id = current_user.id` 过滤；展示层回查姓名。
- **文件**：`data/db_core.py`（ADD COLUMN + 迁移）、`data/db_governance.py`、`data/db_dispatch.py`、`ui/pages_grid/issues_mgmt.py`
- **验收**：两个同名网格员测试用例不串单。

### 3.2 派单通知闭环（P1）
- **现状**：`auto_dispatch` 直接写 `assignee`，网格员无感知。
- **方案**：派单成功后 `create_notification(assignee_id, "new_dispatch", "你被派了新工单 #X …")` + 侧边栏徽章计数（`render_sidebar_badge` 已存在）+ 工作台「新派单」区块置顶。
- **验收**：派单后网格员通知中心有记录、徽章+1。

### 3.3 SLA 超时升级机制（P1）
- **现状**：`get_sla_breaches()` 只展示"超时了"。
- **方案**：
  1. `data/db_sla.py` 新增 `escalation` 档：超时 1× → 工作台置顶 + 徽章；超时 2×（极急 12h / 紧急 48h / 普通 144h）→ `escalated` 标记（`community_issues` 加 `escalated_at`）+ 邮件通知（复用 `data/email_notify.py`）。
  2. `ui/pages_grid/dashboard.py` 增加「⏫ 升级工单」区块。
- **验收**：造超时数据后 1×/2× 两档触发可验证；升级有通知痕迹。

### 3.4 满意度复核机制（P1）
- **现状**：居民「不满意」直接重开工单，无审核，可被单方面刷单。
- **方案**：`set_satisfaction` 不满意 → 工单进入「待复核」状态（新增状态或 `satisfaction_reason` 已存 + `status='待复核'`）；网格员工作台确认 → 重开或驳回（驳回保留评价但不重开）。闭环：确认重开→处理→再解决→评价重置（保留现有重置逻辑）。
- **文件**：`data/db_governance.py`、`ui/pages/mine.py`、`ui/pages_grid/issues_mgmt.py`
- **验收**：测试覆盖"不满意→待复核→确认重开→再解决→可再评价"全链路。

### 3.5 工单管理页重构（P2）
- **现状**：`issues_mgmt.py` 手写 `_detail_assignee_{iid}` session_state key、6 列挤一屏、移动端崩。
- **方案**：改用 `st.form` 收敛编辑控件；新增勾选→批量改状态/派单（`update_issue_status` 批量循环）；列布局按断点折叠（复用已做的移动端 CSS）。
- **验收**：无 widget ownership 错误；移动端宽度可操作。

### 3.6 周报/邮件可观测（P2）
- `data/email_notify.py` 失败在 UI 显示"📧 发送失败（请检查 SMTP 配置）"，不再静默；日志 `error` 级。
- **验收**：断网/无凭据时界面有明确提示。

---

## 4. Agent 竞争力专项（核心，答辩胜负手）

### 4.1 现状诊断
| 维度 | 现状 | 天花板 |
|---|---|---|
| 意图路由 | `prompt.py` 穷举触发词→工具映射 + `detect_persona` 关键词 | 没写过的说法就路由不到 |
| 任务编排 | 提示词里"固定组合模式"（如脉搏→统计） | 只能走写死的两步 |
| 反思 | `enforce_tool_call` 安全网（防幻觉） | 只校验"调没调工具"，不校验"结果对不对" |
| 记忆 | 会话窗口 + user_profile | 无跨会话事件记忆 |

### 4.2 五大升级（目标态）
1. **语义路由**（`agent/router.py`）：意图→工具改为 LLM 语义打分 + 关键词兜底 + 置信度阈值。未登录表述（如"我家楼道灯忽闪忽闪的"）也能路由到 `report_issue`；低置信度回退关键词链。**替换而非删除**：现有 `detect_persona` 作为兜底保留。
2. **自主规划 Plan-and-Execute**（`agent/planner.py`）：主 Agent 先产出步骤计划（如"查同类工单→查提案→建工单→告知进展"），执行器逐步调用工具，每步结果回填计划，失败自动 replan。替代提示词里写死的"组合模式"。
3. **事实校验反思 v2**（`agent/verifier.py`）：LLM 回复中的数字/工单号/状态与 DB 事实核对（工单号回查 `community_issues`），不一致则修正或重新生成。与 `enforce_tool_call` 互补：一个管"调没调"，一个管"答得对不对"。
4. **多 Agent 协作**：后台 Worker 角色——`ObserverAgent`（感知→主动发现，已有 `perception` + `reflector` 基础）、`DispatcherAgent`（主动派单，已有 `db_dispatch`）、`AuditorAgent`（治理审计，已有 `governance_audit`）。主对话 Agent 可"调起"它们并引用其结论，形成"感知→处置→审计"闭环叙事。
5. **记忆与个性化**：新增 `event_memory`（跨会话事件：用户报过的工单、关注的类别、历史评价），`get_system_prompt` 注入"与你相关的事件摘要"；画像驱动建议（如老年用户主动提醒助餐/体检，已有 seed 数据）。

### 4.3 文件级实现路径
| 升级 | 新增/改动文件 | 关键函数 |
|---|---|---|
| 语义路由 | `agent/router.py`（新）、`agent/prompt.py`（触发词表→路由兜底） | `route_intent(text) -> (tool, confidence)` |
| 自主规划 | `agent/planner.py`（新）、`agent/engine.py`（run 阶段接入） | `plan(text) -> steps` / `execute(step)` / `replan(fail)` |
| 事实校验 | `agent/verifier.py`（新）、`agent/enforce.py`（并入） | `verify_facts(reply, steps) -> corrected` |
| 多 Agent | `agent/workers.py`（新，聚合三个 worker）、`agent/engine.py` | `run_workers(trigger)` |
| 记忆 | `data/db_memory.py`（新表 `event_memory`）、`agent/memory.py`、`agent/prompt.py` | `remember_event()` / `get_event_summary(user_id)` |

### 4.4 评测体系（让"竞争力"可量化、可答辩）
- 新增 `agent/eval/eval_suite.py`：**20+ 场景**，三类：
  1. 标准场景（锐评里可演示的：上报/查单/提案/脉搏）。
  2. **未见过表述**（"我车轱辘陷坑里了"→停车管理上报；"楼上半夜咚咣的"→噪音扰民），验证语义路由。
  3. **失败注入**（DeepSeek 超时、工具返回空、用户二次追问），验证降级与反思。
- 指标：`任务完成率`、`工具正确调用率`（期望工具集合匹配度）、`幻觉率`（回复数字与 DB 不一致比例）、`平均工具步数`（效率）。
- **验收**：评测基线落盘（`agent/eval/report.md`），答辩可直接引用数字："语义路由把未见表述的工具命中率从 X% 提到 Y%"。

### 4.5 降级保障（红线不变）
- 三层回退链（CommunityAgent → OfflineAgent → graceful_fallback）**保留不动**。
- 新决策层（router/planner/verifier）任何异常自动落到现有规则链；评测里失败注入即验证这一点。
- 规则兜底（`detect_persona` / `enforce_tool_call` / 关键词分类）作为"保底层"永久保留——这是防现场翻车的保险，不是技术落后。

---

## 5. 实施路线图

| 阶段 | 任务 | 文件 | 验收 | 估时 |
|---|---|---|---|---|
| P0-1 | 角色权限隔离（切换账号 + 页面守卫 + API 鉴权文档） | `ui/sidebar.py`、`app.py`、`ui/guard.py`、`config.py` | 居民无法进 grid；无 key 401 | 0.5 天 |
| P0-2 | 匿名闭环修复 | `data/db_governance.py`、`ui/pages/mine.py` | 匿名工单可见可追踪 | 0.5 天 |
| P0-3 | 迁移框架化（schema_version + 有序迁移 + 失败即报） | `data/db_core.py`、`tests/` | 三路径测试 + 幂等 | 1 天 |
| P1-1 | assignee_id + 派单通知 | `db_core`、`db_governance`、`db_dispatch`、`issues_mgmt` | 同名不串单；通知可达 | 1 天 |
| P1-2 | SLA 升级两档 | `data/db_sla.py`、`dashboard.py` | 1×/2× 触发验证 | 0.5 天 |
| P1-3 | 满意度复核 | `db_governance.py`、`mine.py`、`issues_mgmt.py` | 全链路测试 | 1 天 |
| P1-4 | **Agent 竞争力核心**：语义路由 + 事实校验 | `agent/router.py`、`agent/verifier.py`、`agent/engine.py` | 未见表述命中率提升；幻觉率下降 | 2 天 |
| P1-5 | 老年可用性（语音/大字/一键拨号/校验放宽） | `ui/theme.py`、`ui/pages/voice.py`、`ui/pages/issues.py` | 核心路径 3 次点击 | 1 天 |
| P1-6 | 处理进度透明 | `ui/components.issue_card` | 卡片含责任网格员+时间线 | 0.5 天 |
| P2-1 | 自主规划 Plan-and-Execute | `agent/planner.py`、`agent/engine.py` | 多步编排场景通过 | 2 天 |
| P2-2 | 多 Agent 协作 + event_memory | `agent/workers.py`、`data/db_memory.py` | 后台 worker 结论进对话 | 1.5 天 |
| P2-3 | 评测体系 | `agent/eval/eval_suite.py` | 基线报告落盘 | 1 天 |
| P2-4 | 测试重构 / 死代码清理 / 异常分级 / 中间层收敛 | 全库 | 无警告、grep 干净 | 1 天 |
| P2-5 | 激励治理化 / 注册语义 / 工单页重构 / 邮件可观测 | UI 各页 | 文案与交互验收 | 1 天 |

---

## 6. 风险与取舍

- **时间紧**：若距比赛不足 3 天，只做 P0 全部 + P1-4（语义路由+事实校验）即可形成"拆雷 + 竞争力"双卖点；P2 项可全部顺延。
- **语义路由风险**：LLM 路由有不确定性 → 必须保留关键词兜底 + 置信度阈值 + 评测验证，不允许"去掉保底层"。
- **迁移框架风险**：重写 init_db 是动地基 → 以三路径测试（新库/旧库/失败）为硬门槛，绝不边改边上线。
- **多 Agent 成本**：后台 worker 会额外消耗 API 额度 → Observer/Dispatcher 尽量走规则（perception + db_dispatch 已是规则），只有 Auditor 的深度解读走 LLM。

---

## 7. 最终验收清单

1. `python -m pytest -q` 全绿，无 `PytestReturnNotNoneWarning`。
2. 居民/网格员双角色隔离可现场演示（切换账号不可达 grid）。
3. 匿名上报→「我的-匿名工单」→处理→评价 全链路可演示。
4. 派单有通知、SLA 有两档升级、满意度有复核，均可现场造数据验证。
5. `agent/eval` 基线报告存在，答辩可引用"未见表述命中率 / 幻觉率"数字。
6. 三层回退链验证脚本（失败注入）通过。
