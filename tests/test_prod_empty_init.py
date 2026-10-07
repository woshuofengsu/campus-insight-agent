# -*- coding: utf-8 -*-
"""生产空库初始化门禁：**"空库初始化 · 不迁移演示库 · 不灌演示数据/账号"** 必须是代码事实。

## 为什么要有这个测试

2026-10-06 第一次真跑 `scripts/empty_db_drill.py`（空库演练）就抓到一个**生产安全洞**：

```
DEMO_MODE=false（生产姿态）+ 全新空库 → 启动后库里凭空出现
6 个演示账号（其中 2 个密码是 demo123）+ 38 条虚构工单 + 19 条提案 + 17 条知识库
```

原因是 `api_web._ensure_db()` **无条件**调 `data.seed.seed_all()`，而 `seed_all` 对空库会灌整套
比赛演示数据 —— 于是"部署手册写的红线"和"代码的实际行为"**是矛盾的**，而且只在**真跑一遍**时才看得见。

修法：`config.SEED_DEMO_DATA`（默认跟随 `DEMO_MODE`）+ `api_web._ensure_db()` 按姿态决定是否灌种子，
再补 `scripts/bootstrap_admin.py` 解决"空库没有账号怎么登进去"。
本文件把这几条钉住——**用子进程跑真实的启动路径**（不是断言配置变量的字面值，
那样改一行 `_ensure_db` 就能骗过测试）。
"""
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

_PORJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 用与 `uvicorn api_web:app` 完全相同的启动路径初始化一套空库。
_INIT = r"""
import config
import api_web
api_web._ensure_db()
print("INIT_DONE", config.DB_PATH)
"""

#: 校验账号能不能真的登进去（走 data.db_user.authenticate，即服务用的同一条路径）。
_AUTH = r"""
import os, sys
import config
from data.db_core import init_db
from data.db_user import authenticate
init_db(config.DB_PATH)
user = authenticate(sys.argv[1], sys.argv[2])
if not user:
    print("AUTH_FAIL")
    sys.exit(3)
print("AUTH_OK", user.get("role"), user.get("community"))
"""


def _clean_env(extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEMO_MODE", "SEED_DEMO_DATA", "DEMO_AUTO_WORKER",
                        "COMMUNITY_DB_PATH", "CRYPTO_KEY", "WEB_JWT_SECRET")}
    env["PYTHONPATH"] = _PORJ + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _mkdb(tmp: str, name: str) -> str:
    return os.path.join(tmp, f"{name}.db")


def _init_db(db: str, extra: dict) -> subprocess.CompletedProcess:
    env = _clean_env({"COMMUNITY_DB_PATH": db, **extra})
    return subprocess.run([sys.executable, "-c", _INIT], cwd=_PORJ, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _counts(db: str) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        def one(sql, args=()):
            return conn.execute(sql, args).fetchone()[0]
        return {
            "demo_users": one("SELECT COUNT(*) FROM user_profile WHERE username LIKE 'demo%'"),
            "demo_pw": one("SELECT COUNT(*) FROM user_profile WHERE username LIKE 'demo%' "
                           "AND length(COALESCE(password_hash,''))>0"),
            "users": one("SELECT COUNT(*) FROM user_profile"),
            "issues": one("SELECT COUNT(*) FROM community_issues"),
            "tables": one("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                          "AND name NOT LIKE 'sqlite_%'"),
            "schema": one("SELECT MAX(version) FROM schema_version"),
        }
    finally:
        conn.close()


_PROD = {"DEMO_MODE": "false", "CRYPTO_KEY": "Zx9" + "k" * 45,
         "WEB_JWT_SECRET": "J" + "w" * 47}
_DEMO = {"DEMO_MODE": "true", "CRYPTO_KEY": "Zx9" + "k" * 45,
         "WEB_JWT_SECRET": "J" + "w" * 47}


def test_prod_posture_empty_db_has_no_demo_accounts_or_data():
    """生产姿态的空库：只有表结构 + 最新 schema，**没有**演示账号、没有业务数据。"""
    with tempfile.TemporaryDirectory(prefix="prod_empty_") as tmp:
        db = _mkdb(tmp, "prod")
        p = _init_db(db, _PROD)
        assert "INIT_DONE" in (p.stdout or ""), f"启动失败：{p.stdout}\n{p.stderr}"
        c = _counts(db)
    assert c["demo_users"] == 0, f"生产空库里出现了演示账号：{c}"
    assert c["issues"] == 0 and c["users"] == 0, f"生产空库里出现了数据/账号：{c}"
    assert c["tables"] >= 50 and c["schema"] == 54, f"表结构不完整：{c}"


def test_demo_posture_still_seeds_demo_accounts():
    """演示姿态照旧一键可用（修生产不能把演示修坏）。"""
    with tempfile.TemporaryDirectory(prefix="demo_seed_") as tmp:
        db = _mkdb(tmp, "demo")
        p = _init_db(db, _DEMO)
        assert "INIT_DONE" in (p.stdout or ""), f"启动失败：{p.stdout}\n{p.stderr}"
        c = _counts(db)
    assert c["demo_users"] >= 1, f"演示姿态没有演示账号：{c}"
    assert c["issues"] > 0, f"演示姿态没有演示数据：{c}"


def test_seed_can_be_forced_off_even_in_demo_posture():
    """`SEED_DEMO_DATA=false` 能覆盖演示姿态（预发环境想要空库时用得上）。"""
    with tempfile.TemporaryDirectory(prefix="demo_noseed_") as tmp:
        db = _mkdb(tmp, "noseed")
        p = _init_db(db, {**_DEMO, "SEED_DEMO_DATA": "false"})
        assert "INIT_DONE" in (p.stdout or ""), f"启动失败：{p.stdout}\n{p.stderr}"
        c = _counts(db)
    assert c["demo_users"] == 0 and c["issues"] == 0, f"显式关掉种子仍然灌了数据：{c}"


def test_bootstrap_admin_creates_first_admin_and_it_can_login():
    """空库 → bootstrap 建首个负责人 → **真的能用这个密码登进去**。"""
    with tempfile.TemporaryDirectory(prefix="bootstrap_") as tmp:
        db = _mkdb(tmp, "boot")
        assert "INIT_DONE" in (_init_db(db, _PROD).stdout or "")
        env = _clean_env({"COMMUNITY_DB_PATH": db, **_PROD})
        p = subprocess.run(
            [sys.executable, "scripts/bootstrap_admin.py", "--username", "zhuren01",
             "--name", "王主任", "--community", "幸福里社区", "--generate-password"],
            cwd=_PORJ, env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace")
        out = (p.stdout or "") + (p.stderr or "")
        assert p.returncode == 0, f"bootstrap 失败：{out}"
        m = re.search(r"一次性密码：(\S+)", out)
        assert m, f"没有打印一次性密码：{out}"
        pw = m.group(1)
        assert len(pw) >= 12

        ok = subprocess.run([sys.executable, "-c", _AUTH, "zhuren01", pw],
                            cwd=_PORJ, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        assert "AUTH_OK grid 幸福里社区" in (ok.stdout or ""), \
            f"建了账号但登不进去：{ok.stdout} {ok.stderr}"
        bad = subprocess.run([sys.executable, "-c", _AUTH, "zhuren01", "wrong-password-123"],
                             cwd=_PORJ, env=env, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        assert "AUTH_FAIL" in (bad.stdout or ""), "错误密码竟然也能登录"


def test_bootstrap_admin_refuses_demo_prefix_weak_password_and_empty_community():
    """三条硬约束：不许 `demo` 前缀、密码 ≥12 位、社区名必填（租户键）。"""
    with tempfile.TemporaryDirectory(prefix="boot_refuse_") as tmp:
        db = _mkdb(tmp, "bootr")
        assert "INIT_DONE" in (_init_db(db, _DEMO).stdout or "")
        env = _clean_env({"COMMUNITY_DB_PATH": db, **_DEMO})
        base = [sys.executable, "scripts/bootstrap_admin.py", "--force"]
        cases = {
            "演示账号前缀": base + ["--username", "demo_boss", "--name", "X",
                                    "--community", "幸福里社区", "--password", "L" * 14],
            "密码太短": base + ["--username", "zhuren02", "--name", "X",
                                "--community", "幸福里社区", "--password", "short123"],
            "没给密码": base + ["--username", "zhuren03", "--name", "X",
                                "--community", "幸福里社区"],
            "社区名为空": base + ["--username", "zhuren04", "--name", "X",
                                  "--community", "  ", "--password", "L" * 14],
        }
        for label, cmd in cases.items():
            p = subprocess.run(cmd, cwd=_PORJ, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            out = (p.stdout or "") + (p.stderr or "")
            assert p.returncode != 0, f"「{label}」竟然通过了：{out}"
            assert "[失败]" in out, f"「{label}」失败但没有说清原因：{out}"
        # ⚠️ 断言要写**真正被保证的事**：这是演示姿态的库，它本来就有 6 个演示账号，
        # 所以不能断言"库里没有账号"（第一版就是这么写错的——失败的是断言，不是代码）。
        # 该保证的是：**这四次被拒绝的调用一个账号都没建出来**。
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            created = conn.execute(
                "SELECT COUNT(*) FROM user_profile WHERE username IN "
                "('demo_boss','zhuren02','zhuren03','zhuren04')").fetchone()[0]
        finally:
            conn.close()
        assert created == 0, f"被拒绝的调用竟然建出了 {created} 个账号"


def test_bootstrap_refuses_in_demo_posture_without_force():
    """演示姿态下默认拒绝（生产工具别误用在演示库上），加 --force 才执行。"""
    with tempfile.TemporaryDirectory(prefix="boot_demo_") as tmp:
        db = _mkdb(tmp, "bootd")
        assert "INIT_DONE" in (_init_db(db, _DEMO).stdout or "")
        env = _clean_env({"COMMUNITY_DB_PATH": db, **_DEMO})
        cmd = [sys.executable, "scripts/bootstrap_admin.py", "--username", "zhuren05",
               "--name", "X", "--community", "幸福里社区", "--password", "L" * 14]
        p = subprocess.run(cmd, cwd=_PORJ, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        assert p.returncode != 0 and "演示姿态" in ((p.stdout or "") + (p.stderr or ""))
        p2 = subprocess.run(cmd + ["--force"], cwd=_PORJ, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        assert p2.returncode == 0, f"加 --force 仍失败：{p2.stdout} {p2.stderr}"


def test_production_env_template_declares_the_demo_isolation_switches():
    """生产环境模板必须**显式**写出三项演示隔离开关（别只靠默认值）。"""
    path = os.path.join(_PORJ, "deploy", ".env.production.example")
    src = open(path, encoding="utf-8").read()
    for key, want in (("DEMO_MODE", "false"), ("SEED_DEMO_DATA", "false"),
                      ("DEMO_AUTO_WORKER", "false")):
        assert re.search(rf"^{key}={want}\s*$", src, re.M), \
            f"{path} 没有显式写 {key}={want}"
    # 诚实口径：应用本体仍是 SQLite（PG 属阶段 1B，未执行），模板不许暗示已经能切 PG
    assert "只支持 SQLite" in src or "只支持 sqlite" in src, \
        "模板没有说明应用本体仍是 SQLite —— 会让部署的人以为 DB_BACKEND=postgres 就切过去了"
    assert "bootstrap_admin.py" in src, "模板没写空库初始化后怎么建第一个账号"
