# -*- coding: utf-8 -*-
"""演示前一键体检 / 复位（现场用）。

**为什么必须有它**：彩排、试讲、点错按钮都会在库里留下"半途状态"，而有些状态会**直接卡住演示步骤**。
2026-09-24 实测踩到：老年端有一条 **2026-09-14 遗留的「求助中」SOS**，于是
① 首页一直显示"最近求助：求助中"（观众以为系统没处理）；
② `trigger_sos` 有"已有进行中的求助不重复触发"的保护 → **场景 5 的 SOS 现场根本点不动**。

本工具做两件事：
- **体检**（默认，只读）：列出可能影响演示的状态并给出结论；
- **复位**（`--apply`）：把"卡住流程"的状态**通过业务接口**收干净（不是裸改库，会留痕）。

用法：
    python scripts/demo_reset.py                 # 只体检（安全，随时可跑）
    python scripts/demo_reset.py --apply         # 体检 + 复位（会写库、会留痕）
    python scripts/demo_reset.py --base http://10.101.179.6:8000 --apply
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

DEFAULT_BASE = "http://127.0.0.1:8000"


def call(method, path, token=None, body=None, base=DEFAULT_BASE, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, {"error": "响应无法解析"}
    except Exception as e:  # noqa: BLE001
        return -1, {"error": str(e)}


def grid_token(base: str, community: str = "海淀小区"):
    st, r = call("POST", "/api/web/auth/demo", body={"role": "grid", "community": community},
                 base=base)
    if not r.get("success"):
        print(f"❌ 拿不到 {community} 网格员身份：{r.get('error')}")
        return None
    return r["data"]["token"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--apply", action="store_true", help="真正执行复位（默认只体检）")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    problems: list[str] = []

    print("=" * 78)
    print(f"演示前体检 · {base}" + ("　【复位模式：会写库】" if args.apply else "　【只读体检】"))
    print("=" * 78)

    tok = grid_token(base)
    if not tok:
        return 2

    # ---------- 1. 遗留的进行中 SOS（会卡住场景 5） ----------
    print("\n① 紧急求助（SOS）状态")
    st, r = call("GET", "/api/web/elderly/manage/sos?limit=50", tok, base=base)
    rows = r.get("data") or []
    open_rows = [x for x in rows if x.get("status") in ("求助中", "已响应")]
    if not open_rows:
        print("   ✅ 没有未结束的求助（现场可以完整演示 SOS）")
    else:
        for x in open_rows:
            print(f"   ⚠️ #{x['id']} 状态「{x['status']}」{x.get('created_at')} —— "
                  f"**会阻塞现场再次触发 SOS**")
        problems.append(f"{len(open_rows)} 条未结束的 SOS 会阻塞现场演示")
        if args.apply:
            for x in open_rows:
                cid = x["id"]
                if x["status"] == "求助中":
                    call("POST", f"/api/web/elderly/emergency/{cid}/action", tok,
                         {"action": "respond"}, base=base)
                st2, r2 = call("POST", f"/api/web/elderly/emergency/{cid}/action", tok,
                               {"action": "close",
                                "handle_note": "演示前复位：历史遗留的进行中求助，现场确认处置"},
                               base=base)
                print(f"      → 已关闭 #{cid}（HTTP {st2}，留痕已记）"
                      if r2.get("success") else f"      → 关闭 #{cid} 失败：{r2.get('error')}")

    # ---------- 2. 遗留草稿（会把上一次报修的描述带进新的确认卡片）----------
    print("\n② 遗留草稿（现场高危：新报修的确认卡片可能写着上次的问题）")
    for role, accounts in (("resident", [("demo_resident", ""), ("demo_resident_cy", "demo123")]),):
        for user, pwd in accounts:
            st, r = call("POST", "/api/web/auth/login", body={"username": user, "password": pwd},
                         base=base)
            if not r.get("success"):
                print(f"   ⚠️ {user} 登录失败，跳过")
                continue
            t = r["data"]["token"]
            # 「取消」是应用自带的**清草稿**路径（orchestrator 对取消会清空草稿与会话状态），
            # 比裸删库表干净：走的是业务逻辑，且不会留下不一致状态。
            st2, r2 = call("POST", "/api/web/agent/chat", t, {"text": "取消"}, base=base)
            ok = bool(r2.get("success"))
            print(f"   {'✅' if ok else '⚠️'} {user}：已清空遗留草稿与会话"
                  f"（{str((r2.get('data') or {}).get('reply'))[:26]}）")

    # ---------- 3. 演示要用的两社区数据是否都在 ----------
    print("\n③ 两社区演示数据")
    for com in ("海淀小区", "朝阳试点社区"):
        t = grid_token(base, com)
        if not t:
            problems.append(f"{com} 拿不到网格员身份（两社区对比演示会失败）")
            continue
        st, r = call("GET", "/api/web/issues?limit=500", t, base=base)
        n = len(r.get("data") or []) if isinstance(r.get("data"), list) else "?"
        flag = "✅" if isinstance(n, int) and n > 0 else "⚠️"
        print(f"   {flag} {com}：网格端可见工单 {n} 条")
        if not isinstance(n, int) or n == 0:
            problems.append(f"{com} 网格端看不到工单")

    # ---------- 3. 老年端可演示项 ----------
    print("\n④ 老年端可演示项")
    st, r = call("POST", "/api/web/auth/demo", body={"role": "elderly"}, base=base)
    etok = r["data"]["token"] if r.get("success") else None
    if not etok:
        problems.append("老年端演示账号拿不到（免登录入口异常）")
    else:
        for label, path in (("用药提醒", "/api/web/elderly/medications"),
                            ("紧急联系人", "/api/web/elderly/emergency-contacts"),
                            ("健康记录", "/api/web/elderly/vitals")):
            st, r = call("GET", path, etok, base=base)
            data = r.get("data")
            n = len(data) if isinstance(data, list) else "?"
            ok = isinstance(n, int) and n > 0
            print(f"   {'✅' if ok else '⚠️'} {label}：{n} 条")
            if not ok:
                problems.append(f"老年端「{label}」为空，演示时是空页面")

    # ---------- 4. 网格端演示面 ----------
    print("\n⑤ 网格端演示面")
    for label, path in (("人工处理包", "/api/web/agent/handoffs?limit=50"),
                        ("通知管理", "/api/web/notices/manage?limit=200"),
                        ("知识库", "/api/web/knowledge?limit=300"),
                        ("Agent 留痕", "/api/web/agent/logs?limit=50")):
        st, r = call("GET", path, tok, base=base)
        data = r.get("data")
        n = len(data) if isinstance(data, list) else "?"
        print(f"   {'✅' if isinstance(n, int) and n > 0 else '⚠️'} {label}：{n} 条")

    # ---------- 5. 前端产物新鲜度 ----------
    print("\n⑥ 前端产物（改了 web/src 没 build 会演旧包）")
    st, r = call("GET", "/api/web/auth/me", base=base)     # 未登录 → 401，说明服务活着
    print(f"   {'✅' if st == 401 else '⚠️'} 服务鉴权在位（未登录 /me → HTTP {st}，期望 401）")

    print("\n" + "=" * 78)
    if problems:
        print(f"体检结论：发现 {len(problems)} 项需要注意")
        for p in problems:
            print(f"   · {p}")
        if not args.apply:
            print("\n跑 `python scripts/demo_reset.py --apply` 可自动收掉其中可自动处理的部分。")
    else:
        print("体检结论：全部就绪 ✅")
    print("=" * 78)
    return 0 if not problems or args.apply else 1


if __name__ == "__main__":
    sys.exit(main())
