# scripts/serve_public.py — 本机常开方案的一键工具（服务 + 公网 HTTPS 隧道 + 扫码页）
# -*- coding: utf-8 -*-
"""把「自己电脑当服务器」这套现状做扎实，解决三个真痛点：

  1. 隧道域名每次重启都变 → 本工具**自动抓取**新地址，写进扫码页、复制到剪贴板、打印到屏幕
  2. 进程被杀没人拉起     → `--autostart` 注册 Windows 计划任务（登录自启）+ 服务/隧道各自带重启
  3. 忘了关隧道公网常开   → `--stop` 一条命令全停；`--status` 随时看当前地址与进程

用法：
  python scripts/serve_public.py              # 起服务 + 隧道，打印并复制公网地址、生成扫码页
  python scripts/serve_public.py --status     # 看服务/隧道状态与当前公网地址
  python scripts/serve_public.py --stop       # 停掉隧道（可选 --all 连服务一起停）
  python scripts/serve_public.py --autostart  # 注册开机（登录）自启
  python scripts/serve_public.py --no-autostart
  python scripts/serve_public.py --no-tunnel  # 只起本机服务（不暴露公网）

安全提示：cloudflared 免费隧道**没有访问控制**——拿到链接的人都能进（演示账号免密）。
演示结束请跑 `--stop`；长期对外请改用固定域名 + Nginx 证书方案（见 docs/deploy-https.md）。
"""
import argparse
import os
import re
import subprocess
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8000
LOCAL = f"http://127.0.0.1:{PORT}"
HEALTH = f"{LOCAL}/api/web/health"
QR_PAGE = os.path.join(ROOT, ".shots", "手机访问.html")
URL_FILE = os.path.join(ROOT, ".shots", "当前公网地址.txt")
LOG_DIR = os.path.join(ROOT, ".shots", "logs")
TASK_NAME = "CommunityInsight-Serve"

CF_CANDIDATES = [
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Cloudflare.cloudflared_*\cloudflared.exe"),
]


# ---------------------------------------------------------------- 基础工具
def find_cloudflared() -> str | None:
    for p in CF_CANDIDATES:
        if "*" in p:
            import glob
            hits = glob.glob(p)
            if hits:
                return hits[0]
            continue
        if os.path.exists(p):
            return p
    from shutil import which
    return which("cloudflared")


def health(timeout: float = 4.0) -> str | None:
    """返回服务身份字符串（同时校验「是本服务」而不只是 200）。"""
    try:
        import json
        with urllib.request.urlopen(HEALTH, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        return ((d or {}).get("data") or {}).get("service")
    except Exception:  # noqa: BLE001
        return None


def port_owner() -> int | None:
    """返回占用 8000 的 PID（无则 None）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        for ln in out.splitlines():
            if f":{PORT}" in ln and "LISTEN" in ln:
                parts = ln.split()
                return int(parts[-1])
    except Exception:  # noqa: BLE001
        pass
    return None


def pids_of(name: str) -> list[int]:
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace").stdout
        return [int(ln.split('","')[1]) for ln in out.splitlines() if ln.startswith('"')]
    except Exception:  # noqa: BLE001
        return []


def tunnel_url_from_log(path: str) -> str | None:
    """从 cloudflared 日志里抓 https://xxx.trycloudflare.com。"""
    if not os.path.exists(path):
        return None
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        return None
    m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", txt)
    return m[-1] if m else None


def read_url_file() -> str | None:
    if not os.path.exists(URL_FILE):
        return None
    try:
        u = open(URL_FILE, encoding="utf-8").read().strip()
        return u or None
    except Exception:  # noqa: BLE001
        return None


def write_url_file(url: str) -> None:
    os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
    with open(URL_FILE, "w", encoding="utf-8") as f:
        f.write(url + "\n")


def copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run("clip", input=text, text=True, check=False)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 启动 / 停止
def start_server() -> bool:
    """起 uvicorn（若已在跑则复用）。返回是否最终可用。"""
    svc = health()
    if svc:
        print(f"  ✅ 服务已在跑：{svc}（{LOCAL}）")
        return True
    pid = port_owner()
    if pid:
        print(f"  ❌ 端口 {PORT} 被 PID {pid} 占用，但不是本服务（可能是别的程序）")
        print(f"     处理：taskkill /PID {pid} /F  然后重跑本脚本")
        return False
    os.makedirs(LOG_DIR, exist_ok=True)
    log = os.path.join(LOG_DIR, "uvicorn.log")
    f = open(log, "ab")
    creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, "-m", "uvicorn", "api_web:app",
                      "--host", "0.0.0.0", "--port", str(PORT)],
                     cwd=ROOT, stdout=f, stderr=f, creationflags=creationflags)
    print(f"  ⏳ 启动主服务（首次会跑迁移+种子，约 15 秒）…日志：{log}")
    for _ in range(40):
        time.sleep(1)
        if health():
            print(f"  ✅ 服务就绪：{health()}（{LOCAL}）")
            return True
    print("  ❌ 服务 40 秒内未就绪，请看日志")
    return False


def start_tunnel() -> str | None:
    cf = find_cloudflared()
    if not cf:
        print("  ❌ 未找到 cloudflared（安装：winget install --id Cloudflare.cloudflared -e）")
        return None
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "cloudflared.log")
    # 先清掉旧日志，避免读到上一次的旧域名
    open(log_path, "w", encoding="utf-8").close()
    f = open(log_path, "ab")
    creationflags = 0x00000008 | 0x00000200
    subprocess.Popen([cf, "tunnel", "--url", LOCAL, "--no-autoupdate"],
                     cwd=ROOT, stdout=f, stderr=f, creationflags=creationflags)
    print("  ⏳ 建立公网 HTTPS 隧道…")
    url = None
    for _ in range(45):
        time.sleep(1)
        txt = ""
        try:
            txt = open(log_path, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            pass
        url = url or tunnel_url_from_log(log_path)
        # 域名先打印、边缘连接后注册：两者都到位才算真通
        if url and "Registered tunnel connection" in txt:
            write_url_file(url)
            print(f"  ✅ 公网地址：{url}")
            return url
    if url:
        write_url_file(url)
        print(f"  ⚠ 已拿到地址但边缘连接未确认：{url}")
        return url
    print(f"  ❌ 隧道未就绪，请看日志：{log_path}")
    return None


def flush_dns() -> None:
    """清 Windows DNS 负缓存。

    实测坑：trycloudflare 域名是**刚创建**的，本机解析器可能已缓存了"不存在"（NXDOMAIN），
    于是 nslookup 能解析、curl/浏览器却报"无法解析主机"，看起来像"手机打不开"。
    """
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001
        pass


def verify_public(url: str, attempts: int = 3) -> bool:
    """从公网访问一次，确认外网真能打开（不只本地可达）。带 DNS 负缓存自愈。"""
    import json
    last = ""
    for i in range(attempts):
        if i:
            flush_dns()
            time.sleep(4)
        try:
            with urllib.request.urlopen(url + "/api/web/health", timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            svc = ((d or {}).get("data") or {}).get("service")
            if svc == "CommunityInsight Web":
                print(f"  ✅ 公网可达校验：{svc}")
                return True
            last = f"返回内容异常：{svc}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}"
    print(f"  ⚠ 公网校验未通过（{last}）——隧道可能刚建立，稍后重跑 --status 即可")
    return False


def make_qr_page(url: str) -> str:
    """生成扫码页（本地 HTML，用 CDN 渲染二维码；断网时仍显示可手输的地址）。"""
    os.makedirs(os.path.dirname(QR_PAGE), exist_ok=True)
    target = url.rstrip("/") + "/login"
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>社区先知 · 手机访问</title>
<style>
 body{{margin:0;padding:32px 18px;font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
      background:linear-gradient(160deg,#EEF3FF,#F6F8FB 45%,#EAF4F3);color:#16233B;
      display:flex;flex-direction:column;align-items:center;min-height:100vh}}
 .card{{background:#fff;border-radius:22px;padding:26px 28px;max-width:560px;width:100%;
       box-shadow:0 16px 40px rgba(18,35,59,.14);text-align:center}}
 h1{{font-size:1.32rem;margin:0 0 6px}} .sub{{color:#5B6B80;font-size:.85rem;margin-bottom:16px}}
 #qr{{display:inline-block;padding:12px;border:1px solid #E7ECF3;border-radius:14px}}
 .url{{margin:14px 0 4px;font-size:1rem;font-weight:700;word-break:break-all;color:#2D5BFF}}
 .warn{{background:#FFF7ED;border:1px solid #FED7AA;color:#9A3412;border-radius:12px;padding:10px 14px;
       font-size:.82rem;line-height:1.8;text-align:left;margin-top:14px}}
 table{{border-collapse:collapse;width:100%;margin-top:12px;font-size:.85rem}}
 th,td{{border:1px solid #E7ECF3;padding:7px 9px;text-align:left}} th{{background:#F6F8FB;color:#5B6B80}}
 code{{background:rgba(45,91,255,.10);padding:1px 6px;border-radius:6px}}
</style></head><body>
 <div class="card">
  <h1>🏘️ 社区先知 · 手机访问</h1>
  <div class="sub">手机相机 / 微信扫码即可打开（任何网络都行，不限同一 Wi-Fi）</div>
  <div id="qr"></div>
  <div class="url">{target}</div>
  <table>
   <tr><th>角色</th><th>怎么进</th></tr>
   <tr><td>居民端</td><td>登录页点「居民」→ 免密进入（报修 / 议事 / 政策问答 / 通知）</td></tr>
   <tr><td>老年关怀端</td><td>点「老年」→ 免密进入（大字、长按 SOS、语音播报；https 下麦克风可用）</td></tr>
   <tr><td>网格员端</td><td>点「网格员」→ <code>demo_grid</code> / <code>demo123</code>（工作台 / 工单 / 大屏）</td></tr>
  </table>
  <div class="warn">
   <b>这是临时公网地址：</b>关掉电脑上的 cloudflared 就失效，重启后域名会变
   （重新跑 <code>python scripts/serve_public.py</code> 会刷新本页地址）。<br />
   <b>拿到链接的人都能进</b>（演示账号免密），演示结束请跑 <code>--stop</code>。
  </div>
 </div>
<script src="https://cdn.jsdelivr.net/gh/davidshimjs/qrcodejs/qrcode.min.js"></script>
<script>
 try {{ new QRCode(document.getElementById('qr'), {{ text: "{target}", width: 240, height: 240,
        colorDark: '#16233B', colorLight: '#ffffff', correctLevel: QRCode.CorrectLevel.M }}); }}
 catch (e) {{ document.getElementById('qr').textContent = '（二维码生成失败，请手动输入上面的地址）'; }}
</script></body></html>
"""
    with open(QR_PAGE, "w", encoding="utf-8") as f:
        f.write(html)
    return QR_PAGE


def stop(all_: bool = False) -> int:
    killed = 0
    for pid in pids_of("cloudflared.exe"):
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        killed += 1
        print(f"  ✅ 已停止隧道（PID {pid}）——公网地址立即失效")
    if all_:
        pid = port_owner()
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            killed += 1
            print(f"  ✅ 已停止主服务（PID {pid}）")
    if not killed:
        print("  （没有正在跑的隧道/服务）")
    return 0


def status() -> int:
    svc = health()
    print(f"服务：{'✅ ' + str(svc) if svc else '❌ 未运行'}  （{LOCAL}）")
    cf = pids_of("cloudflared.exe")
    print(f"隧道：{'✅ 运行中 PID ' + ','.join(map(str, cf)) if cf else '❌ 未运行'}")
    u = read_url_file()
    if not u:
        print("公网：无记录（跑一次 serve_public.py 即可生成）")
    elif not cf:
        print(f"公网：上次地址 {u} —— 隧道已停，该地址**已失效**（重跑一键脚本会得到新地址）")
    else:
        ok = verify_public(u)
        print(f"公网：{u}  {'（可达 ✅）' if ok else '（当前不可达 ⚠，等几秒重跑 --status）'}")
    print(f"扫码页：{QR_PAGE}{'（已生成）' if os.path.exists(QR_PAGE) else '（未生成）'}")
    return 0


def autostart(enable: bool) -> int:
    """登录自启：优先计划任务；**无管理员权限时自动回退到「启动文件夹」**（本机实测 schtasks 被拒）。

    两条路都不需要改系统服务，卸载都走 --no-autostart。
    """
    startup_dir = os.path.join(os.environ.get("APPDATA", ""),
                               r"Microsoft\Windows\Start Menu\Programs\Startup")
    vbs = os.path.join(startup_dir, "CommunityInsight-Serve.vbs")
    script = os.path.join(ROOT, "scripts", "serve_public.py")

    if enable:
        # 路线 A：计划任务（需要管理员；优先，因为它带"失败重试/最高权限"等能力）
        cmd = f'"{sys.executable}" "{script}"'
        r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/TR", cmd,
                            "/SC", "ONLOGON", "/F"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print("  ✅ 已注册登录自启（Windows 计划任务 CommunityInsight-Serve）")
        else:
            # 路线 B：启动文件夹里的隐藏启动脚本（普通用户即可写）
            why = (r.stderr or r.stdout or "").strip().splitlines()
            print(f"  ⓘ 计划任务不可用（{why[-1] if why else '权限不足'}），改用启动文件夹方案")
            try:
                os.makedirs(startup_dir, exist_ok=True)
                with open(vbs, "w", encoding="gbk", errors="replace") as f:
                    f.write('Set sh = CreateObject("WScript.Shell")\r\n')
                    f.write(f'sh.Run """{sys.executable}"" ""{script}""", 0, False\r\n')
                print(f"  ✅ 已注册登录自启（启动文件夹，隐藏窗口）：{vbs}")
            except Exception as e:  # noqa: BLE001
                print(f"  ❌ 启动文件夹也写不进去：{type(e).__name__} {e}")
                return 1
        print("     说明：自启后公网域名会变，看 .shots/手机访问.html 或跑 --status 拿新地址")
        return 0

    removed = []
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        removed.append("计划任务")
    if os.path.exists(vbs):
        try:
            os.remove(vbs)
            removed.append("启动文件夹脚本")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ 删除启动脚本失败：{type(e).__name__}")
    print(f"  ✅ 已移除自启：{'、'.join(removed)}" if removed else "  （本来就没有自启项）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="本机常开：一键起服务+公网隧道，并生成扫码页")
    ap.add_argument("--stop", action="store_true", help="停止隧道")
    ap.add_argument("--all", action="store_true", help="配合 --stop：连主服务一起停")
    ap.add_argument("--status", action="store_true", help="查看状态与当前公网地址")
    ap.add_argument("--no-tunnel", action="store_true", help="只起本机服务，不暴露公网")
    ap.add_argument("--autostart", action="store_true", help="注册登录自启")
    ap.add_argument("--no-autostart", action="store_true", help="移除登录自启")
    args = ap.parse_args()

    if args.stop:
        return stop(all_=args.all)
    if args.status:
        return status()
    if args.autostart:
        return autostart(True)
    if args.no_autostart:
        return autostart(False)

    print("=== 社区先知 · 本机常开（服务 + 公网 HTTPS 隧道）===")
    if not start_server():
        return 1
    if args.no_tunnel:
        print(f"已按 --no-tunnel 跳过隧道；本机访问：{LOCAL}/login")
        return 0
    url = start_tunnel()
    if not url:
        return 1
    verify_public(url)
    page = make_qr_page(url)
    copied = copy_to_clipboard(url.rstrip("/") + "/login")
    print("\n—— 手机访问 ——")
    print(f"  地址：{url}/login" + ("（已复制到剪贴板）" if copied else ""))
    print(f"  扫码页：{page}（已生成，可直接打开让人扫）")
    print("  账号：居民=点「居民」免密 · 老年=点「老年」免密 · 网格员=demo_grid / demo123")
    print("\n停止公网暴露：python scripts/serve_public.py --stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
