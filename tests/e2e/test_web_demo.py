# -*- coding: utf-8 -*-
"""api_web 端到端演示流程（模拟评委演示路径）：三端全闭环。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

_tmp = tempfile.mkdtemp(prefix="e2e_web_")
config.DB_PATH = os.path.join(_tmp, "e2e.db")

import pytest
from fastapi.testclient import TestClient
import api_web


@pytest.fixture(scope="module")
def client():
    with TestClient(api_web.app) as c:
        yield c


def _login(client, username, password=""):
    r = client.post("/api/web/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200 and r.json()["success"], r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def test_full_demo_flow(client):
    """完整演示：通知 → 报修闭环 → 提案闭环 → 政策 → 老年端。"""
    # 1) 负责人登录 + 发布通知
    gh = _login(client, "demo_grid", "demo123")
    r = client.post("/api/web/notices", json={
        "title": "社区活动通知", "notice_type": "社区公告", "publish_scope": "全体居民",
        "body": "本周六上午 9 点在社区活动室举办重阳节活动，欢迎参加。",
    }, headers=gh)
    assert r.json()["success"], r.text
    print("✓ 负责人发布通知")

    # 2) 居民报修 → 负责人处理 → 居民反馈（全闭环）
    rh = _login(client, "demo_resident")
    r = client.post("/api/web/issues", json={
        "title": "3号楼二楼楼道灯不亮了", "category": "公共设施", "issue_type": "室内",
        "location": "海淀小区3号楼2单元", "description": "楼道灯不亮，晚上走路很危险",
        "urgency": "一般", "reporter_name": "王阿姨", "reporter_phone": "13800138000",
    }, headers=rh)
    assert r.json()["success"], r.text
    iid = r.json()["data"]["issue_id"]
    print(f"✓ 居民提交报修 #{iid}")

    assert client.post(f"/api/web/issues/{iid}/action",
                       json={"action": "audit", "approve": True}, headers=gh).json()["success"]
    assert client.post(f"/api/web/issues/{iid}/action",
                       json={"action": "dispatch", "assignee_name": "维修工甲",
                             "assignee_phone": "13900000000"}, headers=gh).json()["success"]
    assert client.post(f"/api/web/issues/{iid}/action",
                       json={"action": "start"}, headers=gh).json()["success"]
    assert client.post(f"/api/web/issues/{iid}/action",
                       json={"action": "resolve", "note": "已更换灯管"}, headers=gh).json()["success"]
    r = client.post(f"/api/web/issues/{iid}/action",
                    json={"action": "feedback", "satisfied": True}, headers=rh)
    assert r.json()["success"], r.text
    r = client.get(f"/api/web/issues/{iid}", headers=gh)
    assert r.json()["data"]["status"] == "处理结束"
    print("✓ 报修全闭环：审核→派单→处理→反馈→处理结束")

    # 3) 提案闭环：提交 → 审核 → 公示 → 投票 → 决定执行
    r = client.post("/api/web/proposals", json={
        "title": "建议增设快递柜", "description": "建议在小区门口增设快递柜方便大家取件减少丢件",
        "category": "其他", "is_public": 1, "reporter_name": "王阿姨",
        "reporter_phone": "13800138000",
    }, headers=rh)
    assert r.json()["success"], r.text
    pid = r.json()["data"]["proposal_id"]
    assert client.post(f"/api/web/proposals/{pid}/action",
                       json={"action": "audit", "approve": True, "opinion": "同意"},
                       headers=gh).json()["success"]
    assert client.post(f"/api/web/proposals/{pid}/action",
                       json={"action": "confirm", "is_public": 1}, headers=rh).json()["success"]
    eh = _login(client, "demo_elderly")
    assert client.post(f"/api/web/proposals/{pid}/vote", json={"score": 5},
                       headers=eh).json()["success"]
    print("✓ 提案闭环：审核→公示→匿名投票")

    # 4) 政策问答：自动回答 / 转人工
    r = client.post("/api/web/qa/ask", json={"question": "医保报销需要带什么材料？"}, headers=rh)
    assert r.status_code == 200 and r.json()["success"]
    print(f"✓ 政策问答（matched={r.json()['data']['matched']}）")

    # 5) 老年端：语音报修 + 用药 + 首页聚合
    r = client.post("/api/web/elderly/voice-report", json={"text": "家门口的灯坏了"}, headers=eh)
    assert r.json()["success"], r.text
    r = client.post("/api/web/elderly/medications", json={
        "drug_name": "降压药", "dosage": "1片", "times": "08:00", "repeat_rule": "每天",
        "start_date": "2026-08-21", "end_date": "2026-12-31",
    }, headers=eh)
    assert r.json()["success"], r.text
    r = client.get("/api/web/elderly/home", headers=eh)
    assert r.json()["success"] and "name" in r.json()["data"]
    print("✓ 老年端：语音报修 + 用药 + 首页聚合")

    # 6) 健康咨询：居民提交 → 负责人回复
    r = client.post("/api/web/health/consults", json={
        "name": "王阿姨", "phone": "13800138000", "consult_type": "健康知识",
        "content": "最近流感多发想了解怎么预防",
    }, headers=rh)
    assert r.json()["success"], r.text
    cid = r.json()["data"]["consult_id"]
    assert client.post(f"/api/web/health/consults/{cid}/reply",
                       json={"reply": "注意通风，建议接种流感疫苗"}, headers=gh).json()["success"]
    print("✓ 健康咨询：提交 → 回复")

    print("\n===== 端到端演示流程全部通过 =====")
