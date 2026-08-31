# -*- coding: utf-8 -*-
"""WS4：接待员 LLM 二级意图兜底测试（离线，monkeypatch agent.llm_client.chat）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.intent_llm as il
from agent.blackboard import Blackboard
from agent.roles.receptionist import ReceptionistAgent


def _set_switch(monkeypatch, on):
    monkeypatch.setattr("config.RECEPTION_LLM_FALLBACK", on)
    monkeypatch.setattr("agent.intent_llm.RECEPTION_LLM_FALLBACK", on)


def _chat_ok(text):
    def _chat(*a, **k):
        return {"ok": True, "text": text, "tokens_in": 1, "tokens_out": 1}
    return _chat


def test_llm_intent_off_returns_none(monkeypatch):
    _set_switch(monkeypatch, False)
    assert il.llm_intent("楼上往下渗水好几天没人管") is None


def test_llm_intent_valid(monkeypatch):
    _set_switch(monkeypatch, True)
    monkeypatch.setattr("agent.llm_client.chat", _chat_ok("政策问答"))
    assert il.llm_intent("那个补助的事我想问一下") == "政策问答"


def test_llm_intent_whitelist_rejects(monkeypatch):
    _set_switch(monkeypatch, True)
    monkeypatch.setattr("agent.llm_client.chat", _chat_ok("帮我写诗"))
    assert il.llm_intent("帮我写首诗") is None  # 白名单外 → 未识别


def test_llm_intent_failure_returns_none(monkeypatch):
    _set_switch(monkeypatch, True)
    def _fail(*a, **k):
        return {"ok": False, "error": "no_key", "text": ""}
    monkeypatch.setattr("agent.llm_client.chat", _fail)
    assert il.llm_intent("随便说点什么") is None


def test_reception_routes_to_policy_via_llm(monkeypatch):
    """开关开 + 规则未命中 + LLM 命中 → 路由 policy，并标记 intent_via=llm。"""
    _set_switch(monkeypatch, True)
    monkeypatch.setattr("agent.web_agent.detect_intent", lambda text, role=None: None)
    monkeypatch.setattr("agent.llm_client.chat", _chat_ok("政策问答"))
    bb = Blackboard()
    ctx = {"role": "resident", "uid": 99991, "name": "测试",
           "user_input": "补贴的申请流程我不太清楚", "state": {}}
    r = ReceptionistAgent(bb).process(ctx)
    assert r["status"] == "routed", r
    assert r["intent"] == "policy", r
    assert ctx["state"].get("intent_via") == "llm"


def test_reception_unknown_when_llm_off(monkeypatch):
    """开关关 + 规则未命中 → 保持未知意图（不误路由）。"""
    _set_switch(monkeypatch, False)
    monkeypatch.setattr("agent.web_agent.detect_intent", lambda text, role=None: None)
    bb = Blackboard()
    ctx = {"role": "resident", "uid": 99991, "name": "测试",
           "user_input": "补贴的申请流程我不太清楚", "state": {}}
    r = ReceptionistAgent(bb).process(ctx)
    assert r["status"] == "成功" and r["intent"] == "未知意图"
    assert ctx["state"].get("intent_via") is None
