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


# ---------------- 新模块列表缓存（报修/提案/通知/天气/政策/健康，操作后由各页 invalidate） ----------------

@st.cache_data(ttl=15, show_spinner=False)
def cached_repair_issues(status=None, issue_type=None, category=None, reporter_id=None, limit=200):
    """报修工单列表（db_repair.get_issues）。"""
    from data.db_repair import get_issues as _get
    return _get(status=status, issue_type=issue_type, category=category,
                reporter_id=reporter_id, limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_repair_stats():
    from data.db_repair import get_issues as _get
    rows = _get(limit=1000)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get("status", "")] = by_status.get(r.get("status", ""), 0) + 1
    return {"total": len(rows), "by_status": by_status, "today_new": 0}


@st.cache_data(ttl=15, show_spinner=False)
def cached_proposals_full(status=None, limit=500):
    """提案全量列表（db_proposal.get_proposals）。"""
    from data.db_proposal import get_proposals as _get
    return _get(status=status, limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_notices_with_stats(notice_type=None, status=None, publish_scope=None, keyword=None, limit=200):
    """通知列表 + 已读统计。"""
    from data.db_notice import get_notices_with_stats as _get
    return _get(notice_type, status, publish_scope, keyword, limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_active_alerts():
    """当前生效的极端天气预警（居民端/负责人端/老年端共用）。"""
    from data.db_weather import get_active_alerts as _get
    return _get()


@st.cache_data(ttl=15, show_spinner=False)
def cached_weather_overview(limit=50):
    """负责人端天气概况。"""
    from data.db_weather import get_community_weather_overview as _get
    return _get(limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_check_tasks(status=None, limit=100):
    """天气检查任务列表。"""
    from data.db_weather import list_check_tasks as _get
    return _get(status=status, limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_check_task_history(alert_type=None, status=None, limit=200):
    """天气检查任务历史。"""
    from data.db_weather import get_check_task_history as _get
    return _get(alert_type=alert_type, status=status, limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_knowledge_list(status=None, category=None, search="", limit=300):
    """政策知识库列表。"""
    from data.db_policy import get_knowledge_list as _get
    return _get(status=status, category=category, search=search, limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_my_consults(user_id: int, limit=50):
    """居民我的健康咨询。"""
    from data.db_health_content import get_my_consults as _get
    return _get(user_id, limit=limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_consults(status=None, limit=100):
    """负责人端咨询列表。"""
    from data.db_health_content import list_consults as _get
    return _get(status=status, limit=limit)


# 失效：操作后调用，保证列表即时刷新

def invalidate_repair():
    """报修列表失效（审核/派单/处理/反馈/改分类等操作后）。"""
    cached_repair_issues.clear()
    cached_repair_stats.clear()
    cached_issues.clear()
    cached_issues_stats.clear()
    cached_my_issues.clear()
    cached_my_stats.clear()


def invalidate_proposals_full():
    """提案列表失效（db_proposal 侧）。"""
    cached_proposals_full.clear()
    cached_proposals.clear()
    cached_proposals_stats.clear()
    cached_my_proposals.clear()
    cached_my_stats.clear()


def invalidate_notices():
    """通知列表失效（发布/下架/编辑/置顶等操作后）。"""
    cached_notices_with_stats.clear()


def invalidate_weather():
    """天气数据失效（预警触发/确认/解除后）。"""
    cached_active_alerts.clear()
    cached_weather_overview.clear()
    cached_check_tasks.clear()
    cached_check_task_history.clear()


def invalidate_knowledge():
    """政策知识库失效（审核/编辑/下架/导出等操作后）。"""
    cached_knowledge_list.clear()


def invalidate_health():
    """健康内容/咨询失效。"""
    cached_my_consults.clear()
    cached_consults.clear()


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
    cached_repair_issues.clear()   # 报修状态机列表
    cached_repair_stats.clear()


def invalidate_proposals():
    """清掉提案相关缓存（含个人视图）。"""
    cached_proposals.clear()
    cached_proposals_stats.clear()
    cached_my_proposals.clear()
    cached_my_stats.clear()
    cached_proposals_full.clear()   # db_proposal 侧列表


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
