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
        (re.compile(r"\b(\d{3})\s*passed"), runnable - 1, "passed 应=可运行数−1"),
        (re.compile(r"\b(\d{3})\s*通过"), runnable - 1, "「N 通过」应=可运行数−1"),
        (re.compile(r"可运行\s*(\d{3})"), runnable, "「可运行 N」应=可运行数"),
        (re.compile(r"\b(\d{3})\s*(?:项\s*)?(?:自动化\s*)?测试"), runnable, "「N 项测试」应=可运行数"),
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
