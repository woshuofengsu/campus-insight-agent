# agent/policy_rag.py
"""政策真 RAG（WS3）：仅基于检索到的已发布知识片段生成，强制结构化引用。

防幻觉（相较"在自由文本里找标题子串"更强）：
- LLM 必须返回 JSON：{"answer": "...", "cited_index": <整数 1..N>}，即"引用第几条材料"。
- `cite_index` 必须是检索结果集内的合法下标；否则整条弃用，回退人工。
- 引用标题由调用方从数据库真实行拼装（而非让模型复述标题），杜绝标题子串伪造。
- 零结果（not results）绝不生成 → 维持原 `no_knowledge` 转人工（防幻觉底线）。
- 材料不足时模型只输出 INSUFFICIENT → 弃用。

开关：POLICY_LLM_RAG=1 才走真实 LLM；关闭/无 key/失败 → 返回 None（调用方回退原逻辑）。
"""
import json

from config import POLICY_LLM_RAG

_SYS = (
    "你是社区政策问答助手。只能依据【材料】回答，不得使用材料外知识，不得给医疗/法律诊断结论。"
    "若材料不足以回答，只输出 INSUFFICIENT。"
    "必须输出 JSON（不要多字）：{\"answer\": \"回答正文\", \"cited_index\": <整数，引用第几条材料，从1计>}。"
    "answer 用不超过 200 字的口语化中文，仅基于所引用的那一条材料。"
)

_MAX_CTX = 5


def _context(results):
    blocks = []
    for i, e in enumerate(results[:_MAX_CTX], 1):
        body = (e.get("plain_interpretation") or e.get("summary") or e.get("content") or "")[:600]
        blocks.append(f"[{i}] 标题：{e.get('title')}（V{e.get('version') or 1}）\n正文：{body}")
    return "\n\n".join(blocks)


def generate(question, results):
    """生成 {answer, cited_index, cited_title, tokens_in, tokens_out}；失败/不合规返回 None。"""
    if not POLICY_LLM_RAG or not results:
        return None
    from agent.llm_client import chat
    ctx = _context(results)
    r = chat(
        [{"role": "system", "content": _SYS},
         {"role": "user", "content": f"【材料】\n{ctx}\n\n【问题】{question}"}],
        module="policy_rag", purpose=question[:60],
        temperature=0.1, max_tokens=500, timeout=8,
        response_format={"type": "json_object"},
    )
    if not r["ok"]:
        return None
    text = r["text"].strip()
    if not text or "INSUFFICIENT" in text[:60]:
        return None
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    ans = (obj.get("answer") or "").strip()
    idx = obj.get("cited_index")
    # H4 修复：兼容 int 与数字字符串下标（如 "2"），拒绝 bool/None/非法值
    if not ans or isinstance(idx, bool):
        return None
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return None
    if idx < 1 or idx > len(results[:_MAX_CTX]):
        return None  # 引用下标越界 → 弃用（防伪造）
    cited = results[idx - 1]
    return {"answer": ans, "cited_index": idx,
            "cited_title": cited.get("title") or "",
            "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"]}
