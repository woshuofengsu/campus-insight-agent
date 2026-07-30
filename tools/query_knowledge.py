# tools/query_knowledge.py
"""校园百科 RAG — 语义搜索学校规章制度、校历、FAQ 等信息。

升级自原来的 SQL LIKE 关键词匹配，现在使用字符 n-gram TF-IDF
语义搜索引擎，能理解问题意图而不仅仅是匹配关键词。

例如："食堂几点关门" 能匹配到 "食堂营业时间" 条目，
即使"关门"和"营业时间"没有共同关键词。
"""
from langchain.tools import tool
from agent.rag import semantic_search, rag_search, get_rag_context


@tool
def query_knowledge(query: str) -> str:
    """搜索校园百科知识库——学校规章制度、校历、通知、FAQ等。

    使用语义搜索（RAG），能理解问题的真正意图，不限于精确关键词匹配。
    适合回答：校规政策、办事流程、食堂/图书馆营业时间、校历安排等。

    参数：
        query: 自然语言查询，如 "食堂营业时间" 或 "奖学金申请条件"

    返回：最相关的知识库条目，按语义相关度排序。
    """
    try:
        return rag_search(query, top_k=5)
    except Exception as e:
        return f"⚠️ 校园百科搜索暂不可用：{e}\n请稍后重试。"


@tool
def get_school_policy(topic: str) -> str:
    """查询学校规章制度和政策的原文——用于AI回答需要引用校规的场景。

    与 query_knowledge 不同，本工具专注于 governance 和 notice 类别的
    官方信息，会返回完整的政策原文，适合需要"引用校规原文回答"的场景。

    参数：
        topic: 政策主题，如 "宿舍管理规定" 或 "奖学金评定办法"

    返回：相关政策原文 + 语义相关度评分。
    """
    try:
        results = semantic_search(topic, top_k=3, category="governance")
        if not results:
            results = semantic_search(topic, top_k=3)
        if not results:
            return f"未找到与「{topic}」相关的校规政策。"
        lines = [f"📋 **校规检索**：「{topic}」相关条目：\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"**{i}. {r['title']}** `相关度 {r.get('score', 0):.2f}`\n{r['content']}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ 校规检索暂不可用：{e}"
