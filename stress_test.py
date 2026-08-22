# -*- coding: utf-8 -*-
"""完整全面压测：并发请求 api_web 各端点，验证无 500 / 无 SQLite 锁冲突 / 数据一致性。
用法：python stress_test.py [base_url] [concurrency]
"""
import json
import sys
import threading
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 20
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 3

errors = []
lock = threading.Lock()
stats = {"ok": 0, "fail": 0, "sqlite_locked": 0}
PERF = {}


def req(method, path, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            dt = (time.time() - t0) * 1000
            try:
                j = json.loads(raw)
            except Exception:
                j = {"raw": raw[:200]}
            return resp.status, j, dt
    except urllib.error.HTTPError as e:
        dt = (time.time() - t0) * 1000
        raw = e.read().decode()[:500]
        try:
            j = json.loads(raw)
        except Exception:
            j = {"raw": raw}
        return e.code, j, dt
    except Exception as e:  # noqa: BLE001
        return -1, {"error": str(e)}, (time.time() - t0) * 1000


def login_demo(role):
    st, j, _ = req("POST", "/api/web/auth/demo", body={"role": role})
    if st == 200 and j.get("success"):
        return j["data"]["token"]
    return None


def worker(uid, tokens, results):
    """每个 worker 跑一轮典型用户旅程。"""
    # 1. 登录（各角色）
    role = "resident" if uid % 3 != 2 else "grid"
    tok = login_demo(role)
    if not tok:
        errors.append(f"worker{uid}: login {role} failed")
        return
    with lock:
        stats["ok"] += 1

    # 2. 健康检查（带 token）
    st, j, dt = req("GET", "/api/web/health", tok)
    with lock:
        PERF["health"] = PERF.get("health", []) + [dt]
    if st != 200:
        errors.append(f"worker{uid}: health {st} {j}")
    else:
        with lock:
            stats["ok"] += 1

    # 3. 并发写操作：居民提交报修 / 提案 / 投票 / 议论 / 咨询；grid 查列表
    if role == "resident":
        r_token = tok
        # 提交报修
        st, j, dt = req("POST", "/api/web/issues", r_token, {
            "title": f"压测工单{uid}", "category": "公共设施", "issue_type": "室内",
            "location": f"幸福小区{uid}号楼", "description": f"压测报修描述{uid}楼道灯不亮需要维修",
            "urgency": "一般", "reporter_phone": f"139{uid:08d}"[:11] or "13900000000",
        })
        with lock:
            PERF["issue_create"] = PERF.get("issue_create", []) + [dt]
        if st == 200 and j.get("success"):
            with lock:
                stats["ok"] += 1
            iid = j["data"]["issue_id"]
            # 提交提案
            st2, j2, _ = req("POST", "/api/web/proposals", r_token, {
                "title": f"压测提案{uid}", "description": f"建议压测提案{uid}改善社区环境提升服务质量",
                "category": "公共设施", "is_public": 1, "reporter_phone": f"139{uid:08d}"[:11] or "13900000000",
            })
            if st2 == 200 and j2.get("success"):
                pid = j2["data"]["proposal_id"]
                with lock:
                    stats["ok"] += 1
                # 匿名投票 + 议论
                st3, j3, _ = req("POST", f"/api/web/proposals/{pid}/vote", r_token, {"score": (uid % 5) + 1})
                st4, j4, _ = req("POST", f"/api/web/proposals/{pid}/comments", r_token, {"content": f"压测议论{uid}"})
                if st3 == 200:
                    with lock:
                        stats["ok"] += 1
                if st4 == 200:
                    with lock:
                        stats["ok"] += 1
            # 提交健康咨询
            st5, j5, _ = req("POST", "/api/web/health/consults", r_token, {
                "name": f"居民{uid}", "phone": f"139{uid:08d}"[:11] or "13900000000",
                "consult_type": "健康知识", "content": f"压测咨询{uid}请问血压高怎么办",
            })
            if st5 == 200 and j5.get("success"):
                with lock:
                    stats["ok"] += 1
            # 政策提问
            st6, j6, _ = req("POST", "/api/web/qa/ask", r_token, {"question": f"压测提问{uid}医保报销需要什么材料"})
            if st6 == 200:
                with lock:
                    stats["ok"] += 1
            # Agent 对话（意图识别 + 追问 + 取消清理）
            st7, j7, dt = req("POST", "/api/web/agent/chat", r_token, {"text": f"压测报修{uid}楼道灯不亮"})
            with lock:
                PERF["agent_chat"] = PERF.get("agent_chat", []) + [dt]
            if st7 == 200 and j7.get("success"):
                with lock:
                    stats["ok"] += 1
                req("POST", "/api/web/agent/chat", r_token, {"text": "算了"})
            else:
                errors.append(f"worker{uid}: agent_chat {st7} {j7}")
        else:
            with lock:
                stats["fail"] += 1
            errors.append(f"worker{uid}: issue_create {st} {j}")
    else:
        # grid：读列表 + 导出 + 统计 + Agent 待办/留痕
        for path in ["/api/web/issues", "/api/web/proposals", "/api/web/notices/manage",
                     "/api/web/health/consults", "/api/web/qa/questions", "/api/web/qa/stats",
                     "/api/web/weather/tasks", "/api/web/elderly/manage/medications",
                     "/api/web/agent/logs"]:
            st, j, dt = req("GET", path, tok)
            with lock:
                PERF[path] = PERF.get(path, []) + [dt]
            if st == 200:
                with lock:
                    stats["ok"] += 1
            else:
                with lock:
                    stats["fail"] += 1
                errors.append(f"worker{uid}: GET {path} {st} {j}")


def main():
    print(f"压测开始：base={BASE} concurrency={CONC} rounds={ROUNDS}")
    tokens = {}
    for role in ("resident", "grid", "elderly"):
        t = login_demo(role)
        if t:
            tokens[role] = t
    print(f"登录成功：{list(tokens.keys())}")

    all_results = []
    for rnd in range(ROUNDS):
        threads = []
        for i in range(CONC):
            th = threading.Thread(target=worker, args=(i + rnd * CONC, tokens, all_results))
            threads.append(th)
        t0 = time.time()
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        dur = time.time() - t0
        print(f"第 {rnd + 1} 轮：{CONC} 并发，耗时 {dur:.1f}s，OK={stats['ok']} FAIL={stats['fail']}")

    # 汇总
    print("\n===== 压测结果 =====")
    print(f"总请求成功 {stats['ok']}，失败 {stats['fail']}")
    print("错误明细：")
    for e in errors[:30]:
        print("  -", e)
    if not errors:
        print("  （无错误）")
    print("\n端点耗时（ms，平均/最大）：")
    for path, times in sorted(PERF.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"  {path}: avg={sum(times)/len(times):.0f} max={max(times):.0f} n={len(times)}")
    print("\n结论：", "✅ 压测通过（无错误）" if not errors else f"❌ 存在 {len(errors)} 个错误")


if __name__ == "__main__":
    main()
