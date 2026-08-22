# -*- coding: utf-8 -*-
"""Agent 统一入口模块端点测试（识别意图 → 引导补全 → 路由执行 → 返回；留痕/历史/越权）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

_tmp = tempfile.mkdtemp(prefix="agent_")
config.DB_PATH = os.path.join(_tmp, "agent.db")

import pytest
from fastapi.testclient import TestClient
import api_web


@pytest.fixture(scope="module")
def client():
    with TestClient(api_web.app) as c:
        yield c


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
    return r.json()["data"], token


# ---------- 意图识别 ----------

def test_intent_report_issue_flow(client):
    """报修闭环：识别 → 追问分类 → 追问紧急 → 确认 → 提交返工单号。"""
    out, _ = _chat(client, "我家水管漏水了")
    assert out["intent"] == "报修" and out["status"] == "追问"
    out, _ = _chat(client, "家里")
    assert "紧急" in out["reply"]
    out, _ = _chat(client, "紧急")
    assert out["status"] == "需确认" and "确认报修信息" in out["reply"]
    out, _ = _chat(client, "确认提交")
    assert out["status"] == "成功" and out["related_id"] and "工单号" in out["reply"]


def test_intent_proposal_flow(client):
    """提案闭环：识别 → 追问公开/私有 → 确认 → 提交返编号。"""
    out, _ = _chat(client, "我想提个建议，社区应该多装几个路灯")
    assert out["intent"] == "提案" and out["status"] == "追问"
    out, _ = _chat(client, "公开")
    assert out["status"] == "需确认"
    out, _ = _chat(client, "确认提交")
    assert out["status"] == "成功" and out["related_id"] and "提案编号" in out["reply"]


def test_intent_policy_weather_notice_contact(client):
    """政策/天气/通知/联系社区直接执行。"""
    out, _ = _chat(client, "医保怎么报销")
    assert out["intent"] == "政策问答"
    out, _ = _chat(client, "今天天气怎么样")
    assert out["intent"] == "天气查询" and "今天天气" in out["reply"]
    out, _ = _chat(client, "最近有什么通知")
    assert out["intent"] == "通知查询"
    out, _ = _chat(client, "帮我联系社区")
    assert out["intent"] == "联系社区" and any(a.get("type") == "confirm_call" for a in out["actions"])


def test_intent_withdraw_and_help(client):
    out, _ = _chat(client, "我要取消报修")
    assert out["intent"] == "撤回引导"
    out, _ = _chat(client, "你们这个怎么用")
    assert out["intent"] == "使用帮助"
    out, _ = _chat(client, "你是谁")
    assert out["intent"] == "自我介绍"
    out, _ = _chat(client, "谢谢")
    assert out["intent"] == "礼貌回复"


def test_intent_correction_confirm(client):
    """错别字纠正先确认：我加水管漏水 → 我家水管漏水。"""
    out, _ = _chat(client, "我加水管漏水")
    assert out["intent"] == "纠正确认" and out["status"] == "需确认" and "我家水管漏水" in out["reply"]
    out, _ = _chat(client, "对")
    assert out["intent"] == "报修"


def test_unknown_and_emotion(client):
    _chat(client, "算了")  # 清理上轮会话残留
    out, _ = _chat(client, "今天吃了什么好吃的")
    assert out["intent"] == "未知意图"
    out, _ = _chat(client, "你们到底管不管，气死我了")
    assert out["intent"] == "情绪安抚"


def test_emergency_mark(client):
    """紧急语义：水哗哗的快点来 → 纠正确认 → 报修确认（紧急程度紧急）。"""
    out, _ = _chat(client, "那个水哗哗的，快点来")
    if out["intent"] == "纠正确认":
        out, _ = _chat(client, "对")
    assert out["intent"] == "报修"
    if out["status"] == "追问":
        out, _ = _chat(client, "家里")
    assert out["status"] in ("追问", "需确认")
    if out["status"] == "需确认":
        assert "紧急" in out["reply"]
    _chat(client, "算了")  # 清理会话


# ---------- 老年端 ----------

def test_elderly_body_and_report(client):
    out, _ = _chat(client, "我不舒服", role="elderly", elder=True)
    assert out["intent"] == "身体不适"
    out, _ = _chat(client, "家里灯不亮了", role="elderly", elder=True)
    assert out["intent"] == "报修" and out["status"] == "需确认" and "室内" in out["reply"]
    out, _ = _chat(client, "确认提交", role="elderly", elder=True)
    assert out["status"] == "成功"


# ---------- 负责人端 ----------

def test_grid_todo_export_stats_jump(client):
    out, _ = _chat(client, "今天有什么待办", role="grid")
    assert out["intent"] == "待办提醒" and "待办" in out["reply"]
    out, _ = _chat(client, "导出本月工单", role="grid")
    assert out["intent"] == "导出数据" and out["status"] == "需确认"
    out, _ = _chat(client, "确认", role="grid")
    assert any(a.get("type") == "download" for a in out["actions"])
    out, _ = _chat(client, "本周工单统计", role="grid")
    assert out["intent"] == "统计查询"
    out, _ = _chat(client, "打开待审核工单", role="grid")
    assert any(a.get("type") == "navigate" and a.get("to") == "/grid/work-orders" for a in out["actions"])


def test_grid_search(client):
    out, _ = _chat(client, "查一下公共设施", role="grid")
    assert out["intent"] == "搜索资料"


# ---------- 历史对话 / 留痕 / 越权 ----------

def test_history_and_delete(client):
    token = _login(client, "resident")
    _chat(client, "今天天气怎么样")
    r = client.get("/api/web/agent/history", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    rows = r.json()["data"]
    assert rows and any(row.get("is_bot") for row in rows)
    # 删除第一条
    did = rows[0]["id"]
    r = client.delete(f"/api/web/agent/history/{did}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # 越权删除他人记录
    token2 = _login(client, "resident")
    r = client.delete(f"/api/web/agent/history/{did}", headers={"Authorization": f"Bearer {token2}"})
    assert r.status_code == 400 and not r.json()["success"]


def test_agent_logs_only_grid(client):
    """留痕仅负责人可见；居民访问被拒。"""
    token = _login(client, "resident")
    r = client.get("/api/web/agent/logs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400 and not r.json()["success"]
    token2 = _login(client, "grid")
    r = client.get("/api/web/agent/logs", headers={"Authorization": f"Bearer {token2}"})
    assert r.status_code == 200
    assert r.json()["data"] is not None
    # 留痕含 Agent 模块来源与意图字段
    rows = r.json()["data"]
    if rows:
        assert rows[0]["intent"]


def test_export_agent_logs_grid_only(client):
    token = _login(client, "resident")
    r = client.get("/api/web/export/agent-logs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400 and not r.json()["success"]
    token2 = _login(client, "grid")
    r = client.get("/api/web/export/agent-logs", headers={"Authorization": f"Bearer {token2}"})
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
