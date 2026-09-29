# scripts/rag_eval.py — RAG 检索命中率评测（U1 混合检索）
# -*- coding: utf-8 -*-
"""RAG 检索质量量化：用 golden 查询集测「同义/口语查询」的召回命中率。

用法：
  python scripts/rag_eval.py                 # 用当前配置（EMBEDDING_PROVIDER）
  python scripts/rag_eval.py --verbose       # 打印每条命中情况
  python scripts/rag_eval.py --json          # 输出 JSON（CI/报告用）
  python scripts/rag_eval.py --topk 3        # 指定 top-k（默认 3）

评测口径：
  - 每条 case 给「居民口语查询」+「期望命中的关键词集合」（命中任一即算命中该 case）
  - 命中率 = top-k 结果中含期望关键词的 case 数 / 总 case 数
  - 基线要求：无 provider（纯词法+同义词扩展）≥ 70%；有 provider（混合）≥ 85%

数据来源：tests/llm_eval/rag_golden.jsonl（与本脚本一并维护）
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GOLDEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tests", "llm_eval", "rag_golden.jsonl")
# 「无证据不许编」评测集（v2 §11.4）：refuse=库里确实没依据（不许编），answer=控制组（必须能答）
REFUSAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tests", "llm_eval", "refusal_set.jsonl")
# 对抗集（外部评审第十一轮："100% 是不是过拟合"）：
# confusable 相似但错误 / colloquial 口语错别字 / sensitive 敏感医疗法律 / cross_region 跨社区
ADVERSARIAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "tests", "llm_eval", "adversarial_set.jsonl")


def load_golden(path: str = GOLDEN) -> list[dict]:
    cases = []
    if not os.path.isfile(path):
        return cases
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cases.append(json.loads(line))
    return cases


def load_refusal(path: str = REFUSAL) -> list[dict]:
    """读「无证据不许编」评测集（与 golden 同格式，`expect` 取值 refuse / answer）。"""
    return load_golden(path)


def load_adversarial(path: str = ADVERSARIAL) -> list[dict]:
    """读对抗集（`kind` 决定判据，见文件头说明）。"""
    return load_golden(path)


def run_adversarial(verbose: bool = False, db_path: str | None = None,
                    tenant_community: str = "海淀小区",
                    cross_tenant_community: str = "朝阳试点社区") -> dict:
    """**对抗集**：正面回答"100% 是不是过拟合"（外部评审第十一轮）。

    · `confusable` 相似但错误 —— 库里没有的东西，字面像某条 → **不许拿别的当答案**（张冠李戴红线）；
    · `colloquial` 口语/错别字   —— 库里有依据 → 应当答上（检验检索对噪声的鲁棒性，**允许掉分**）；
    · `sensitive`  敏感/医疗/法律 —— 必须转人工（安全红线，硬门禁）；
    · `cross_region` 别的社区问属地专属问题 —— 可以答，但**不许拿海淀区专属文件冒充**。

    与前两集一致：走**产品入口** `ask_question`，在数据库**临时副本**上跑（不污染真实提问记录），
    并校验评测库的已发布知识条数（数字可比性的前提）。
    """
    import shutil
    import sqlite3
    import tempfile

    from config import DB_PATH
    from data import db_core

    rows = load_adversarial()
    if not rows:
        return {"cases": 0, "error": "对抗集为空（tests/llm_eval/adversarial_set.jsonl）"}

    src = db_path or DB_PATH
    tmpdir = tempfile.mkdtemp(prefix="adversarial_")
    tmp_db = os.path.join(tmpdir, "adv.db")
    orig_path = db_core._DB_PATH
    try:
        shutil.copy(src, tmp_db)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmpdir, ignore_errors=True)
        return {"cases": 0, "db": src, "error": f"评测库不可读：{src}（{str(e)[:60]}）"}

    details = []
    kb_published = 0
    db_core._DB_PATH = tmp_db
    try:
        conn = sqlite3.connect(tmp_db)
        try:
            kb_published = conn.execute(
                "SELECT COUNT(*) FROM knowledge_base WHERE audit_status='已发布'").fetchone()[0]
            # 跨社区用例要用"另一个社区"的居民身份（租户只从服务端身份来）
            row = conn.execute("SELECT id FROM user_profile WHERE community=? ORDER BY id LIMIT 1",
                               (cross_tenant_community,)).fetchone()
            cross_uid = row[0] if row else 1
        finally:
            conn.close()
        if kb_published == 0:
            return {"cases": 0, "db": src, "kb_published": 0,
                    "error": f"评测库没有已发布知识（{src}）—— 对抗集无从谈起"}

        from data.db_policy import ask_question
        from utils.region import resolve_region
        regions = {t: resolve_region(t) for t in (tenant_community, cross_tenant_community)}
        for c in rows:
            kind = (c.get("kind") or "").strip()
            expect = (c.get("expect") or "").strip()
            uid = cross_uid if kind == "cross_region" else 1
            tenant = cross_tenant_community if kind == "cross_region" else tenant_community
            r = ask_question(uid, c["query"], region=regions[tenant])
            answered = bool(r.get("matched"))
            reason = r.get("reason") or ("matched" if answered else "")
            cit_area = ((r.get("knowledge") or {}).get("applicable_area") or "")
            blob = " ".join([
                str((r.get("knowledge") or {}).get("title") or ""),
                str((r.get("knowledge") or {}).get("keywords") or ""),
                str(r.get("auto_answer") or ""),
            ])
            wants = c.get("expect_any") or []
            if expect == "refuse":
                ok = (not answered)
                if kind == "sensitive":
                    ok = ok and reason == "manual"     # 敏感类必须是"转人工"，不是"没找到"
            else:
                ok = answered and (not wants or any(w in blob for w in wants))
                if kind == "cross_region":
                    # 不许拿"海淀区专属"文件冒充（跨区只扣 0.5 分，压不过主题分差距，历史上真出过）
                    ok = ok and cit_area != "北京市海淀区"
            details.append({"id": c.get("id"), "kind": kind, "query": c["query"],
                            "expect": expect, "answered": answered, "reason": reason,
                            "cited_area": cit_area, "ok": ok, "why": c.get("why", "")})
            if verbose:
                print(f"[{'✓' if ok else '✗'}] ({kind}) {c['query']} → "
                      f"{'自动回答' if answered else '不自动回答'}（{reason}）引用地区={cit_area or '—'}")
    finally:
        db_core._DB_PATH = orig_path
        shutil.rmtree(tmpdir, ignore_errors=True)

    def _rate(pick) -> dict:
        sub = [d for d in details if pick(d)]
        good = sum(1 for d in sub if d["ok"])
        return {"n": len(sub), "ok": good,
                "rate": round(good * 100 / len(sub), 1) if sub else 0.0,
                "failed": [d["query"] for d in sub if not d["ok"]]}

    from utils.embedding import describe
    out = {
        "cases": len(details), "db": src, "kb_published": kb_published,
        "set_digest": refusal_digest(ADVERSARIAL),
        # 检索姿态必须记录：跑的时候向量服务连不上（网络抖动）会自动退化成纯词法，
        # 口语/错别字类的成绩会明显不同 —— 不写姿态的百分比没法比较（实测踩到）
        "embedding": describe(),
        "by_kind": {k: _rate(lambda d, k=k: d["kind"] == k)
                    for k in ("confusable", "colloquial", "sensitive", "cross_region")},
        "details": details,
    }
    out["failed"] = [d["query"] for d in details if not d["ok"]]
    return out


def refusal_digest(path: str = REFUSAL) -> str:
    """评测集指纹：**数字是在哪一版样本上测的**（v2 §11.1 要求记录样本版本）。

    只对"有效行"（去掉注释与空行）做哈希，并按行归一化 —— 加注释/调换顺序不该改指纹，
    改一条用例则必变。
    """
    import hashlib
    rows = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    rows.append(json.dumps(json.loads(line), ensure_ascii=False, sort_keys=True))
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:16]


def run(topk: int = 3, verbose: bool = False, no_embedding: bool = False,
        path: str = "threshold") -> dict:
    from config import DB_PATH
    from data.db_core import init_db
    init_db(DB_PATH)
    _orig_is_enabled = None
    if no_embedding:
        # 对比基线：临时关闭语义向量 → 只走词法（+同义词扩展），用于量化语义增益。
        # 注意必须在 finally 里恢复：直接改写模块函数会污染同进程内后续调用/测试。
        import utils.embedding as E
        _orig_is_enabled = E.is_enabled
        E.is_enabled = lambda: False
    try:
        return _run_cases(topk=topk, verbose=verbose, path=path)
    finally:
        if _orig_is_enabled is not None:
            import utils.embedding as E
            E.is_enabled = _orig_is_enabled


def run_all_paths(topk: int = 3, verbose: bool = False, no_embedding: bool = False) -> dict:
    """**两条线上检索入口各测一遍**（v2 §11.2/§11.4）：只报一条就等于"评测测 A、产品用 B"。

    返回 `{"threshold": {...}, "hybrid": {...}}`，每个都带 `path_label` 说明数字来自哪条路径。
    """
    return {p: run(topk=topk, verbose=verbose, no_embedding=no_embedding, path=p)
            for p in ("threshold", "hybrid")}


def run_refusal(verbose: bool = False, tenant_community: str = "海淀小区",
                db_path: str | None = None, expect_kb: int | None = None) -> dict:
    """**无证据不许编**：用产品入口判"该不该答"（v2 §11.4）。

    为什么必须走 `ask_question` 而不是自己复刻一套匹配逻辑：
    评测必须验**产品真实用的那条判定链**（阈值按社区取、敏感词/医疗法律先转人工、
    无结果/低分/弱证据不自动回答）。复刻一份就等于"评测 A 路径、产品 B 路径"（§11.2 明确反对）。

    为什么在**临时副本**上跑：`ask_question` 命中时会落 `policy_questions` 与留痕，
    在原库上跑会把评测提问混进"真实居民提问"里——不能为了评测污染业务事实。
    副本是原库的逐字节拷贝，知识库内容一致，判定行为与线上一致。

    `db_path`：显式指定评测库（默认 `config.DB_PATH`）。**为什么要能显式给**：
    `config.DB_PATH` 是模块级全局，别的测试可能改过它；不校验就可能悄悄测到"另一个库"上
    （实测踩到：全量跑时它指向一个只有 17 条 seed 知识的临时库 —— 阈值回落默认 2.0、
    "居住证怎么办理"被拒答，而拒答率照样看着正常）。
    `expect_kb`：期望该库已发布知识条数，不符就**直接报错**，不给出会误导人的数字。

    返回：
      · `kb_published` —— 本次实际测的库里有几条已发布知识（数字可比性的前提）；
      · `refuse_total/refused/refusal_rate` —— 无依据问题里"没有自动回答"的比例（要 100%）；
      · `answer_total/answered/answer_rate` —— 控制组里"确实答上来了"的比例（要 100%）；
      · `fabricated` —— **不合格清单**：无依据却给出了自动回答的问题（这是本项目的红线）；
      · `over_refused` —— 反向不合格清单：该答的却拒答了（防止"为了拒答把能答的也拒了"）。
    """
    import shutil
    import sqlite3
    import tempfile

    from config import DB_PATH
    from data import db_core

    rows = load_refusal()
    if not rows:
        return {"cases": 0, "error": "评测集为空（tests/llm_eval/refusal_set.jsonl）"}

    src = db_path or DB_PATH
    tmpdir = tempfile.mkdtemp(prefix="refusal_eval_")
    tmp_db = os.path.join(tmpdir, "refusal.db")
    orig_path = db_core._DB_PATH
    try:
        shutil.copy(src, tmp_db)          # 连知识库一起拷，判定与线上一致
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmpdir, ignore_errors=True)
        return {"cases": 0, "db": src, "error": f"评测库不可读：{src}（{str(e)[:60]}）"}

    details, fabricated, over_refused = [], [], []
    db_core._DB_PATH = tmp_db
    kb_published = 0
    try:
        conn = sqlite3.connect(tmp_db)
        try:
            kb_published = conn.execute(
                "SELECT COUNT(*) FROM knowledge_base WHERE audit_status='已发布'").fetchone()[0]
        finally:
            conn.close()
        if expect_kb is not None and kb_published != expect_kb:
            return {"cases": 0, "db": src, "kb_published": kb_published,
                    "error": (f"评测库与预期不符：已发布知识 {kb_published} 条，期望 {expect_kb} 条"
                              f"（{src}）—— 数字不可比，先确认评测用的是哪个库")}
        if kb_published == 0:
            return {"cases": 0, "db": src, "kb_published": 0,
                    "error": f"评测库没有已发布知识（{src}）—— 拒答评测无从谈起"}

        from data.db_policy import ask_question
        from utils.region import resolve_region
        region = resolve_region(tenant_community)
        for c in rows:
            expect = (c.get("expect") or "").strip()
            r = ask_question(1, c["query"], region=region)
            answered = bool(r.get("matched"))
            reason = r.get("reason") or ("matched" if answered else "")
            ok = (not answered) if expect == "refuse" else answered
            details.append({"id": c.get("id"), "query": c["query"], "expect": expect,
                            "answered": answered, "reason": reason, "ok": ok,
                            "score": r.get("score"), "why": c.get("why", "")})
            if not ok:
                (fabricated if expect == "refuse" else over_refused).append(c["query"])
            if verbose:
                print(f"[{'✓' if ok else '✗'}] ({expect}) {c['query']} → "
                      f"{'自动回答' if answered else '不自动回答'}（{reason}）")
    finally:
        db_core._DB_PATH = orig_path
        shutil.rmtree(tmpdir, ignore_errors=True)

    ref = [d for d in details if d["expect"] == "refuse"]
    ans = [d for d in details if d["expect"] == "answer"]
    return {
        "cases": len(details),
        "db": src,
        "kb_published": kb_published,
        "set_digest": refusal_digest(),
        "refuse_total": len(ref),
        "refused": sum(1 for d in ref if not d["answered"]),
        "refusal_rate": round(sum(1 for d in ref if not d["answered"]) * 100 / len(ref), 1) if ref else 0.0,
        "answer_total": len(ans),
        "answered": sum(1 for d in ans if d["answered"]),
        "answer_rate": round(sum(1 for d in ans if d["answered"]) * 100 / len(ans), 1) if ans else 0.0,
        "fabricated": fabricated,
        "over_refused": over_refused,
        "details": details,
    }


def _run_cases(topk: int = 3, verbose: bool = False, path: str = "threshold") -> dict:
    """跑一遍 golden 查询集。

    `path` 决定用**哪条线上检索入口**（v2 §11.2「统一线上问答和离线评测的检索入口」）——
    项目里客观存在两条、各有用途，所以**两条都要测、且必须标明数字来自哪条**：
      · `threshold` = `data.db_policy.search_published_knowledge()`：居民端政策问答的作答判定用
        （同义词扩展词法分 + 语义加性加分，配业务阈值决定"自动回答 / 转人工"）；
      · `hybrid`    = `agent.rag.search_hybrid()`：Agent 侧 LLM 上下文注入用（词法 + 语义 RRF 融合）。
    只用一条路径的数字去代表"RAG 效果"，就会出现"评测测 A、产品用 B"（§11.2 明确反对）。
    """
    if path == "hybrid":
        from agent.rag import search_hybrid as _retrieve
    else:
        from data.db_policy import search_published_knowledge as _retrieve
    from utils.embedding import describe
    _PATH_LABEL = {
        "threshold": "阈值判定路径（居民端政策问答作答用：词法分+语义加分 vs 业务阈值）",
        "hybrid": "RRF 融合路径（Agent 侧 LLM 上下文注入用：词法+语义排名融合）",
    }

    cases = load_golden()
    hits, top1_hits, details = 0, 0, []
    region_cases = region_ok = 0
    for c in cases:
        q = c["query"]
        expects = c.get("expect_any") or []
        # 属地用例（地区识别 WS6）：case 里可选带 "region": "<社区名>"，
        # 用来证明"同一句话在给定属地下，本地条目优先、且全国条目仍可兜底"。
        region = None
        if c.get("region"):
            from utils.region import resolve_region
            region = resolve_region(c["region"])
        results = _retrieve(q, top_k=topk, region=region)
        blob = " ".join(
            f"{r.get('title', '')} {r.get('keywords', '')} {r.get('content', '')}"
            for r in results)
        hit = any(k in blob for k in expects)
        # hit@1：更严格——只看第一条是否命中（Top-1 正确性，避免「靠后面的结果凑命中」）
        blob1 = ""
        if results:
            r0 = results[0]
            blob1 = f"{r0.get('title', '')} {r0.get('keywords', '')} {r0.get('content', '')}"
        hit1 = bool(results) and any(k in blob1 for k in expects) if expects else False
        # "expect_top1": true 的用例要求 Top-1 命中（属地用例用它来断言"本地优先"）
        if c.get("expect_top1"):
            region_cases += 1
            if hit1:
                region_ok += 1
        route = results[0].get("retrieval") or ("rrf" if path == "hybrid" else "none") if results else "none"
        hits += 1 if hit else 0
        top1_hits += 1 if hit1 else 0
        details.append({"query": q, "hit": hit, "hit_at_1": hit1, "route": route,
                        "region": c.get("region", ""),
                        "region_level": results[0].get("region_level", "") if results else "",
                        "top": [r.get("title") for r in results]})
        if verbose:
            mark = "✓" if hit1 else ("~" if hit else "✗")
            print(f"[{mark}] {q} → {route} | {details[-1]['top'][:2]}")
    n = len(cases)
    return {"cases": n, "hits": hits, "hit1": top1_hits,
            "hit_rate": round(hits * 100 / n, 1) if n else 0.0,
            "hit1_rate": round(top1_hits * 100 / n, 1) if n else 0.0,
            "region_cases": region_cases, "region_top1_ok": region_ok,
            "topk": topk, "path": path, "path_label": _PATH_LABEL.get(path, path),
            "embedding": describe(), "details": details}


def main():
    ap = argparse.ArgumentParser(description="RAG 检索命中率评测（U1）")
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true")
    # 对比基线：强制关闭语义向量（量化「混合检索」相对「纯词法」的增益）
    ap.add_argument("--no-embedding", action="store_true",
                    help="强制纯词法（关闭语义向量），用于对比实验")
    # 阈值：无 provider 走纯词法（含同义词扩展）基线较低；有 provider 要求更高
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()

    r = run(topk=args.topk, verbose=args.verbose, no_embedding=args.no_embedding)
    emb = r["embedding"]
    threshold = args.threshold
    if threshold is None and not args.no_embedding:
        threshold = 85.0 if emb.get("enabled") else 70.0

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        if args.no_embedding:
            mode = "纯词法（同义词扩展，语义向量已强制关闭）"
        else:
            mode = f"混合检索（{emb['provider']}/{emb['model']}）" if emb.get("enabled") else "纯词法（同义词扩展）"
        print("=== RAG 检索命中率评测（U1）===")
        print(f"模式：{mode} | 用例 {r['cases']} 条")
        print(f"  top-{r['topk']} 命中率：{r['hit_rate']}%（{r['hits']}/{r['cases']}）")
        print(f"  hit@1（Top-1 正确率）：{r['hit1_rate']}%（{r['hit1']}/{r['cases']}）")
        if r.get("region_cases"):
            print(f"  属地用例 Top-1 优先命中：{r['region_top1_ok']}/{r['region_cases']}"
                  "（同一句话在给定属地下本地条目优先）")
        if args.no_embedding:
            print("（对比基线：不加 --no-embedding 即混合检索模式，可量化语义向量增益）")
        else:
            print(f"阈值：top-k {threshold}% → {'✅ 达标' if r['hit_rate'] >= threshold else '❌ 未达标'}")
            if not emb.get("enabled"):
                print("提示：配置 EMBEDDING_PROVIDER=bailian + DASHSCOPE_API_KEY 可启用语义向量，命中率进一步提升。")
    if args.no_embedding:
        sys.exit(0)
    sys.exit(0 if r["hit_rate"] >= threshold else 1)


if __name__ == "__main__":
    main()
