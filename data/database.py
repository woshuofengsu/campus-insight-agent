# data/database.py
"""Database layer — re-export hub.

All database functions are organized into focused submodules under data/.
This file re-exports everything for backward compatibility so existing
imports from `data.database` continue to work unchanged.

Submodules:
  data.db_core      — connection management, context manager, helpers
  data.db_user      — user profile CRUD
  data.db_knowledge — knowledge base, feedback items
  data.db_governance — community issues, proposals, topics, opinions
  data.db_sla       — SLA deadlines & escalation (imported directly, not re-exported)
  data.db_dispatch  — proactive auto-dispatch to grid workers
  data.db_memory    — cross-session event memory (imported directly)
  data.db_elderly   — elderly care profile & safety (re-exported below)
  data.db_health    — health score analytics, timelines
"""

# ── Core ──
from data.db_core import (
    init_db,
    get_connection,
    get_db,
)

# ── User ──
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
)

# ── Knowledge ──
from data.db_knowledge import (
    search_knowledge,
    get_knowledge_base,
    get_community_events,
    get_feedback_stats,
    add_feedback,
    get_feedback_by_topic,
    aggregate_feedback,
)

# ── Governance ──
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

# ── Health ──
from data.db_health import (
    get_avg_resolution_days,
    get_recent_issue_counts,
    get_issues_timeline,
    compute_health_score,
)

# ── Elderly care ──
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
