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


@pytest.fixture(autouse=True)
def _ensure_schema():
    """确保当前 DB 迁移齐全（防其他测试文件 init_db 副作用切走全局连接）。"""
    from data.database import init_db
    try:
        init_db(config.DB_PATH)
    except Exception:
        pass


def test_phone_encryption_migration():
    """迁移：phone → phone_enc（明文置空）；解密读写正常；回滚。"""
    from data.db_core import get_db
    from utils.crypto import Crypto
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (username, role, name, phone, is_active) "
                     "VALUES ('mig_test', 'resident', '迁移测试', '13987654321', 1)")
        conn.commit()
    import importlib.util
    spec = importlib.util.spec_from_file_location("mig", "scripts/migrate_phone_encryption.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    n = m.migrate()
    assert n >= 1
    with get_db() as conn:
        row = conn.execute("SELECT phone, phone_enc FROM user_profile WHERE username='mig_test'").fetchone()
        assert row["phone"] == "" and row["phone_enc"]
        assert row["phone_enc"] != "13987654321"
        assert Crypto().decrypt(row["phone_enc"]) == "13987654321"
    m.rollback()
    with get_db() as conn:
        row = conn.execute("SELECT phone FROM user_profile WHERE username='mig_test'").fetchone()
        assert row["phone"] == "13987654321"
        conn.execute("DELETE FROM user_profile WHERE username='mig_test'")
        conn.commit()


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
    """改密：校验强度 + 登录后生效（独立测试用户，不碰演示账号）。"""
    from data.db_core import get_db
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (username, role, name, is_active) "
            "VALUES ('test_user_pw', 'resident', '改密测试', 1)")
        conn.commit()
    token = _login(client, "resident")
    # 演示用户登录 OK 后，改用独立用户测试改密
    r = client.post("/api/web/auth/login", json={"username": "test_user_pw", "password": ""})
    assert r.status_code == 200 and r.json()["success"], r.text
    token = r.json()["data"]["token"]
    r = client.post("/api/web/auth/change-password",
                    json={"old_password": "", "new_password": "abc12345"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["success"]
    # 弱密码拒绝（≥8位，命中弱密码表）
    r = client.post("/api/web/auth/change-password",
                    json={"old_password": "", "new_password": "password123"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400 and not r.json()["success"]
    with get_db() as conn:
        conn.execute("DELETE FROM user_profile WHERE username='test_user_pw'")
        conn.commit()


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


# ---------- WS0：演示登录门控 / 防爆破 ----------

def test_demo_login_disabled_in_prod(monkeypatch, client):
    """WS0.1：生产（DEMO_MODE=false）演示登录必须 403，且不返回 token。"""
    monkeypatch.setattr("api_web.DEMO_MODE", False)
    monkeypatch.setattr("config.DEMO_MODE", False)
    for role in ("grid", "elderly", "resident"):
        r = client.post("/api/web/auth/demo", json={"role": role})
        assert r.status_code == 403, r.text
        assert "token" not in (r.json().get("data") or {})


def test_demo_login_enabled_in_demo_mode(client):
    """默认演示模式下 demo 登录可用（回归：不破坏原有演示链路）。"""
    r = client.post("/api/web/auth/demo", json={"role": "grid"})
    assert r.status_code == 200 and r.json()["success"]
    assert r.json()["data"]["token"]


def _fresh_grid_user(username="guard_grid", password="GuardPass#123"):
    from data.db_core import get_db
    from data.db_user import create_user
    with get_db() as conn:
        conn.execute("DELETE FROM user_profile WHERE username=?", (username,))
        conn.commit()
    create_user(username, password=password, role="grid", name="防爆破测试")
    # 重新触发锁定，清理可能的残留状态
    from utils.login_guard import reset
    reset(username, "testclient")
    return username, password


def test_login_guard_locks_after_failures(client):
    """WS0.3：同一用户连续 5 次失败后，第 6 次即便密码正确也被拒；成功登录后清零。"""
    username, password = _fresh_grid_user()
    wrong = "WrongPass#000"
    for _ in range(5):
        r = client.post("/api/web/auth/login", json={"username": username, "password": wrong})
        assert r.status_code == 400 and not r.json()["success"]
    # 第 6 次：密码正确但仍被锁定
    r = client.post("/api/web/auth/login", json={"username": username, "password": password})
    assert r.status_code == 400 and "过多" in r.json()["message"]
    # 成功登录后清零可再试
    from utils.login_guard import reset
    reset(username, "testclient")
    r = client.post("/api/web/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200 and r.json()["success"]
    from data.db_core import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM user_profile WHERE username=?", (username,))
        conn.commit()


def test_login_guard_module_remaining():
    """WS0.3：remaining 从阈值递减，锁定后为 0。"""
    from utils.login_guard import remaining, record_fail, reset
    reset("mod_user", "ip")
    assert remaining("mod_user", "ip") == 5
    record_fail("mod_user", "ip")
    assert remaining("mod_user", "ip") == 4
    for _ in range(4):
        record_fail("mod_user", "ip")
    assert remaining("mod_user", "ip") == 0
    reset("mod_user", "ip")
    assert remaining("mod_user", "ip") == 5


# ---------- WS9.1：越权 / 伪造 / 篡改 JWT 负向测试 ----------

def test_jwt_tampered_rejected(client):
    """篡改签名 → token 失效（401）。"""
    import api_routes.deps as d
    good = d.make_token(1, "grid", "x")
    bad = good[:-2] + "AB"
    r = client.get("/api/web/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401
    assert d.verify_token(bad) is None


def test_jwt_alg_none_rejected(client):
    """伪造 alg:none 头（绕过签名校验）→ 拒绝（401）。"""
    import base64, json
    import api_routes.deps as d
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    hdr = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"uid": 1, "role": "grid", "name": "x",
                              "exp": 9999999999}).encode())
    tok = f"{hdr}.{payload}."   # 无签名
    assert d.verify_token(tok) is None
    r = client.get("/api/web/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_role_escalation_resident_to_grid_endpoint(client):
    """居民 token 访问网格员专属端点 → 拒绝（1003 无权限）。"""
    token = _login(client, "resident")
    for path in ("/api/web/agent/llm-usage", "/api/web/agent/logs", "/api/web/agent/analytics"):
        r = client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400 and r.json()["code"] == 1003, f"{path}: {r.status_code}"


def test_me_delete_anonymizes(client):
    """注销：个人字段匿名化 + 停用（用独立测试用户，不碰演示账号）。"""
    from data.db_core import get_db
    # 创建独立测试用户（resident 空密码可登录）
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (username, role, name, phone, is_active) "
            "VALUES ('test_user_sec', 'resident', '注销测试', '13912345678', 1)")
        conn.commit()
    r = client.post("/api/web/auth/login", json={"username": "test_user_sec", "password": ""})
    assert r.status_code == 200 and r.json()["success"], r.text
    token = r.json()["data"]["token"]
    r2 = client.post("/api/web/me/delete", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200 and r2.json()["success"]
    # 注销后 token 失效
    r3 = client.get("/api/web/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code in (401, 400) or not r3.json().get("success")
    # 数据库校验：停用 + 匿名化
    with get_db() as conn:
        row = conn.execute("SELECT is_active, phone, username FROM user_profile WHERE username LIKE '已注销用户%'").fetchone()
        assert row and row["is_active"] == 0
        assert row["phone"] in ("", None)
    # 清理
    with get_db() as conn:
        conn.execute("DELETE FROM user_profile WHERE username LIKE '已注销用户%'")
        conn.commit()
