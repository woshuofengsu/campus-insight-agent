# data/database.py
"""Database layer — re-export hub.

All database functions are organized into focused submodules under data/.
This file re-exports everything for backward compatibility so existing
imports from `data.database` continue to work unchanged.

Submodules:
  data.db_core      — connection management, context manager, helpers
  data.db_user      — user profile CRUD
  data.db_academic  — courses, exams, events, club activities
  data.db_knowledge — knowledge base, feedback items
  data.db_governance — campus issues, proposals, topics, opinions
  data.db_health    — health score analytics, timelines
"""

# ── Core ──
from data.db_core import (
    init_db,
    get_connection,
    get_db,
    resolve_author,
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

# ── Academic ──
from data.db_academic import (
    get_courses,
    get_today_courses,
    add_course,
    delete_course,
    get_exams,
    add_exam,
    get_upcoming_exams,
    get_events,
    create_event,
    get_overdue_reminders,
    check_conflict,
    get_club_activities,
    get_activities_by_tags,
)

# ── Knowledge ──
from data.db_knowledge import (
    search_knowledge,
    get_knowledge_base,
    get_campus_events,
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
    get_my_proposals,
    get_my_stats,
    update_issue_status,
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
