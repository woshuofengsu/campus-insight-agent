# -*- coding: utf-8 -*-
"""答辩演示：两条真实多智能体协作链一键演示（录屏素材）。

场景1：老人"我有点头晕" + 高温红色预警 → 健康顾问⇄天气守护员 双向协商
场景2：居民"楼道闻到燃气味" → 报修调度员→通知管理员 隐患升级
退出码 0 = 两链协作节点齐全。"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEMO_MODE", "true")

from fastapi.testclient import TestClient
import api_web


def _login(c, role):
    r = c.post("/api/web/auth/demo", json={"role": role})
    return r.json()["data"]["token"]


def _chat(c, role, token, text):
    path = "/api/web/agent/elderly/chat" if role == "elderly" else "/api/web/agent/chat"
    r = c.post(path, json={"text": text}, headers={"Authorization": f"Bearer {token}"})
    return r.json()["data"]


def _show(title, out):
    print(f"\n{'='*56}\n【{title}】意图={out['intent']} 状态={out['status']}\n{'-'*56}")
    for c in out["execution_chain"]:
        print(f"  [{c['agent']}] {c['action']} {c.get('note', '')[:40]}")
    print(f"{'-'*56}\n回复：\n{out['reply'][:300]}")


def main():
    ok = True
    with TestClient(api_web.app) as c:
        # 造高温红色预警
        from data.db_core import get_db
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        exp = (datetime.now() + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute("INSERT INTO weather_alerts (alert_id,alert_type,level,effective_time,expire_time,status) "
                         "VALUES ('demo-collab','高温','红色',?,?,'active')", (now, exp))
            conn.commit()
        try:
            # 每场景前清会话残留（演示库 uid 可能有历史草稿/状态，避免续接干扰新场景）
            try:
                _chat(c, "elderly", _login(c, "elderly"), "算了")
            except Exception:
                pass
            t1 = _login(c, "elderly")
            o1 = _chat(c, "elderly", t1, "我有点头晕")
            _show("场景1：健康顾问 ⇄ 天气守护员（反向联动）", o1)
            hit1 = any(x["agent"] == "negotiation" for x in o1["execution_chain"]) and "天气守护员" in o1["reply"]
            ok &= hit1

            try:
                _chat(c, "resident", _login(c, "resident"), "算了")
            except Exception:
                pass
            t2 = _login(c, "resident")
            o2 = _chat(c, "resident", t2, "楼道里闻到很浓的燃气味")
            _show("场景2：报修调度员 → 通知管理员（隐患升级）", o2)
            hit2 = any(x["agent"] == "negotiation" for x in o2["execution_chain"]) and "通知管理员" in o2["reply"]
            ok &= hit2
        finally:
            with get_db() as conn:
                conn.execute("DELETE FROM weather_alerts WHERE alert_id='demo-collab'")
                conn.commit()
    print(f"\n{'✅ 两条协作链演示通过' if ok else '❌ 协作链缺失'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
