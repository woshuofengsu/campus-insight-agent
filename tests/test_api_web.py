# -*- coding: utf-8 -*-
"""api_web.py（FastAPI + Vue3 前端后端）端点测试。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

# 用独立临时库，不污染正式数据
_tmp = tempfile.mkdtemp(prefix="apiweb_")
config.DB_PATH = os.path.join(_tmp, "web.db")

import pytest
from fastapi.testclient import TestClient
import api_web


@pytest.fixture(scope="module")
def client():
    with TestClient(api_web.app) as c:
        yield c


def _login(client, username="demo_grid", password="demo123"):
    r = client.post("/api/web/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"], body
    return body["data"]


def test_health_no_dist(client):
    """dist 未构建时根路径返回服务说明。"""
    r = client.get("/")
    assert r.status_code == 200
    assert "CommunityInsight" in r.text


def test_jwt_login_and_me(client):
    data = _login(client)
    assert data["token"] and data["role"] == "grid"
    r = client.get("/api/web/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert r.status_code == 200 and r.json()["data"]["role"] == "grid"


def test_auth_required(client):
    """无 token 访问受保护端点 → 401。"""
    r = client.get("/api/web/issues")
    assert r.status_code == 401
    assert r.json()["code"] == 1002


def test_bad_login(client):
    r = client.post("/api/web/auth/login", json={"username": "demo_grid", "password": "wrong"})
    assert r.status_code == 400 and not r.json()["success"]


def test_demo_login(client):
    r = client.post("/api/web/auth/demo", json={"role": "resident"})
    assert r.status_code == 200 and r.json()["success"]
    assert r.json()["data"]["role"] == "resident"


def test_issue_flow(client):
    """报修提交 → 审核 → 派单 → 处理 → 解决 → 反馈全闭环。"""
    res = _login(client, "demo_resident", "")
    h = {"Authorization": f"Bearer {res['token']}"}
    r = client.post("/api/web/issues", json={
        "title": "楼道灯不亮", "category": "公共设施", "issue_type": "室内",
        "location": "海淀小区3号楼2单元", "description": "楼道灯不亮需要维修",
        "urgency": "一般", "reporter_name": "王阿姨", "reporter_phone": "13800138000",
    }, headers=h)
    assert r.status_code == 200, r.text
    iid = r.json()["data"]["issue_id"]
    assert iid > 0

    # 非法参数：空标题
    r = client.post("/api/web/issues", json={"title": ""}, headers=h)
    assert r.status_code == 422

    # 居民列表可见
    r = client.get("/api/web/issues", headers=h)
    assert r.json()["success"] and any(i["id"] == iid for i in r.json()["data"])

    # 负责人审核 → 派单 → 开始处理 → 解决
    g = _login(client)
    gh = {"Authorization": f"Bearer {g['token']}"}
    r = client.post(f"/api/web/issues/{iid}/action", json={"action": "audit", "approve": True}, headers=gh)
    assert r.json()["success"], r.text
    r = client.post(f"/api/web/issues/{iid}/action",
                    json={"action": "dispatch", "assignee_name": "维修工", "assignee_phone": "13900000000"},
                    headers=gh)
    assert r.json()["success"], r.text
    r = client.post(f"/api/web/issues/{iid}/action", json={"action": "start"}, headers=gh)
    assert r.json()["success"], r.text
    r = client.post(f"/api/web/issues/{iid}/action",
                    json={"action": "resolve", "note": "已更换灯管", "reason": "现场未拍照"}, headers=gh)
    assert r.json()["success"], r.text

    # 居民反馈满意 → 处理结束
    r = client.post(f"/api/web/issues/{iid}/action",
                    json={"action": "feedback", "satisfied": True}, headers=h)
    assert r.json()["success"], r.text
    r = client.get(f"/api/web/issues/{iid}", headers=gh)
    assert r.json()["data"]["status"] == "处理结束"

    # 状态冲突：已结束再审核被拒
    r = client.post(f"/api/web/issues/{iid}/action", json={"action": "audit", "approve": True}, headers=gh)
    assert not r.json()["success"] and r.json()["code"] == 2001


def test_proposal_vote(client):
    """提案提交 → 审核 → 公示 → 投票 → 重复投票拦截。"""
    r = _login(client, "demo_resident", "")
    h = {"Authorization": f"Bearer {r['token']}"}
    r = client.post("/api/web/proposals", json={
        "title": "增设快递柜", "description": "建议在小区门口增设快递柜方便取件",
        "category": "其他", "is_public": 1, "reporter_name": "王阿姨",
        "reporter_phone": "13800138000",
    }, headers=h)
    assert r.status_code == 200, r.text
    pid = r.json()["data"]["proposal_id"]

    # 另一个用户投票（demo_elderly，避免「不能给自己提案投票」）
    e = _login(client, "demo_elderly", "")
    eh = {"Authorization": f"Bearer {e['token']}"}
    r = client.post(f"/api/web/proposals/{pid}/vote", json={"score": 5}, headers=eh)
    assert not r.json()["success"], "待审核不能投票"

    # 审核通过 + 确认公开（负责人操作在数据层直接调，web 端点后续补）
    from data.db_proposal import audit_proposal, confirm_visibility
    audit_proposal(pid, True, opinion="同意", actor="网格员A")
    confirm_visibility(pid, 1, actor="王阿姨")

    r = client.post(f"/api/web/proposals/{pid}/vote", json={"score": 5}, headers=eh)
    assert r.json()["success"], r.text
    r = client.post(f"/api/web/proposals/{pid}/vote", json={"score": 3}, headers=eh)
    assert not r.json()["success"] and "投过" in r.json()["error"], "重复投票应拦截"


def test_upload_rejects_oversize(client):
    """上传超 5MB 文件被拒。"""
    r = _login(client, "demo_grid", "demo123")
    h = {"Authorization": f"Bearer {r['token']}"}
    big = b"x" * (5 * 1024 * 1024 + 1)
    r = client.post("/api/web/upload?folder=test",
                    files={"files": ("big.jpg", big, "image/jpeg")}, headers=h)
    assert r.status_code == 400
    assert "5MB" in r.json()["error"]


def test_jwt_tamper(client):
    """篡改 token 被拒。"""
    r = _login(client, "demo_resident", "")
    token = r["token"][:-2] + "xx"
    r = client.get("/api/web/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
