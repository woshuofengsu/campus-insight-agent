"""数据库层统一出口，各个功能的 SQL 都拆在 data/ 下面的子模块里。

这里把所有函数再 re-export 一遍，老代码里 `from data.database import xxx`
的写法不用改也能继续用。

子模块：
  data.db_core      — 连接管理、上下文管理器、公共小工具
  data.db_user      — 用户资料增删改查
  data.db_knowledge — 知识库、反馈
  data.db_governance — 社区问题、提案、话题、意见
  data.db_sla       — SLA 时限与升级（直接 import，不在这里导出）
  data.db_dispatch  — 主动派单给网格员
  data.db_memory    — 跨会话事件记忆（直接 import）
  data.db_elderly   — 老人档案与安全（下面有 re-export）
  data.db_health    — 健康分统计、时间线
"""

from data.db_core import (
    init_db,
    get_connection,
    get_db,
)

from data.db_user import (
    authenticate,
    get_current_user,
    get_user_by_id,
    get_user_by_username,
    list_users,
    create_user,
    get_or_create_user,
    update_user_profile,
    set_onboarding_done,
    reset_onboarding,
    bind_elderly,
    unbind_elderly,
    get_bound_elderly,
)

from data.db_knowledge import (
    search_knowledge,
    get_knowledge_base,
    get_community_events,
    get_feedback_stats,
    add_feedback,
    get_feedback_by_topic,
    aggregate_feedback,
)

from data.db_governance import (
    report_issue,
    get_issues,
    get_issues_stats,
    get_my_issues,
    get_my_anonymous_issues,
    get_my_proposals,
    get_my_stats,
    update_issue_status,
    set_satisfaction,
    review_dissatisfaction,
    get_satisfaction_stats,
    get_dissatisfaction_reasons,
    create_proposal,
    get_proposals,
    support_proposal,
    update_proposal_status,
    get_proposals_stats,
    create_topic,
    get_active_topics,
    close_topic,
    increment_topic_participants,
    add_opinion,
    get_opinions_by_topic,
    get_opinion_summary,
    get_opinion_summaries_batch,
)

from data.db_health import (
    get_avg_resolution_days,
    get_recent_issue_counts,
    get_issues_timeline,
    compute_health_score,
)

from data.db_elderly import (
    get_profile as get_elderly_profile,
    set_health_info as set_elderly_health_info,
    set_medication_reminders as set_elderly_medication_reminders,
    set_emergency_contact as set_elderly_emergency_contact,
    touch_active as touch_elderly_active,
    get_inactive_elders,
    sos_request,
    get_pending_sos,
    mark_sos_done,
    due_reminders as get_due_reminders,
    get_care_reminders as get_elderly_care_reminders,
)
