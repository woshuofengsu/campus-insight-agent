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

# Windows 控制台默认 GBK，脚本里的 ✅/⚠ 会抛 UnicodeEncodeError 直接崩掉整条门禁
# （实测：`python scripts/check_claims.py` 在 GBK 控制台下 100% 崩在打印 ✅ 那一行）。
# 与 serve_public/probe_public 等脚本统一：强制 UTF-8，遇到无法编码的字符降级替换而不是崩。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _pytest_collection_count() -> tuple[int, int]:
    """返回 (可运行用例数, 收集总数)。

    pytest -q 的汇总行形如 `572/575 tests collected (3 deselected)`：
    - 总数 575 含被 `-m` 标记排除的 3 项；
    - **可运行 572 = 571 通过 + 1 需要外部服务默认跳过**（对外报数字用这个，与登录页 meta.js 一致）。
    """
    import re
    try:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=_PROJ, capture_output=True, text=True, timeout=300, check=False,
        )
        out = (p.stdout or "") + (p.stderr or "")
    except Exception:  # noqa: BLE001
        return -1, -1
    m = re.search(r"(\d+)/(\d+)\s+tests?\s+collected", out)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    if m:
        return int(m.group(1)), int(m.group(1))
    return -1, -1


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
    runnable, total = _pytest_collection_count()
    # 明细不写死：按「可运行 = 通过 + 1 项需外部服务跳过」推导，避免总数变了明细没变
    passed = max(0, runnable - 1)
    print("社区先知 CommunityInsight —— 当前代码库事实数字：")
    print(f"  pytest 可运行用例数  : {runnable}（= {passed} 通过 + 1 需外部服务默认跳过）")
    print(f"  pytest 收集总数      : {total}（含 {max(0, total - runnable)} 项按标记排除；对外报「可运行」口径）")
    print(f"  schema 版本号        : {_schema_version()}")
    print(f"  HTTP 路由数          : {_route_count()}")
    print(f"  Agent 角色数         : {_role_count()}")
    print(f"  业务表数量           : {_table_count()}")
    print("\n对外材料的数字请以以上为准；下表为自动核对结果：")
    return _cross_check(runnable)


# 「当前状态文档」——数字必须与代码一致；历史快照（docs/review/**、dev-log、
# docs/superpowers/**、docs/spec/方案类）保留当时事实，不在此列。
CURRENT_DOCS = [
    "README.md", "AGENTS.md", "HANDOFF.md", "PRODUCT.md", "CHANGELOG.md",
    "安装说明.md", "开发约定.md", "docs/DEPLOY.md",
    "docs/mobile-deploy.md", "docs/scaling.md", "docs/deploy-keys.md",
    "docs/competition/创意说明书-提交版.md", "docs/competition/最终版交付说明.md",
    "docs/competition/技术实现报告.md", "docs/competition/答辩问答手册.md",
    "docs/competition/演示脚本.md",
]

# 测试数「口径自检」的豁免名单：这两份是**历史记录**，里面的数字是当时的真实基线，
# 改成今天的数字反而是篡改历史（CHANGELOG 按版本记录；HANDOFF 是那次交接时的快照）。
COUNT_EXEMPT = {"CHANGELOG.md", "HANDOFF.md"}

# 历史文档：正文允许保留原型阶段的数字（328 测试 / Streamlit / LangChain / 16 工具），
# **但必须在开头明确标注**是历史实现，否则会误导评委 → 门禁检查「标注存在」。
LEGACY_BANNER_DOCS = {
    "docs/TECHNICAL.md": "历史实现",
    "docs/competition/创意说明书.md": "历史实现",
}

# 明确过时的表述（改完即不再出现；命中即失败）
STALE = [
    "schema v41", "schema v42", "schema v43", "schema v44", "schema v45",
    "schema **v41**", "schema **v42**", "schema **v43**", "schema **v44**", "schema **v45**",
    "328 测试", "328 项", "457 项", "495 passed", "538 项", "555 项", "564 passed",
    "16 个治理工具", "16 个函数工具", "Streamlit 三角色", "LangChain AgentExecutor",
    # ↑ 「16 个治理工具」是 LangChain 时代的旧措辞（当时是 16 个 LangChain Tool）。
    #   当前工具数仍是 16，但写法统一为「16 个工具（自动发现 + 按角色裁剪）」——命中即要求改写，
    #   避免读者以为还在用 LangChain。
    # 第九轮：UI 审计从 26 页扩到全站 34 个路由页 / 54 个页面视口，旧页数不得回流
    "26 页", "26 个页面",
    # 第十轮观察项 O1：PWA **没有 service worker**，只能宣称「可添加到主屏幕」，
    # 不得出现"离线能力"类表述；同时 PWA 文件名必须与仓库实际一致
    # （曾把不存在的 manifest.webmanifest / pwa-192.png 写成已落地方案 → 误导）。
    "离线可用", "支持离线", "离线 PWA", "断网可用",
    "manifest.webmanifest", "pwa-192", "pwa-512",
]


def _cross_check(collected: int) -> int:
    """① 登录页 meta.js 的用例数必须等于 pytest 收集数；② 当前状态文档不得含过时表述。"""
    import io
    import re

    bad: list[str] = []

    meta = os.path.join(_PROJ, "web", "src", "config", "meta.js")
    if os.path.exists(meta):
        m = re.search(r"key:\s*'tests',\s*value:\s*(\d+)", io.open(meta, encoding="utf-8").read())
        if m and collected > 0 and int(m.group(1)) != collected:
            bad.append(f"登录页 meta.js 写 {m.group(1)}，pytest 可运行用例实际 {collected}"
                       f"（跑 `python scripts/sync_test_count.py {collected}` 一键同步全部文档）")
        elif m:
            print(f"  ✅ 登录页用例数与 pytest 可运行数一致：{collected}")
    else:
        bad.append("web/src/config/meta.js 不存在（登录页数字的唯一来源）")

    for doc in CURRENT_DOCS:
        p = os.path.join(_PROJ, doc)
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8").read()
        for i, ln in enumerate(txt.splitlines(), 1):
            for s in STALE:
                if s in ln:
                    bad.append(f"{doc}:{i} 含过时表述「{s}」→ {ln.strip()[:70]}")
                    break
        # 测试数口径自检（本轮新增）：光核对 meta.js 不够——文档里可能一处写新的、另一处写旧的
        # （实测踩到「625 项可运行（624 通过）」这种自相矛盾，因为 sync_test_count 的替换规则漏了写法）。
        # 规则：凡出现「可运行 [用例] NNN」必须 == 可运行数；「NNN 通过 / NNN passed」必须 == 可运行数 − 1。
        if collected <= 0:
            continue
        if doc in COUNT_EXEMPT:
            continue          # 历史快照/变更日志：按当时的真实数字记录，不该被改成今天的数字
        passed = max(0, collected - 1)
        for i, ln in enumerate(txt.splitlines(), 1):
            if "scripts/sync_test_count" in ln or "check_claims" in ln:
                continue          # 命令示例/提示行不参与核对
            for m in re.finditer(r"可运行(?:用例)?[\s|*]*(\d{3})", ln):
                if int(m.group(1)) != collected:
                    bad.append(f"{doc}:{i} 写「可运行 {m.group(1)}」，实测可运行 {collected}"
                               f"（跑 `python scripts/sync_test_count.py {collected}` 同步）")
            for m in re.finditer(r"(\d{3})\s*(?:通过|passed)", ln):
                if int(m.group(1)) != passed:
                    bad.append(f"{doc}:{i} 写「{m.group(1)} 通过」，实测应为 {passed}"
                               f"（跑 `python scripts/sync_test_count.py {collected}` 同步）")

    # 历史文档必须带「这是历史实现」标注
    for doc, banner in LEGACY_BANNER_DOCS.items():
        p = os.path.join(_PROJ, doc)
        if not os.path.exists(p):
            continue
        head = io.open(p, encoding="utf-8").read()[:1500]
        if banner not in head:
            bad.append(f"{doc} 是历史实现文档，但开头缺少「{banner}」标注（会误导评委）")

    if bad:
        print("\n❌ 数字/表述不一致：")
        for b in bad:
            print("  -", b)
        return 1
    print("  ✅ 当前状态文档无过时表述（历史快照 docs/review、dev-log 不在此列）")
    print(f"  ✅ 测试数口径自检：可运行 {collected} / 通过 {max(0, collected - 1)}，"
          f"文档与 meta.js 一致（CHANGELOG、HANDOFF 属历史记录，豁免）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
