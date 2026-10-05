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
    """返回 (可运行用例数, 收集总数)；**拿不到就返回 -1，调用方必须据此失败**。

    pytest -q 的汇总行形如 `572/575 tests collected (3 deselected)`：
    - 总数 575 含被 `-m` 标记排除的 3 项；
    - **可运行 572 = 571 通过 + 1 需要外部服务默认跳过**（对外报数字用这个，与登录页 meta.js 一致）。

    ⚠️ 2026-09-29 修掉一个门禁缺口（外部复核指出）：本函数拿不到数字时返回 -1，
    而调用方原来写 `if collected <= 0: continue` —— **静默跳过全部测试数核对，最后照样返回 0（绿灯）**。
    也就是说"环境里没有 pytest"这件事会伪装成"口径全部一致"。
    现在改成：**无法收集 = 直接失败**（要绕过必须显式 `--allow-no-pytest` 并在输出里写明，
    免得有人拿没装 pytest 的环境得出"全绿"结论）。
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


def _migration_count() -> int:
    """版本化迁移条数 = db_core 的 post 注册表条数（不是 schema 版本号，两者差 1）。"""
    import io as _io
    import re as _re
    src = _io.open(os.path.join(_PROJ, "data", "db_core.py"), encoding="utf-8").read()
    post = src.split("post = [", 1)[1].split("\n    ]", 1)[0]
    return len(_re.findall(r"\((\d+),\s*\"", post))


def _audit_counts() -> dict:
    """UI 审计的视口数/路由页数、移动审计的页数（材料里会写这些数）。"""
    import scripts.mobile_audit as M
    import scripts.ui_audit as U
    specs = getattr(U, "PAGES", None) or getattr(U, "SPECS", None) or []
    routes = set()
    for s in specs:
        try:
            routes.add(s[2])
        except (IndexError, TypeError):
            continue
    return {"viewports": len(specs), "audit_routes": len(routes), "mobile_pages": len(M.PAGES)}


def main():
    runnable, total = _pytest_collection_count()
    allow_no_pytest = "--allow-no-pytest" in sys.argv[1:]
    # 明细不写死：按「可运行 = 通过 + 1 项需外部服务跳过」推导，避免总数变了明细没变
    passed = max(0, runnable - 1)
    struct = {"schema": _schema_version(), "routes": _route_count(),
              "roles": _role_count(), "tables": _table_count(),
              "migrations": _migration_count(), **_audit_counts()}
    print("社区先知 CommunityInsight —— 当前代码库事实数字：")
    if runnable > 0:
        print(f"  pytest 可运行用例数  : {runnable}（= {passed} 通过 + 1 需外部服务默认跳过）")
        print(f"  pytest 收集总数      : {total}（含 {max(0, total - runnable)} 项按标记排除；对外报「可运行」口径）")
    else:
        # ⚠️ 门禁缺口修复（外部复核指出）：原来这里会静默跳过测试数核对、最后返回 0——
        # "环境里没有 pytest"于是伪装成"口径全部一致"。现在**默认失败**。
        print("  pytest 可运行用例数  : **无法收集**（本环境跑不了 pytest）")
        print("  pytest 收集总数      : **无法收集**")
    print(f"  schema 版本号        : {struct['schema']}（版本化迁移 {struct['migrations']} 条）")
    print(f"  HTTP 路由数          : {struct['routes']}")
    print(f"  Agent 角色数         : {struct['roles']}")
    print(f"  业务表数量           : {struct['tables']}")
    print(f"  UI 审计覆盖面        : {struct['audit_routes']} 个路由页 / {struct['viewports']} 个视口"
          f" · 移动审计 {struct['mobile_pages']} 页")
    if runnable <= 0 and not allow_no_pytest:
        print("\n❌ 口径核对**无法完成**：本环境收集不到 pytest 用例数（缺 pytest / 装在别的解释器里）。")
        print("   → 装好测试依赖后重跑；确实只做结构数字核对时，显式加 `--allow-no-pytest`，")
        print("     但**那种情况下不得对外说「口径门禁全绿」**（测试数那一半根本没核对）。")
        return 1
    if runnable <= 0 and allow_no_pytest:
        print("\n⚠️ 已按 --allow-no-pytest 继续：**测试数口径未核对**，"
              "本次结果不能作为「口径全绿」的依据（只有结构数字被核对过）。")
    print("\n对外材料的数字请以以上为准；下表为自动核对结果：")
    return _cross_check(runnable, struct)


# 「当前状态文档」——数字必须与代码一致；历史快照（docs/review/**、dev-log、
# docs/superpowers/**、docs/spec/方案类）保留当时事实，不在此列。
CURRENT_DOCS = [
    "README.md", "AGENTS.md", "HANDOFF.md", "PRODUCT.md", "CHANGELOG.md",
    "安装说明.md", "开发约定.md", "docs/DEPLOY.md",
    "docs/mobile-deploy.md", "docs/scaling.md", "docs/deploy-keys.md",
    "docs/competition/创意说明书-提交版.md", "docs/competition/最终版交付说明.md",
    "docs/competition/技术实现报告.md", "docs/competition/答辩问答手册.md",
    "docs/competition/演示脚本.md",
    # ⚠️ 提交前清单原来**不在**这份名单里（2026-09-29 第 3–7 阶段发现）：它是交给评委看的文件，
    # 却因为没进名单而**长期停在旧数字**（1003/1004 · schema v51）没人发现——
    # "最该被核对的那份清单自己没人核对"。加进来后立刻由门禁盯着。
    "docs/competition/提交前清单-2026-09-29.md",
]

# 测试数「口径自检」的豁免名单：这两份是**历史记录**，里面的数字是当时的真实基线，
# 改成今天的数字反而是篡改历史（CHANGELOG 按版本记录；HANDOFF 是那次交接时的快照）。
COUNT_EXEMPT = {"CHANGELOG.md", "HANDOFF.md"}

# 「结构数字」黑名单的豁免：同样是历史记录/交接快照 → 允许保留当时的 schema 版本、
# 路由数、表数（改它等于篡改"当时是什么样"）。其余当前状态文档一律不许出现旧值。
STRUCTURE_EXEMPT = {"CHANGELOG.md", "HANDOFF.md"}

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
    # 第十一轮：B3/B5/B6 把 schema 推到 v48（v47 老年健康记录、v48 多租户真隔离），
    # 路由 130→135（老年端健康记录/管理端点），业务表 50→51。旧数字不得回流——
    # 评委按「对应当前代码库」核对时会对不上。当前值以本脚本头部实时计算的数字为准。
    "schema v46", "schema **v46**", "schema v47", "schema **v47**",
    "130 条路由", "HTTP 路由 **130**", "50 张业务表", "**50 张业务表**",
    "50 张表", "46 个版本化迁移", "46 个迁移", "**46 个版本化迁移**",
]

# 上述「结构数字」黑名单的适用文件（历史快照豁免见 STRUCTURE_EXEMPT）
STRUCTURE_ONLY = [
    "schema v46", "schema **v46**", "schema v47", "schema **v47**",
    "130 条路由", "HTTP 路由 **130**", "50 张业务表", "**50 张业务表**",
    "50 张表", "46 个版本化迁移", "46 个迁移", "**46 个版本化迁移**",
]

#: 「历史基线」块的起止标记：夹在中间的行**允许保留当时的数字**（改它等于篡改历史），
#: 块外的行必须与当前代码一致。
#:
#: 为什么要有这个机制（2026-09-29 外部复核指出）：`基线冻结与验收清单.md` 记的是"冻结那一刻"的
#: 结构数字（HTTP 路由 150 / 可运行 1057），但文件里**没有区分"当时"和"现在"**，
#: 于是同一次发布里既有 150 又有 153，读的人分不清哪个是当前值。
#: 外部复核的原话说得很准：**把历史基线和当前基线分开写**。
#: 现在：标明块 = 历史快照（豁免），块外 = 当前状态（必须核对）。
#:
#: ⚠️ 标记的**权威定义在 `scripts/sync_test_count.py`**（那里也用它来避免自动同步改写历史）。
#: 这里写成同一份字面量而不是 import：`check_claims` 顶部不能引 `sync_test_count`
#: （实测踩到：模块级 `M.HIST_BEGIN` 会 NameError → 连 `tests/test_claims_consistency.py`
#: 都 import 不进来 → 用例数从 1103 掉到 1086，一个常量把整个测试文件搞挂）。
#: 两处必须字面一致，由 `tests/test_claims_consistency.py::test_history_markers_are_single_sourced` 守着。
HIST_BEGIN = "<!-- baseline:historical:begin -->"
HIST_END = "<!-- baseline:historical:end -->"


def _current_lines(txt: str) -> list[str]:
    """去掉「历史基线块」之后的行（保持行号不变，便于报错定位）。

    未闭合的块 → **视为全部历史**并告警由调用方失败（宁可不核对，也不假装核对了）。
    """
    out, inside = [], False
    for ln in txt.splitlines():
        if HIST_BEGIN in ln:
            inside = True
            out.append("")            # 标记行本身不参与核对
            continue
        if HIST_END in ln:
            inside = False
            out.append("")
            continue
        out.append("" if inside else ln)
    return out


def _unclosed_hist_block(txt: str) -> bool:
    """历史块必须成对（缺 END 会静默把后面所有行都豁免掉，那等于把门禁关掉）。"""
    return txt.count(HIST_BEGIN) != txt.count(HIST_END)


#: 「基线快照类」文档：它们**同时**记着"冻结那一刻"和"当前值"，所以必须用历史块标记分开。
#: 这类文档也要被核对（否则就会像 `基线冻结与验收清单.md` 一样静默漂移）。
SNAPSHOT_DOCS = [
    "docs/spec/升级方案/基线冻结与验收清单.md",
    "docs/spec/升级方案/执行台账.md",
]


def _cross_check(collected: int, struct: dict | None = None) -> int:
    """① 登录页 meta.js 的用例数必须等于 pytest 收集数；② 当前状态文档不得含过时表述；
    ③ **结构数字**（schema / HTTP 路由 / Agent 角色 / 业务表）也必须与代码实际值一致。"""
    import io
    import re

    bad: list[str] = []
    struct = struct or {}

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

    for doc in CURRENT_DOCS + SNAPSHOT_DOCS:
        p = os.path.join(_PROJ, doc)
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8").read()
        if _unclosed_hist_block(txt):
            bad.append(f"{doc} 的「历史基线块」标记不成对（{HIST_BEGIN} / {HIST_END}）→ "
                       "会把块后所有内容都豁免掉，等于把门禁关掉。请补齐成对标记。")
            continue
        struct_exempt = doc in STRUCTURE_EXEMPT
        for i, ln in enumerate(_current_lines(txt), 1):
            for s in STALE:
                if s in ln:
                    # 历史记录/交接快照允许保留"当时的结构数字"（改它等于篡改历史）
                    if struct_exempt and s in STRUCTURE_ONLY:
                        continue
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
        for i, ln in enumerate(_current_lines(txt), 1):
            if "scripts/sync_test_count" in ln or "check_claims" in ln:
                continue          # 命令示例/提示行不参与核对
            for m in re.finditer(r"可运行(?:用例)?[\s|*]*(\d{3,})", ln):
                if int(m.group(1)) != collected:
                    bad.append(f"{doc}:{i} 写「可运行 {m.group(1)}」，实测可运行 {collected}"
                               f"（跑 `python scripts/sync_test_count.py {collected}` 同步）")
            for m in re.finditer(r"(\d{3,})\s*(?:通过|passed)", ln):
                if int(m.group(1)) != passed:
                    bad.append(f"{doc}:{i} 写「{m.group(1)} 通过」，实测应为 {passed}"
                               f"（跑 `python scripts/sync_test_count.py {collected}` 同步）")

    # ---- ③ 结构数字核对（2026-09-29 新增）----
    # 为什么补这一条：实测发现 `技术实现报告.md` / `演示脚本.md` 里还写着
    # 「schema v51 · HTTP 路由 135 · 业务表 51」——代码早就到 v52 / 150 / 53 了。
    # 测试数那条守卫很严（每个数字都核对），结构数字却**没人管**，于是静默漂移了几轮。
    # 评委真去数一遍就是"材料与实际不符"，比少写一个功能更伤。
    # 规则：文档里凡出现 `schema vN` / `HTTP 路由 N` / `Agent 角色 N` / `业务表 N`，都必须等于实测值。
    if struct:
        pats = {
            "schema": (r"schema\s*\*{0,2}v(\d+)", struct.get("schema"), "schema 版本"),
            "routes": (r"HTTP\s*路由\s*\*{0,2}(\d{2,})", struct.get("routes"), "HTTP 路由数"),
            # ⚠️ 2026-09-29 补（外部复核指出）：只认「HTTP 路由 N」会漏掉「N 条路由」这种写法，
            # 而**提交件里写的正是后者** —— 实测 `PRODUCT.md` 与 `创意说明书-提交版.md`
            # 都写着「150 条路由」（实际 153），门禁全绿。同一个数字的另一种说法必须一起管。
            "routes_alt": (r"(\d{2,})\s*条路由", struct.get("routes"), "HTTP 路由数"),
            # ⚠️ 负向断言是实测补的：`(\d{2,})\s*个路由` 会把「37 个路由**页**」（UI 审计覆盖面）
            # 和「14 个路由**模块**」（api_routes/ 的模块数）一起误判成路由数 —— 那是**误报**，
            # 误报比漏报更坏：它会让门禁失去可信度，然后有人去"改数字"把正确的改错。
            "routes_alt2": (r"(\d{2,})\s*个路由(?!页|模块|文件|层)", struct.get("routes"), "HTTP 路由数"),
            "roles": (r"Agent\s*角色\s*\*{0,2}(\d+)", struct.get("roles"), "Agent 角色数"),
            "tables": (r"业务表\s*\*{0,2}(\d{2,})", struct.get("tables"), "业务表数量"),
            # 「N 张业务表 / N 张表」同样是"业务表数量"的另一种说法
            "tables_alt": (r"(\d{2,})\s*张(?:业务)?表", struct.get("tables"), "业务表数量"),
            # 2026-09-29 再补三条：迁移条数、UI 审计视口数、移动端审计页数
            # （实测这三处也漂了：「54 页视口 + 21 页移动端审计」vs 实际 58 / 31）
            "migrations": (r"(\d{2,})\s*个(?:版本化)?迁移", struct.get("migrations"), "迁移条数"),
            "viewports": (r"(\d{2,})\s*(?:页|个)视口", struct.get("viewports"), "UI 审计视口数"),
            "mobile_pages": (r"(\d{2,})\s*页移动(?:端)?审计", struct.get("mobile_pages"), "移动审计页数"),
        }
        for doc in CURRENT_DOCS + SNAPSHOT_DOCS:
            if doc in COUNT_EXEMPT or doc in STRUCTURE_EXEMPT:
                continue
            p = os.path.join(_PROJ, doc)
            if not os.path.exists(p):
                continue
            txt = io.open(p, encoding="utf-8").read()
            for i, ln in enumerate(_current_lines(txt), 1):
                if "check_claims" in ln or "sync_test_count" in ln:
                    continue
                for _k, (pat, actual, label) in pats.items():
                    if actual in (None, 0):
                        continue
                    for m in re.finditer(pat, ln):
                        if int(m.group(1)) != int(actual):
                            bad.append(f"{doc}:{i} 写「{label} {m.group(1)}」，实测 {actual}"
                                       f"（结构数字必须与代码一致：{ln.strip()[:60]}）")

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
