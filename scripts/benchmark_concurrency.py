# -*- coding: utf-8 -*-
"""并发压测：复现「550 并发零失败」。

用法：先起服务，再 python scripts/benchmark_concurrency.py

⚠️ 踩过的坑（2026-09-15 实测）：本脚本以前不做探活，**服务没在跑时会打印
「成功率 0/550 = 0.0%」并断言失败**——看起来像"并发扛不住"，实际是"服务没启动"。
这种误导性结论在答辩现场是致命的（你会当场说错话），所以现在先探活：
服务不可用直接退出并给出正确解读，不产出"并发失败"的假结论。
"""
import concurrent.futures as cf
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
ENDPOINT = "/api/web/auth/demo"
CONCURRENCY = 550
BODY = b'{"role":"resident","mode":"demo"}'
HEADERS = {"Content-Type": "application/json"}


def preflight() -> bool:
    """探活：服务必须真的在跑，否则后面的失败率毫无意义。"""
    try:
        with urllib.request.urlopen(f"{BASE}/api/web/health", timeout=8) as r:
            body = json.loads(r.read().decode("utf-8"))
        svc = (body.get("data") or {}).get("service")
        print(f"服务探活：OK  {svc}（{BASE}）")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"服务探活：失败，无法访问 {BASE}（{type(e).__name__}: {e}）")
        print("  处理：先启动服务 → python scripts/serve_public.py --no-tunnel --no-open")
        print("  注意：此时不要解读为「并发能力不足」——服务根本没在跑。")
        return False


def _hit(_):
    req = urllib.request.Request(BASE + ENDPOINT, data=BODY, headers=HEADERS)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            return time.perf_counter() - t0, (200, True)
    except urllib.error.HTTPError as e:       # 4xx/5xx 才算真失败，且记录状态码
        return time.perf_counter() - t0, (e.code, False)
    except Exception:                          # 连接层失败
        return time.perf_counter() - t0, (None, False)


def main() -> int:
    if not preflight():
        return 2
    lat, ok, codes = [], 0, {}
    start = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for dur, (code, success) in ex.map(_hit, range(CONCURRENCY)):
            lat.append(dur)
            ok += 1 if success else 0
            codes[code] = codes.get(code, 0) + 1
    total = time.perf_counter() - start
    lat.sort()
    n = len(lat)
    print(f"并发数: {CONCURRENCY}")
    print(f"成功率: {ok}/{n} = {ok/n*100:.1f}%")
    print(f"总耗时: {total:.2f}s | 吞吐: {n/total:.0f} req/s")
    print(f"延迟 p50={lat[n//2]*1000:.0f}ms p95={lat[int(n*.95)]*1000:.0f}ms "
          f"p99={lat[int(n*.99)]*1000:.0f}ms max={lat[-1]*1000:.0f}ms")
    print(f"状态码分布: {codes}")
    print("口径说明：本项压的是**演示登录端点**（轻量读），结论是「高并发下不崩、不锁库、无 500」；"
          "业务混合压测（p50/p95/p99 + QPS + 错误率）见 scripts/benchmark_business.py。")
    if ok != n:
        print(f"结论：存在失败请求（状态码分布 {codes}）")
        return 1
    print("结论：550 并发零失败 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
