# 开发日志

> 依据《社区服务智能体最终版定义文档》改造本项目。每阶段完成追加一条日志。

---

## 阶段 0：地基（已完成）

**做了什么**
1. 需求文档落盘到 `docs/spec/`（00-总览与跨模块联动 + 01~07 七个模块 + 00-改造方案）。
2. schema 从 v10 升级到 v18，新增 16 张表（40 张表总数），覆盖 7 模块全部数据需求。
3. 留痕系统扩展：`activity_log` 表新增 `module`/`before_value`/`after_value` 字段，`log_activity()` 函数支持传入这三个参数，满足文档「操作人/时间/类型/前值/后值/关联编号/模块来源」的留痕要求。

**新增表清单**
issue_drafts / safety_reminders / issue_supplements / proposal_votes / proposal_vote_dedup / proposal_drafts / weather_cache / weather_alerts / weather_check_tasks / health_contents / health_consults / notices / notice_reads / medication_reminders / emergency_contacts / emergency_calls / knowledge_versions / policy_questions（另扩展 community_issues、proposals、knowledge_base 字段）

**验证**：`328 passed, 3 deselected` 全绿（迁移未破坏现有功能）。

---

## 阶段 1：报修模块 · 数据层（已完成）

**做了什么**
新建 `data/db_repair.py`，实现文档《01-报修.md》的完整状态机与审核派单闭环。

**状态机**（11 状态）：待审核 → 退回补充信息 → 已审核待派单 → 已派单 → 处理中 → 待居民反馈 → 处理结束，外加 已撤回/已关闭/待协商/已转出；安全隐患走 safety_reminders 表不进状态机。

**核心函数**：submit_issue（校验+特殊情况识别）/ audit_issue（审核）/ dispatch_issue（分派）/ start_process / resolve_issue / feedback_issue（满意/不满意重新计时）/ withdraw_issue / reopen_issue / close_issue / transfer_issue（违规转出）/ negotiate_issue（费用协商）/ supplement_issue（24小时最多2次）/ detect_special_case / create_draft / get_issue_timeline。

**验证**：端到端闭环跑通（提交→审核→分派→处理→填结果→反馈满意→处理结束，6 条留痕）；安全隐患正确拦截不生成工单；手机号格式校验正确。

**遗留**：工具层（action_report_issue.py）与 UI 层（issues.py / issues_mgmt.py）改造由并行子任务进行中。

---

## 阶段 2~7：进行中（6 个并行子任务）

- 报修收尾 ✅ 已完成（工具层四档紧急度+室内外分类、居民端/负责人端重写、11状态全覆盖）
- 提案模块 ✅ 已完成（14状态机+匿名投票+55项冒烟测试；补 audited_at/resolved_at/community_building/feedback_at/feedback_reason/satisfaction 6列）
- 老年端
- 政策问答 ✅ 已完成（68 项冒烟断言；知识库审核版本/自动回答转人工/3次循环/高频统计）
- 通知发布 ✅ 已完成（55 项冒烟测试通过）
- 天气 + 疾病预防 ✅ 已完成（数据层+核心逻辑约60项断言；天气预警检测/检查任务升级/健康内容审核/健康咨询/联动）

## 阶段 2~7：验证中发现的 bug 与修复

1. **提案 submit_proposal SQL bug（已修复）**：`data/db_proposal.py` 的 INSERT 语句中 `is_public` 列被误硬编码为 `'待审核'`，导致 17 列只给 16 值（`16 values for 17 columns`）。修复：`VALUES (?,?,?,?,0,'待审核',?,'待审核',...)`，is_public 改为参数占位符。修复后验证：提交/审核/确认公开/投票全链路跑通，投票匿名正确（proposal_votes 只存分数、proposal_vote_dedup 只存 user_id，两表物理隔离，均分 4.5）。

## 整合阶段待办清单（子任务全部完成后执行）

1. 注册新页面路由到 app.py：`ui/pages_grid/notices_mgmt.py`（通知管理）、`ui/pages_grid/policy_mgmt.py`（政策问答管理）、居民端 `ui/pages/policy.py` 等新增页面。
2. 首页强制弹窗 + 未读角标接入（居民端 home.py、老年端 home.py）。
3. 清理临时文件：`_smoke_*.py`、`tests/_tmp_*.py` 等子任务遗留的冒烟测试脚本。
4. 适配 seed.py 到新状态机（工单 11 状态、提案新字段）。
5. 改写旧测试（64 处旧状态「待处理/处理中/已解决」「讨论中/已回应/已采纳」引用）。
6. 补数据层函数：报修 `resubmit_issue`（居民把「退回补充信息」重新提交回「待审核」）、提案同理（提案 subagent 已实现 resubmit_proposal）。
7. 更新 `agent/enforce.py` 安全网调用（传 reporter_phone，适配四档紧急度+手机号强校验）。
8. 旧页面遗留：`ui/pages_grid/dashboard.py`、`ui/sidebar.py`、`ui/pages/mine.py`、`transparency.py` 等仍读旧三态，需适配新状态机。
9. 全量测试 + 审查优化。

## 整合阶段（进行中）

**已完成**
1. 注册新页面路由到 app.py：grid 端加「通知管理」「政策问答管理」，居民端加「政策问答」。
2. schema v20：proposals 补 6 列（audited_at/community_building/resolved_at/feedback_at/feedback_reason/satisfaction），解决测试库缺列问题。
3. 改写 9 个失效旧测试（test_tools.py）适配新逻辑：四档紧急度、手机号强校验、提案 5 类+必填、附议改投票。
4. 补数据层函数 `resubmit_issue`（居民把退回单重新提交回待审核）。
5. 全量测试 328 passed 全绿（回到基线）。

**已完成（阶段 1~7 全部完成）**
- 天气/疾病预防 UI 页面（居民端天气 weather.py / 居民端疾病预防 health.py / 负责人端天气管理 weather_mgmt.py / 负责人端疾病预防管理 health_mgmt.py / 老年端大字版天气 home.py），已注册路由。
- 旧页面适配：统计函数聚合兼容新状态机（get_issues_stats/get_proposals_stats 保留旧键+新键）、UI 状态颜色映射（components.py 补全 11 状态+提案状态颜色）。
- seed.py 适配新状态机（工单 11 状态、提案新状态、四档紧急度）。
- resubmit UI 调用（居民端 issues.py 加「重新提交」按钮）。
- agent/enforce.py 适配手机号校验（从用户资料读 name/phone）。
- schema v21：user_profile 加 phone 字段；seed 给 demo 用户填手机号。

**验证**
- 全量测试 328 passed 全绿（回到基线）。
- Streamlit AppTest 端到端：启动无异常、Agent 初始化 16 工具、demo_resident 登录成功、居民端渲染无异常。
- 各模块数据层冒烟验证：报修 11 状态闭环、提案匿名投票（两表物理隔离）、老年端紧急求助闭环、政策问答审核版本+自动回答+转人工、通知 55 项、天气+疾病预防约 60 项、统计聚合、seed 新状态分布。

## 后台调度器（补充完成）

**做了什么**
新建 `scripts/scheduler.py`：后台守护线程，每 60 秒轮询一次全部幂等自动任务，让 spec 要求的「系统自动触发」（A 类停机点）在无人操作时也真正执行。
- 通知：定时发布 / 紧急通知到期取消 / 置顶到期取消（db_notice.run_auto_tasks）
- 天气：极端天气预警检测 / 检查任务超时标记 / 超时升级（db_weather）
- 提案：逾期默认确认公开私有 / 逾期未反馈视为满意（db_proposal）
- 疾病预防：咨询 24h 超时 / 7 天未反馈关闭 / 疫苗内容到期下架 / 置顶取消 / 月度更新提醒（db_health_content）

**集成**：app.py 启动时 `ensure_scheduler_started()` 启动守护线程（进程级单例，幂等任务，失败不影响主流程）；也可独立运行 `python scripts/scheduler.py`。

**验证**：run_all 全部任务执行成功（还实测触发了一个雷电黄色预警）；328 测试全绿；AppTest 确认调度器线程随 app 启动。

## 遗留项（用户白天处理）

按用户指示「遇到解决不了的问题跳过，白天来解决」，以下两项记录为遗留：

1. **照片/附件真实文件存储**：当前只存文件名（photo_before/photo_after、attachment_json 存元数据），未做真实上传。本地可做（uploads 目录 + st.file_uploader），但 Streamlit Cloud 文件系统临时会重置，需外部存储（S3/对象存储 + 配置）才稳定——留待用户白天决定是否接。
2. **在线负责人列表**：紧急升级通知默认发全部 grid 角色（escalate_overdue_tasks 已预留 online_user_ids 参数）。Web 应用无长连接，心跳机制不精确，需额外架构——留待用户白天决定。
3. **跨模块联动 #9（政策通知与知识库版本更新联动）**：spec 要求「关联知识库更新时提示负责人处理」，「关联」规则在 spec 中未定义（知识库条目与政策通知无关联字段），实现需先澄清关联规则——留待用户白天定义。其余 10 个联动点均已实现（天气事件去重 / 检查任务清单匹配 / 紧急通知下架移除弹窗 / 老年草稿恢复 / SOS 状态刷新 / 用药审核期间原规则继续 / 暂停恢复对象 / 语音确认超时草稿 / 留痕模块来源 / 老年天气延迟提示）。

**其他已知限制（首版合理简化）**：匹配阈值/联动阈值存进程内（重启回默认）；投票防重复表对多账号不强制关联；附件只存文件名。

## 最终审查（完成）

- **27 个注册页面全部可加载**：init_db 后逐页 import 25/27 直接通过，dashboard.py / home.py 2 处裸环境误报（无 Streamlit session 时顶层代码访问会话对象），AppTest 实测居民端登录 + grid 端登录均**异常数 0**，确认运行时正常。
- 端到端验证链：app 启动 → 居民端登录（demo_resident）→ 渲染 → grid 端登录（demo_grid）→ 工作台渲染，全部通过。
- 7 模块核心闭环数据层冒烟验证全过；328 测试全绿；后台调度器随 app 启动。
- 遗留项（用户白天处理）：照片/附件真实存储（上云重置，需外部存储）、在线负责人列表（Web 无长连接）。

## 补充自查（完成）

- **「二次确认」类 spec 要求全覆盖**：紧急通知发布/定时二次确认、通知下架/删草稿、提案关闭/下架/查看手机号、工单特殊关闭/处理中改派/查看手机号、疾病预防下架/需线下就医/联动关闭重开、政策问答删草稿/下架、老年端 SOS/联系拨打确认 + 10 秒超时自动取消。
- **咨询处理人角色管理**（疾病预防压测修正）：`is_disease_prevention_manager` 按角色判断、`list_consult_handlers` 默认全部 grid、联动阈值/关闭/重开仅疾病预防负责人可操作（二次确认留痕）。
- **新模块持久化单元测试**：`tests/unit/test_new_modules.py` 10 个测试覆盖 7 模块核心闭环（报修闭环/提案匿名投票/通知发布/政策问答/老年端 SOS/天气检查/疾病预防），全量测试 338 passed。
