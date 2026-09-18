# scripts/benchmark_business.py
"""业务混合压测（WS7.1）：按真实比例混合请求，产出 p50/p95/p99、错误率、QPS。

要求：先起主服务（python -m uvicorn api_web:app --host 0.0.0.0 --port 8000），
再运行本脚本。演示模式（DEMO_MODE=true）下会自动登录 demo_resident / demo_grid。

用法：python scripts/benchmark_business.py [--base http://127.0.0.1:8000]
"""
import argparse
import concurrent.futures as cf
import json
import random
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
# 并发阶梯
LADDER = [50, 100, 200]
# 每档请求总数
TOTAL = 400

# 混合请求比例：iss 列表 / agent 对话（规则）/ 通知 / 政策常见问题（写 / 读 混合）
MIX = [("issues", 0.30), ("agent_chat", 0.25), ("notices", 0.20), ("policy_faq", 0.15), ("create_issue", 0.10)]


def _req(method, path, token, body=None, timeout=20):
    """发一个请求，返回 (耗时, 分类, 状态码)。

    分类（2026-09-15 修正，之前只统计"非 2xx = 错误"，会把**设计内的限流**算成故障）：
      ok      = 2xx
      throttle= 400 且错误码/文案是频控（agent 对话有防刷限制，压测必然触发）
      client  = 其他 4xx（参数/权限，通常说明压测载荷不符契约）
      server  = 5xx（真故障）
      conn    = 连接层失败
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    t0 = time.perf_counter()

    def classify(code: int, text: str) -> str:
        if 200 <= code < 300:
            return "ok"
        if code >= 500:
            return "server"
        if code == 400 and ("1002" in text or "喘口气" in text or "有点快" in text):
            return "throttle"
        return "client"

    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return time.perf_counter() - t0, classify(resp.status, text), resp.status
    except urllib.error.HTTPError as e:
        text = ""
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return time.perf_counter() - t0, classify(e.code, text), e.code
    except Exception:
        return time.perf_counter() - t0, "conn", None


def _login_resident(base):
    req = urllib.request.Request(base + "/api/web/auth/demo", data=b'{"role":"resident"}',
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["data"]["token"]


def _login_grid(base):
    req = urllib.request.Request(base + "/api/web/auth/login",
                                 data=json.dumps({"username": "demo_grid", "password": "demo123"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["data"]["token"]


def _build(rtok, gtok):
    """返回一个请求执行函数（按比例从真实端点抽取）。

    两处修正（实测发现）：
    ① `agent_chat` 以前写死返回 True —— 等于把 25% 流量排除在统计外，错误率被人为压低；
    ② `create_issue` 载荷缺**合法手机号**，接口会返回 400「请输入正确的手机号」——
       这不是服务端缺陷，是压测载荷不符合接口契约。
    """
    def run(_):
        x = random.random()
        acc = 0.0
        kind = "issues"
        for k, p in MIX:
            acc += p
            if x <= acc:
                kind = k
                break
        if kind == "agent_chat":
            dur, cls, code = _req("POST", "/api/web/agent/chat", rtok,
                                  {"text": random.choice(["家里水管漏水了", "楼道灯不亮",
                                                          "申请垃圾分类提案", "今天会下雨吗"])})
        elif kind == "notices":
            dur, cls, code = _req("GET", "/api/web/notices", rtok)
        elif kind == "policy_faq":
            dur, cls, code = _req("GET", "/api/web/qa/high-freq", rtok)
        elif kind == "create_issue":
            dur, cls, code = _req("POST", "/api/web/issues", rtok,
                                  {"title": random.choice(["楼道灯坏了", "电梯按键失灵", "垃圾桶满"]),
                                   "category": "设施维修", "location": "3号楼", "urgency": "一般",
                                   "description": "压测造数请忽略",
                                   "reporter_name": "压测", "reporter_phone": "13800138000"})
        else:
            dur, cls, code = _req("GET", "/api/web/issues?limit=20", rtok)
        return kind, dur, cls, code
    return run


def _bench(concurrency, run):
    lat = []
    tally = {"ok": 0, "throttle": 0, "client": 0, "server": 0, "conn": 0}
    codes: dict = {}
    per_kind: dict = {}
    start = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        for kind, dur, cls, code in ex.map(run, range(TOTAL)):
            lat.append(dur)
            tally[cls] = tally.get(cls, 0) + 1
            codes[code] = codes.get(code, 0) + 1
            k = per_kind.setdefault(kind, {"n": 0, "ok": 0, "throttle": 0, "client": 0,
                                           "server": 0, "conn": 0, "codes": {}})
            k["n"] += 1
            k[cls] += 1
            k["codes"][code] = k["codes"].get(code, 0) + 1
    total = time.perf_counter() - start
    lat.sort()
    n = len(lat)

    def p(q):
        return lat[int(q * (n - 1))] * 1000
    return {"concurrency": concurrency, "qps": n / total,
            "p50": round(p(0.50), 1), "p95": round(p(0.95), 1), "p99": round(p(0.99), 1),
            "requests": n, "tally": tally, "codes": codes, "per_kind": per_kind,
            # 「错误率」只统计真问题：客户端参数问题 + 服务端故障 + 连接失败（限流单列）
            "err_rate": round((tally["client"] + tally["server"] + tally["conn"]) / n * 100, 3),
            "throttle_rate": round(tally["throttle"] / n * 100, 3),
            "server_err": tally["server"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    rtok = _login_resident(args.base)
    gtok = _login_grid(args.base)
    run = _build(rtok, gtok)
    print(f"业务混合压测（base={args.base}，并发阶梯 {LADDER}，每档 {TOTAL} 请求）")
    print(f"混合比例：issues/chat/notices/policy/create = "
          f"{'/'.join(f'{k}:{int(p*100)}%' for k, p in MIX)}")
    rows = []
    for c in LADDER:
        row = _bench(c, run)
        rows.append(row)
        t = row["tally"]
        print(f"  conc={c:>4} qps={row['qps']:7.1f} p50={row['p50']:7.1f}ms "
              f"p95={row['p95']:7.1f}ms p99={row['p99']:7.1f}ms "
              f"| 成功={t['ok']} 限流={t['throttle']} 客户端4xx={t['client']} "
              f"服务端5xx={t['server']} 连接失败={t['conn']}")
        print(f"        状态码分布：{row['codes']}")
        for kind, k in row["per_kind"].items():
            print(f"          {kind:<12} n={k['n']:<4} 成功={k['ok']:<4} 限流={k['throttle']:<4} "
                  f"4xx={k['client']:<4} 5xx={k['server']} {k['codes']}")
    print("\n| 并发 | QPS | p50(ms) | p95(ms) | p99(ms) | 成功 | 限流 | 4xx | 5xx |")
    print("|------|-----|---------|---------|---------|------|------|-----|-----|")
    for r in rows:
        t = r["tally"]
        print(f"| {r['concurrency']} | {r['qps']:.1f} | {r['p50']} | {r['p95']} | {r['p99']} | "
              f"{t['ok']} | {t['throttle']} | {t['client']} | {t['server']} |")
    print("\n口径说明（重要）：")
    print("  · **限流**（400 + code 1002「您说得有点快」）是 agent 对话的防刷设计，压测必然触发，"
          "不算故障——它在真实使用时保护服务不被刷。")
    print("  · **客户端 4xx** 通常是压测载荷不符接口契约（例：上报必须带合法手机号），应在脚本里修掉。")
    print("  · **服务端 5xx / 连接失败** 才是真故障：本脚本的合格线是 **5xx = 0**。")
    print("  · 业务压测会真实写入工单数据（create_issue 10%），跑完建议清理或使用演示库。")


if __name__ == "__main__":
    main()
