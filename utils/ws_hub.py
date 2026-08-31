# utils/ws_hub.py
"""轻量 WebSocket 连接池（P2-4 实时通知）。

前端网格员端连接 /ws/notify 注册；create_notification 落库后调用
broadcast() 向所有在线连接推送「有新通知」，前端收到即刷新通知列表，
替代 30 秒轮询。

设计：单进程内存连接池（演示/单机够用）；多进程/横向扩展时需换
Redis 发布订阅（见 docs/scaling.md 演进路径）。
"""
import asyncio
import logging

_log = logging.getLogger(__name__)

# 连接集合：set[WebSocket]
_clients: set = set()
_hub_lock = asyncio.Lock()


async def register(ws) -> None:
    """注册新连接。"""
    async with _hub_lock:
        _clients.add(ws)


async def unregister(ws) -> None:
    """移除连接。"""
    async with _hub_lock:
        _clients.discard(ws)


async def broadcast(message: str) -> int:
    """向所有在线连接推送消息。失败的连接自动剔除。返回送达数。"""
    if not _clients:
        return 0
    dead = []
    sent = 0
    for ws in list(_clients):
        try:
            await ws.send_text(message)
            sent += 1
        except Exception as e:  # noqa: BLE001
            _log.warning("WS 推送失败：%s", e)
            dead.append(ws)
    for ws in dead:
        await unregister(ws)
    return sent


def has_clients() -> bool:
    return len(_clients) > 0


def notify_sync(message: str = '{"type":"notify"}') -> None:
    """同步入口：供 data 层（无上下文）落库后广播刷新信号。

    用独立线程的事件循环执行广播，避免在主 event loop 已存在时
    asyncio.run 报错。无连接时快速返回（不起线程）。失败静默（演示级）。
    """
    if not has_clients():
        return
    import threading

    def _run():
        try:
            asyncio.run(broadcast(message))
        except Exception as e:  # noqa: BLE001
            _log.warning("WS 广播失败：%s", e)

    threading.Thread(target=_run, daemon=True).start()
