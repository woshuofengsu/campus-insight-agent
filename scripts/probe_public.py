# -*- coding: utf-8 -*-
"""公网入口端到端探测：证明"外人从公网进来"这条链路完整可用，而不只是 /health 通。

检查项：健康身份 / 登录页 / 三角色登录 / 智能体对话（真实走编排器）/ 静态资源。
用法：python scripts/probe_public.py [url]   （默认读 .shots/当前公网地址.txt）
"""
import json
import os
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_FILE = os.path.join(ROOT, ".shots", "当前公网地址.txt")


def _bypass_local_dns(host: str) -> None:
    """本机解析器打不开这个新域名时（校园网常见），用公共 DNS 解析并改写本进程解析结果。

    实测：校园 DNS 对刚创建的 *.trycloudflare.com 返回 NXDOMAIN，8.8.8.8 正常。
    不改写就没法在这台机器上验证公网链路（会误判成"隧道坏了"）。
    """
    try:
        from net_probe import describe_dns, local_dns_ok, patch_getaddrinfo, resolve_bypass
    except ImportError:
        return
    if local_dns_ok(host):
        return
    ip, how = resolve_bypass(host)
    print(f"  ⓘ {describe_dns(host)}")
    if ip:
        patch_getaddrinfo(host, ip)
        print(f"  ⓘ 已临时改用 {how} 解析（{ip}）继续校验；TLS SNI 仍是原域名，证书校验不受影响\n")


def base() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1].rstrip("/")
    if os.path.exists(URL_FILE):
        return open(URL_FILE, encoding="utf-8").read().strip().rstrip("/")
    sys.exit("未指定 URL，且没有 .shots/当前公网地址.txt（先跑 scripts/serve_public.py）")


def req(method: str, path: str, body: dict | None = None, token: str | None = None,
        timeout: int = 25):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base() + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return resp.status, json.loads(raw)
    except json.JSONDecodeError:
        return resp.status, raw


def main() -> int:
    b = base()
    print(f"目标：{b}\n")
    _bypass_local_dns(b.split("//", 1)[-1].split("/")[0])
    ok = bad = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok, bad
        if cond:
            ok += 1
            print(f"  ✅ {name}{(' — ' + detail) if detail else ''}")
        else:
            bad += 1
            print(f"  ❌ {name}{(' — ' + detail) if detail else ''}")

    # 1) 健康 + 服务身份
    try:
        st, d = req("GET", "/api/web/health")
        svc = ((d or {}).get("data") or {}).get("service")
        check("健康检查（服务身份）", st == 200 and svc == "CommunityInsight Web", f"{st} {svc}")
    except urllib.error.URLError as e:
        check("健康检查（服务身份）", False, f"URLError {e}")
        print("\n公网不可达，后续检查跳过（先 --status 确认隧道，或等几秒重试）")
        return 1

    # 2) 登录页（SPA 首页，公网能拿到 HTML）
    st, html = req("GET", "/login")
    n = len(html) if isinstance(html, str) else 0
    check("登录页 HTML", st == 200 and n > 800, f"{st} {n} 字节")

    # 3) PWA 清单与图标（手机"添加到主屏幕"用）
    st, _ = req("GET", "/manifest.json")
    check("PWA manifest", st == 200, str(st))
    st, _ = req("GET", "/icon-192.png")
    check("PWA 图标 192", st == 200, str(st))

    # 4) 三角色进入（契约：POST /api/web/auth/demo {role} → data.token；网格员另有密码登录）
    token = None
    for label, path, body in (
        ("网格员 密码登录 demo_grid/demo123", "/api/web/auth/login",
         {"username": "demo_grid", "password": "demo123"}),
        ("居民 演示登录", "/api/web/auth/demo", {"role": "resident"}),
        ("老年 演示登录", "/api/web/auth/demo", {"role": "elderly"}),
    ):
        try:
            st, d = req("POST", path, body)
            data = (d or {}).get("data") or {}
            tk = data.get("token")
            check(f"进入 {label}", st == 200 and bool(tk), f"{st} role={data.get('role')}")
            if label.startswith("居民"):
                token = token or tk
        except urllib.error.HTTPError as e:
            check(f"进入 {label}", False, f"HTTP {e.code}")

    # 5) 智能体对话：真走多智能体编排（公网链路 + 业务链路一起验）
    if token:
        try:
            st, d = req("POST", "/api/web/agent/chat",
                        {"text": "我家水管漏水了，麻烦安排师傅"}, token, timeout=90)
            data = (d or {}).get("data") or {}
            reply = str(data.get("reply") or "")
            route = data.get("agent") or data.get("route") or data.get("intent") or data.get("handled_by")
            check("智能体对话（报修）", st == 200 and bool(reply),
                  f"{st} 路由={route} 回复{len(reply)}字")
        except urllib.error.HTTPError as e:
            check("智能体对话（报修）", False, f"HTTP {e.code}")
    else:
        check("智能体对话（报修）", False, "没有拿到 token")

    print(f"\n结果：{ok} 通过 / {bad} 失败")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
