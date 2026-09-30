# -*- coding: utf-8 -*-
"""RAG 口径门禁（v2 §11）：两条线上检索入口都要测 + 无证据不许编。

**为什么单立这个文件**：
  ① 项目里客观存在**两条线上检索入口**——居民端政策问答作答用
     `data.db_policy.search_published_knowledge()`（词法分+语义加分 vs 业务阈值），
     Agent 侧注入 LLM 上下文用 `agent.rag.search_hybrid()`（RRF 融合）。
     只测一条、却拿它的数字代表"RAG 效果"，就是 §11.2 明确反对的"评测测 A、产品用 B"。
  ② 检索命中率（Recall@k）只说明"该找到的找到了"，**完全不说明"库里没有的时候会不会编"**。
     后者才是这个项目最在意的口径，所以单列一集（`tests/llm_eval/refusal_set.jsonl`）来测。

本文件同时守住"门禁不是摆设"：把弱证据闸门关掉，拒答用例必须变红（见最后一条）。
"""
import io
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFUSAL = os.path.join(ROOT, "tests", "llm_eval", "refusal_set.jsonl")


def _set_rows() -> list[dict]:
    from scripts.rag_eval import load_refusal
    rows = load_refusal()
    assert rows, "缺少 tests/llm_eval/refusal_set.jsonl（无证据不许编的评测集）"
    return rows


# ---------------------------------------------------------------- 评测集本身

def test_refusal_set_has_both_directions_and_reasons():
    """两个方向都要有，且每条写清"为什么算有依据/无依据"（否则没法复核）。"""
    rows = _set_rows()
    kinds = {r.get("expect") for r in rows}
    assert kinds == {"refuse", "answer"}, f"评测集必须同时含 refuse 与 answer：{kinds}"
    assert sum(1 for r in rows if r["expect"] == "refuse") >= 6, "无依据用例太少，测不出问题"
    assert sum(1 for r in rows if r["expect"] == "answer") >= 6, "控制组太少，防不住'一律拒答'"
    for r in rows:
        assert r.get("query") and r.get("id"), f"用例缺字段：{r}"
        assert len(r.get("why") or "") >= 8, f"用例 {r.get('id')} 没写 why（凭什么算无依据/有依据）"
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "用例 id 重复"


def test_refusal_digest_is_stable_and_content_sensitive():
    """样本指纹：加注释/调序不变，改用例必变（否则"数字在哪版样本上测的"说不清）。"""
    import tempfile

    from scripts.rag_eval import refusal_digest
    base = refusal_digest()
    assert len(base) == 16, base
    # 调序 + 加注释 → 指纹不变
    src = io.open(REFUSAL, encoding="utf-8").read()
    lines = [ln for ln in src.splitlines() if ln.strip() and not ln.startswith("#")]
    tmp = os.path.join(tempfile.mkdtemp(prefix="refusal_digest_"), "s.jsonl")
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(
        "# 注释不该影响指纹\n" + "\n".join(reversed(lines)) + "\n")
    assert refusal_digest(tmp) == base, "调序/加注释改了指纹"
    # 改一条用例 → 必变
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(
        "\n".join(lines[:-1]) + "\n" + lines[-1].replace("高龄老人津贴", "高龄老人补贴") + "\n")
    assert refusal_digest(tmp) != base, "改了用例内容指纹却没变"


# ---------------------------------------------------------------- 判定规则（单元级）

def test_generic_terms_are_not_evidence():
    """只有「办理/怎么/流程」这类泛化词命中，**不算有依据**（这就是"问护照答居住证"的成因）。"""
    from data.db_policy import has_topic_evidence
    entry = {"title": "居住证办理", "keywords": "居住证 办理 流程"}
    assert has_topic_evidence("居住证怎么办理", entry), "标题实体命中应算有依据"
    assert not has_topic_evidence("个人护照怎么办理，去哪办", entry), \
        "只命中「办理/流程」这类泛化词时不许当成有依据（否则就是张冠李戴）"
    assert not has_topic_evidence("这个手续去哪办", entry), "纯泛化词问句同样不算"


def test_topic_evidence_true_for_real_matches():
    """真命中的条目仍要有依据（防止"闸门收得太紧，把能答的也拒了"）。"""
    from data.db_policy import has_topic_evidence
    assert has_topic_evidence(
        "老旧小区加装电梯需要多少业主同意",
        {"title": "老旧小区加装电梯业主表决比例（双三分之二）", "keywords": "电梯 表决 三分之二"})
    assert has_topic_evidence(
        "失业保险金怎么申领",
        {"title": "北京市失业保险金申领发放实施办法（试行）", "keywords": "失业 保险金 申领"})


# ---------------------------------------------------------------- 端到端口径（产品入口）

def _published_kb(path: str) -> int:
    import sqlite3
    try:
        conn = sqlite3.connect(path)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM knowledge_base WHERE audit_status='已发布'").fetchone()[0]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return 0


def _demo_db() -> tuple[str, int]:
    """挑一个"确实带着正式语料"的库来测：`config.DB_PATH` 可能被别的测试模块改过。

    为什么不能直接用全局：`config.DB_PATH` 是模块级全局，某些测试文件在**导入期**就把它
    指向自己的临时库（pytest 先导入全部模块、再跑用例）→ 评测就可能悄悄测到"另一个库"上。
    实测踩到：全量跑时它指向只有 17 条 seed 知识的临时库，阈值回落默认 2.0、
    「居住证怎么办理」被拒答，而拒答率看着照样"正常"。
    """
    import config
    for p in (getattr(config, "DB_PATH", ""), os.path.join(ROOT, "data", "community_insight.db")):
        if p and os.path.isfile(p):
            n = _published_kb(p)
            if n >= 50:            # 正式语料（62 条，其中已发布 61）才够格
                return p, n
    return "", 0


def test_refusal_eval_uses_product_entry_and_never_fabricates():
    """走产品入口 `ask_question`：无依据的一律不自动回答；库里明确有的必须答上来。"""
    import pytest
    from scripts.rag_eval import run_refusal
    db, n = _demo_db()
    if not db:
        pytest.skip("本机没有带正式语料的库（data/community_insight.db）——拒答口径门禁需要它；"
                    "已落盘报告仍由 test_committed_report_labels_paths_and_refusal 守着")
    r = run_refusal(db_path=db, expect_kb=n)
    assert not r.get("error"), r.get("error")
    assert r["kb_published"] == n, f"评测库与预期不符：{r}"
    assert r["refuse_total"] >= 6 and r["answer_total"] >= 6
    assert not r["fabricated"], f"无依据却自动回答了（红线）：{r['fabricated']}"
    assert not r["over_refused"], f"该答的却拒答了：{r['over_refused']}"
    assert r["refusal_rate"] == 100.0 and r["answer_rate"] == 100.0
    # 拒答理由要可解释（no_knowledge / low_score / weak_evidence / manual 都算合格）
    ok_reasons = {"no_knowledge", "low_score", "weak_evidence", "manual"}
    for d in r["details"]:
        if d["expect"] == "refuse":
            assert d["reason"] in ok_reasons, f"没自动回答但理由不认识：{d}"


def test_refusal_eval_does_not_touch_the_demo_db():
    """评测跑在**临时副本**上：不许把评测提问写进演示库（那会污染"真实居民提问"）。"""
    import sqlite3

    import pytest
    from data import db_core
    from scripts.rag_eval import run_refusal
    db, n = _demo_db()
    if not db:
        pytest.skip("本机没有演示库，跳过「不写库」的验证")

    def _rows():
        conn = sqlite3.connect(db)
        try:
            return conn.execute("SELECT COUNT(*) FROM policy_questions").fetchone()[0]
        finally:
            conn.close()

    before = _rows()
    run_refusal(db_path=db, expect_kb=n)
    assert _rows() == before, "拒答评测往演示库里写了提问记录（必须跑在临时副本上）"
    assert db_core._DB_PATH in ("", None) or os.path.exists(str(db_core._DB_PATH)), \
        "评测结束后 db_core._DB_PATH 必须恢复成原来的值"


def test_refusal_eval_refuses_to_report_on_the_wrong_corpus():
    """**给错库就报错**，不许给出看似正常的百分比（否则引用时会张冠李戴）。"""
    import tempfile

    from data import db_core
    from scripts.rag_eval import run_refusal

    tmp = tempfile.mkdtemp(prefix="wrongkb_")
    p = os.path.join(tmp, "empty.db")
    db_core.init_db(p)
    # 前置条件先自己核一遍：临时库真的建出表了（2026-09-29 全量跑时这条用例偶发过一次
    # "no such table"，当时只能看到一个裸 OperationalError，分不清是库的问题还是产品的问题）。
    conn = sqlite3.connect(p)
    try:
        conn.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()
    finally:
        conn.close()
    before = db_core._DB_PATH
    try:
        r = run_refusal(db_path=p)
        assert r.get("error"), f"空库竟然给出了数字：{r}"
        assert r["cases"] == 0 and r.get("kb_published") == 0
        assert db_core._DB_PATH == before, "报错路径也必须把库路径恢复回去"
    finally:
        db_core._DB_PATH = before


def test_refusal_eval_reports_unreadable_copy_instead_of_raising():
    """副本不是数据库（缺表/损坏）时，必须**如实报"数字不可比"**，不许抛裸异常。

    为什么单列：全量跑时实测偶发过一次副本缺表（临时库刚 `init_db` 完、schema 还在 WAL 里
    就被拷走）——裸 `OperationalError` 把用例打红，看的人分不清"评测环境坏了"还是"产品答错了"。
    评测工具的头等纪律是"数字不可比就说不可比"，所以这里连"非数据库文件"这种输入也要给出明确错误。
    """
    import tempfile

    from data import db_core
    from scripts.rag_eval import run_adversarial, run_refusal

    tmp = tempfile.mkdtemp(prefix="notadb_")
    p = os.path.join(tmp, "notadb.db")
    with open(p, "wb") as f:
        f.write(b"this is not a sqlite database at all" * 10)
    before = db_core._DB_PATH
    try:
        for name, fn in (("refusal", run_refusal), ("adversarial", run_adversarial)):
            r = fn(db_path=p)
            assert r.get("error"), f"{name}：非数据库文件竟然给出了数字：{r}"
            assert r["cases"] == 0, f"{name}：报错路径还有用例数 {r['cases']}"
            assert "不可读" in r["error"] or "不可比" in r["error"], r["error"]
        assert db_core._DB_PATH == before, "报错路径也必须把库路径恢复回去"
    finally:
        db_core._DB_PATH = before


# ---------------------------------------------------------------- 两条入口都要测

def test_both_online_retrieval_paths_are_measured():
    """阈值判定路径与 RRF 融合路径都要有数字，且各自标明"数字来自哪条入口"。"""
    from scripts.rag_eval import run_all_paths
    r = run_all_paths(topk=3)
    assert set(r) == {"threshold", "hybrid"}, f"两条入口都要测：{list(r)}"
    for p, d in r.items():
        assert d["cases"] >= 48, f"{p} 用例数异常：{d.get('cases')}"
        assert d["path"] == p and d.get("path_label"), f"{p} 缺 path/path_label（数字来源不可辨）"
        assert "居民端" in d["path_label"] or "Agent" in d["path_label"]


def test_committed_report_labels_paths_and_refusal():
    """落盘的评测报告必须写清"哪条入口"与"拒答口径"，否则引用时又会张冠李戴。"""
    md_path = os.path.join(ROOT, "docs", "eval", "eval-report.md")
    js_path = os.path.join(ROOT, "docs", "eval", "eval-report.json")
    assert os.path.isfile(md_path) and os.path.isfile(js_path), "缺少评测报告"
    md = io.open(md_path, encoding="utf-8").read()
    assert "阈值判定路径" in md and "RRF 融合路径" in md, "报告没区分两条检索入口"
    assert "拒答" in md and "无证据" in md, "报告缺「无证据不许编」这一节"
    data = json.load(io.open(js_path, encoding="utf-8"))
    for key in ("rag", "rag_lexical_only", "rag_agent_path", "compare", "refusal", "corpus"):
        assert key in data, f"评测报告 JSON 缺字段：{key}"
    assert data["refusal"].get("cases"), "报告里的拒答评测是空的"


# ---------------------------------------------------------------- 门禁自检

def test_gate_catches_a_fabricating_engine():
    """**门禁自检**：把弱证据闸门关掉（相当于恢复"问护照答居住证"），拒答用例必须变红。"""
    import pytest
    import data.db_policy as P
    from scripts.rag_eval import run_refusal
    db, n = _demo_db()
    if not db:
        pytest.skip("本机没有带正式语料的库，跳过门禁自检")
    orig = P.has_topic_evidence
    P.has_topic_evidence = lambda question, entry: True       # 关掉闸门
    try:
        r = run_refusal(db_path=db, expect_kb=n)
    finally:
        P.has_topic_evidence = orig
    assert r["fabricated"], (
        "关掉弱证据闸门后竟然没有编造项 —— 说明这组用例测不出这个问题，门禁是摆设")
