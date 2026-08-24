# -*- coding: utf-8 -*-
"""P1-1：Agent 会话 LRU 上限测试（_agent_orchs 防内存膨胀）。

隔离说明：不使用 module 级写 config.DB_PATH（会对同进程其他测试文件造成污染），
fixture 内建临时库并设置 db_core._DB_PATH，teardown 恢复原始值。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402
from types import SimpleNamespace  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """每个用例建临时库；teardown 恢复 db_core 全局路径（不与 config.DB_PATH 全局冲突）。"""
    _orig_db_path = db_core._DB_PATH
    _tmp = tempfile.mkdtemp(prefix="agent_lru_")
    _path = os.path.join(_tmp, "agent_lru.db")
    db_core._DB_PATH = ""
    if os.path.exists(_path):
        os.unlink(_path)
    db_core.init_db(_path)
    yield
    db_core._DB_PATH = _orig_db_path  # 恢复，而非置空


def _make_request():
    """构造带 .app.state._agent_orchs 的 request 代理（贴合 _get_orchestrator 的访问路径）。"""
    app = SimpleNamespace()
    app.state = SimpleNamespace()
    app.state._agent_orchs = {}
    req = SimpleNamespace()
    req.app = app
    return req


def test_new_session_created_on_miss():
    from api_routes.agent import _get_orchestrator
    req = _make_request()
    orch = _get_orchestrator(req, "resident:1")
    assert orch is not None
    assert "resident:1" in req.app.state._agent_orchs


def test_existing_session_reused():
    from api_routes.agent import _get_orchestrator
    req = _make_request()
    o1 = _get_orchestrator(req, "resident:1")
    o2 = _get_orchestrator(req, "resident:1")
    assert o1 is o2  # 同一用户复用同一实例


def test_lru_evicts_oldest_when_over_limit():
    from api_routes.agent import _get_orchestrator, _MAX_AGENT_SESSIONS
    req = _make_request()
    # 先建一批，把 last_active 压成递增
    for i in range(_MAX_AGENT_SESSIONS):
        o = _get_orchestrator(req, f"resident:{i}")
        o.last_active = i
    # 再插入一个超出上限的 → 淘汰 last_active 最小的（resident:0）
    o_new = _get_orchestrator(req, "grid:999")
    assert len(req.app.state._agent_orchs) <= _MAX_AGENT_SESSIONS
    assert "resident:0" not in req.app.state._agent_orchs  # 最旧被淘汰
    assert "grid:999" in req.app.state._agent_orchs  # 新会话进入
