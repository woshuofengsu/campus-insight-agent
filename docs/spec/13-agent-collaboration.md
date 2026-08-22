# 13-Agent 协作增强（适配版：主动协商 / 冲突仲裁 / 幻觉防线 / 无缝转人工）

> 依据四份完善版设计落地，并按本项目（FastAPI+Vue3，零第三方依赖，规则引擎为主 + LLM 可选）
> 适配。代码：`agent/blackboard.py` / `agent/arbiter.py` / `agent/verifier.py` / `agent/orchestrator.py` /
> `agent/roles/*`；表：v30 agent_dialogs+agent_logs、v31 agent_sessions、v32 agent_handoffs。

## 一、主动协商

- 事件触发：业务 Agent 处理中发现需协助立即 `post_message`（如天气守护员发现极端天气 → 通知健康顾问/通知管理员；健康顾问遇疑似紧急症状 → handoff 接待员）。
- 定时触发：调度器（scripts/scheduler.py）驱动天气/联动/超时等自动任务（复用现有调度，不引入 APScheduler）。
- 消息协议：`{from,to,type(task_request/task_response/notify/error/handoff),priority(high/normal/low),payload,timestamp}`。
- 优先级队列：orchestrator 按 priority 排序处理目标收件箱；协商结果并入回复（协作提示），发起方消息留黑板。
- 超时/重试：`_call_agent` 超时重试一次；仍失败降级转人工。
- 循环防护：同目标累计协商 >2 轮强制转人工（`negotiation:{target}` 计数）。

## 二、冲突仲裁（agent/arbiter.py）

规则顺序：合规优先（审计失败→block）→ 安全优先（人身安全→human）→ 专业优先（采纳专业 Agent）
→ 人工优先（费用/不可逆→human）→ 数据一致（版本冲突→最新版）→ 默认保守（转人工）。
接入点：Verifier block 重试仍失败、合规审计失败 → 仲裁 → block/human/transferred_to_human；裁决写入执行链「⚖️冲突仲裁」节点。

## 三、LLM 幻觉防线（agent/verifier.py）

统一校验器按业务类型选规则集：通用（空输出/敏感词/手机号/身份证/乱码/超长）+ 政策（引用强制，
无引用不回答）+ 健康（不诊断/不荐药/紧急症状提示就医）+ 网格（不代替审批/导出脱敏）。判定 PASS/WARN/BLOCK；
BLOCK 重试一次仍失败 → 仲裁/转人工；WARN 降级安全回答；结果写黑板 verify_result，执行链「🔍校验」节点。
适配说明：离线规则引擎输出天然来自数据库（无幻觉），Verifier 是 LLM 链路强制防线 + 全输出统一挂链（无绕过路径）。

## 四、无缝转人工（agent_handoffs v32）

触发（T1-T10 中已接入 5 类）：T1 政策无引用 / T2 健康紧急症状 / T6 用户主动转人工 /
T7 合规审计不通过 / T8 仲裁失败（Verifier block → human）。
处理包 `{session_id,user(脱敏),original_input,intent,collected_fields(黑板草稿),execution_chain,
pending_issues,recent_history(5条),verification_result}`：
- 生成 → 合规审计脱敏检查（含完整手机号/身份证则移除敏感字段）→ 落 `agent_handoffs` → 通知 grid 消息中心。
- 负责人：`GET /api/web/agent/handoffs` 列表（含上下文摘要）、`POST .../{id}/resolve` 处理完成；
  AI 助手说「查处理包」直接返回待办列表（AI 已整理上下文，无需重新询问用户）。
- 用户端：回复附「已为您转接工作人员，他们会直接联系您，不用重新说一遍」+ 查看消息入口。
- 留痕：negotiation 节点（「转人工」原因）+ agent_logs。

## 五、执行链可视化

前端 AgentChat 渲染 `execution_chain`：角色节点（灰）+ 校验（蓝/绿/黄/红按动作）+ 协商（紫）+ 仲裁（橙）+ 审计（青），
答辩可直接演示「接待员→业务Agent→校验→协商→仲裁→审计」完整链路。

## 六、测试

`tests/test_agent.py` 26 项（含协商天气→健康、胸痛 handoff、仲裁 block/安全/默认、循环防护 2 轮转人工、
政策无引用转人工、用户主动转人工、处理包查询/处理、幻觉规则 通用/政策/健康/网格）；
`tests/test_security.py` 8 项。全量 pytest 394 passed。
