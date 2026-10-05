# -*- coding: utf-8 -*-
"""对外数字与材料措辞一致性（CI 友好版，秒级）。

背景：评委最容易查的就是数字。历史上有过「材料写 328 测试 / schema v41，代码已是别的版本」这类漂移，
第七轮复审也见过「登录页自转率 62% 与后端口径对不上」。这里把三件事钉进 CI：

  1. 登录页 `web/src/config/meta.js` 的数字必须是正整数，且 agent/知识集等**可核对项**与实测一致；
  2. 「当前状态文档」不得出现已过时的表述（旧版本号/旧测试数/旧架构词）；
  3. 历史文档（原型阶段）必须带「历史实现」标注，避免误导评委。

完整的实时核对（含 pytest 收集数、路由数、表数）由 `python scripts/check_claims.py` 承担，
并在 `demo_preflight` 的演示前自检里跑。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import check_claims as C

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_current_docs_have_no_stale_wording():
    """当前状态文档不得含过时表述（旧 schema 版本 / 旧测试数 / 旧架构词）。

    豁免规则与 `scripts/check_claims.py` **共用同一份常量**（`STRUCTURE_EXEMPT` /
    `STRUCTURE_ONLY`）：CHANGELOG 的版本历史与 HANDOFF 的交接快照允许保留"当时的
    结构数字"（schema 版本/路由数/表数）——把历史改成今天的数字才是篡改。
    规则只此一处，避免两处清单各写一份、慢慢漂移。
    """
    hits = []
    for doc in C.CURRENT_DOCS:
        p = os.path.join(PROJ, doc)
        if not os.path.exists(p):
            continue
        struct_exempt = doc in getattr(C, "STRUCTURE_EXEMPT", set())
        for i, ln in enumerate(io.open(p, encoding="utf-8").read().splitlines(), 1):
            for s in C.STALE:
                if s in ln:
                    if struct_exempt and s in getattr(C, "STRUCTURE_ONLY", []):
                        continue
                    hits.append(f"{doc}:{i} 「{s}」")
                    break
    assert not hits, "当前状态文档出现过时表述：\n  " + "\n  ".join(hits)


def test_legacy_docs_are_banner_labeled():
    """历史实现文档必须标注，否则读者会拿原型阶段数字当现状。"""
    for doc, banner in C.LEGACY_BANNER_DOCS.items():
        p = os.path.join(PROJ, doc)
        if not os.path.exists(p):
            continue
        assert banner in io.open(p, encoding="utf-8").read()[:1500], \
            f"{doc} 缺少「{banner}」标注"


def test_meta_js_is_wellformed_and_matches_checkable_facts():
    """登录页数字来源可解析，且可核对项与实测一致（rag_golden / agents）。"""
    from scripts import demo_preflight as P
    declared = P.parse_brand_metrics()
    assert declared, "meta.js 应至少声明一项指标"

    from scripts.rag_eval import load_golden
    assert declared["rag_golden"] == len(load_golden()), \
        f"登录页写 {declared['rag_golden']} 条评测集，实测 {len(load_golden())} 条"

    from agent.roles import AGENT_CLASSES
    assert declared["agents"] == len(AGENT_CLASSES), \
        f"登录页写 {declared['agents']} 个角色，实测 {len(AGENT_CLASSES)} 个"

    # tests 必须是正整数（其精确值由 demo_preflight / check_claims 用 --collect-only 核对）
    assert isinstance(declared["tests"], int) and declared["tests"] > 0


def test_doc_test_numbers_match_single_source():
    """**主文档**里的测试数必须与其口径匹配（不是"落在某个集合里"就算过）。

    只查「评委当成现状来读」的四份主文档（README / AGENTS / 最终版交付说明 / 创意说明书-提交版）；
    CHANGELOG、HANDOFF、dev-log、技术报告正文等属于历史或日志，其中的旧数字是当时事实，不应改写。

    为什么按口径分别校验：实测踩过两次坑——① 批量改总数后正文仍写「571 通过」；
    ② 同步脚本把「N passed」也替换成可运行数，产出「577 passed（可运行 576）」这种**互换**。
    """
    from scripts import demo_preflight as P
    runnable = P.parse_brand_metrics()["tests"]
    primary = [
        "README.md", "AGENTS.md",
        "docs/competition/最终版交付说明.md", "docs/competition/创意说明书-提交版.md",
    ]
    RULES = [
        (re.compile(r"\b(\d{3,})\s*passed"), runnable - 1, "passed 应=可运行数−1"),
        (re.compile(r"\b(\d{3,})\s*通过"), runnable - 1, "「N 通过」应=可运行数−1"),
        (re.compile(r"可运行\s*(\d{3,})"), runnable, "「可运行 N」应=可运行数"),
        (re.compile(r"\b(\d{3,})\s*(?:项\s*)?(?:自动化\s*)?测试"), runnable, "「N 项测试」应=可运行数"),
    ]
    bad = []
    for doc in primary:
        p = os.path.join(PROJ, doc)
        if not os.path.exists(p):
            continue
        for i, ln in enumerate(io.open(p, encoding="utf-8").read().splitlines(), 1):
            for pat, want, why in RULES:
                for m in pat.finditer(ln):
                    if int(m.group(1)) != want:
                        bad.append(f"{doc}:{i} 出现 {m.group(1)}，应为 {want}（{why}）→ {ln.strip()[:60]}")
    assert not bad, "主文档测试数与口径不一致：\n  " + "\n  ".join(bad)


def test_final_delivery_doc_exists_and_covers_key_gates():
    """最终版交付说明必须存在，且覆盖「怎么跑 / 怎么验 / 怎么讲」三类信息。"""
    p = os.path.join(PROJ, "docs", "competition", "最终版交付说明.md")
    assert os.path.exists(p), "缺少 docs/competition/最终版交付说明.md"
    text = io.open(p, encoding="utf-8").read()
    for needle in ("uvicorn api_web:app", "demo_preflight.py", "ui_audit.py",
                   "check_claims.py", "demo_resident", "已知边界"):
        assert needle in text, f"交付说明缺少关键信息：{needle}"
    # 文档里的测试数字必须与 meta.js 口径一致（防交付说明自己写漂）
    m = re.search(r"(\d+)\s*(?:项)?\s*(?:自动化)?测试", text)
    assert m, "交付说明应写明测试规模"


# ---------------------------------------------------------------------------
# 第十轮观察项 O1：PWA「可安装」≠「可离线」——把口径钉死，别再靠"记得别说"
# ---------------------------------------------------------------------------

def test_pwa_is_installable_but_not_offline():
    """① 仓库里确实**没有** service worker（所以"无离线"是真事实，不是谦虚）；
    ② PWA 资源与当前文档里写的文件名必须真实存在（曾把不存在的 `manifest.webmanifest`
    写成已落地）；③ 当前状态文档不得出现"离线能力"类表述，但必须保留诚实的那半句
    「可添加到主屏幕」——只删不立同样会让材料失真。
    """
    web = os.path.join(PROJ, "web")

    # ① 无 SW：既没有注册代码，也没有 sw 文件
    src_files = []
    for dirpath, _dirs, files in os.walk(os.path.join(web, "src")):
        src_files += [os.path.join(dirpath, f) for f in files]
    registrations = []
    for f in src_files:
        txt = io.open(f, encoding="utf-8", errors="replace").read()
        if "serviceWorker" in txt or "navigator.serviceWorker" in txt:
            registrations.append(os.path.relpath(f, PROJ))
    assert not registrations, (
        f"检测到 service worker 注册代码：{registrations}。"
        "要么实现完整的 app-shell 缓存策略，要么保持'无 SW'——不要半成品")
    sw_files = []
    for sub in ("public", "dist"):
        d = os.path.join(web, sub)
        if os.path.isdir(d):
            sw_files += [os.path.relpath(os.path.join(d, f), PROJ)
                         for f in os.listdir(d) if f.lower().startswith("sw") and f.endswith(".js")]
    assert not sw_files, f"存在 service worker 文件：{sw_files}"

    # ② 文档里提到的 PWA 文件名必须真实存在
    manifest = os.path.join(web, "public", "manifest.json")
    assert os.path.exists(manifest), "缺少 web/public/manifest.json"
    import json
    data = json.loads(io.open(manifest, encoding="utf-8").read())
    for key in ("name", "short_name", "start_url", "display", "icons"):
        assert key in data, f"manifest.json 缺 {key}"
    assert data["display"] == "standalone", "manifest 应为 standalone（类 App 全屏）"
    for icon in data["icons"]:
        p = os.path.join(web, "public", icon["src"].lstrip("/"))
        assert os.path.exists(p), f"manifest 引用的图标不存在：{icon['src']}"

    # ③ 措辞：过时表述表（脚本与 pytest 共用同一份）必须覆盖离线类宣称；
    #    同时确认"可添加到主屏幕"这句诚实表述还在某份当前状态文档里。
    for forbidden in ("离线可用", "支持离线", "离线 PWA", "断网可用"):
        assert forbidden in C.STALE, f"check_claims.STALE 应包含「{forbidden}」"

    docs_text = []
    for doc in C.CURRENT_DOCS:
        p = os.path.join(PROJ, doc)
        if os.path.exists(p):
            docs_text.append(io.open(p, encoding="utf-8").read())
    joined = "\n".join(docs_text)
    assert "添加到" in joined and "主屏幕" in joined, \
        "当前状态文档应保留「可添加到手机主屏幕」这一诚实表述，不能一删了之"


# ---------------------------------------------------------------------------
# 第十轮观察项 O2：581 里的"供数冒烟项"必须与强断言测试成对，且只减不增
# ---------------------------------------------------------------------------

# tests/test_ablation.py 里的供数型（只 return dict、不做断言）冒烟项——**这是白名单，不是描述**
ABLATION_SMOKE = {
    "test_persona_routing",
    "test_tool_discovery",
    "test_ooda_pipeline_latency",
    "test_db_performance",
    "test_reflector_components",
    "test_memory_operations",
}

# 对外材料真正引用的指标 → 守住它的强断言测试（有引用就必须有断言）
ABLATION_QUOTED = {
    "test_persona_routing": "test_persona_routing_is_accurate",
    "test_tool_discovery": "test_tool_discovery_covers_expected",
}


def test_ablation_smoke_items_are_whitelisted():
    """供数冒烟项**只能是**这 6 个：新增一个不做断言的 `test_*` 会让"581 全绿"重新变得不可信。

    为什么单独守：这 6 个函数以 `test_` 开头、`return dict` 给消融报告供数，pytest 收集它们
    只是"能跑不崩"，**永远不会失败**（`PytestReturnNotNoneWarning` 已在 pytest.ini 显式登记）。
    第八轮就是靠补真断言才发现人设路由只有 91.67%。
    """
    import ast
    p = os.path.join(PROJ, "tests", "test_ablation.py")
    tree = ast.parse(io.open(p, encoding="utf-8").read())
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(node))
            if not has_assert:
                found.add(node.name)
    assert found == ABLATION_SMOKE, (
        f"供数冒烟项集合变了。新增：{sorted(found - ABLATION_SMOKE)}；"
        f"消失：{sorted(ABLATION_SMOKE - found)}。"
        "新增的必须补 assert（或登记进白名单并说明为何不需要）")


def test_ablation_quoted_metrics_have_asserting_tests():
    """材料引用的指标（人设路由准确率、工具覆盖）必须由**真断言**测试守住，且断言要够硬。"""
    import ast
    p = os.path.join(PROJ, "tests", "test_ablation.py")
    tree = ast.parse(io.open(p, encoding="utf-8").read())
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    for smoke, asserting in ABLATION_QUOTED.items():
        assert asserting in funcs, f"{smoke} 对外引用指标却缺少强断言测试 {asserting}"
        node = funcs[asserting]
        asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
        assert asserts, f"{asserting} 里没有 assert（那就还是冒烟项）"
        src = ast.unparse(node)
        assert "100.0" in src or "==" in src, \
            f"{asserting} 的断言不够硬（应有明确阈值/等值断言）"


def test_current_status_docs_still_reference_ablation_smoke_scope():
    """口径自洽：若材料把「消融 6 用例」算进测试规模，就必须同时说明它们是供数冒烟项。"""
    p = os.path.join(PROJ, "docs", "competition", "最终版交付说明.md")
    text = io.open(p, encoding="utf-8").read()
    if "消融" in text:
        assert "冒烟" in text or "供数" in text, \
            "交付说明提到消融用例，应说明其性质（供数冒烟项 + 关键指标另有强断言）"


# ---------------------------------------------------------------- 结构数字（2026-09-29 新增）

def test_structure_numbers_in_docs_match_code():
    """材料里的**结构数字**必须与代码一致：schema / HTTP 路由 / Agent 角色 / 业务表 /
    迁移条数 / UI 审计视口数 / 移动审计页数。

    为什么补这一条：实测发现 `技术实现报告.md` 与 `演示脚本.md` 里还写着
    「schema v51 · HTTP 路由 135 · 业务表 51 · 54 页视口 · 21 页移动端审计」——
    而代码早已是 v52 / 150 / 53 / 58 / 31。**测试数那条守卫很严（逐处核对），
    结构数字却没人管**，于是静默漂移了好几轮。评委真去数一遍就是「材料与实际不符」。
    """
    struct = {"schema": C._schema_version(), "routes": C._route_count(),
              "roles": C._role_count(), "tables": C._table_count(),
              "migrations": C._migration_count(), **C._audit_counts()}
    # 直接调用生产用的核对逻辑；返回 1 即说明有文档对不上
    assert C._cross_check(0, struct) == 0, "材料里的结构数字与代码不一致（详见 check_claims 输出）"


def test_structure_gate_would_catch_a_stale_number():
    """**门禁自检**：给一个错的结构数字，核对逻辑必须报出来（证明它不是摆设）。"""
    import tempfile

    fake = os.path.join(tempfile.mkdtemp(prefix="claims_selfcheck_"), "doc.md")
    io.open(fake, "w", encoding="utf-8").write(
        "> schema **v1** · HTTP 路由 **3** · Agent 角色 **1** · 业务表 **2** · 5 个版本化迁移\n")
    orig_docs, orig_exempt = C.CURRENT_DOCS, C.COUNT_EXEMPT
    try:
        rel = os.path.relpath(fake, PROJ)
        C.CURRENT_DOCS = [rel]
        C.COUNT_EXEMPT = set()
        rc = C._cross_check(0, {"schema": 52, "routes": 150, "roles": 9, "tables": 53,
                                "migrations": 51, "viewports": 58, "audit_routes": 37,
                                "mobile_pages": 31})
        assert rc == 1, "假文档里全是错数字，核对逻辑竟然放过了（门禁失效）"
    finally:
        C.CURRENT_DOCS, C.COUNT_EXEMPT = orig_docs, orig_exempt

    # 反向：数字写对时不该报错
    io.open(fake, "w", encoding="utf-8").write("> schema **v52** · HTTP 路由 **150**\n")
    orig_docs = C.CURRENT_DOCS
    try:
        C.CURRENT_DOCS = [os.path.relpath(fake, PROJ)]
        assert C._cross_check(0, {"schema": 52, "routes": 150, "roles": 9, "tables": 53,
                                  "migrations": 51, "viewports": 58, "audit_routes": 37,
                                  "mobile_pages": 31}) == 0, "数字写对却被判错（误报）"
    finally:
        C.CURRENT_DOCS = orig_docs


# ---------------------------------------------------------------------------
# 2026-09-29（收敛方案第 3–7 阶段）：**交给评委看的文件必须自己也在门禁里**
# ---------------------------------------------------------------------------

#: 面向评委/组委会的提交件——它们写的数字必须被门禁核对。
#: 这份名单是**下限**：少一份就意味着那份材料可以静默漂移。
JUDGE_FACING_DOCS = [
    "docs/competition/创意说明书-提交版.md",
    "docs/competition/技术实现报告.md",
    "docs/competition/最终版交付说明.md",
    "docs/competition/答辩问答手册.md",
    "docs/competition/演示脚本.md",
    "docs/competition/提交前清单-2026-09-29.md",
]


def test_judge_facing_docs_are_under_the_number_gate():
    """**门禁自检**：每份交给评委的文件都必须被 `check_claims` 逐个核对数字。

    为什么单列这条：`提交前清单-2026-09-29.md` **原来不在** `CURRENT_DOCS` 里，
    于是它长期停在 `1003/1004 · schema v51` 没人发现——那份文件恰恰是"照着勾一遍"用的，
    是评委最可能最后读的一份。**最该被核对的清单自己没人核对**，这就是本条要防的事。
    """
    from scripts import sync_test_count as S
    missing = [d for d in JUDGE_FACING_DOCS if not os.path.exists(os.path.join(PROJ, d))]
    assert not missing, f"提交件不存在（名单过期了？）：{missing}"
    for doc in JUDGE_FACING_DOCS:
        assert doc in C.CURRENT_DOCS, (
            f"{doc} 不在 check_claims.CURRENT_DOCS 里 → 它写的数字没有任何门禁核对，"
            "会静默漂移（提交前清单就出过这个事）")
    # 会写「测试数」的文件同时必须在同步名单里，否则一键同步会漏掉它
    for doc in JUDGE_FACING_DOCS:
        assert doc in S.DOCS, f"{doc} 不在 sync_test_count.DOCS 里 → 测试数同步会漏掉它"


def test_judge_facing_docs_declare_their_numbers_source():
    """提交件必须写明数字口径从哪来（否则读者只能选择相信，无法复算）。"""
    for doc in JUDGE_FACING_DOCS:
        text = io.open(os.path.join(PROJ, doc), encoding="utf-8").read()
        assert ("check_claims" in text or "可复算" in text or "复算" in text), \
            f"{doc} 没有说明数字怎么复算（应引用 check_claims 或写明可复算）"


# ---------------------------------------------------------------------------
# 2026-09-29（外部复核）：两个门禁缺口 —— "没装 pytest 也算全绿" 与 "旧数字换种说法就漏检"
# ---------------------------------------------------------------------------

def test_claims_gate_fails_when_pytest_is_unavailable():
    """**门禁自检**：收集不到 pytest 用例数时，`check_claims` 必须**失败**而不是静默跳过。

    外部复核实测：在没有 pytest 的环境里，`_pytest_collection_count()` 返回 `-1`，
    而核对逻辑写的是 `if collected <= 0: continue` —— **所有测试数核对被跳过，脚本照样返回 0**。
    后果是"环境里没有 pytest"被伪装成"口径全部一致"，属于最危险的一类门禁缺口
    （它绿着，只是因为它没在检查）。
    """
    import contextlib

    orig = C._pytest_collection_count
    buf = io.StringIO()
    try:
        C._pytest_collection_count = lambda: (-1, -1)
        with contextlib.redirect_stdout(buf):
            rc = C.main()
    finally:
        C._pytest_collection_count = orig
    out = buf.getvalue()
    assert rc == 1, "pytest 不可用时 check_claims 竟然返回成功（门禁缺口）"
    assert "无法收集" in out and "无法完成" in out, out[-400:]

    # 显式豁免时必须**明说**测试数没核对，且不返回 0 之外的歧义
    buf2 = io.StringIO()
    try:
        C._pytest_collection_count = lambda: (-1, -1)
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["check_claims.py", "--allow-no-pytest"]
        try:
            with contextlib.redirect_stdout(buf2):
                rc2 = C.main()
        finally:
            _sys.argv = old_argv
    finally:
        C._pytest_collection_count = orig
    assert "测试数口径未核对" in buf2.getvalue(), buf2.getvalue()[-300:]
    assert rc2 in (0, 1), rc2       # 结构数字仍然照常核对，只是不能再宣称"全绿"


def test_route_count_phrasings_are_all_checked():
    """**门禁自检**：路由数的**各种说法**都要被核对，不能只认「HTTP 路由 N」。

    外部复核实测：`PRODUCT.md` 与 `创意说明书-提交版.md` 都写着「150 条路由」（实际 153），
    而门禁全绿 —— 因为判据是 `HTTP\\s*路由\\s*(\\d+)`，**「N 条路由」这种写法直接漏检**，
    偏偏提交件里用的就是后者。这条用例把几种常见说法逐个喂给核对逻辑，必须都能报出来。
    """
    import tempfile
    struct = {"schema": 52, "routes": 153, "roles": 9, "tables": 53,
              "migrations": 51, "viewports": 58, "audit_routes": 37, "mobile_pages": 31}
    for phrase in ("HTTP 路由 **150**", "FastAPI，150 条路由", "**150 条路由**",
                   "FastAPI（150 条路由）", "150 个路由"):
        fake = os.path.join(tempfile.mkdtemp(prefix="claims_routes_"), "doc.md")
        io.open(fake, "w", encoding="utf-8").write(f"- 后端：{phrase}\n")
        orig_docs, orig_snap = C.CURRENT_DOCS, list(C.SNAPSHOT_DOCS)
        try:
            C.CURRENT_DOCS = [os.path.relpath(fake, PROJ)]
            C.SNAPSHOT_DOCS = []
            rc = C._cross_check(1100, struct)
        finally:
            C.CURRENT_DOCS, C.SNAPSHOT_DOCS = orig_docs, orig_snap
        assert rc == 1, f"「{phrase}」写错了路由数（实际 153），核对逻辑竟然放过"


def test_history_markers_are_single_sourced():
    """历史块标记是**语义契约**：两处（`check_claims` 读、`sync_test_count` 写）必须字面一致。

    如果不一致，后果是"门禁把某段当历史豁免了，而自动同步工具却照样去改它"——
    也就是**悄悄篡改历史基线**，而且没有任何地方会报错。
    （实测：曾想在 `check_claims` 里直接 `import` 对方的常量，模块级引用直接 NameError，
    把一个测试文件整个搞挂、可运行用例数从 1103 掉到 1086——一个常量能造成这种级联。）
    """
    from scripts import sync_test_count as S
    assert C.HIST_BEGIN == S.HIST_BEGIN, "历史块起始标记两处不一致"
    assert C.HIST_END == S.HIST_END, "历史块结束标记两处不一致"
    # 切分逻辑同口径：同一段文本两边判定的"历史/当前"必须一样
    sample = f"当前\n{C.HIST_BEGIN}\n历史\n{C.HIST_END}\n当前2\n"
    lines = C._current_lines(sample)
    # 行号必须保持（报错要能指到原行）：0=当前 1=标记 2=历史(被吃掉) 3=标记 4=当前2
    assert lines[0].strip() == "当前"
    assert lines[2] == "", "块内必须被吃掉"
    assert lines[4].strip() == "当前2", "块外内容不许被连带吃掉"
    segs = S.split_historical(sample)
    assert any(hist and "历史" in seg for hist, seg in segs), "sync 侧没把块内识别为历史"
    assert any(not hist and "当前2" in seg for hist, seg in segs)
    # sync 的整篇改写必须**放过**块内数字（否则就是篡改历史）
    out = S.rewrite_counts_doc(f"可运行 1000\n{C.HIST_BEGIN}\n可运行 1000\n{C.HIST_END}\n", 1200)
    assert out.count("1000") == 1, f"历史块内的数字被改写工具动了（等于篡改历史）：{out}"
    assert "可运行 1200" in out, out


# ---------------------------------------------------------------------------
# 2026-09-29（外部复核第 3 点）：**覆盖率不能包装成准确率**
#
# 实测口径：有系统建议 6 条 / 窗口期 306 单 → 覆盖率约 2%，一致率 83.3%，人工改过 1 条。
# 这组数字能证明的是"**对照链路已经接上**"，**不能**证明"分类效果好"——
# 6 条样本的一致率不是准确率，拿它当准确率是"用极小分母冒充结论"。
# 而这条纪律此前**没有任何门禁守着**，全靠人记得。
# ---------------------------------------------------------------------------

#: 会把"一致率"说成"准确率"的写法（命中即红）
ACCURACY_PHRASES = ("分类准确率", "分类的准确率", "自动分类准确率", "分类准确率 83", "准确率 83.3%")

#: 涉及"系统建议 vs 人工最终"对照的材料（当前状态文档 + 台账/基线）
#: ⚠️ 别把"老年观察方案"这类无关文档塞进来：范围定错会让门禁变成"到处都不让提某个词"，
#: 最后没人看得懂它到底在守什么（实测踩到：把 elderly-user-study 放进来 → 报"没写不用于模型训练"）。
CORRECTION_DOCS = [
    "docs/spec/升级方案/执行台账.md",
    "docs/spec/升级方案/基线冻结与验收清单.md",
]

#: 删除 markdown 删除线内容：`~~系统分类准确率 83.3%~~` 是**反面例子**，
#: 不是"在宣称准确率"。不处理它 → 门禁会咬到自己写的纪律条款
#: （本项目第二次踩这个坑，见 dev-log 四十五：禁止短语表把自己的注释判红）。
_STRIKE_RE = re.compile(r"~~.+?~~", re.S)

#: 「禁止态」标记：纪律条款需要**点名**被禁的说法（"不得写成「分类准确率」"）。
#: 判定要求标记出现在短语**之前** —— 这样「不得写成 X」放行，
#: 而「X 83.3%（不需要解释）」这种把宣称藏在句尾的写法仍然会被抓。
_PROHIBIT_RE = re.compile(r"(不得|不许|不要|禁止|避免|不该)")


def test_category_agreement_is_never_called_accuracy():
    """**口径门禁**：对照清单的"一致率"不得被写成"准确率"。

    为什么单独守这条：覆盖率约 2%（有建议 6 条 / 306 单）**不能**支撑"分类准不准"的结论。
    一旦材料里出现"分类准确率 83.3%"，读者会以为系统在全体工单上准确率 83%——
    而真实情况是"绝大多数工单根本没有系统建议"。

    实现注意：先删掉 `~~…~~` 删除线（那是"不许这么说"的反面例子）。
    """
    docs = list(C.CURRENT_DOCS) + CORRECTION_DOCS + ["docs/spec/dev-log.md"]
    bad = []
    for rel in dict.fromkeys(docs):
        p = os.path.join(PROJ, rel)
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8").read()
        for i, ln in enumerate(C._current_lines(txt), 1):
            plain = _STRIKE_RE.sub("", ln)      # 反面例子（删除线）不算宣称
            for phrase in ACCURACY_PHRASES:
                idx = plain.find(phrase)
                if idx < 0:
                    continue
                # 短语前面出现禁止态标记 = 这是"在禁止"，不是"在宣称"
                if _PROHIBIT_RE.search(plain[:idx]):
                    continue
                bad.append(f"{rel}:{i} 出现「{phrase}」→ {ln.strip()[:70]}")
    assert not bad, (
        "对照清单的一致率被写成了「准确率」（2% 覆盖率支撑不了准确率结论）：\n  " + "\n  ".join(bad))


def test_accuracy_phrase_check_still_catches_a_plain_claim():
    """**门禁自检**：删除线与"禁止态"两个例外不能把门禁变成永远绿。"""
    assert ACCURACY_PHRASES, "判据表不能为空"
    assert any(p in "系统分类准确率 83.3%" for p in ACCURACY_PHRASES), \
        "自检失效：明文宣称竟然匹配不到任何判据"
    assert not any(p in _STRIKE_RE.sub("", "~~分类准确率 83.3%~~") for p in ACCURACY_PHRASES), \
        "删除线的反面例子应被忽略（否则门禁会咬自己的纪律条款）"

    # 禁止态：标记在短语**之前** → 放行（纪律条款需要点名被禁说法）
    assert _PROHIBIT_RE.search("不得把一致率写成「分类准确率」"[:6]), "禁止态识别失效"
    # 把宣称藏在句尾（标记在短语之后）→ 仍然必须被抓
    line = "系统分类准确率 83.3%（不需要额外解释）"
    idx = line.find("分类准确率")
    assert idx > 0 and not _PROHIBIT_RE.search(line[:idx]), \
        "「宣称 + 句尾否定词」竟被当成禁止态放过了——例外开得太大"


def test_agreement_rate_is_always_shown_with_coverage():
    """凡引用了"一致率"，同一处必须同时给出**覆盖率**与**样本量**。

    只给一致率 = 拿一小撮样本冒充全体（外部复核的原话：**绝不能只展示一致率**）。
    """
    bad = []
    for rel in dict.fromkeys(C.CURRENT_DOCS + CORRECTION_DOCS + ["docs/spec/dev-log.md"]):
        p = os.path.join(PROJ, rel)
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8").read()
        lines = C._current_lines(txt)
        for i, ln in enumerate(lines, 1):
            if "一致率" not in ln:
                continue
            # 同一行或前后 6 行内必须出现覆盖率/建议条数（表格里常分行写）
            window = "\n".join(lines[max(0, i - 7):i + 6])
            has_cov = any(k in window for k in ("覆盖率", "覆盖率必须", "with_suggestion", "有系统建议"))
            assert has_cov, (
                f"{rel}:{i} 引用了「一致率」但附近没有「覆盖率/有系统建议条数」——"
                f"只报一致率就是拿一小撮样本冒充全体：{ln.strip()[:70]}")
    assert not bad, "\n".join(bad)


def test_correction_list_disclaims_training_use():
    """对照清单必须写明「不用于模型训练/调参」（本项目没有这条链路，不许对外那么说）。"""
    for rel in CORRECTION_DOCS:
        p = os.path.join(PROJ, rel)
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8").read()
        assert "不用于模型训练" in txt, f"{rel} 没有写明对照清单不用于模型训练"

    """历史基线块：**块内豁免、块外必须核对、标记必须成对**（缺 END 等于把门禁关掉）。"""
    assert C.HIST_BEGIN != C.HIST_END, "起止标记不能相同"
    txt = f"当前值 HTTP 路由 **153**\n{C.HIST_BEGIN}\n冻结时 HTTP 路由 **150**\n{C.HIST_END}\n"
    lines = C._current_lines(txt)
    assert any("153" in ln for ln in lines), "块外的当前值不该被吃掉"
    assert not any("150" in ln for ln in lines), "块内的历史值必须被豁免"
    assert C._unclosed_hist_block(txt) is False
    assert C._unclosed_hist_block(f"{C.HIST_BEGIN}\n150\n") is True, "缺 END 必须被判定为不成对"

    # 快照类文档真的用了标记（否则里面的历史数字会被当成当前值报红，或者更糟：被无视）
    for doc in C.SNAPSHOT_DOCS:
        p = os.path.join(PROJ, doc)
        if os.path.exists(p):
            t = io.open(p, encoding="utf-8").read()
            assert C.HIST_BEGIN in t, (
                f"{doc} 是「历史 + 当前」混排的快照文档，必须用 {C.HIST_BEGIN} 标出历史部分")
            assert not C._unclosed_hist_block(t), f"{doc} 的历史基线块标记不成对"


def test_every_doc_quoting_a_test_count_is_in_the_sync_list():
    """**门禁自检（本轮抓到的第二个漏网文件）**：写测试数的**当前状态文档**必须在
    `sync_test_count.DOCS` 里，否则一键同步会跳过它 → 数字静默漂移。

    实测两次栽在这上面：`提交前清单-2026-09-29.md` 与 `docs/复现指南.md` 都写着
    "可运行 N / N passed" 却都不在同步名单里，跑完同步的人以为"已经全同步了"。
    这条把"漏一个文件"从**靠人记得**变成**跑测试就知道**。

    ⚠️ 范围刻意**只覆盖"当前状态文档"**（`check_claims.CURRENT_DOCS` + 复现指南）：
    一开始我想"全仓库凡写测试数的都管"，结果扫出 60 多份**历史快照**
    （`docs/review/**` 各轮评审报告、9/22 路演包、旧方案稿）——那些保留当时数字是**诚实**，
    真去改反而是篡改历史。**门禁范围定得过宽，等于逼人写一长串豁免，最后没人看。**
    """
    from scripts import sync_test_count as S
    pat = re.compile(r"\d{3,4}\s*(?:passed|通过|可运行|项测试|测试)")
    candidates = [d for d in C.CURRENT_DOCS if d not in C.COUNT_EXEMPT]
    # 复现指南是"给别人照着跑"的当前文档，同样必须被同步覆盖（它不在数字核对名单里，
    # 因为它写的是"应该看到什么"，但同样会漂）
    candidates.append("docs/复现指南.md")
    must_sync = []
    for d in candidates:
        p = os.path.join(PROJ, d)
        if os.path.exists(p) and pat.search(io.open(p, encoding="utf-8", errors="replace").read()):
            must_sync.append(d)      # 只要求**真的写了测试数**的那些进同步名单
    missing = [d for d in must_sync if d not in S.DOCS]
    assert not missing, (
        "以下当前状态文档写了测试数但不在 sync_test_count.DOCS 里 → 一键同步会跳过它们，"
        "数字会静默漂移：\n  " + "\n  ".join(missing)
        + "\n（加进 DOCS；若确属历史记录，请登记进 COUNT_EXEMPT 并写明理由）")
    # 名单里不许有僵尸条目（文件已删/已改名 → 同步在对着空气做功）
    stale = [d for d in S.DOCS if not os.path.exists(os.path.join(PROJ, d))]
    assert not stale, f"sync_test_count.DOCS 里有不存在的文件（僵尸条目）：{stale}"
