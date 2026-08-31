# -*- coding: utf-8 -*-
"""P2-4：ws_hub 广播核心逻辑测试（同进程注册连接 + 广播送达断言）。
用 asyncio.run 驱动，避免额外依赖 pytest-asyncio。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import ws_hub  # noqa: E402


class _FakeWS:
    """模拟 WebSocket：记录 send_text 收到的消息。"""

    def __init__(self):
        self.sent: list = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def _run(coro):
    return asyncio.run(coro)


def test_register_and_broadcast():
    fw = _FakeWS()

    async def scenario():
        await ws_hub.register(fw)
        assert ws_hub.has_clients()
        sent = await ws_hub.broadcast('{"type":"notify"}')
        assert sent == 1
        assert fw.sent and fw.sent[-1] == '{"type":"notify"}'
        await ws_hub.unregister(fw)
        assert not ws_hub.has_clients()
        assert await ws_hub.broadcast("x") == 0

    _run(scenario())


def test_unregister_removes():
    fw = _FakeWS()

    async def scenario():
        await ws_hub.register(fw)
        await ws_hub.unregister(fw)
        assert not ws_hub.has_clients()
        assert await ws_hub.broadcast("y") == 0

    _run(scenario())


def test_notify_sync_skips_when_no_client():
    """无连接时 notify_sync 立即返回（不起线程，不抛异常）。"""
    assert not ws_hub.has_clients()
    ws_hub.notify_sync()
