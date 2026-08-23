# -*- coding: utf-8 -*-
"""P1-C1-01 NLU 增强测试：方言归一化 / 指代消解 / 否定与模糊处理（5+ 条语义）。

评审要求：NLU 仍规则级（无方言/指代/否定）→ 本轮补规则兜底 + 语义回归。
- 单元：web_agent.normalize_dialect / resolve_reference / extract_negation_target / nlu_preprocess
- 端到端：receptionist + orchestrator 话题切换（/api/web/agent/chat）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

_tmp = tempfile.mkdtemp(prefix="nlu_")
config.DB_PATH = os.path.join(_tmp, "nlu.db")

import pytest
from fastapi.testclient import TestClient
import api_web

from agent import web_agent as A


@pytest.fixture(scope="module")
def client():
    with TestClient(api_web.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _ensure_schema():
    """确保当前 DB 迁移齐全（防其他测试文件 init_db 副作用切走全局连接）。"""
    from data.database import init_db
    try:
        init_db(config.DB_PATH)
    except Exception:
        pass


def _login(client, role="resident"):
    r = client.post("/api/web/auth/demo", json={"role": role})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"], body
    return body["data"]["token"]


def _chat(client, text, role="resident", elder=False):
    token = _login(client, role)
    path = "/api/web/agent/elderly/chat" if elder else "/api/web/agent/chat"
    r = client.post(path, json={"text": text},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _reset(client, role="resident", elder=False):
    try:
        _chat(client, "算了", role=role, elder=elder)
    except Exception:
        pass


# ---------- 单元：方言归一化 ----------

def test_dialect_beijing_normalized():
    t = A.normalize_dialect("您嘞，我们家灯忒暗了，您瞅瞅咋回事")
    assert "您" in t and "太暗了" in t and "看看" in t and "怎么" in t
    assert "忒" not in t and "瞅瞅" not in t and "咋" not in t


def test_dialect_shanghai_normalized():
    t = A.normalize_dialect("阿拉屋里厢水管漏了，老灵额帮帮忙")
    assert "我" in t and "水管" in t
    assert "阿拉" not in t


# ---------- 单元：指代消解 ----------

def test_reference_resolution_uses_recent_entity():
    # 「那个」→ 最近实体「水管」
    t = A.resolve_reference("那个又坏了", "水管")
    assert "水管" in t and "那个" not in t
    # 无最近实体 → 原样
    assert A.resolve_reference("那个又坏了", None) == "那个又坏了"
    # 已含业务关键词 → 不替换（避免误改）
    assert A.resolve_reference("那个灯坏了", "水管") == "那个灯坏了"


def test_reference_entity_extraction():
    assert A.extract_recent_entity("家里水管漏水了") == "水管"
    assert A.extract_recent_entity("电梯门打不开") == "电梯"
    assert A.extract_recent_entity("今天天气不错") is None


# ---------- 单元：否定 / 纠偏 ----------

def test_negation_extracts_positive_target():
    # 「不是A是B」→ B
    assert A.extract_negation_target("不是报修是查医保政策") == "查医保政策"
    # 「不要A要B」
    assert A.extract_negation_target("不要修灯要修水管") == "修水管"
    # 无否定结构 → None
    assert A.extract_negation_target("我想报修") is None


def test_nlu_preprocess_chain():
    # 方言 + 否定：一句同时触发两能力
    out = A.nlu_preprocess("阿拉不是要报修，是要问医保", "水管")
    assert "医保" in out and "阿拉" not in out
    # 指代 + 否定
    out2 = A.nlu_preprocess("不是那个，是电梯坏了", "水管")
    assert "电梯" in out2 and "水管" not in out2


# ---------- 端到端：receptionist 路由 ----------

def test_chat_dialect_routes_to_repair(client):
    _reset(client)
    out = _chat(client, "阿拉屋里厢水管漏了")
    assert out["intent"] == "repair_dispatch", out.get("reply")
    # 追问仍能接（状态机不因方言打乱）
    out = _chat(client, "家里")
    assert out["intent"] == "repair_dispatch"


def test_chat_negation_reroutes(client):
    _reset(client)
    out = _chat(client, "不是报修是查医保政策")
    assert out["intent"] == "policy_expert", out.get("reply")


def test_chat_reference_after_entity(client):
    _reset(client)
    # 第一轮：报修 + 提取实体「水管」
    out = _chat(client, "家里水管漏水了")
    assert out["intent"] == "repair_dispatch"
    # 第二轮：用指代「那个」继续（应续接报修，而不是未知意图/话题切换）
    out = _chat(client, "那个又坏了")
    assert out["intent"] == "repair_dispatch", out.get("reply")


def test_chat_reference_without_entity_unknown(client):
    _reset(client)
    # 无最近实体时「那个」无法消解 → 未知意图（不误路由）
    # 注意：「那个又坏了」含「坏了」仍会按报修关键词路由（正确）；
    # 这里用不含业务关键词的指代句验证无实体时不会凭空路由。
    out = _chat(client, "那个怎么样了")
    assert out["intent"] in ("", "未知意图") or "没太理解" in out.get("reply", "")
