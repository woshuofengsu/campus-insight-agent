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

- 报修收尾（工具+UI）
- 提案模块
- 老年端
- 政策问答
- 通知发布
- 天气 + 疾病预防
