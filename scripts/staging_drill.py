# -*- coding: utf-8 -*-
"""staging 环境演练 —— 把"预发与生产分离"从文档变成**本机真跑一遍**。

## 为什么要有它

用户给的 1 周清单里有 9 项环境工作（staging / 库分离 / 独立账号 / 空生产库 / 备份恢复 /
HTTPS / 日志 / 密钥 / 租户隔离）。其中**大部分要真服务器**（HTTPS、Caddy、Docker），
但**"环境分离"这件事本身在本机就能真验**，而且它是最容易做成"写在手册里、从来没跑过"的那种。

所以本脚本在**同一台机器**上起一套 staging 实例（独立库 + 独立密钥 + 独立账号 + 独立端口），
然后证明四件事：

1. **库是空的、也没演示账号**（生产姿态不灌种子）；
2. **独立账号能登、演示账号登不上**（`demo_grid/demo123` 在预发环境里**必须**失败）；
3. **写入只落在 staging 库**：预发建的工单只出现在预发、与演示库互不可见；
4. **密钥是分开的**：用预发密钥加密的密文，用演示密钥解不开（同一密文跨环境失效）。

另外全程比对**演示库文件的指纹**（大小 + 修改时间），证明这次演练没碰它。
任一项不达标 → 退出码非 0（纪律同 `restore_drill.py` / `empty_db_drill.py`）。

用法：
    python scripts/staging_drill.py            # 真跑（临时目录，绝不碰演示库）
    python scripts/staging_drill.py --keep     # 保留产物目录（含 staging 库与日志）
    python scripts/staging_drill.py --port 8011
"""
import argparse
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(ROOT, "data", "community_insight.db")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STAGING_COMMUNITY = "预发测试社区"
RESIDENT = ("staging_resident", "Resident-Pass-2026!")
GRID = ("staging_grid", "Grid-Pass-2026-OK!")


def _stamp(path: str):
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    return (st.st_size, round(st.st_mtime, 3))


def _health(base: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base}/api/web/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _post(base: str, path: str, body: dict, token: str = "") -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {"success": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


def _get(base: str, path: str, token: str = "") -> dict:
    req = urllib.request.Request(f"{base}{path}",
                                 headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {"success": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


def _run_bootstrap(db: str, username: str, password: str, name: str, role: str,
                   jwt: str, key: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEMO_MODE", "SEED_DEMO_DATA", "COMMUNITY_DB_PATH",
                        "CRYPTO_KEY", "WEB_JWT_SECRET")}
    env.update({"COMMUNITY_DB_PATH": db, "DEMO_MODE": "false",
                "WEB_JWT_SECRET": jwt, "CRYPTO_KEY": key, "PYTHONIOENCODING": "utf-8"})
    return subprocess.run([sys.executable, "scripts/bootstrap_admin.py", "--username", username,
                           "--name", name, "--community", STAGING_COMMUNITY, "--role", role,
                           "--password", password],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _key_isolation_check(staging_key: str, demo_key: str, tmp: str) -> tuple[bool, str]:
    """用两把密钥各加密一次、互相解密：预发密钥的密文在演示密钥下必须解不开。"""
    snippet = ("import sys\n"
               "try:\n"
               "    from utils.crypto import Crypto\n"
               "    c = Crypto()\n"
               "    mode = sys.argv[1]\n"
               "    if mode == 'enc':\n"
               "        open(sys.argv[2], 'w', encoding='utf-8').write(c.encrypt('13800001111'))\n"
               "        print('ENC_OK')\n"
               "    else:\n"
               "        print('DECRYPTED:' + str(c.decrypt(open(sys.argv[2], encoding='utf-8').read()) or ''))\n"
               "except Exception as e:\n"
               "    print('FAILED:' + type(e).__name__ + ':' + str(e)[:80])\n")
    script = os.path.join(tmp, "crypto_probe.py")
    open(script, "w", encoding="utf-8").write(snippet)
    token = os.path.join(tmp, "token.txt")

    def run(mode: str, key: str) -> str:
        env = {k: v for k, v in os.environ.items() if k != "CRYPTO_KEY"}
        env.update({"CRYPTO_KEY": key, "PYTHONIOENCODING": "utf-8",
                    # ⚠️ 必须把仓库根加进 PYTHONPATH：探针脚本写在临时目录里，
                    # sys.path[0] 是那个临时目录 → `import utils` 会 ModuleNotFoundError，
                    # 于是两次解密都"无输出"，判据看着像"隔离失败"，其实是**探针本身没跑起来**
                    # （同一个坑在 empty_db_drill 的 worker 里踩过一次）。
                    "PYTHONPATH": ROOT + os.pathsep + env.get("PYTHONPATH", "")})
        return subprocess.run([sys.executable, script, mode, token], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace").stdout.strip()

    enc = run("enc", staging_key)
    out = run("dec", demo_key)
    same = run("dec", staging_key)
    ok = (enc == "ENC_OK" and out.startswith("FAILED")
          and same == "DECRYPTED:13800001111")
    return ok, f"加密={enc or '（无输出）'} · 跨密钥解密={out or '（无输出）'} · 同密钥解密={same or '（无输出）'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--dir", default="")
    ap.add_argument("--port", type=int, default=8001)
    a = ap.parse_args()

    tmp = a.dir or tempfile.mkdtemp(prefix="staging_drill_")
    os.makedirs(tmp, exist_ok=True)
    staging_db = os.path.join(tmp, "staging.db")
    base = f"http://127.0.0.1:{a.port}"
    staging_jwt, staging_key = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    demo_key = os.getenv("CRYPTO_KEY") or "demo-please-set-a-crypto-key"

    print("=" * 78)
    print("staging 环境演练（独立库 / 独立密钥 / 独立账号 / 独立端口）")
    print(f"staging 库：{staging_db}")
    print(f"staging 端口：{a.port} · 演示库：{REAL_DB}")
    print("=" * 78)
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""))

    before = _stamp(REAL_DB)

    # ---- 建库（生产姿态启动一次即可：init_db 建表，不灌种子）----
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEMO_MODE", "SEED_DEMO_DATA", "COMMUNITY_DB_PATH",
                        "CRYPTO_KEY", "WEB_JWT_SECRET")}
    env.update({"COMMUNITY_DB_PATH": staging_db, "DEMO_MODE": "false",
                "WEB_JWT_SECRET": staging_jwt, "CRYPTO_KEY": staging_key,
                "PYTHONPATH": ROOT, "PYTHONIOENCODING": "utf-8"})
    init = subprocess.run([sys.executable, "-c",
                           "import api_web; api_web._ensure_db(); print('INIT_OK')"],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    check("① staging 空库能初始化（生产姿态只建表、不灌演示数据）",
          "INIT_OK" in (init.stdout or ""), (init.stdout or init.stderr or "")[-80:])

    # ---- 独立账号（bootstrap 拒绝 demo 前缀、强制强密码、社区必填）----
    for username, password, name, role in ((RESIDENT[0], RESIDENT[1], "预发居民", "resident"),
                                           (GRID[0], GRID[1], "预发网格员", "grid")):
        p = _run_bootstrap(staging_db, username, password, name, role, staging_jwt, staging_key)
        check(f"② 建独立测试账号 {username}（role={role}，不属于演示账号命名）",
              p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-90:].replace("\n", " "))

    conn = sqlite3.connect(staging_db)
    conn.row_factory = sqlite3.Row
    demo_users = conn.execute(
        "SELECT COUNT(*) FROM user_profile WHERE username LIKE 'demo%'").fetchone()[0]
    issues_before = conn.execute("SELECT COUNT(*) FROM community_issues").fetchone()[0]
    conn.close()
    check("③ staging 库里**没有演示账号**、业务数据为空",
          demo_users == 0 and issues_before == 0,
          f"演示账号 {demo_users} 个 · 工单 {issues_before} 条")

    # ---- 起 staging 服务（独立端口、独立库、独立密钥、生产姿态）----
    log = open(os.path.join(tmp, "staging_server.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api_web:app",
                             "--host", "127.0.0.1", "--port", str(a.port)],
                            cwd=ROOT, env=env, stdout=log, stderr=log)
    ready = False
    for _ in range(45):
        if _health(base):
            ready = True
            break
        if proc.poll() is not None:
            break
        time.sleep(1)
    check("④ staging 实例起来了（独立端口）", ready, base)

    try:
        if ready:
            # 演示账号在预发环境必须登不上
            bad = _post(base, "/api/web/auth/login",
                        {"username": "demo_grid", "password": "demo123"})
            check("⑤ 演示账号在 staging **登不上**（生产姿态不放演示账号）",
                  bad.get("success") is False, str(bad.get("error"))[:60])
            nodemo = _post(base, "/api/web/auth/demo", {"role": "grid"})
            check("⑥ 免密演示登录在 staging **被拒**（DEMO_MODE=false 硬关）",
                  nodemo.get("success") is False, str(nodemo.get("error"))[:60])

            # 独立账号能登
            lr = _post(base, "/api/web/auth/login",
                       {"username": RESIDENT[0], "password": RESIDENT[1]})
            rtoken = (lr.get("data") or {}).get("token") or ""
            check("⑦ 独立居民账号能登录", bool(rtoken), str(lr.get("error") or "")[:50])
            lg = _post(base, "/api/web/auth/login",
                       {"username": GRID[0], "password": GRID[1]})
            gtoken = (lg.get("data") or {}).get("token") or ""
            check("⑧ 独立网格员账号能登录", bool(gtoken), str(lg.get("error") or "")[:50])

            # 写入只落在 staging（手机号用**测试号**：这是预发环境的临时库，演练结束即删）
            mark = f"[staging演练 {time.strftime('%m%d-%H%M%S')}]"
            cr = _post(base, "/api/web/issues",
                       {"title": f"预发环境闭环验证 {mark}", "category": "公共设施",
                        "issue_type": "室外", "location": "预发楼1单元",
                        "description": f"预发环境写入验证 {mark}", "urgency": "一般",
                        "reporter_name": "预发居民", "reporter_phone": "13800001111"},
                       token=rtoken)
            iid = (cr.get("data") or {}).get("issue_id") or 0
            check("⑨ 在 staging 里建单成功（走真实接口）", cr.get("success") is True and iid > 0,
                  f"issue_id={iid} · {str(cr.get('error') or '')[:40]}")
            gl = _get(base, "/api/web/issues?limit=50", token=gtoken)
            seen = [i for i in ((gl.get("data") or []) if isinstance(gl.get("data"), list) else [])
                    if i.get("id") == iid]
            check("⑩ staging 网格员**看得到**这条单（同社区内闭环成立）", bool(seen),
                  f"列表命中 {len(seen)} 条")

            conn = sqlite3.connect(staging_db)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT id, tenant_id, is_demo FROM community_issues "
                               "WHERE id=?", (iid,)).fetchone()
            demo_cnt = conn.execute("SELECT COUNT(*) FROM community_issues "
                                    "WHERE COALESCE(is_demo,0)=1").fetchone()[0]
            conn.close()
            check("⑪ 数据落在 **staging 库**且带租户（租户=预发测试社区，非演示数据）",
                  bool(row) and row["tenant_id"] == STAGING_COMMUNITY and demo_cnt == 0,
                  f"tenant={row['tenant_id'] if row else '—'}")

            # 演示库里**不该**出现这条预发数据（按唯一标记在库里查，而不是拿预发 token 去问演示实例——
            # 预发 token 用预发密钥签的，演示实例本来就会 401，那种"查不到"是假证据）
            if os.path.exists(REAL_DB):
                dconn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
                try:
                    leaked = dconn.execute(
                        "SELECT COUNT(*) FROM community_issues WHERE description LIKE ?",
                        (f"%{mark}%",)).fetchone()[0]
                finally:
                    dconn.close()
                check("⑫ 演示库里**查不到**这条预发数据（两个环境的库真的分开了）",
                      leaked == 0, f"演示库命中 {leaked} 条（标记 {mark}）")

        # 密钥隔离（不需要服务）
        ok, detail = _key_isolation_check(staging_key, demo_key, tmp)
        check("⑬ 密钥是分开的：预发密钥的密文用演示密钥解不开", ok, detail)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()

    after = _stamp(REAL_DB)
    check("⑭ 全程没有改动演示库（大小/修改时间一致）", before == after,
          f"{before} → {after}")

    passed = sum(1 for _n, ok, _d in results if ok)
    print("-" * 78)
    print(f"检查项：{passed}/{len(results)} 通过")
    print(f"产物目录：{tmp}" + ("" if a.keep else "（加 --keep 可保留 staging 库与日志）"))
    if passed != len(results):
        print("结论：**不达标** —— 环境分离还有没落实的地方，见上面 FAIL 行。")
        return 1
    print("结论：全部达标（预发与演示在**库 / 密钥 / 账号 / 端口**四个维度都分开了，"
          "且写进去的数据只落在预发）。")
    if not a.keep and not a.dir:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
