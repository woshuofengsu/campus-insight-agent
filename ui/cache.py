# ui/cache.py
"""数据库重查询的缓存包装 — 用 st.cache_data 带 TTL。"""
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


# 清缓存别直接调 st.cache_data.clear()，用下面这些，
# 只刷新受影响的部分，别的缓存还能继续用。

def invalidate_issues():
    """清掉所有工单相关缓存（改状态、新工单等场景用）。"""
    cached_issues.clear()
    cached_issues_stats.clear()
    cached_issues_timeline.clear()
    cached_health_score.clear()
    cached_my_issues.clear()       # 个人的工单列表
    cached_my_stats.clear()        # 个人的统计


def invalidate_proposals():
    """清掉提案相关缓存（含个人视图）。"""
    cached_proposals.clear()
    cached_proposals_stats.clear()
    cached_my_proposals.clear()
    cached_my_stats.clear()


def invalidate_opinions(topic_id: int = 0):
    """清意见缓存（用户发表意见后调用）。

    注意：现在是把意见缓存整体清掉。topic_id 参数只是留着
    兼容接口，以后可以优化成只清对应议题的那条。
    """
    # TODO: 按议题粒度清缓存，用 cached_opinions_by_topic.clear(topic_id)
    cached_opinions_by_topic.clear()


def invalidate_content():
    """清知识库、议题、事件缓存（发内容后调用）。"""
    cached_knowledge_base.clear()
    cached_active_topics.clear()
    cached_community_events.clear()       # 通知/事件类内容发布后需要刷新
    cached_feedback_stats.clear()      # 反馈汇总可能关联新议题


def invalidate_all():
    """全量清空 — 只有重置引导时才用。"""
    st.cache_data.clear()
