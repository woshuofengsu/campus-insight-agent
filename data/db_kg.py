# data/db_kg.py
"""轻量知识图谱（U6）：规则抽实体 → 建关系 → 按实体反查业务对象。

**设计口径（答辩要回答「图谱解决了什么」）**：
  - 只做「能查出东西」的图谱：三张表 `kg_entity` / `kg_relation` / `kg_mention`（schema v45），
    **不做可视化花架子**（不做力导向图渲染，前端可直接复用既有列表/卡片组件）。
  - 实体抽取**纯规则**（`extract_entities`）：不依赖 LLM、不花 token、可单测、可复现。
    五类实体：building（楼栋）/ facility（设施）/ topic（政策事项）/ group（人群）/
    category（工单类别，来自 `community_issues.category`，不靠文本猜）。
  - **反查是核心价值**：
      · `query_entity("3号楼")` → 该楼栋历史工单 + 相关设施（电梯/水管）+ 相关政策 + 归属工单类别；
      · `query_entity("3号楼 电梯")` → 复合查询，**取交集**（同时提到两个实体的工单），
        即竞品对标方案里的「3 号楼电梯」场景；
      · `query_entity("老人")` → 含「独居老人 / 高龄老人」等更具体实体的结果（子串扩展）。
  - **幂等**：`build_graph` 可重复调用——实体走 upsert（`name` UNIQUE），关系/引用先清后写，
    重复调用实体数、关系数不翻倍；图谱是业务数据的**派生视图**，重建即全量覆盖。

数据来源：`community_issues`（工单）/ `knowledge_base`（已发布政策）/ `proposals`（提案）。
合规：图谱只落实体名、关系与业务对象 id，**不存原文、不含手机号等 PII**。
"""
import json
import logging
import re
from collections import Counter

from data.db_core import get_db

_log = logging.getLogger(__name__)

# 实体类型（与 v45 迁移注释一致）
ETYPES = ("building", "facility", "topic", "group", "category")
# 关系类型（与 v45 迁移注释一致）
RELS = ("located_in", "has_facility", "applies_to", "mentions", "related_issue")

# ---------------------------------------------------------------- 抽取规则

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}

# 楼栋：必须以「号楼 / 栋 / 幢」结尾——避免把「二楼」（楼层）误判成楼栋
_BUILDING_RE = re.compile(r"([一二三四五六七八九十两\d]{1,3})\s*(?:号楼|栋|幢)")

# 设施 / 公共部位（canonical → 同义说法；匹配时最长优先，避免「垃圾投放点」被「垃圾投放」截断成政策事项）
_FACILITY_ALIASES = {
    "电梯": ("电梯", "货梯", "扶梯", "升降梯", "电梯间"),
    "水管": ("水管", "水龙头", "下水道", "下水管", "供水管", "自来水", "管道"),
    "路灯": ("路灯", "楼道灯", "声控灯", "照明灯", "楼道照明", "庭院灯"),
    "垃圾桶": ("垃圾桶", "垃圾箱", "垃圾站", "垃圾房", "垃圾投放点"),
    "健身器材": ("健身器材", "健身设施", "健身路径", "健身器"),
    "充电桩": ("充电桩", "充电柜", "充电站"),
    "消防栓": ("消防栓", "消火栓"),
    "消防通道": ("消防通道", "消防楼梯"),
    "无障碍坡道": ("无障碍坡道", "无障碍通道", "无障碍设施", "坡道"),
    "楼道": ("楼道", "楼梯间", "走廊"),
    "单元门": ("单元门", "门禁"),
    "地锁": ("地锁",),
    "摄像头": ("摄像头", "监控探头", "监控摄像头"),
}

# 人群（政策适用对象）
_GROUP_ALIASES = {
    "独居老人": ("独居老人", "空巢老人", "独居长者"),
    "高龄老人": ("高龄老人", "高龄长者", "百岁老人"),
    "老人": ("老年人", "老人", "老年居民", "长者", "老大爷", "老大妈"),
    "残疾人": ("残疾人", "残障人士", "残障", "残疾"),
    "低保户": ("低保户", "低保家庭", "低保", "困难家庭", "困难户"),
    "优抚对象": ("优抚对象", "退役军人"),
    "儿童": ("儿童", "未成年人", "幼儿"),
    "孕妇": ("孕妇", "孕产妇"),
}

# 政策事项（办事/治理议题）
_TOPIC_ALIASES = {
    "加装电梯": ("加装外挂电梯", "加装电梯", "电梯加装"),
    "垃圾分类": ("垃圾分类", "分类投放", "厨余垃圾", "垃圾投放"),
    "公租房": ("公共租赁住房", "公租房", "保障性住房", "保障房"),
    "医保报销": ("医疗保险报销", "医保报销", "异地就医", "医疗报销", "医保"),
    "高龄津贴": ("高龄津贴", "高龄补贴", "养老津贴", "老年津贴"),
    "养老服务": ("养老服务", "居家养老", "老年食堂", "养老驿站", "助餐"),
    "老旧小区改造": ("老旧小区改造", "老旧改造", "小区改造"),
    "低保申请": ("低保申请", "低保认定", "低保复核"),
}

_TYPE_TABLES = (("facility", _FACILITY_ALIASES), ("group", _GROUP_ALIASES), ("topic", _TOPIC_ALIASES))

# 已在专用规则里表达的实体对（其余落到 mentions）
_COVERED_PAIRS = {
    frozenset(("building", "facility")),
    frozenset(("building", "group")),
    frozenset(("topic", "group")),
}

_ISSUE_FIELDS = ("title", "location", "description", "category")
_KB_FIELDS = ("title", "keywords", "plain_interpretation", "summary", "content", "category")
_PROPOSAL_FIELDS = ("title", "description", "category", "response_text")


def _cn_num_to_int(raw: str) -> str:
    """中文数字归一：`十二` → `12`、`三` → `3`、`3` → `3`（无法解析时原样返回）。

    目的：让「四号楼」和「4号楼」合并成同一个楼栋实体（同义归一才谈得上"图"）。
    """
    s = (raw or "").strip()
    if not s:
        return s
    if s.isdigit():
        return str(int(s))
    if "十" in s:  # 十 / 十二 / 二十 / 二十三
        left, _, right = s.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return str(tens * 10 + ones)
    if all(ch in _CN_DIGITS for ch in s):
        return "".join(str(_CN_DIGITS[ch]) for ch in s)
    return s


def extract_entities(text: str) -> dict:
    """规则抽取实体（不依赖 LLM，可单测）。

    返回 `{"building": [...], "facility": [...], "group": [...], "topic": [...]}`，
    每个列表已去重；无命中时各列表为空。跨词典**最长匹配优先 + 区间不重叠**：
    例如「加装电梯」只出政策事项「加装电梯」，不会再多出一个设施「电梯」；
    「独居老人」不会同时出「老人」。
    """
    out = {"building": [], "facility": [], "group": [], "topic": []}
    if not text:
        return out

    hits: list[tuple[int, int, str, str]] = []  # (start, end, etype, name)
    for m in _BUILDING_RE.finditer(text):
        num = _cn_num_to_int(m.group(1))
        if num:
            hits.append((m.start(), m.end(), "building", f"{num}号楼"))
    for etype, table in _TYPE_TABLES:
        for canonical, aliases in table.items():
            for alias in aliases:
                for m in re.finditer(re.escape(alias), text):
                    hits.append((m.start(), m.end(), etype, canonical))

    # 起点升序、同起点长的优先（最长匹配）
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    taken: list[tuple[int, int]] = []
    for start, end, etype, name in hits:
        if any(not (end <= ts or start >= te) for ts, te in taken):
            continue  # 与已命中区间重叠 → 丢弃（保长弃短）
        taken.append((start, end))
        if name not in out[etype]:
            out[etype].append(name)
    return out


def _pair_relations(groups: dict) -> list[tuple[str, str, str]]:
    """同一业务对象内的实体两两配对 → 关系边 `(src_name, rel, dst_name)`。

    - 楼栋 × 设施 → `has_facility`（「3号楼」有「电梯」）
    - 人群 × 楼栋 → `located_in`（「独居老人」在「11号楼」）
    - 政策事项 × 人群 → `applies_to`（「高龄津贴」适用于「高龄老人」）
    - 其余**跨类型**实体对 → `mentions`（同类型不连边，避免噪声团）
    """
    pairs: list[tuple[str, str, str]] = []
    buildings = groups.get("building", [])
    facilities = groups.get("facility", [])
    people = groups.get("group", [])
    topics = groups.get("topic", [])
    for b in buildings:
        for f in facilities:
            pairs.append((b, "has_facility", f))
    for g in people:
        for b in buildings:
            pairs.append((g, "located_in", b))
    for t in topics:
        for g in people:
            pairs.append((t, "applies_to", g))
    items = sorted((n, et) for et, names in groups.items() for n in names)
    for i, (n1, t1) in enumerate(items):
        for n2, t2 in items[i + 1:]:
            if t1 == t2 or frozenset((t1, t2)) in _COVERED_PAIRS:
                continue
            pairs.append((n1, "mentions", n2))
    return pairs


# ---------------------------------------------------------------- 建图

def _row_text(ref_type: str, row: dict) -> str:
    """把业务对象的相关字段拼成一段文本供抽取（只读，不落库原文）。"""
    fields = {"issue": _ISSUE_FIELDS, "knowledge": _KB_FIELDS, "proposal": _PROPOSAL_FIELDS}.get(ref_type, ())
    return "；".join(str(row.get(f) or "") for f in fields if str(row.get(f) or "").strip())


def _load_sources(conn, limit: int) -> list[tuple[str, dict]]:
    """读三类来源（各限 limit 条，按 id 倒序 = 最新优先）。"""
    src: list[tuple[str, dict]] = []
    for r in conn.execute(
        "SELECT id, title, location, description, category FROM community_issues "
        "ORDER BY id DESC LIMIT ?", (limit,)):
        src.append(("issue", dict(r)))
    for r in conn.execute(
        "SELECT id, title, keywords, plain_interpretation, summary, content, category "
        "FROM knowledge_base WHERE audit_status='已发布' ORDER BY id DESC LIMIT ?", (limit,)):
        src.append(("knowledge", dict(r)))
    for r in conn.execute(
        "SELECT id, title, description, category, response_text FROM proposals "
        "ORDER BY id DESC LIMIT ?", (limit,)):
        src.append(("proposal", dict(r)))
    return src


def build_graph(limit: int = 500) -> dict:
    """从工单 / 已发布政策 / 提案抽取实体与关系并入库（**幂等**）。

    - 实体：`kg_entity` upsert（`name` UNIQUE），同一实体重复出现只更新来源计数；
    - 关系：`kg_relation` 按 `(src, rel, dst)` 聚合并把各来源权重相加，
      `UNIQUE(src_id, rel, dst_id)` 兜底，重复建图不产生重复边；
    - 引用：`kg_mention` 记录「实体 ↔ 业务对象」，是反查历史工单/政策的依据；
    - 每次重建**覆盖**上一次结果（派生视图），避免源数据删除后留下悬挂边。

    返回统计：`{"entities", "relations", "mentions", "sources", "limit"}`。
    """
    limit = max(1, min(int(limit or 500), 5000))
    ent_type: dict[str, str] = {}
    ent_refs: dict[str, Counter] = {}
    mention_set: set[tuple[str, str, int]] = set()
    edge_weight: Counter = Counter()
    edge_sources: dict[tuple[str, str, str], set[str]] = {}
    by_source: Counter = Counter()

    with get_db() as conn:
        for ref_type, row in _load_sources(conn, limit):
            rid = int(row["id"])
            by_source[ref_type] += 1
            groups = extract_entities(_row_text(ref_type, row))
            names: list[tuple[str, str]] = [(n, et) for et, ns in groups.items() for n in ns]
            # 工单类别是结构化字段，直接成为实体（不靠文本猜）
            category = str(row.get("category") or "").strip() if ref_type == "issue" else ""
            if category:
                names.append((category, "category"))
            for name, etype in names:
                ent_type[name] = etype
                ent_refs.setdefault(name, Counter())[ref_type] += 1
                mention_set.add((name, ref_type, rid))
            for src_name, rel, dst_name in _pair_relations(groups):
                key = (src_name, rel, dst_name)
                edge_weight[key] += 1
                edge_sources.setdefault(key, set()).add(ref_type)
            if category:
                for name, etype in names:
                    if etype == "category":
                        continue
                    key = (name, "related_issue", category)
                    edge_weight[key] += 1
                    edge_sources.setdefault(key, set()).add(ref_type)

        # 1) 清空派生表（关系/引用完全由本次重建决定）
        conn.execute("DELETE FROM kg_relation")
        conn.execute("DELETE FROM kg_mention")
        # 2) 实体 upsert（保 id 稳定）+ 清理已不存在的实体
        id_of: dict[str, int] = {}
        stale: list[int] = []
        for r in conn.execute("SELECT id, name FROM kg_entity").fetchall():
            if r["name"] in ent_type:
                id_of[r["name"]] = int(r["id"])
            else:
                stale.append(int(r["id"]))
        if stale:
            conn.executemany("DELETE FROM kg_entity WHERE id=?", [(i,) for i in stale])
        for name, etype in ent_type.items():
            attrs = json.dumps({"refs": dict(ent_refs[name])}, ensure_ascii=False)
            if name in id_of:
                conn.execute("UPDATE kg_entity SET etype=?, attrs_json=? WHERE id=?",
                             (etype, attrs, id_of[name]))
            else:
                cur = conn.execute(
                    "INSERT INTO kg_entity (name, etype, attrs_json) VALUES (?,?,?)",
                    (name, etype, attrs))
                id_of[name] = int(cur.lastrowid)
        # 3) 关系（同一对实体跨来源合并权重）+ 引用
        for (src_name, rel, dst_name), weight in edge_weight.items():
            sid, did = id_of.get(src_name), id_of.get(dst_name)
            if not sid or not did:
                continue
            conn.execute(
                "INSERT INTO kg_relation (src_id, rel, dst_id, weight, source) VALUES (?,?,?,?,?) "
                "ON CONFLICT(src_id, rel, dst_id) DO UPDATE SET weight=excluded.weight, "
                "source=excluded.source",
                (sid, rel, did, float(weight), ",".join(sorted(edge_sources[(src_name, rel, dst_name)]))))
        for name, ref_type, ref_id in sorted(mention_set):
            eid = id_of.get(name)
            if not eid:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO kg_mention (entity_id, ref_type, ref_id) VALUES (?,?,?)",
                (eid, ref_type, ref_id))
        conn.commit()

    stats = {
        "entities": len(ent_type),
        "relations": len(edge_weight),
        "mentions": len(mention_set),
        "by_type": dict(Counter(ent_type.values())),
        "sources": {k: by_source[k] for k in ("issue", "knowledge", "proposal")},
        "limit": limit,
    }
    _log.info("知识图谱重建：%s", stats)
    return stats


# ---------------------------------------------------------------- 查询

_EMPTY_STATS = {
    "entities": 0, "relations": 0, "mentions": 0, "by_type": {}, "by_rel": {},
    "by_ref_type": {}, "top_entities": [], "built_at": "", "coverage": {},
    "entity_types": list(ETYPES), "rel_types": list(RELS),
}


def _resolve_entities(conn, token: str) -> list[dict]:
    """解析一个查询词 → 实体列表：精确名优先；否则子串扩展（「老人」→ 独居老人/高龄老人）。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, name, etype, community, attrs_json FROM kg_entity WHERE name=? LIMIT 5", (token,))]
    if rows:
        return rows
    return [dict(r) for r in conn.execute(
        "SELECT id, name, etype, community, attrs_json FROM kg_entity "
        "WHERE name LIKE ? ORDER BY LENGTH(name) LIMIT 10", (f"%{token}%",))]


def _placeholders(n: int) -> str:
    return ",".join("?" for _ in range(n))


def _refs_of_group(conn, entity_ids: set, ref_type: str) -> set:
    """某个查询词组（一组实体）命中的业务对象 id 集合（ref_type ∈ issue/knowledge/proposal）。"""
    ids = sorted(entity_ids)
    if not ids:
        return set()
    rows = conn.execute(
        f"SELECT DISTINCT ref_id FROM kg_mention WHERE ref_type=? AND entity_id IN ({_placeholders(len(ids))})",
        (ref_type, *ids)).fetchall()
    return {int(r["ref_id"]) for r in rows}


def query_entity(name: str, limit: int = 20) -> dict:
    """按实体反查业务对象（**图谱的核心价值**）。

    - 单实体：`query_entity("3号楼")` → 该楼栋历史工单 + 相关设施 + 相关政策 + 归属类别；
    - 复合实体：`query_entity("3号楼 电梯")` → 分词后**取交集**（同时提到两者的工单），
      交集为空时退回并集并在 `match_mode` 标注 `any`；
    - 查不到不编造：`found=False` 并给出提示（图谱未构建 / 实体未收录）。

    返回 `{query, found, match_mode, entities, related_issues, related_knowledge,
    related_proposals, related_entities, summary, hint}`。
    """
    q = (name or "").strip()
    limit = max(1, min(int(limit or 20), 100))
    out: dict = {
        "query": q, "found": False, "match_mode": "", "entities": [],
        "related_issues": [], "related_knowledge": [], "related_proposals": [],
        "related_entities": [], "summary": "", "hint": "", "graph_entities": 0,
    }
    if not q:
        out["hint"] = "请提供实体名，如 name=3号楼 / name=电梯 / name=加装电梯"
        return out
    # 查询词先过一遍抽取器：支持「3号楼电梯」这种不带分隔符的复合查询
    tokens = [n for ns in extract_entities(q).values() for n in ns] or [q]
    try:
        with get_db() as conn:
            out["graph_entities"] = conn.execute("SELECT COUNT(*) c FROM kg_entity").fetchone()["c"] or 0
            if not out["graph_entities"]:
                out["hint"] = "图谱尚未构建：请先调用 build_graph() 或 POST /api/web/agent/kg/rebuild"
                return out

            pairs = [(t, _resolve_entities(conn, t)) for t in tokens]
            pairs = [(t, g) for t, g in pairs if g]
            if not pairs:
                out["hint"] = f"图谱中未收录「{q}」（已收录 {out['graph_entities']} 个实体）"
                return out
            used_tokens = [t for t, _ in pairs]
            groups = [g for _, g in pairs]
            id_sets = [{r["id"] for r in g} for g in groups]
            all_ids = set().union(*id_sets)
            out["found"] = True
            out["tokens"] = used_tokens
            out["entities"] = [
                {"id": r["id"], "name": r["name"], "etype": r["etype"],
                 "community": r["community"] or "", "token": t}
                for t, g in pairs for r in g
            ]

            # 复合查询在**业务对象层面**取交集：同一个查询词组内取并集，
            # 不同查询词组之间取交集（「3号楼电梯」= 同时提到 3号楼 与 电梯 的工单）。
            per_group = [{rt: _refs_of_group(conn, ids, rt) for rt in ("issue", "knowledge", "proposal")}
                         for ids in id_sets]
            if len(per_group) == 1:
                chosen = {rt: set(per_group[0][rt]) for rt in per_group[0]}
                out["match_mode"] = "single"
            else:
                out["match_mode"] = "all" if set.intersection(
                    *[g["issue"] for g in per_group]) else "any"
                chosen = {}
                for rt in ("issue", "knowledge", "proposal"):
                    inter = set.intersection(*[g[rt] for g in per_group])
                    chosen[rt] = inter if inter else set().union(*[g[rt] for g in per_group])

            if chosen["issue"]:
                ph = _placeholders(len(chosen["issue"]))
                for r in conn.execute(
                    f"SELECT id, title, category, status, location, reported_at "
                    f"FROM community_issues WHERE id IN ({ph}) "
                    f"ORDER BY reported_at DESC, id DESC LIMIT ?",
                    (*sorted(chosen["issue"]), limit)):
                    out["related_issues"].append(dict(r))

            if chosen["knowledge"]:
                ph = _placeholders(len(chosen["knowledge"]))
                for r in conn.execute(
                    f"SELECT id, title, category, source, audit_status, effective_date "
                    f"FROM knowledge_base WHERE id IN ({ph}) ORDER BY id DESC LIMIT ?",
                    (*sorted(chosen["knowledge"]), limit)):
                    out["related_knowledge"].append(dict(r))

            if chosen["proposal"]:
                ph = _placeholders(len(chosen["proposal"]))
                for r in conn.execute(
                    f"SELECT id, title, category, status, supporter_count "
                    f"FROM proposals WHERE id IN ({ph}) "
                    f"ORDER BY supporter_count DESC, id DESC LIMIT ?",
                    (*sorted(chosen["proposal"]), limit)):
                    out["related_proposals"].append(dict(r))

            ph = _placeholders(len(all_ids))
            args = sorted(all_ids)
            rel_rows = conn.execute(
                f"SELECT e.name, e.etype, r.rel, r.weight, r.source, 'out' AS direction "
                f"FROM kg_relation r JOIN kg_entity e ON e.id = r.dst_id "
                f"WHERE r.src_id IN ({ph}) "
                f"UNION ALL "
                f"SELECT e.name, e.etype, r.rel, r.weight, r.source, 'in' AS direction "
                f"FROM kg_relation r JOIN kg_entity e ON e.id = r.src_id "
                f"WHERE r.dst_id IN ({ph}) "
                f"ORDER BY weight DESC, name LIMIT ?",
                (*args, *args, max(limit, 20))).fetchall()
            seen: set[tuple] = set()
            for r in rel_rows:
                key = (r["name"], r["rel"], r["direction"])
                if key in seen:
                    continue
                seen.add(key)
                out["related_entities"].append({
                    "name": r["name"], "etype": r["etype"], "rel": r["rel"],
                    "weight": r["weight"], "source": r["source"], "direction": r["direction"]})
    except Exception as e:  # noqa: BLE001
        _log.warning("实体查询失败：%s", e, exc_info=True)
        out["hint"] = "图谱查询暂不可用"
        return out

    out["summary"] = (
        f"「{q}」关联 {len(out['related_issues'])} 条历史工单、"
        f"{len(out['related_knowledge'])} 条政策、{len(out['related_proposals'])} 条提案、"
        f"{len(out['related_entities'])} 个关联实体"
        + ("（复合查询：取交集）" if out["match_mode"] == "all" else ""))
    return out


def graph_stats() -> dict:
    """图谱规模统计（实体/关系/引用数 + 类型分布 + 关系强度 top + 工单覆盖率）。

    供网格端大屏展示「图谱不是摆设」：覆盖率 = 至少命中一个实质实体
    （楼栋/设施/人群/政策事项，不含工单类别）的工单占比。
    """
    out = json.loads(json.dumps(_EMPTY_STATS, ensure_ascii=False))
    try:
        with get_db() as conn:
            out["entities"] = conn.execute("SELECT COUNT(*) c FROM kg_entity").fetchone()["c"] or 0
            out["relations"] = conn.execute("SELECT COUNT(*) c FROM kg_relation").fetchone()["c"] or 0
            out["mentions"] = conn.execute("SELECT COUNT(*) c FROM kg_mention").fetchone()["c"] or 0
            for r in conn.execute(
                    "SELECT etype, COUNT(*) c FROM kg_entity GROUP BY etype ORDER BY c DESC"):
                out["by_type"][r["etype"] or "unknown"] = r["c"]
            for r in conn.execute(
                    "SELECT rel, COUNT(*) c FROM kg_relation GROUP BY rel ORDER BY c DESC"):
                out["by_rel"][r["rel"] or "unknown"] = r["c"]
            for r in conn.execute(
                    "SELECT ref_type, COUNT(*) c FROM kg_mention GROUP BY ref_type ORDER BY c DESC"):
                out["by_ref_type"][r["ref_type"]] = r["c"]
            out["top_entities"] = [dict(r) for r in conn.execute(
                "SELECT e.name, e.etype, COUNT(x.id) AS degree FROM kg_entity e "
                "LEFT JOIN (SELECT id, src_id AS eid FROM kg_relation "
                "           UNION ALL SELECT id, dst_id FROM kg_relation) x ON x.eid = e.id "
                "GROUP BY e.id ORDER BY degree DESC, e.name LIMIT 10")]
            row = conn.execute("SELECT MAX(created_at) t FROM kg_entity").fetchone()
            out["built_at"] = (row["t"] or "") if row else ""

            total = conn.execute("SELECT COUNT(*) c FROM community_issues").fetchone()["c"] or 0
            covered = conn.execute(
                "SELECT COUNT(DISTINCT m.ref_id) c FROM kg_mention m "
                "JOIN kg_entity e ON e.id = m.entity_id "
                "WHERE m.ref_type='issue' AND e.etype != 'category'").fetchone()["c"] or 0
            out["coverage"] = {
                "issues_total": total, "issues_covered": covered,
                "issue_coverage": round(covered * 100.0 / total, 1) if total else 0.0,
            }
    except Exception:
        _log.warning("图谱统计失败（返回零值结构）", exc_info=True)
    return out
