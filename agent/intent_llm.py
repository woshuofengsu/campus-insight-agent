# agent/intent_llm.py
"""接待员 LLM 二级意图兜底（WS4）：规则未命中才触发，且限定白名单输出。

防误判：
- 白名单闭集输出——模型只能从不允许集合里选一个，别的一律视为未识别。
- 开关默认关（RECEPTION_LLM_FALLBACK=1 才启用）；无 key / 熔断 / 异常 → 返回 None。
- 仅输出一个词，temperature=0.0，max_tokens 极小（8），进不了长篇输出。
"""
from config import RECEPTION_LLM_FALLBACK

# 与 web_agent.detect_intent 词表对齐的闭集（只允许这些中文意图）
_ALLOWED = {"报修", "提案", "政策问答", "通知查询", "天气查询", "身体不适", "联系社区", "使用帮助"}


def llm_intent(text: str, role: str = "resident"):
    """白名单判别：返回一个中文意图；无法判定/未启用/失败 → None。"""
    if not RECEPTION_LLM_FALLBACK:
        return None
    from agent.llm_client import chat
    r = chat(
        [{"role": "system", "content":
          "判断用户诉求意图。只输出一个词，且必须在候选里选："
          + "、".join(_ALLOWED) + "。无法判断时输出「未识别」。不输出别的字。"},
         {"role": "user", "content": text[:120]}],
        module="intent_fallback", purpose=text[:40],
        temperature=0.0, max_tokens=8, timeout=3,
    )
    if not r["ok"]:
        return None
    t = r["text"].strip("。.，,、 ")
    # 白名单闭集：碰到闭集外 → 未识别
    if t == "未识别":
        return None
    return t if t in _ALLOWED else None
