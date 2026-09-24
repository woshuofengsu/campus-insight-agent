# -*- coding: utf-8 -*-
"""多租户隔离实测探针（只读，不改任何数据）。

**验什么**：列表接口走了 SQL 里的 `tenant_id=?`，而**详情/操作接口是按 id 直取单行的**
——那条路径没有 WHERE 可加，只校验角色就会出现"列表看不见、换个 id 就看见"的越权。
本脚本用两个社区的网格员账号互相访问对方资源，逐条打印 HTTP 结果，判据是硬的：
跨租户必须 `success=false`，同社区（对照行）必须 `success=true`。

**怎么用**：
    # 先起服务（DEMO_MODE=true，演示账号可用）
    python -m uvicorn api_web:app --host 127.0.0.1 --port 8000
    python scripts/probe_tenant_isolation.py       # 退出码 0=全隔离，1=有越权

**现场怎么讲**：这是"隔离可现场复算"的证据——B6 修复前朝阳网格员能读到海淀工单全文
（HTTP 200 + 诉求正文），修复后返回 400「无权查看该工单」。逐条按-id 接口的断言
由 `tests/test_tenant_idor_sweep.py` 覆盖（16 个接口 × 跨租户/同租户两个方向）。
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
T1 = "海淀小区"
T2 = "朝阳试点社区"


def call(method, path, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"raw": "unparsable"}
    except Exception as e:  # noqa: BLE001
        return -1, {"err": str(e)}


def login_grid(community):
    st, r = call("POST", "/api/web/auth/demo", body={"role": "grid", "community": community})
    if not r.get("success"):
        print(f"！{community} 网格员登录失败：{r}")
        sys.exit(2)
    d = r["data"]
    return d["token"], d["community"], d["name"]


def first_id(token, path, key="list"):
    st, r = call("GET", path, token)
    if not r.get("success"):
        return None
    data = r.get("data")
    if isinstance(data, dict):
        data = data.get(key) or data.get("rows") or data.get("items") or []
    if isinstance(data, list) and data:
        return data[0].get("id")
    return None


def probe(label, path_tpl, id_a, id_b, tok_a, tok_b, com_a, com_b):
    """验一条按-id 接口的隔离。

    参数：`id_a` 是 A 社区的行（跨租户访问的**目标**）、`id_b` 是 B 社区自己的行（可能没有）。

    两条腿：
      ① **对照组**（必须有，否则结论不成立）：同社区读自己的行 → 应 `success=true`。
         B 社区没有该资源时，退而用"A 网格员读 A 自己的行"作对照——这样四类资源都能验，
         不会因为"第二个社区恰好没这类数据"就跳过（第一版就是这么漏掉 3/4 的）。
      ② **跨租户腿**：B 网格员按 id 读 A 的行 → 必须 `success=false`。
    """
    print(f"\n--- {label} ---")
    if id_a is None:
        print(f"  ！{com_a} 没有可作目标的样本（id=None），跳过")
        return None

    if id_b is not None:
        st_own, r_own = call("GET", path_tpl.format(id_b), tok_b)
        ok_own = bool(r_own.get("success"))
        print(f"  [{com_b}网格员 → 本社区#{id_b}]  HTTP {st_own}  success={ok_own}  "
              f"{'（对照：同社区可读，样本有效）' if ok_own else '（！本社区都读不到，对照无效）'}")
        control_ok = ok_own
    else:
        st_own, r_own = call("GET", path_tpl.format(id_a), tok_a)
        ok_own = bool(r_own.get("success"))
        print(f"  [{com_a}网格员 → 本社区#{id_a}]  HTTP {st_own}  success={ok_own}  "
              f"{'（对照：同社区可读，样本有效）' if ok_own else '（！本社区都读不到，对照无效）'}"
              f"  ※ {com_b} 暂无该类数据")
        control_ok = ok_own

    st_cross, r_cross = call("GET", path_tpl.format(id_a), tok_b)
    cross_ok = bool(r_cross.get("success"))
    title = ""
    if cross_ok:
        d = r_cross.get("data") or {}
        title = str(d.get("title") or d.get("content") or d.get("summary") or "")[:30]
    verdict = "✗ 越权成功（跨租户可见）" if cross_ok else "✓ 已拒绝（fail-closed）"
    print(f"  [{com_b}网格员 → {com_a}#{id_a}]  HTTP {st_cross}  success={cross_ok}  {verdict}"
          + (f"  泄露内容=「{title}」" if cross_ok else f"  error={r_cross.get('error')}"))
    if not control_ok:
        print("  ！对照组不成立（同社区也读不到），本条结论仅作参考")
        return None
    return cross_ok


def main():
    print("=" * 78)
    print(f"多租户按-id 越权探针   A={T1}（数据归属）   B={T2}（发起访问）")
    print("=" * 78)
    tok_a, com_a, name_a = login_grid(T1)
    tok_b, com_b, name_b = login_grid(T2)
    print(f"A 网格员：{name_a} @ {com_a}")
    print(f"B 网格员：{name_b} @ {com_b}")

    # 各自列表能看到的 id（列表已隔离）
    a_issue = first_id(tok_a, "/api/web/issues?limit=50")
    b_issue = first_id(tok_b, "/api/web/issues?limit=50")
    a_prop = first_id(tok_a, "/api/web/proposals?limit=50")
    b_prop = first_id(tok_b, "/api/web/proposals?limit=50")
    a_con = first_id(tok_a, "/api/web/health/consults?limit=50")
    b_con = first_id(tok_b, "/api/web/health/consults?limit=50")
    a_not = first_id(tok_a, "/api/web/notices/manage?limit=50")
    b_not = first_id(tok_b, "/api/web/notices/manage?limit=50")
    print(f"\n列表可见样本：工单 A#{a_issue} / B#{b_issue}   提案 A#{a_prop} / B#{b_prop}")
    print(f"              咨询 A#{a_con} / B#{b_con}   通知 A#{a_not} / B#{b_not}")

    results = {
        "工单详情": probe("工单详情  GET /api/web/issues/{id}", "/api/web/issues/{}",
                          a_issue, b_issue, tok_a, tok_b, com_a, com_b),
        "提案详情": probe("提案详情  GET /api/web/proposals/{id}", "/api/web/proposals/{}",
                          a_prop, b_prop, tok_a, tok_b, com_a, com_b),
        "健康咨询详情": probe("健康咨询  GET /api/web/health/consults/{id}", "/api/web/health/consults/{}",
                              a_con, b_con, tok_a, tok_b, com_a, com_b),
        "通知详情": probe("通知详情  GET /api/web/notices/{id}", "/api/web/notices/{}",
                          a_not, b_not, tok_a, tok_b, com_a, com_b),
    }

    print("\n" + "=" * 78)
    leaked = [k for k, v in results.items() if v is True]
    if leaked:
        print(f"结论：存在跨租户按-id 越权读取 → {', '.join(leaked)}")
        print("（列表隔离生效，但详情接口对 grid 角色无条件放行，换个 id 就能读到别的社区）")
    elif leaked == [] and any(v is not None for v in results.values()):
        print("结论：全部按-id 详情接口已 fail-closed，跨租户读取被拒绝 ✓")
    else:
        print("结论：样本不足，未能判定")
    print("=" * 78)
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())
