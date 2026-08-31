# -*- coding: utf-8 -*-
"""并发压测：复现「550 并发零失败」。只读/轻写端点。
用法：先起服务，再 python scripts/benchmark_concurrency.py"""
import concurrent.futures as cf
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
ENDPOINT = "/api/web/auth/demo"
CONCURRENCY = 550
BODY = b'{"role":"resident","mode":"demo"}'
HEADERS = {"Content-Type": "application/json"}


def _hit(_):
    req = urllib.request.Request(BASE + ENDPOINT, data=BODY, headers=HEADERS)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            return time.perf_counter() - t0, r.status == 200
    except Exception:
        return time.perf_counter() - t0, False


def main():
    lat, ok = [], 0
    start = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for dur, success in ex.map(_hit, range(CONCURRENCY)):
            lat.append(dur)
            ok += 1 if success else 0
    total = time.perf_counter() - start
    lat.sort()
    n = len(lat)
    print(f"并发数: {CONCURRENCY}")
    print(f"成功率: {ok}/{n} = {ok/n*100:.1f}%")
    print(f"总耗时: {total:.2f}s | 吞吐: {n/total:.0f} req/s")
    print(f"延迟 p50={lat[n//2]*1000:.0f}ms p95={lat[int(n*.95)]*1000:.0f}ms "
          f"p99={lat[int(n*.99)]*1000:.0f}ms max={lat[-1]*1000:.0f}ms")
    assert ok == n, "存在失败请求"
    print("结论：550 并发零失败 ✅")


if __name__ == "__main__":
    main()
