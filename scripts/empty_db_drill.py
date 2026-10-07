# -*- coding: utf-8 -*-
"""空库初始化演练 —— 生产红线："**空库初始化 · 不迁移演示库 · 不灌演示数据**"。

## 为什么要有这个脚本

部署手册把"生产库必须空库初始化、绝不迁移 `data/community_insight.db`、生产不放演示数据/演示账号"
写成了硬红线，但**红线不能只写在文档里**——2026-10-06 第一次真跑这个演练就抓到了问题：

```
生产姿态（DEMO_MODE=false）下启动一套空库 → 库里凭空长出 6 个演示账号（其中 2 个密码是 demo123）
+ 350 条虚构工单 + 演示提案/知识库……
```

原因是服务启动路径 `api_web._ensure_db()` **无条件**调 `data.seed.seed_all()`——
而 `seed_all` 在**空库**上会把整套比赛演示数据灌进去。也就是说：
**文档说"生产不放演示数据"，代码却在第一次启动时自动放进去**，两者当时是矛盾的。

修法见 `config.SEED_DEMO_DATA`（默认跟随 `DEMO_MODE`）与 `api_web._ensure_db()` 的姿态判断；
本脚本负责**把这个红线变成可以随时真跑一遍的检查**（`restore_drill.py` 的同一套纪律：
任一项不达标 → 退出码非 0）。

## 三种姿态（各自一个全新的空库路径）

| 姿态 | 期望结果 |
|---|---|
| 演示姿态 `DEMO_MODE=true` | **可以**有演示账号与演示数据（本机演示/比赛要的就是这个） |
| 生产姿态 `DEMO_MODE=false` + 强密钥 | **0 演示账号、0 业务数据**，只有空表结构（schema 已迁到最新） |
| 生产姿态 + 缺密钥 | **拒绝启动**（fail-closed 仍然有效，不能被这次改动绕过） |

另外每一项都会核对：**演示库文件（`data/community_insight.db`）的大小与修改时间没有被改动**
——"不迁移生产库"这句话只有这样才算验过。

## 用法

```bash
python scripts/empty_db_drill.py           # 真跑（临时目录，绝不碰演示库）
python scripts/empty_db_drill.py --keep    # 保留产物目录，便于人工进库查看
```
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(ROOT, "data", "community_insight.db")

# Windows 中文控制台默认 GBK：打印中文/符号会抛 UnicodeEncodeError，而且是在**跑到那一步时**才崩
# （`restore_drill.py` 踩过：六项校验全过之后打印那一刻崩掉 → 一次成功的演练被报成失败）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

#: 工作进程：**用与真实服务完全相同的启动路径**（`api_web._ensure_db()`）初始化一个空库。
#: 单独起解释器是为了让 `DEMO_MODE` / 密钥这类**导入期读一次**的配置真正生效
#: （同进程里改环境变量对已 import 的 config 无效——那验的就是假东西了）。
_WORKER = r'''
import json, os, sys, traceback
report = {"argv_db": None}
out = sys.argv[sys.argv.index("--json") + 1]
report["argv_db"] = os.environ.get("COMMUNITY_DB_PATH")
try:
    import config
    report["db_path"] = config.DB_PATH
    report["demo_mode"] = bool(config.DEMO_MODE)
    report["seed_demo_data"] = bool(getattr(config, "SEED_DEMO_DATA", None))
    import api_web                                  # 与 uvicorn 启动同一个 App 装配
    api_web._ensure_db()                            # 建表 + 迁移 + （按姿态决定是否）灌种子
    report["started"] = True
except BaseException as e:                          # noqa: BLE001 — 启动被拒绝也是**有效结果**
    report["started"] = False
    report["start_error"] = f"{type(e).__name__}: {e}"
    report["trace_tail"] = traceback.format_exc().strip().splitlines()[-3:]
with open(out, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
'''


def _file_stamp(path: str):
    """演示库的"指纹"：不读内容，只看大小与修改时间——用于证明演练没碰它。"""
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    return (st.st_size, round(st.st_mtime, 3))


def _inspect(db_path: str) -> dict:
    """只读检查空库（若文件不存在则返回 exists=False）。"""
    if not os.path.exists(db_path):
        return {"exists": False}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    def one(sql, args=()):
        try:
            return conn.execute(sql, args).fetchone()[0]
        except Exception as e:  # noqa: BLE001 — 表不存在也要如实报出来，不吞
            return f"ERR:{type(e).__name__}"

    out = {
        "exists": True,
        "schema_version": one("SELECT MAX(version) FROM schema_version"),
        "migrations": one("SELECT COUNT(*) FROM schema_migrations"),
        "tables": one("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                      "AND name NOT LIKE 'sqlite_%'"),
        "users": one("SELECT COUNT(*) FROM user_profile"),
        "demo_users": one("SELECT COUNT(*) FROM user_profile WHERE username LIKE 'demo%'"),
        "demo_users_with_password": one(
            "SELECT COUNT(*) FROM user_profile WHERE username LIKE 'demo%' "
            "AND length(COALESCE(password_hash,''))>0"),
        "issues": one("SELECT COUNT(*) FROM community_issues"),
        "proposals": one("SELECT COUNT(*) FROM proposals"),
        "knowledge": one("SELECT COUNT(*) FROM knowledge_base"),
        "phone_plaintext": one("SELECT COUNT(*) FROM user_profile "
                               "WHERE length(COALESCE(phone,''))>0"),
        "issue_phone_plaintext": one("SELECT COUNT(*) FROM community_issues "
                                     "WHERE length(COALESCE(reporter_phone,''))>0"),
        "issues_without_tenant": one("SELECT COUNT(*) FROM community_issues "
                                     "WHERE COALESCE(tenant_id,'')=''"),
    }
    conn.close()
    return out


def _run_posture(label: str, env_over: dict, tmp: str, name: str) -> dict:
    """在一个干净环境里跑一遍启动路径，然后只读检查它建出来的库。"""
    db_path = os.path.join(tmp, f"{name}.db")
    report_path = os.path.join(tmp, f"{name}.json")
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEMO_MODE", "SEED_DEMO_DATA", "CRYPTO_KEY", "WEB_JWT_SECRET",
                        "COMMUNITY_DB_PATH")}
    env["COMMUNITY_DB_PATH"] = db_path
    env.update(env_over)
    env["PYTHONIOENCODING"] = "utf-8"
    # ⚠️ 必须把仓库根加进 PYTHONPATH：子进程是 `python scripts/empty_db_drill.py`，
    # 此时 sys.path[0] 是 `scripts/`（不是仓库根），`import config` 会 ModuleNotFoundError——
    # 第一次跑就踩到了，而且它让**所有**姿态都以"启动失败"告终（包括本该"拒绝启动"的那一条，
    # 于是那条会因为**错误的原因**通过，属于典型的假绿）。
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--worker",
                        "--json", report_path],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    report = {}
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    return {"label": label, "name": name, "db": db_path, "report": report,
            "inspect": _inspect(db_path), "rc": p.returncode,
            "stderr_tail": (p.stderr or "").strip().splitlines()[-3:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true", help="内部使用：只跑一次启动路径")
    ap.add_argument("--json", default="", help="内部使用：报告写到哪")
    ap.add_argument("--keep", action="store_true", help="保留临时产物目录")
    ap.add_argument("--dir", default="", help="指定产物目录（默认临时目录）")
    args = ap.parse_args()
    if args.worker:
        exec(compile(_WORKER, "<worker>", "exec"), {"__name__": "__main__"})
        return 0

    tmp = args.dir or tempfile.mkdtemp(prefix="empty_db_drill_")
    os.makedirs(tmp, exist_ok=True)
    strong_key = "Zx9" + "k" * 45
    strong_jwt = "J" + "w" * 47

    print("=" * 78)
    print("空库初始化演练 · 生产红线：空库初始化 / 不迁移演示库 / 不灌演示数据")
    print(f"临时目录：{tmp}")
    print("=" * 78)

    before = _file_stamp(REAL_DB)
    t0 = time.time()
    runs = [
        _run_posture("演示姿态（DEMO_MODE=true）",
                     {"DEMO_MODE": "true", "WEB_JWT_SECRET": strong_jwt,
                      "CRYPTO_KEY": strong_key},
                     tmp, "demo_posture"),
        _run_posture("生产姿态（DEMO_MODE=false + 强密钥）",
                     {"DEMO_MODE": "false", "WEB_JWT_SECRET": strong_jwt,
                      "CRYPTO_KEY": strong_key},
                     tmp, "prod_posture"),
        _run_posture("生产姿态 + 缺密钥（应拒绝启动）",
                     {"DEMO_MODE": "false", "CRYPTO_KEY": "", "WEB_JWT_SECRET": ""},
                     tmp, "prod_no_key"),
    ]
    after = _file_stamp(REAL_DB)

    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""))

    # ---- 姿态 1：演示姿态照旧可用（别为了修生产把演示修坏）----
    d = next(r for r in runs if r["name"] == "demo_posture")
    ins = d["inspect"]
    check("① 演示姿态能启动并建库", d["report"].get("started") is True,
          d["report"].get("start_error", "")[:60])
    check("①b 演示姿态**照旧**灌演示账号（本机演示/比赛不受影响）",
          isinstance(ins.get("demo_users"), int) and ins["demo_users"] >= 1,
          f"演示账号 {ins.get('demo_users')} 个 · 工单 {ins.get('issues')}")
    check("①c 演示姿态下 schema 已迁到最新", ins.get("schema_version") == 54,
          f"库内版本 {ins.get('schema_version')} · 迁移记录 {ins.get('migrations')} 条")

    # ---- 姿态 2：生产姿态的空库必须真的是空的 ----
    p = next(r for r in runs if r["name"] == "prod_posture")
    pins = p["inspect"]
    check("② 生产姿态能启动并建库（表结构 + 迁移到位）", p["report"].get("started") is True,
          p["report"].get("start_error", "")[:60])
    check("②b 生产空库**没有任何演示账号**（红线：生产不放演示账号）",
          pins.get("demo_users") == 0, f"演示账号 {pins.get('demo_users')} 个")
    check("②c 生产空库**没有任何业务数据**（红线：生产不放演示数据）",
          pins.get("issues") == 0 and pins.get("proposals") == 0,
          f"工单 {pins.get('issues')} · 提案 {pins.get('proposals')} · 知识库 {pins.get('knowledge')}")
    check("②d 生产空库的表结构是完整的（不是「什么都没建」）",
          isinstance(pins.get("tables"), int) and pins["tables"] >= 50,
          f"{pins.get('tables')} 张表 · schema v{pins.get('schema_version')}"
          f"（{pins.get('migrations')} 条迁移记录）")
    check("②e 生产空库没有手机号明文", pins.get("phone_plaintext") == 0,
          f"明文 {pins.get('phone_plaintext')} 条")

    # ---- 姿态 3：缺密钥仍然 fail-closed（改动不能绕过原有防线）----
    nk = next(r for r in runs if r["name"] == "prod_no_key")
    nk_err = nk["report"].get("start_error") or ""
    check("③ 生产姿态 + 缺密钥 → 仍然**拒绝启动**（fail-closed 没被这次改动绕过）",
          nk["report"].get("started") is False
          and ("CRYPTO_KEY" in nk_err or "WEB_JWT_SECRET" in nk_err),
          nk_err[:70] or "（没有报错信息，拒绝原因不明）")

    # ---- 全局：演练没碰演示库 ----
    check("④ 演练全程**没有改动演示库**（大小/修改时间一致，即「不迁移生产库」）",
          before == after,
          f"演练前 {before} → 演练后 {after}")

    passed = sum(1 for _n, ok, _d in results if ok)
    print("-" * 78)
    print(f"检查项：{passed}/{len(results)} 通过 · 耗时 {time.time() - t0:.1f} 秒")
    print(f"产物目录：{tmp}" + ("" if args.keep else "（加 --keep 可保留）"))
    if passed != len(results):
        print("结论：**不达标** —— 生产红线有未满足项，见上面 FAIL 行。")
        return 1
    print("结论：全部达标（空库初始化可用 · 生产姿态不灌演示数据/账号 · 缺密钥仍拒绝启动）。")
    if not args.keep and not args.dir:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
