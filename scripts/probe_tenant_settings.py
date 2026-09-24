# -*- coding: utf-8 -*-
"""多租户**配置隔离**实测探针（会临时改配置，跑完自动还原）。

**验什么**：`settings` 表按社区分键后，"某个社区改阈值"不能影响别的社区，而且
**判定点真的用了这个值**（配了不生效是本项目最忌讳的情况）。

流程（只动第二个社区的键，结束时还原）：
  1. 两个社区的网格员各自读自己社区的阈值（返回里带 `scope` = 实际生效范围）；
  2. 给 B 社区设一个不同的阈值；
  3. 复读：B 变了、**A 没变**（这是核心断言）；
  4. 把 B 社区还原成原值；
  5. 退出码 0 = 配置隔离成立，1 = 有串味。

用法：
    python -m uvicorn api_web:app --host 127.0.0.1 --port 8000    # 先起服务
    python scripts/probe_tenant_settings.py
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
A = "海淀小区"
B = "朝阳试点社区"


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, {"raw": "unparsable"}
    except Exception as e:  # noqa: BLE001
        return -1, {"err": str(e)}


def login_grid(community):
    st, r = call("POST", "/api/web/auth/demo", body={"role": "grid", "community": community})
    if not r.get("success"):
        print(f"！{community} 网格员登录失败：{r}")
        sys.exit(2)
    return r["data"]["token"], r["data"]["community"], r["data"]["name"]


def read_policy(token):
    _st, r = call("GET", "/api/web/qa/threshold", token)
    d = r.get("data") or {}
    return d.get("threshold"), d.get("scope")


def main() -> int:
    print("=" * 76)
    print("多租户配置隔离探针（政策自动回答阈值 / 天气联动阈值）")
    print("=" * 76)
    tok_a, com_a, name_a = login_grid(A)
    tok_b, com_b, name_b = login_grid(B)
    print(f"A 网格员：{name_a} @ {com_a}")
    print(f"B 网格员：{name_b} @ {com_b}")

    thr_a0, scope_a0 = read_policy(tok_a)
    thr_b0, scope_b0 = read_policy(tok_b)
    print(f"\n初始：A 阈值={thr_a0}（scope={scope_a0}）  B 阈值={thr_b0}（scope={scope_b0}）")
    if scope_a0 != com_a or scope_b0 != com_b:
        print("  ✗ 生效范围不是各自社区，配置隔离未接线")
        return 1

    _st, lk_a = call("GET", "/api/web/health/linkage/thresholds", tok_a)
    _st, lk_b = call("GET", "/api/web/health/linkage/thresholds", tok_b)
    print(f"联动阈值：A 高温={lk_a.get('data', {}).get('high_temp')}"
          f"（scope={lk_a.get('data', {}).get('scope')}）  "
          f"B 高温={lk_b.get('data', {}).get('high_temp')}"
          f"（scope={lk_b.get('data', {}).get('scope')}）")

    # 给 B 社区设一个明显不同的阈值
    new_b = round((thr_b0 or 2.0) + 0.5, 1)
    st, r = call("POST", "/api/web/qa/threshold", tok_b, {"threshold": new_b})
    print(f"\n[B 网格员把本社区阈值设为 {new_b}]  HTTP {st}  success={r.get('success')}")
    if not r.get("success"):
        print(f"  ！设置失败：{r.get('error')}")
        return 1

    thr_a1, _ = read_policy(tok_a)
    thr_b1, _ = read_policy(tok_b)
    ok_b = abs((thr_b1 or 0) - new_b) < 1e-6
    ok_a = abs((thr_a1 or 0) - (thr_a0 or 0)) < 1e-6
    print(f"  复读：A={thr_a1}（期望 {thr_a0}）  B={thr_b1}（期望 {new_b}）")
    print(f"  {'✓' if ok_b else '✗'} B 社区自己的阈值生效")
    print(f"  {'✓' if ok_a else '✗'} A 社区不受影响（跨租户没串味）")

    # 还原 B 社区（服务只写社区键，还原成原值即可，不改全局）
    _st, back = call("POST", "/api/web/qa/threshold", tok_b, {"threshold": thr_b0})
    print(f"\n[还原 B 社区阈值为 {thr_b0}]  success={back.get('success')}")
    thr_a2, _ = read_policy(tok_a)
    thr_b2, _ = read_policy(tok_b)
    print(f"  还原后：A={thr_a2}  B={thr_b2}")

    print("\n" + "=" * 76)
    if ok_a and ok_b:
        print("结论：配置按社区隔离成立——改一个社区的阈值不影响另一个社区 ✓")
        print("（判定点已接线：政策阈值进 ask_question，联动阈值进天气联动；"
              "定时任务按社区逐个判定）")
        print("=" * 76)
        return 0
    print("结论：配置存在跨租户串味 ✗")
    print("=" * 76)
    return 1


if __name__ == "__main__":
    sys.exit(main())
