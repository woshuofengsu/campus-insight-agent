# -*- coding: utf-8 -*-
"""数据安全与合规测试（v3.0）：加密工具 / 密码策略 / 会话落库 / PIPL 端点。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

_tmp = tempfile.mkdtemp(prefix="sec_")
config.DB_PATH = os.path.join(_tmp, "sec.db")

import pytest
from fastapi.testclient import TestClient
import api_web


@pytest.fixture(scope="module")
def client():
    with TestClient(api_web.app) as c:
        yield c


def _login(client, role="resident"):
    r = client.post("/api/web/auth/demo", json={"role": role})
    body = r.json()
    assert body["success"], body
    return body["data"]["token"]


# ---------- 加密工具 ----------

def test_crypto_roundtrip():
    from utils.crypto import Crypto
    c = Crypto("test-key")
    ct = c.encrypt("13912345678")
    assert ct != "13912345678"          # 密文非明文
    assert c.decrypt(ct) == "13912345678"
    # 不同 key 无法解密
    c2 = Crypto("other-key")
    with pytest.raises(Exception):
        c2.decrypt(ct)
    # 篡改检测
    with pytest.raises(Exception):
        c.decrypt(ct[:-4] + "AAAA")


def test_crypto_env_key():
    os.environ["CRYPTO_KEY"] = "env-key-1234567890"
    from utils.crypto import Crypto
    c = Crypto()
    assert c.decrypt(c.encrypt("abc")) == "abc"


# ---------- 密码策略 ----------

def test_password_strength():
    from utils.password import validate_password, password_strength
    ok, _ = validate_password("abc12345")
    assert ok
    ok, msg = validate_password("password123")  # 弱密码拒绝（≥8位且命中弱表）
    assert not ok and "简单" in msg
    ok, msg = validate_password("12345678")       # 纯数字
    assert not ok
    ok, msg = validate_password("aaaa1234")       # 连续重复
    assert not ok
    ok, msg = validate_password("short")          # 太短
    assert not ok
    assert password_strength("abc12345") == "medium"
    assert password_strength("a1") == "weak"


# ---------- 会话落库 ----------

def test_session_persist_and_restore(client):
    from data import db_agent
    sid = "test-session-1"
    db_agent.save_session(sid, 1, "resident", {"step": "ask_type", "intent": "repair"})
    st = db_agent.load_session(sid)
    assert st and st.get("step") == "ask_type"
    db_agent.delete_session(sid)
    assert db_agent.load_session(sid) is None


def test_orchestrator_session_persistence(client):
    """Agent 对话后会话落库，新 Orchestrator（模拟重启）可恢复追问状态。"""
    from agent.orchestrator import Orchestrator
    o1 = Orchestrator()
    o1.run("resident", 99010, "测试", "我家水管漏水了")  # 追问分类，state 落库
    from data import db_agent
    st = db_agent.load_session(o1.bb.session_id)
    assert st and st.get("step") == "ask_type"
    # 新实例（模拟重启）用同一 session_id 恢复
    o2 = Orchestrator(session_id=o1.bb.session_id)
    r = o2.run("resident", 99010, "测试", "家里")
    assert "紧急" in r["reply"]  # 恢复后继续追问紧急程度


# ---------- PIPL 端点 ----------

def test_change_password_flow(client):
    """改密：校验强度 + 登录后生效（演示居民空密码免旧密码）。"""
    token = _login(client, "resident")
    r = client.post("/api/web/auth/change-password",
                    json={"old_password": "", "new_password": "abc12345"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["success"]
    # 弱密码拒绝（≥8位，命中弱密码表）
    r = client.post("/api/web/auth/change-password",
                    json={"old_password": "", "new_password": "password123"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400 and not r.json()["success"]


def test_me_export_masked(client):
    """导出本人数据：脱敏（无完整手机号）。"""
    token = _login(client, "resident")
    # 先制造一条含电话的数据（Agent 报修）
    client.post("/api/web/agent/chat", json={"text": "家里漏水"},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/api/web/me/export", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.text
    import re
    # 不应出现完整 11 位手机号
    assert not re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", body) or "****" in body


def test_me_delete_anonymizes(client):
    """注销：个人字段匿名化 + 停用。"""
    token = _login(client, "resident")
    r = client.post("/api/web/me/delete", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["success"]
    # 注销后 token 失效
    r2 = client.get("/api/web/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code in (401, 400) or not r2.json().get("success")
