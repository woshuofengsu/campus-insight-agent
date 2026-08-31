# -*- coding: utf-8 -*-
"""WS2：统一 LLM 客户端测试（全部离线，monkeypatch urlopen，不发真实网络请求）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.llm_client as lc


def _patch_key(monkeypatch, value="test-api-key"):
    monkeypatch.setattr("agent.llm_client.DEEPSEEK_API_KEY", value)


def _fake_urlopen(monkeypatch, payload_fn):
    """替换 urllib.request.urlopen；payload_fn 接受已解码的 JSON，返回 (resp_bytes, usage)。"""
    def _patch(*a, **k):
        # 读取请求体以模拟不同响应
        import json as _j
        req = a[0]
        body = _j.loads(req.data.decode("utf-8"))
        content, usage = payload_fn(body)
        resp_bytes = _j.dumps({
            "choices": [{"message": {"content": content}}],
            "usage": usage,
        }).encode("utf-8")

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return resp_bytes

            def __iter__(self):
                return iter([resp_bytes])

        return _R()
    monkeypatch.setattr("urllib.request.urlopen", _patch)


def test_chat_success_and_records(monkeypatch):
    _patch_key(monkeypatch)
    calls = []
    monkeypatch.setattr("agent.llm_client._record", lambda *a, **k: calls.append((a, k)))

    def _payload(body):
        return "你好，社区", {"prompt_tokens": 100, "completion_tokens": 20}

    _fake_urlopen(monkeypatch, _payload)
    r = lc.chat([{"role": "user", "content": "hi"}], module="test_mod", purpose="p")
    assert r["ok"] is True
    assert r["text"] == "你好，社区"
    assert r["tokens_in"] == 100 and r["tokens_out"] == 20
    assert r["error"] is None
    assert calls, "应记账"
    assert calls[0][0][0] == "test_mod"
    assert lc.chat.__doc__  # 确保可调用


def test_chat_failure_ok_false_no_raise(monkeypatch):
    _patch_key(monkeypatch)
    monkeypatch.setattr("agent.llm_client._record", lambda *a, **k: None)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    r = lc.chat([{"role": "user", "content": "hi"}], module="m")
    assert r["ok"] is False
    assert r["error"]
    assert r["text"] == ""
    r2 = lc.chat([{"role": "user", "content": "hi"}], module="m")
    assert r2["ok"] is False  # 连续失败不抛异常


def test_chat_circuit_opens_after_threshold(monkeypatch):
    _patch_key(monkeypatch)
    monkeypatch.setattr("agent.llm_client._record", lambda *a, **k: None)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    lc.reset_circuit()
    for _ in range(3):
        r = lc.chat([{"role": "user", "content": "hi"}], module="m")
        assert r["ok"] is False
    # 达到阈值后应进入熔断：即使网络恢复也被快速拒绝
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: None)
    r = lc.chat([{"role": "user", "content": "hi"}], module="m")
    assert r["ok"] is False and r["error"] == "circuit_open"


def test_chat_no_key_fast_fail(monkeypatch):
    _patch_key(monkeypatch, "")
    monkeypatch.setattr("agent.llm_client._record", lambda *a, **k: None)
    r = lc.chat([{"role": "user", "content": "hi"}], module="m")
    assert r["ok"] is False and r["error"] == "no_key"
