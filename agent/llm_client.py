# agent/llm_client.py
"""统一 LLM 客户端（WS2）：熔断 + 超时 + 记账（成功与失败均落 llm_usage）。

设计原则：
- 任何异常都不抛：调用方按 `ok=False` 走规则兜底（不 500）。
- 熔断：连续失败 ≥ 阈值后，锁定窗口内直接快速失败，避免拖垮请求线程。
- 记账：成功记 tokens，失败记 0，duration 照记；**记账失败会懒初始化重试并以 warning 告警**
  （不再静默丢账——实测发现独立进程里 `get_db()` 未初始化会把用量整段丢掉）。
- 与外部解耦：配置从 config.py 读（DEEPSEEK_*），未配 key 时快速失败。

本模块是**新增/依赖 LLM 的调用点的统一入口**（政策 RAG、意图兜底、协商、润色）。
已存在的 LangChain 调用点（engine/planner/reflection/router/weekly_report）为 legacy 链路，
按评审意见不迁移（改无收益、测试面大）。
"""
import json
import logging
import threading
import time
import urllib.request

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

_log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_FAIL = {"n": 0, "open_until": 0.0}
_FAIL_THRESHOLD = 3
_OPEN_SECONDS = 60
_DEFAULT_TIMEOUT = 6
_RECORD_WARNED = False   # 记账失败只告警一次（避免刷屏）

# N5：LLM 输入长度上限（防登录用户发超长文本刷输入 token）
_MAX_SINGLE_MSG = 2000
_MAX_TOTAL_MSGS = 20000


def _clamp_messages(messages):
    """截断超长消息：单条 ≤2000 字、总长 ≤20000 字（统一入口防线）。"""
    total = 0
    out = []
    for m in messages:
        if isinstance(m, dict) and isinstance(m.get("content"), str):
            c = m["content"]
            if len(c) > _MAX_SINGLE_MSG:
                c = c[:_MAX_SINGLE_MSG]
            total += len(c)
            if total > _MAX_TOTAL_MSGS:
                c = c[: max(0, _MAX_TOTAL_MSGS - (total - len(c)))]
                total = _MAX_TOTAL_MSGS
            out.append({"role": m.get("role", "user"), "content": c})
        else:
            out.append(m)
    return out


def chat(messages, *, module, purpose="", temperature=0.2, max_tokens=512,
         timeout=_DEFAULT_TIMEOUT, response_format=None, uid=None):
    """统一 LLM 调用。

    返回 dict(ok, text, raw, tokens_in, tokens_out, duration_ms, error)。
    - 熔断：连续失败 ≥_FAIL_THRESHOLD 后，_OPEN_SECONDS 内直接快速失败。
    - 无 key：快速失败（ok=False, error='no_key'）。
    - 成功/失败均写 llm_usage（失败 token=0，module/purpose 可溯源）。
    """
    messages = _clamp_messages(messages)  # N5：入口统一截断超长文本
    now = time.time()
    if not DEEPSEEK_API_KEY:  # 无 key 是永久条件，优先于瞬态熔断
        return {"ok": False, "error": "no_key", "text": "", "raw": None,
                "tokens_in": 0, "tokens_out": 0, "duration_ms": 0}
    if now < _FAIL["open_until"]:
        return {"ok": False, "error": "circuit_open", "text": "", "raw": None,
                "tokens_in": 0, "tokens_out": 0, "duration_ms": 0}

    payload = {"model": DEEPSEEK_MODEL or "deepseek-chat",
               "messages": messages,
               "temperature": temperature,
               "max_tokens": max_tokens}
    if response_format:
        payload["response_format"] = response_format

    body = json.dumps(payload).encode("utf-8")
    url = f"{(DEEPSEEK_BASE_URL or 'https://api.deepseek.com/v1').rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dt = int((time.time() - t0) * 1000)
        txt = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        u = data.get("usage", {})
        ti, to = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
        with _LOCK:
            _FAIL.update(n=0, open_until=0.0)
        _record(module, ti, to, dt, purpose, uid)
        return {"ok": True, "text": txt, "raw": data,
                "tokens_in": ti, "tokens_out": to, "duration_ms": dt, "error": None}
    except Exception as e:
        dt = int((time.time() - t0) * 1000)
        with _LOCK:
            _FAIL["n"] += 1
            if _FAIL["n"] >= _FAIL_THRESHOLD:
                _FAIL["open_until"] = time.time() + _OPEN_SECONDS
        _log.warning("llm call fail(module=%s): %s", module, e)
        _record(module, 0, 0, dt, purpose, uid)
        return {"ok": False, "error": str(e)[:120], "text": "", "raw": None,
                "tokens_in": 0, "tokens_out": 0, "duration_ms": dt}


def reset_circuit():
    """重置熔断器（测试/故障恢复用）。"""
    with _LOCK:
        _FAIL.update(n=0, open_until=0.0)


def _record(module, ti, to, dt, purpose, uid):
    """写用量记账。**不允许静默丢账**（本轮修）。

    背景（实测发现的真 BUG）：记账走 `data.db_llm_usage.record_usage` → `get_db()`，
    而 `get_db()` 在**没有调用过 `init_db()` 的进程里**会抛
    `RuntimeError: Database not initialized`。原实现用 `_log.debug` 吞掉这个异常，
    结果是：脚本 / 扣子插件入口 / 任何独立进程里 **LLM 调用真的发生了、钱真的花了，
    但 llm_usage 一条记录都没有** —— 直接打穿"成本可现场复算"这个对外主张。

    现在的策略：① 失败时**懒初始化一次**再重试；② 仍失败则以 **warning** 明确告警（每次进程只喊一次）。
    """
    global _RECORD_WARNED
    try:
        from data.db_llm_usage import record_usage
        record_usage(module, ti, to, dt, input_preview=(purpose or "")[:80])
        return
    except Exception as e:  # noqa: BLE001
        first_err = e
    try:  # ① 懒初始化（独立进程/脚本/插件入口的常见情况）
        import config
        from data.db_core import init_db
        init_db(config.DB_PATH)
        from data.db_llm_usage import record_usage as _ru
        _ru(module, ti, to, dt, input_preview=(purpose or "")[:80])
        return
    except Exception as e2:  # noqa: BLE001
        if not _RECORD_WARNED:
            _RECORD_WARNED = True
            _log.warning("LLM 用量记账失败（本次调用仍已发生、成本已产生）：%s / 懒初始化后：%s",
                         first_err, e2)
