# tools/query_knowledge.py
"""社区知识检索 — 字符 n-gram TF-IDF 检索社区规章、活动安排、办事指南、FAQ 等信息。

升级自原来的 SQL LIKE 关键词匹配，现在使用字符 n-gram TF-IDF
检索，通过字符重叠度匹配近似表达，而非仅精确关键词。

例如："电梯几点检修" 能匹配到 "电梯检修时间安排" 条目，
即使"检修"和"时间安排"没有共同关键词。
"""
import logging
from langchain.tools import tool
from agent.rag import semantic_search, rag_search, get_rag_context

_log = logging.getLogger(__name__)


@tool
def query_knowledge(query: str) -> str:
    """搜索社区知识库——社区规章、活动安排、办事指南、通知、FAQ等。

    使用字符 n-gram TF-IDF 检索，通过字符重叠度匹配近似表达（如"检修"可匹配"时间安排"），
    不限于精确关键词匹配。
    适合回答：社区规章、办事流程、电梯检修/垃圾清运时间、活动安排等。

    参数：
        query: 自然语言查询，如 "电梯检修时间" 或 "垃圾分类驿站位置"

    返回：最相关的知识库条目，按相关度排序。
    """
    try:
        return rag_search(query, top_k=5)
    except Exception as e:
        _log.debug("rag_search failed: %s", e, exc_info=True)
        return f"⚠️ 社区知识搜索暂不可用：{e}\n请稍后重试。"


@tool
def get_community_policy(topic: str) -> str:
    """查询社区规章制度和政策的原文——用于AI回答需要引用规章的场景。

    与 query_knowledge 不同，本工具专注于 governance 和 notice 类别的
    官方信息，会返回完整的政策原文，适合需要"引用社区规章原文回答"的场景。

    参数：
        topic: 政策主题，如 "居民公约" 或 "物业收费标准"

    返回：相关政策原文 + 相关度评分。
    """
    try:
        results = semantic_search(topic, top_k=3, category="governance")
        if not results:
            results = semantic_search(topic, top_k=3)
        if not results:
            return f"未找到与「{topic}」相关的社区规章。"
        lines = [f"📋 **规章检索**：「{topic}」相关条目：\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"**{i}. {r['title']}** `相关度 {r.get('score', 0):.2f}`\n{r['content']}\n")
        return "\n".join(lines)
    except Exception as e:
        _log.debug("semantic_search (get_community_policy) failed: %s", e, exc_info=True)
        return f"⚠️ 规章检索暂不可用：{e}"
