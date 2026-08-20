# tools/query_knowledge.py
"""社区知识检索 — 对接政策问答数据层（data/db_policy.py）。

只检索「已审核发布且未失效」的知识条目，自动回答优先引用「通俗解读」
并附「依据：XX政策（Vn）」；来源为社区整理的内容自动附带
「本指引由社区整理，仅供参考」标注。不再检索草稿/待审核/已下架内容。
"""
import logging
from langchain.tools import tool

_log = logging.getLogger(__name__)


def _published_search(query: str, top_k: int = 3,
                      category: str | None = None) -> list[dict]:
    """只检索已发布且未失效的条目（数据层实现），失败返回空列表。"""
    try:
        from data.db_policy import search_published_knowledge
        return search_published_knowledge(query, top_k=top_k, category=category)
    except Exception as e:
        _log.debug("search_published_knowledge 挂了: %s", e, exc_info=True)
        return []


def _render(results: list[dict], query: str, with_original: bool = False) -> str:
    """把检索结果格式化成 markdown（通俗解读 + 依据：XX政策）。"""
    from data.db_policy import format_knowledge_answer
    lines = [f"📚 **知识检索**：「{query}」相关条目：\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"**{i}. {r['title']}** `相关度 {r.get('score', 0):.2f}`\n"
            f"{format_knowledge_answer(r)}\n"
        )
        if with_original:
            body = (r.get("content") or "").strip()
            if body:
                lines.append(
                    f"📄 政策原文：\n{body[:500]}{'...' if len(body) > 500 else ''}\n"
                )
    return "\n".join(lines)


@tool
def query_knowledge(query: str) -> str:
    """搜索社区知识库——社区规章、办事指引、政策解读、通知、FAQ等。

    只检索已通过负责人审核发布且未失效的知识条目，自动回答优先引用「通俗解读」
    并附「依据：XX政策（版本号）」；社区整理内容附带「本指引由社区整理，仅供参考」。

    参数：
        query: 自然语言查询，如 "养老金怎么领取" 或 "高龄补贴需要什么材料"

    返回：最相关的知识库条目（通俗解读 + 依据），按相关度排序。
    """
    results = _published_search(query, top_k=3)
    if not results:
        return "暂未找到相关社区政策信息。建议您咨询社区居委会（62310001）或拨打12345，也可以转人工咨询。"
    return _render(results, query)


@tool
def get_community_policy(topic: str) -> str:
    """查询社区规章制度和政策的原文——用于AI回答需要引用规章的场景。

    与 query_knowledge 不同，本工具在通俗解读之外还会返回政策原文正文，
    只检索已发布且未失效的条目。

    参数：
        topic: 政策主题，如 "居民公约" 或 "物业收费标准"

    返回：相关政策通俗解读 + 依据 + 政策原文。
    """
    results = _published_search(topic, top_k=3)
    if not results:
        return f"未找到与「{topic}」相关的社区规章。"
    return _render(results, topic, with_original=True)
