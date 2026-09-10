# utils/embedding.py
"""文本向量化 Provider 抽象（U1 混合检索）——零依赖降级设计。

EMBEDDING_PROVIDER 取值：
  - `none`（默认）：不使用语义向量，检索走纯词法（**行为与升级前完全一致**，零风险）
  - `bailian`：阿里云百炼 text-embedding-v3（读 DASHSCOPE_API_KEY）
  - `zhipu`：智谱 embedding-3（读 ZHIPU_API_KEY）

设计原则（「降级即设计」）：
  1. 默认关闭；未配 key / 网络失败 / 额度耗尽 → `is_enabled()` 为 False 或
     `embed_texts()` 返回 None，调用方自动回退词法检索，**绝不抛异常中断业务**。
  2. 查询向量进程内缓存（同 query 不重复计费）；文档向量落 SQLite（见 rag.py）。
  3. 只用 `requests`（项目已有依赖），不引入向量库/重依赖。
"""
import logging
import threading

_log = logging.getLogger(__name__)

# 查询向量进程内缓存（LRU 简化版：dict + 上限淘汰）
_QUERY_CACHE: dict[str, list[float]] = {}
_QUERY_CACHE_MAX = 512
_cache_lock = threading.Lock()

# 每批嵌入条数（百炼/智谱单请求均支持批量，保守取 10）
_BATCH = 10


def get_provider() -> str:
    """当前 provider（none/bailian/zhipu）。"""
    try:
        from config import EMBEDDING_PROVIDER
        return (EMBEDDING_PROVIDER or "none").lower()
    except Exception:
        return "none"


def get_model() -> str:
    """当前嵌入模型名（按 provider 给默认值，可用 EMBEDDING_MODEL 覆盖）。"""
    try:
        from config import EMBEDDING_MODEL
        if EMBEDDING_MODEL:
            return EMBEDDING_MODEL
    except Exception:
        pass
    return {"bailian": "text-embedding-v3", "zhipu": "embedding-3"}.get(get_provider(), "")


def get_api_key() -> str:
    """当前 provider 对应的 key（未配返回空串）。"""
    p = get_provider()
    try:
        from config import DASHSCOPE_API_KEY, ZHIPU_API_KEY
    except Exception:
        return ""
    return {"bailian": DASHSCOPE_API_KEY, "zhipu": ZHIPU_API_KEY}.get(p, "") or ""


def is_enabled() -> bool:
    """语义向量是否可用（provider 非 none 且 key 已配）。"""
    return get_provider() in ("bailian", "zhipu") and bool(get_api_key())


def _endpoint() -> str:
    return {
        "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4/embeddings",
    }.get(get_provider(), "")


def _post_batch(texts: list[str]) -> list[list[float]] | None:
    """单批嵌入请求；失败返回 None（由上层降级）。"""
    import requests
    provider = get_provider()
    body = {"model": get_model(), "input": texts}
    if provider == "bailian":
        body["encoding_format"] = "float"
    try:
        resp = requests.post(
            _endpoint(), json=body, timeout=15,
            headers={"Authorization": f"Bearer {get_api_key()}",
                     "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            _log.warning("embedding 请求失败（%s %s）：%s", provider, resp.status_code, resp.text[:200])
            return None
        data = resp.json().get("data") or []
        # 按 index 排序，保证与输入顺序一致
        data = sorted(data, key=lambda d: d.get("index", 0))
        vecs = [d.get("embedding") for d in data]
        if len(vecs) != len(texts) or any(v is None for v in vecs):
            _log.warning("embedding 返回条数不匹配：期望 %d 实际 %d", len(texts), len(vecs))
            return None
        return vecs
    except Exception as e:  # noqa: BLE001
        _log.warning("embedding 调用异常（%s）：%s", provider, e)
        return None


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """批量嵌入。不可用时返回 None（调用方回退词法），绝不抛异常。"""
    if not texts or not is_enabled():
        return None
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i:i + _BATCH]
        vecs = _post_batch(batch)
        if vecs is None:
            return None
        out.extend(vecs)
    return out


def embed_query(text: str) -> list[float] | None:
    """查询嵌入（带进程内缓存，同 query 不重复计费）。不可用返回 None。"""
    if not text or not is_enabled():
        return None
    key = text.strip()
    with _cache_lock:
        hit = _QUERY_CACHE.get(key)
    if hit is not None:
        return hit
    vecs = embed_texts([key])
    if not vecs:
        return None
    vec = vecs[0]
    with _cache_lock:
        if len(_QUERY_CACHE) >= _QUERY_CACHE_MAX:
            _QUERY_CACHE.clear()  # 简化淘汰：满则清空（演示级，避免内存无界）
        _QUERY_CACHE[key] = vec
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    """两向量余弦相似度（维度不一致或空向量返回 0）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def describe() -> dict:
    """当前向量化配置（供健康度端点/自检脚本展示）。"""
    return {"provider": get_provider(), "model": get_model(),
            "enabled": is_enabled(), "has_key": bool(get_api_key())}
