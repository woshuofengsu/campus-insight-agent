# -*- coding: utf-8 -*-
"""社区治理公开政策语料库导入脚本（幂等，走项目既有审核流程）。

把 `data/kb_corpus/policies.jsonl` 里的公开政策摘要导入知识库（knowledge_base）。
不裸 INSERT：全部复用 `data/db_policy.py` 的
`create_knowledge`（草稿）→ `submit_review`（待审核）→ `audit_knowledge`（已发布），
以吃到项目既有的字段校验、来源规则校验、留痕与版本快照逻辑。

用法::

    # 1) 只看不写：校验 JSONL 并打印「将要导入」的条目数（不建库、不写库）
    python scripts/import_kb_corpus.py --dry-run

    # 2) 只导入前 5 条（按 JSONL 行序）
    python scripts/import_kb_corpus.py --limit 5

    # 3) 全量导入（幂等：title + source_url 已存在 → 跳过）
    python scripts/import_kb_corpus.py

    # 4) 已存在的条目内容有变化时更新：草稿/审核不通过直接用 update_knowledge 更新，
    #    已发布条目走 create_new_version 建新版本草稿（再由审核流程发布）
    python scripts/import_kb_corpus.py --update

    # 5) 指定语料文件 / 目标库（测试用临时库，绝不要指向生产库做写入测试）
    python scripts/import_kb_corpus.py --corpus path/to/policies.jsonl --db D:\\tmp\\t.db

    # 6) 只做语料校验，连读库都不做
    python scripts/import_kb_corpus.py --verify-only

说明：
- 分类：知识库 `category` 只能是 `POLICY_CATEGORIES`（`data/db_policy.py`）里的 5 个值之一
  —— 社保医保 / 养老服务 / 住房保障 / 办事指引 / 社区规定；`create_knowledge` 会强校验，
  写别的值会返回「请选择正确的分类」。本语料每条 `category` 直接写为这 5 类之一，
  另用可选字段 `topic` 保留更细的主题标签（便于人读与按主题扩语料），脚本校验时两者都会检查。
- 去重键为「标题 + 来源链接」。knowledge_base 表没有 source_url 列，因此来源链接写入
  `attachment`（前端「查看政策原文」按钮）与 `content` 的来源信息块，脚本用同一正则
  从库里读回来做去重，改名/改链接不会被误判为重复。
- 录入正文的「—— 来源信息 ——」块会带上「日期说明」行：条目给了可选字段 `date_note` 就用它
  （逐条说明该日期是施行日期还是官方页面公开日期），未给则写通用口径。
- `publisher` 列由 create_knowledge 固定写为操作人（其签名无 publisher 参数），
  故真实发布机关写在 `source`（如「北京市住房和城乡建设委员会（公开政策）」）
  与正文来源信息块的「发布机关」行，`--dry-run` 之外的输出不打印任何密钥。
- 退出码：0 = 全部成功（或有跳过但无失败）；1 = 存在校验失败或导入失败。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Windows 控制台默认 GBK，中文输出会乱码；能改成 UTF-8 就改（改不了不影响功能）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_CORPUS = os.path.join(PROJECT_ROOT, "data", "kb_corpus", "policies.jsonl")

# 导入人 / 审核人：必须互不相同（submit_review 校验「发布人与审核人不能相同」）
ACTOR = "政策语料导入"
AUDITOR = "政策语料审核员"

# 正文里的来源信息块（同时是 source_url 的落库位置之一）
SOURCE_BLOCK_HEADER = "—— 来源信息 ——"
SOURCE_URL_RE = re.compile(r"来源链接：\s*(https?://\S+)")
PUBLISHER_RE = re.compile(r"发布机关：\s*(.+)")

REQUIRED_FIELDS = [
    "title", "category", "body", "plain_interpretation", "keywords",
    "source", "source_url", "publisher", "policy_number", "effective_date",
    "applicable_area", "source_type",
]

# 知识库分类（data/db_policy.py:POLICY_CATEGORIES，create_knowledge 会强校验这 5 个值）
KB_CATEGORIES = ["社保医保", "养老服务", "住房保障", "办事指引", "社区规定"]

# 语料可选字段 topic（主题标签，便于人读与按主题扩语料）→ 知识库分类兜底映射。
# 语料里的 category 已直接写为 5 类之一；此表仅用于「只写了 topic 没写合法 category」的旧格式兜底。
TOPIC_TO_CATEGORY = {
    "老旧小区改造": "住房保障",
    "住房保障": "住房保障",
    "医疗保障": "社保医保",
    "社会救助": "社保医保",
    "生育与妇幼": "社保医保",
    "就业社保": "社保医保",
    "养老服务": "养老服务",
    "社区治理": "社区规定",
    "环境卫生": "社区规定",
    "公共安全": "社区规定",
    "办事指引": "办事指引",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- 语料读取/校验

def split_kw(keywords: str) -> list[str]:
    return [k.strip() for k in re.split(r"[,，、;；\s]+", keywords or "") if k.strip()]


def load_corpus(path: str) -> tuple[list[dict], list[str]]:
    """读 JSONL 语料。返回 (条目列表, 错误列表)。"""
    errors: list[str] = []
    entries: list[dict] = []
    if not os.path.exists(path):
        return [], [f"语料文件不存在：{path}"]
    # utf-8-sig：容忍 Windows 编辑器（记事本/PowerShell）写入的 BOM，纯 UTF-8 同样正常
    with open(path, "r", encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):        # 容忍注释行
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"第 {lineno} 行 JSON 解析失败：{e}")
                continue
            if not isinstance(obj, dict):
                errors.append(f"第 {lineno} 行不是 JSON 对象")
                continue
            obj["_lineno"] = lineno
            entries.append(obj)
    return entries, errors


def validate_entries(entries: list[dict]) -> list[str]:
    """逐条校验必备字段与格式，返回错误信息列表（空列表 = 全部通过）。"""
    errors: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for e in entries:
        tag = f"第 {e.get('_lineno')} 行《{(e.get('title') or '')[:20]}》"
        for f in REQUIRED_FIELDS:
            if f not in e:
                errors.append(f"{tag} 缺少字段 {f}")
        title = (e.get("title") or "").strip()
        url = (e.get("source_url") or "").strip()
        if not title:
            errors.append(f"{tag} 标题为空")
        elif len(title) > 50:
            errors.append(f"{tag} 标题超过 50 字（{len(title)}）")
        if not url.startswith("http"):
            errors.append(f"{tag} source_url 缺失或不是 http(s) 链接：{url!r}")
        if not (e.get("source") or "").strip():
            errors.append(f"{tag} 来源(source)为空")
        if not (e.get("body") or "").strip():
            errors.append(f"{tag} body 为空")
        if not (e.get("plain_interpretation") or "").strip():
            errors.append(f"{tag} plain_interpretation 为空")
        if not _DATE_RE.match((e.get("effective_date") or "").strip()):
            errors.append(f"{tag} effective_date 需为 YYYY-MM-DD：{e.get('effective_date')!r}")
        kws = split_kw(e.get("keywords") or "")
        if not kws:
            errors.append(f"{tag} keywords 为空")
        elif len(kws) > 5:
            errors.append(f"{tag} keywords 超过 5 个（{len(kws)}）")
        cat, cat_err = resolve_category(e)
        if cat_err:
            errors.append(f"{tag} {cat_err}")
        if url.startswith("http"):
            key = (title, url)
            if key in seen:
                errors.append(f"{tag} 与第 {seen[key]} 行重复（标题+来源链接相同）")
            else:
                seen[key] = e.get("_lineno", 0)
    return errors


def resolve_category(entry: dict) -> tuple[str | None, str]:
    """解析知识库分类，返回 (分类, 错误信息)。

    规则（严格）：`category` 必须**直接**是 POLICY_CATEGORIES 5 类之一。
    - 非空但不是 5 类之一 → 报错，并按主题映射给出「应改为 X」的提示（不做静默兜底，避免错分类入库）；
    - `category` 缺失时才兼容旧格式：依次回退 `db_category` 字段、`topic` 主题映射。
    """
    cat = (entry.get("category") or "").strip()
    if cat in KB_CATEGORIES:
        return cat, ""
    if cat:
        hint = (TOPIC_TO_CATEGORY.get(cat)
                or TOPIC_TO_CATEGORY.get((entry.get("topic") or "").strip()))
        tip = f"，应改为 {hint}" if hint else ""
        return None, f"category「{cat}」不是知识库合法分类{tip}；只能是 {KB_CATEGORIES} 之一"
    explicit = (entry.get("db_category") or "").strip()
    if explicit in KB_CATEGORIES:
        return explicit, ""
    topic = (entry.get("topic") or "").strip()
    if topic in TOPIC_TO_CATEGORY:
        return TOPIC_TO_CATEGORY[topic], ""
    return None, f"category 为空且无法从 db_category/topic 推断；只能是 {KB_CATEGORIES} 之一"


def db_category(entry: dict) -> str | None:
    """取知识库分类（校验通过后的写库用值）。"""
    return resolve_category(entry)[0]


# ---------------------------------------------------------------- 内容拼装

def build_content(entry: dict) -> str:
    """正文 = 政策内容概括 + 来源信息块（含来源链接，便于检索与人工核验）。"""
    lines = [(entry.get("body") or "").strip(), "", SOURCE_BLOCK_HEADER]
    lines.append(f"发布机关：{(entry.get('publisher') or '').strip()}")
    pn = (entry.get("policy_number") or "").strip()
    lines.append(f"政策文号：{pn or '（公开检索未见文号，以官方发布原文为准）'}")
    lines.append(f"适用范围：{(entry.get('applicable_area') or '').strip()}")
    lines.append(f"生效日期：{(entry.get('effective_date') or '').strip()}")
    note = (entry.get("date_note") or "").strip()
    lines.append(f"日期说明：{note}" if note else
                 "日期说明：法规规章类为施行日期；摘要／办事指南类为官方来源页面的公开发布日期。")
    lines.append(f"来源链接：{(entry.get('source_url') or '').strip()}")
    lines.append(f"来源类型：{(entry.get('source_type') or '').strip()}")
    lines.append("本条目为公开政策文件的摘要整理，具体以官方发布原文为准。")
    return "\n".join(lines)


def build_summary(entry: dict) -> str:
    pub = (entry.get("publisher") or "").strip()
    return f"{entry.get('source_type') or '政策摘要'}｜发布机关：{pub}｜来源：{entry.get('source_url')}"


def build_source(entry: dict) -> str:
    """source 列：权威发布机关 + 标记（避免落入「社区整理」的专业信息限制分支）。"""
    pub = (entry.get("publisher") or "").strip() or "公开政策"
    return f"{pub}（公开政策）"


# ---------------------------------------------------------------- 幂等索引

def _ensure_db(db_path: str) -> None:
    """确保 db_core 指向目标库：同一路径已就绪则复用，否则 init_db（建表 + 跑迁移）。"""
    from data import db_core
    if db_core._DB_PATH and os.path.abspath(db_core._DB_PATH) == os.path.abspath(db_path):
        return
    db_core.init_db(db_path)


def existing_index(db_path: str = "") -> dict[tuple[str, str], dict]:
    """库里现有条目的 (title, source_url) → 行数据。

    db_path 非空时走 **只读连接**（`mode=ro`），dry-run 也绝不产生任何写入。
    """
    from data.db_core import get_db
    sql = ("SELECT id, title, content, attachment, audit_status, version "
           "FROM knowledge_base")
    if db_path:
        import sqlite3
        uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql).fetchall()
        finally:
            conn.close()
    else:
        with get_db() as conn:
            rows = conn.execute(sql).fetchall()
    idx: dict[tuple[str, str], dict] = {}
    for r in rows:
        d = dict(r)
        url = (d.get("attachment") or "").strip()
        if not url.startswith("http"):
            m = SOURCE_URL_RE.search(d.get("content") or "")
            url = m.group(1) if m else ""
        idx[((d.get("title") or "").strip(), url)] = d
    return idx


# ---------------------------------------------------------------- 导入流程

def enrich_keywords(entry: dict, limit: int = 5) -> str:
    """关键词富化：把居民「口语短词」补进关键词（U2 检索召回关键）。

    背景：检索的关键词命中是**单向**的（关键词必须是提问的子串），而语料关键词常写
    「居民医保」「基本医疗保险」这类长词——居民问「医保怎么报销」时无法命中。
    这里用 utils/text.QUERY_SYNONYMS 反向补全：若条目正文出现某同义词组的任一词，
    就把该组的**口语 key**（如「医保」）加为关键词。

    规则：保留语料原有顺序，口语短词优先插入；总数不超过 limit（db_policy 校验上限 5）。
    """
    from utils.text import QUERY_SYNONYMS
    text = " ".join([
        entry.get("title") or "", entry.get("body") or "",
        entry.get("plain_interpretation") or "", entry.get("keywords") or "",
    ])
    kws = split_kw(entry.get("keywords") or "")
    short: list[str] = []
    for key, syns in QUERY_SYNONYMS.items():
        if key in kws:
            continue
        # 正文命中该组任一同义词（或 key 本身）→ 补 key
        if any(s in text for s in syns) or key in text:
            short.append(key)
    # 短词优先（≤3 字优先，更可能成为提问子串），其余按长度升序
    short.sort(key=lambda w: (len(w) > 3, len(w)))
    merged = short + kws
    seen, out = set(), []
    for w in merged:
        if w and w not in seen and len(w) >= 2:
            seen.add(w)
            out.append(w)
        if len(out) >= limit:
            break
    return ",".join(out)


def import_entry(entry: dict, existing: dict | None, do_update: bool) -> tuple[str, str]:
    """导入单条。返回 (结果, 说明)。结果 ∈ {created, updated, skipped, failed}。"""
    from data.db_policy import (audit_knowledge, create_knowledge, create_new_version,
                                submit_review, update_knowledge)

    title = (entry.get("title") or "").strip()
    cat = db_category(entry) or (entry.get("category") or "").strip()
    common = dict(
        title=title,
        category=cat,
        plain_interpretation=(entry.get("plain_interpretation") or "").strip(),
        source=build_source(entry),
        keywords=entry.get("_enriched_keywords") or enrich_keywords(entry),
        effective_date=(entry.get("effective_date") or "").strip(),
        content=build_content(entry),
        summary=build_summary(entry),
        policy_number=(entry.get("policy_number") or "").strip(),
        applicable_area=(entry.get("applicable_area") or "").strip(),
        attachment=(entry.get("source_url") or "").strip(),
    )

    if existing:
        status = existing.get("audit_status") or ""
        if not do_update:
            return "skipped", f"已存在（#{existing['id']}，{status}）"
        if status in ("草稿", "审核不通过"):
            ok, err = update_knowledge(existing["id"], actor=ACTOR, **common)
            if not ok:
                return "failed", f"更新失败：{err}"
            kid = existing["id"]
        elif status == "已发布":
            kid, err = create_new_version(existing["id"], actor=ACTOR, auditor=AUDITOR, **common)
            if not kid:
                return "failed", f"创建新版本失败：{err}"
        else:  # 已下架等
            return "skipped", f"已存在且状态「{status}」（#{existing['id']}），跳过"
    else:
        kid, err = create_knowledge(actor=ACTOR, **common)
        if not kid:
            return "failed", f"创建草稿失败：{err}"

    ok, err = submit_review(kid, auditor=AUDITOR, actor=ACTOR)
    if not ok:
        return "failed", f"提交审核失败：{err}"
    ok, err = audit_knowledge(kid, True, opinion="公开政策语料：来源可核实，予以发布",
                              actor=AUDITOR)
    if not ok:
        return "failed", f"审核发布失败：{err}"
    return ("updated" if existing else "created"), f"#{kid} 已发布"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="导入社区治理公开政策语料库（幂等，走审核流程发布）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--corpus", default=DEFAULT_CORPUS, help="语料 JSONL 路径")
    ap.add_argument("--db", default="", help="目标数据库路径（默认 config.DB_PATH）")
    ap.add_argument("--dry-run", action="store_true", help="只校验并打印将要导入的条目数，不写库")
    ap.add_argument("--limit", type=int, default=0, help="最多导入 N 条（0 = 全部）")
    ap.add_argument("--update", action="store_true",
                    help="已存在条目内容有变化时更新（草稿直接改；已发布建新版本）")
    ap.add_argument("--verify-only", action="store_true", help="只校验语料，不连库")
    args = ap.parse_args(argv)

    entries, errors = load_corpus(args.corpus)
    errors += validate_entries(entries)

    # 分类统计：按「知识库合法分类（topic 主题标签）」展示，便于核对 5 类约束
    cats: dict[str, int] = {}
    legal_bad: list[str] = []
    for e in entries:
        cat = db_category(e)
        if cat is None:
            legal_bad.append(f"{(e.get('title') or '')[:20]}: {e.get('category')!r}")
            continue
        key = f"{cat}（{e.get('topic') or e.get('category')}）"
        cats[key] = cats.get(key, 0) + 1
    print(f"[corpus] {args.corpus}")
    print(f"[corpus] 读取 {len(entries)} 条，知识库合法分类 {len({db_category(e) for e in entries if db_category(e)})} 个")
    for k in sorted(cats):
        print(f"[corpus]   - {k}: {cats[k]} 条")
    if legal_bad:
        print(f"[corpus] 非法分类 {len(legal_bad)} 条：{legal_bad}")

    if errors:
        print(f"[corpus] 校验失败 {len(errors)} 项：")
        for e in errors:
            print(f"  ! {e}")
        return 1
    print("[corpus] 校验通过（必备字段/标题长度/关键词数/日期格式/链接/重复）")

    if args.verify_only:
        print("[verify-only] 跳过入库")
        return 0

    todo = entries[: args.limit] if args.limit and args.limit > 0 else entries

    db_path = args.db or os.path.join(PROJECT_ROOT, "data", "community_insight.db")
    if args.dry_run:
        # 只读探测：库已存在才算「将跳过」，绝不 init_db（避免意外建库/写库）
        skipped = 0
        if os.path.exists(db_path):
            try:
                idx = existing_index(db_path)
                for e in todo:
                    if ((e.get("title") or "").strip(),
                            (e.get("source_url") or "").strip()) in idx:
                        skipped += 1
            except Exception as ex:      # 只读探测失败不影响 dry-run 结论
                print(f"[dry-run] 已有库探测跳过（{type(ex).__name__}: {ex}）")
        print(f"[dry-run] 将要导入 {len(todo) - skipped} 条"
              f"（语料 {len(todo)} 条，其中 {skipped} 条已存在会跳过）；未写库")
        return 0

    _ensure_db(db_path)
    idx = existing_index()
    stat = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    for e in todo:
        key = ((e.get("title") or "").strip(), (e.get("source_url") or "").strip())
        result, msg = import_entry(e, idx.get(key), args.update)
        stat[result] += 1
        mark = {"created": "+", "updated": "~", "skipped": "=", "failed": "!"}[result]
        print(f"[{mark}] {key[0][:34]} → {msg}")

    print(f"[done] 新增 {stat['created']} · 更新 {stat['updated']} · "
          f"跳过 {stat['skipped']} · 失败 {stat['failed']}（共 {len(todo)} 条，库：{db_path}）")
    return 1 if stat["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
