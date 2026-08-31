# scripts/check_claims.py
"""数字一致性自检（WS1.3）：打印"材料应填数字"，杜绝 328/15 表这类陈旧数字回流。

用法：
    python scripts/check_claims.py

输出均为当前代码库的**事实数字**（从代码 / 迁移注册 / 路由表实时计算），
供对外材料（技术实现报告 / README）回填时直接引用。
"""
import os
import subprocess
import sys
import tempfile

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)


def _pytest_collection_count() -> int:
    """通过子进程运行 pytest --collect-only，解析"tests collected"数字。"""
    try:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only"],
            cwd=_PROJ, capture_output=True, text=True, timeout=180, check=False,
        )
        out = p.stdout or ""
    except Exception:
        return -1
    import re
    m = re.search(r"(\d+)\s+tests? collected", out) or re.search(r"collected (\d+) items", out)
    if m:
        return int(m.group(1))
    # 兜底：退回 -q 点号统计（罕见，不用也行）
    return -1


def _schema_version() -> int:
    """当前 schema 版本 = 迁移注册表 post 列表的最大版本（迁移到临时库后读 schema_version 表）。"""
    import sqlite3

    import config as _c
    tmp = os.path.join(tempfile.mkdtemp(prefix="claims_ver_"), "v.db")
    _c.DB_PATH = tmp
    from data.db_core import init_db
    init_db(tmp)
    con = sqlite3.connect(tmp)
    try:
        row = con.execute("SELECT version FROM schema_version").fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def _route_count() -> int:
    import config as _c
    _c.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="claims_"), "c.db")
    import api_web
    from utils.routes import collect_http_routes
    return len(collect_http_routes(api_web.app))


def _role_count() -> int:
    from agent.roles import AGENT_CLASSES
    return len(AGENT_CLASSES)


def _table_count() -> int:
    import sqlite3

    import config as _c
    tmp = os.path.join(tempfile.mkdtemp(prefix="claims_tbl_"), "t.db")
    _c.DB_PATH = tmp
    from data.db_core import init_db
    init_db(tmp)
    con = sqlite3.connect(tmp)
    try:
        names = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return len(names)
    finally:
        con.close()


def main():
    print("社区先知 CommunityInsight —— 当前代码库事实数字：")
    print(f"  pytest 用例数   : {_pytest_collection_count()}")
    print(f"  schema 版本号  : {_schema_version()}")
    print(f"  HTTP 路由数    : {_route_count()}")
    print(f"  Agent 角色数   : {_role_count()}")
    print(f"  业务表数量     : {_table_count()}")


if __name__ == "__main__":
    main()
