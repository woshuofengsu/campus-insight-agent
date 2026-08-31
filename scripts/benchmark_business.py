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
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            resp.read()
            return time.perf_counter() - t0, resp.status == 200
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, (200 <= e.code < 300)
    except Exception:
        return time.perf_counter() - t0, False


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
    """返回一个请求执行函数（按比例从真实端点抽取）。"""
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
            return _req("POST", "/api/web/agent/chat", rtok,
                        {"text": random.choice(["家里水管漏水了", "楼道灯不亮", "申请垃圾分类提案", "今天会下雨吗"])})[0], True
        if kind == "notices":
            return _req("GET", "/api/web/notices", rtok)
        if kind == "policy_faq":
            return _req("GET", "/api/web/qa/high-freq", rtok)
        if kind == "create_issue":
            return _req("POST", "/api/web/issues", rtok,
                        {"title": random.choice(["楼道灯坏了", "电梯按键失灵", "垃圾桶满"]),
                         "category": "设施维修", "location": "3号楼", "urgency": "普通",
                         "description": "压测造数请忽略", "reporter_phone": ""})
        # issues 列表
        return _req("GET", "/api/web/issues?limit=20", rtok)
    return run


def _bench(concurrency, run):
    lat, ok, err = [], 0, 0
    start = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        for dur, success in ex.map(run, range(TOTAL)):
            lat.append(dur)
            if success:
                ok += 1
            else:
                err += 1
    total = time.perf_counter() - start
    lat.sort()
    n = len(lat)

    def p(q):
        return lat[int(q * (n - 1))] * 1000
    return {"concurrency": concurrency, "qps": n / total,
            "p50": round(p(0.50), 1), "p95": round(p(0.95), 1), "p99": round(p(0.99), 1),
            "err_rate": round(err / n * 100, 3), "requests": n}


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
        print(f"  conc={c:>4} qps={row['qps']:7.1f} p50={row['p50']:7.1f}ms "
              f"p95={row['p95']:7.1f}ms p99={row['p99']:7.1f}ms 错误率={row['err_rate']}%")
    # 输出 markdown（材料口径回填用）
    print("\n| 并发 | QPS | p50(ms) | p95(ms) | p99(ms) | 错误率% |")
    print("|------|-----|---------|---------|---------|---------|")
    for r in rows:
        print(f"| {r['concurrency']} | {r['qps']:.1f} | {r['p50']} | {r['p95']} | {r['p99']} | {r['err_rate']} |")


if __name__ == "__main__":
    main()
