# utils/tracing.py
"""链路追踪（P2-F4-01）：request_id 生成与上下文传递。

FastAPI 中间件为每个请求生成/透传 X-Request-ID，写入 contextvar；
数据层 log_activity / log_agent 通过 get_trace_id() 读取并落库，实现
「一次用户操作 → 一条 trace_id → 业务留痕 / Agent 留痕 / 异常日志」串联。
"""
import contextvars
import uuid

_trace_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def new_trace_id() -> str:
    """生成 trace_id：短 UUID（便于日志与 URL 使用）。"""
    return uuid.uuid4().hex[:16]


def set_trace_id(tid: str) -> None:
    _trace_ctx.set(tid or "")


def get_trace_id() -> str:
    return _trace_ctx.get()


def clear_trace_id() -> None:
    _trace_ctx.set("")
