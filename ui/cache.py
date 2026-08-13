# ui/cache.py
"""Cached wrappers for expensive database queries — uses st.cache_data with TTL."""
import streamlit as st

from data.database import (
    get_issues,
    get_issues_stats,
    get_issues_timeline,
    get_proposals,
    get_proposals_stats,
    get_active_topics,
    get_community_events,
    compute_health_score,
    get_opinions_by_topic,
    get_knowledge_base,
    get_feedback_stats,
    get_my_issues,
    get_my_proposals,
    get_my_stats,
)


@st.cache_data(ttl=30, show_spinner=False)
def cached_issues(category=None, status=None, urgency=None, limit=200):
    return get_issues(category=category, status=status, urgency=urgency, limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def cached_issues_stats():
    return get_issues_stats()


@st.cache_data(ttl=30, show_spinner=False)
def cached_issues_timeline(days=7):
    return get_issues_timeline(days)


@st.cache_data(ttl=30, show_spinner=False)
def cached_proposals(sort_by="supporters", limit=20):
    return get_proposals(sort_by=sort_by, limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def cached_proposals_stats():
    return get_proposals_stats()


@st.cache_data(ttl=30, show_spinner=False)
def cached_active_topics(limit=20):
    return get_active_topics(limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def cached_community_events(limit=10):
    return get_community_events(limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def cached_health_score():
    return compute_health_score()


@st.cache_data(ttl=60, show_spinner=False)
def cached_opinions_by_topic(topic_id: int, limit: int = 50):
    return get_opinions_by_topic(topic_id, limit=limit)


@st.cache_data(ttl=120, show_spinner=False)
def cached_knowledge_base(category: str = "", limit: int = 20):
    return get_knowledge_base(category=category, limit=limit)


@st.cache_data(ttl=60, show_spinner=False)
def cached_feedback_stats():
    return get_feedback_stats()


@st.cache_data(ttl=30, show_spinner=False)
def cached_my_issues(author: str, limit: int = 50):
    return get_my_issues(author, limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def cached_my_proposals(author: str, limit: int = 50):
    return get_my_proposals(author, limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def cached_my_stats(author: str):
    return get_my_stats(author)


# Use these instead of st.cache_data.clear() so only affected
# queries are refreshed, leaving unrelated caches warm.

def invalidate_issues():
    """Clear all issue-related caches (status change, new issue, etc.)."""
    cached_issues.clear()
    cached_issues_stats.clear()
    cached_issues_timeline.clear()
    cached_health_score.clear()
    cached_my_issues.clear()       # user's personal issue list
    cached_my_stats.clear()        # user's personal stats


def invalidate_proposals():
    """Clear all proposal-related caches (including personal views)."""
    cached_proposals.clear()
    cached_proposals_stats.clear()
    cached_my_proposals.clear()
    cached_my_stats.clear()


def invalidate_opinions(topic_id: int = 0):
    """Clear opinion caches (called after user submits an opinion).

    Note: currently clears the full opinion cache. The topic_id parameter is
    accepted for API compatibility — a future optimization could clear only
    the specific topic's cache entry.
    """
    # TODO: per-topic cache invalidation via cached_opinions_by_topic.clear(topic_id)
    cached_opinions_by_topic.clear()


def invalidate_content():
    """Clear knowledge-base, topic, and event caches (content publishing)."""
    cached_knowledge_base.clear()
    cached_active_topics.clear()
    cached_community_events.clear()       # 通知/事件类内容发布后需要刷新
    cached_feedback_stats.clear()      # 反馈汇总可能关联新议题


def invalidate_all():
    """Hard reset — use only for onboarding reset."""
    st.cache_data.clear()
