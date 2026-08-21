# data/db_policy.py
"""政策问答模块数据层 —— 按《07-政策问答.md》实现知识库审核/版本/时效 + 自动回答 + 转人工闭环。

知识库状态机（audit_status 字段，与知识库表同名字段一致）：
  草稿 → 待审核 → 已发布（可被自动回答引用）
              ↘ 审核不通过（退回修改，重新提交原审核人审核）
  已发布 → 已下架（手动下架原因必填 / 被新版本替换 / 到期自动下架）

提问状态机（policy_questions.status）：
  已自动回答 → （居民点转人工）→ 已转人工 → 已回复 → 已结束 / （未解决退回）已转人工
  匹配失败不落提问记录，居民确认转人工才建记录；超过 3 次「未解决→继续回复」
  循环自动标记「需线下沟通」停止循环。

版本管理：每个版本是 knowledge_base 的一行（版本号递增 V1/V2/V3），
新版本审核通过后自动把同政策旧版本下架（audit_opinion 记「被Vx替换」），
每次发布都在 knowledge_versions 留版本快照；历史提问记录的回答文本本身
冻结当时版本，不受新版本影响。

全部关键操作走 log_activity 留痕（module="政策问答"）。
"""
import json
import math
import re
from datetime import datetime, timedelta

from data.db_core import get_db
from data.db_notifications import log_activity

MODULE = "政策问答"

# 知识库分类（5 大类）
POLICY_CATEGORIES = ["社保医保", "养老服务", "住房保障", "办事指引", "社区规定"]

# 知识库状态
KNOWLEDGE_STATUS = ["草稿", "待审核", "审核不通过", "已发布", "已下架"]
# 提问状态（含展示态「超时未回复」，由 24 小时时限计算得出）
QUESTION_STATUS = ["已自动回答", "已转人工", "已回复", "已结束", "需线下沟通", "超时未回复"]

# 状态颜色（居民端/负责人端一致；压测修正配色：已自动回答蓝/已转人工黄/已回复绿/
# 已结束灰/超时未回复红/需线下沟通橙）
STATUS_COLORS = {
    "已自动回答": "#2563eb",
    "已转人工": "#d97706",
    "已回复": "#059669",
    "已结束": "#64748b",
    "需线下沟通": "#ea580c",
    "超时未回复": "#dc2626",
    "草稿": "#64748b",
    "待审核": "#d97706",
    "审核不通过": "#dc2626",
    "已发布": "#059669",
    "已下架": "#94a3b8",
}

MAX_LOOP = 3            # 同一提问最多 3 次「未解决→继续回复」循环
REPLY_HOURS = 24        # 人工回复时限（小时）
AUTO_CLOSE_DAYS = 7     # 人工回复后 7 天未反馈自动结束

# 自动回答匹配阈值：最高匹配度低于该值判定失败提示转人工。
# 负责人可在后台调整（进程内生效，立即生效，留痕；重启恢复默认）。
AUTO_ANSWER_THRESHOLD = 2.0
_match_threshold = AUTO_ANSWER_THRESHOLD

# 知识库来源限制
SELF_MADE_SOURCE = "社区整理"
SELF_MADE_NOTICE = "本内容由社区整理，仅供参考"
SELF_MADE_FOOTER = "本指引由社区整理，仅供参考"
# 疫苗/传染病类专业信息不允许社区自编
_PROHIBITED_SELF_MADE_KEYWORDS = [
    "疫苗", "接种", "传染病", "流感", "肺炎", "手足口", "乙肝", "结核", "艾滋",
    "狂犬", "免疫", "疫情", "禽流感", "新冠", "登革热", "隔离", "消毒", "传染",
]

_SERVICE_KEYWORDS = ["怎么办", "如何", "流程", "材料", "办理", "申请", "手续",
                     "去哪", "哪里办", "怎么办理", "如何申请", "预约", "窗口",
                     "带什么", "步骤", "要什么", "需要什么"]
_POLICY_KEYWORDS = ["政策", "补贴", "标准", "规定", "怎么算", "多少钱", "待遇",
                    "条件", "资格", "比例", "金额", "报销", "减免", "领取", "发放",
                    "档次", "基数", "费率"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NGRAM_KEEP = re.compile(r"[^一-鿿\w]")


# ---------------------------------------------------------------- 小工具

def split_keywords(keywords: str) -> list[str]:
    """关键词按逗号/顿号/空格拆分。"""
    if not keywords:
        return []
    return [k.strip() for k in re.split(r"[,，、;；\s]+", keywords) if k.strip()]


def masked_nickname(user_id: int, role_prefix: str = "居民") -> str:
    """脱敏昵称：居民+手机号后4位（无手机号时取 resident_id 末尾数字兜底）。"""
    try:
        from data.db_user import get_user_by_id
        u = get_user_by_id(user_id) or {}
    except Exception:
        u = {}
    digits = re.sub(r"\D", "", u.get("resident_id") or "")
    if len(digits) >= 4:
        return f"{role_prefix}{digits[-4:]}"
    name = (u.get("name") or "").strip()
    if name:
        return f"{role_prefix}{name[:1]}**"
    return f"{role_prefix}{user_id}"


def check_source_rules(source: str, title: str, content: str,
                       plain_interpretation: str) -> str:
    """知识库来源限制校验。返回错误信息，'' 表示通过。

    - 社区整理内容：正文开头必须标注「本内容由社区整理，仅供参考」（create 时自动补）。
    - 疫苗/传染病等专业信息不允许社区自编，必须来自权威机构。
    """
    src = (source or "").strip()
    if src != SELF_MADE_SOURCE:
        return ""
    text = f"{title or ''} {content or ''} {plain_interpretation or ''}"
    for kw in _PROHIBITED_SELF_MADE_KEYWORDS:
        if kw in text:
            return "疫苗/传染病等专业信息不允许社区自编，请选择权威机构来源（如疾控/卫健部门）或引用官方发布内容。"
    return ""


def apply_source_notice(source: str, content: str) -> str:
    """社区整理内容自动在正文开头标注「本内容由社区整理，仅供参考」。"""
    if (source or "").strip() != SELF_MADE_SOURCE:
        return content or ""
    c = (content or "").strip()
    if c.startswith(SELF_MADE_NOTICE):
        return c
    return f"{SELF_MADE_NOTICE}\n{c}" if c else SELF_MADE_NOTICE


def classify_question(question: str) -> str:
    """意图识别：政策咨询 / 办事指引 / 待人工分类。"""
    q = question or ""
    sv = sum(1 for k in _SERVICE_KEYWORDS if k in q)
    pv = sum(1 for k in _POLICY_KEYWORDS if k in q)
    if sv > pv:
        return "办事指引"
    if pv > sv:
        return "政策咨询"
    return "待人工分类"


def validate_knowledge_fields(title: str, category: str, plain_interpretation: str,
                              source: str, effective_date: str, expire_date: str = "",
                              keywords: str = "") -> str:
    """知识库必填/格式校验。返回错误信息，'' 表示通过。"""
    if not title or not title.strip():
        return "标题不能为空"
    if len(title.strip()) > 50:
        return "标题最长 50 字"
    if category not in POLICY_CATEGORIES:
        return "请选择正确的分类"
    if not plain_interpretation or not plain_interpretation.strip():
        return "通俗解读不能为空"
    if not source or not source.strip():
        return "来源不能为空"
    if not _DATE_RE.match(effective_date or ""):
        return "政策生效日期必填（格式 YYYY-MM-DD）"
    if expire_date:
        if not _DATE_RE.match(expire_date):
            return "政策失效日期格式不正确（YYYY-MM-DD）"
        if expire_date < effective_date:
            return "失效日期不能早于生效日期"
    kws = split_keywords(keywords)
    if not kws:
        return "关键词不能为空（1-5 个，逗号分隔）"
    if len(kws) > 5:
        return "关键词最多 5 个"
    return ""


# ---------------------------------------------------------------- 检索打分

def _char_ngrams(text: str, n: int = 2) -> list[str]:
    cleaned = _NGRAM_KEEP.sub("", (text or "").lower())
    if len(cleaned) < n:
        return [cleaned] if cleaned else []
    return [cleaned[i:i + n] for i in range(len(cleaned) - n + 1)]


def _text_ngrams(text: str) -> list[str]:
    return _char_ngrams(text, 2) + _char_ngrams(text, 3)


def _tf(ngrams: list[str]) -> dict[str, float]:
    total = len(ngrams) or 1
    c: dict[str, float] = {}
    for g in ngrams:
        c[g] = c.get(g, 0) + 1
    return {k: v / total for k, v in c.items()}


def _cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in vec_a)
    na = math.sqrt(sum(v * v for v in vec_a.values())) or 1e-10
    nb = math.sqrt(sum(v * v for v in vec_b.values())) or 1e-10
    return dot / (na * nb)


def _score_entry(question: str, entry: dict) -> tuple[float, list[str]]:
    """单条知识条目与提问的匹配度。

    关键词命中 +2/个、标题整句命中 +3、n-gram 余弦相似度折算最高 +5。
    """
    title = entry.get("title") or ""
    text = " ".join([
        title,
        entry.get("plain_interpretation") or "",
        entry.get("content") or "",
        entry.get("summary") or "",
    ])
    score = 0.0
    kw_hits = [k for k in split_keywords(entry.get("keywords"))
               if len(k) >= 2 and k in (question or "")]
    score += 2.0 * len(kw_hits)
    if title and title in (question or ""):
        score += 3.0
    score += 5.0 * _cosine(_tf(_text_ngrams(question or "")), _tf(_text_ngrams(text)))
    return round(score, 4), kw_hits


def _is_effective(entry: dict) -> bool:
    """已生效且未失效（生效/失效日期为空视为长期有效）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    eff = (entry.get("effective_date") or "").strip()
    exp = (entry.get("expire_date") or "").strip()
    if eff and eff > today:
        return False
    if exp and exp < today:
        return False
    return True


def search_published_knowledge(query: str, top_k: int = 5,
                               category: str | None = None) -> list[dict]:
    """只检索「已发布且未失效」的条目，按匹配度降序返回（带 score 字段）。"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM knowledge_base").fetchall()
    scored: list[tuple[dict, float]] = []
    for r in rows:
        e = dict(r)
        if e.get("audit_status") != "已发布":
            continue
        if category and e.get("category") != category:
            continue
        if not _is_effective(e):
            continue
        s, _ = _score_entry(query, e)
        if s > 0:
            scored.append((e, s))
    scored.sort(key=lambda x: -x[1])
    out = []
    for e, s in scored[:top_k]:
        e["score"] = round(s, 4)
        out.append(e)
    return out


def format_knowledge_answer(entry: dict) -> str:
    """自动回答正文：优先「通俗解读」，附「依据：XX政策（Vn）」，社区整理加脚注。"""
    interp = (entry.get("plain_interpretation") or "").strip() or \
        (entry.get("summary") or "").strip()
    body = interp or (entry.get("content") or "").strip()
    lines = [body] if body else []
    ref = f"依据：{entry.get('title') or ''}（V{entry.get('version') or 1}）"
    if entry.get("policy_number"):
        ref += f" · {entry['policy_number']}"
    lines.append(ref)
    if (entry.get("source") or "").strip() == SELF_MADE_SOURCE:
        lines.append(SELF_MADE_FOOTER)
    return "\n\n".join(lines)


# ---------------------------------------------------------------- 知识库 CRUD

def get_knowledge(knowledge_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM knowledge_base WHERE id=?", (knowledge_id,)).fetchone()
        return dict(row) if row else None


def get_knowledge_list(status: str | None = None, category: str | None = None,
                       search: str = "", limit: int = 300) -> list[dict]:
    q = "SELECT * FROM knowledge_base WHERE 1=1"
    args: list = []
    if status:
        q += " AND audit_status=?"
        args.append(status)
    if category:
        q += " AND category=?"
        args.append(category)
    if search:
        q += " AND (title LIKE ? OR keywords LIKE ? OR content LIKE ?)"
        s = f"%{search}%"
        args += [s, s, s]
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def _get_base_id(conn, knowledge_id: int) -> int | None:
    """从版本快照取血缘：该版本基于哪个版本创建（create_new_version 时写入）。"""
    row = conn.execute(
        "SELECT snapshot_json FROM knowledge_versions WHERE knowledge_id=? "
        "ORDER BY id DESC LIMIT 1",
        (knowledge_id,),
    ).fetchone()
    if not row:
        return None
    try:
        d = json.loads(row["snapshot_json"] or "{}")
        return d.get("_base_knowledge_id")
    except Exception:
        return None


def _ancestor_chain(conn, knowledge_id: int) -> list[int]:
    """版本血缘链（自己 → 基础版本 → 基础的基础 …）。"""
    chain: list[int] = []
    cur = knowledge_id
    seen: set[int] = set()
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = _get_base_id(conn, cur)
    return chain


def create_knowledge(title: str, category: str, plain_interpretation: str,
                     source: str, keywords: str, effective_date: str,
                     content: str = "", summary: str = "", expire_date: str = "",
                     policy_number: str = "", applicable_area: str = "",
                     attachment: str = "", actor: str = "负责人") -> tuple[int, str]:
    """创建知识库草稿（V1）。返回 (id, 错误信息)；错误时 id=0。"""
    err = validate_knowledge_fields(title, category, plain_interpretation, source,
                                    effective_date, expire_date, keywords)
    if err:
        return 0, err
    src_err = check_source_rules(source, title, content, plain_interpretation)
    if src_err:
        return 0, src_err
    content = apply_source_notice(source, content)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_base (category, title, content, keywords, audit_status, "
            "source, effective_date, expire_date, version, plain_interpretation, summary, "
            "publisher, policy_number, applicable_area, attachment, created_at, updated_at) "
            "VALUES (?,?,?,?,'草稿',?,?,?,1,?,?,?,?,?,?,datetime('now','localtime'),"
            "datetime('now','localtime'))",
            (category, title.strip(), content, keywords.strip(), source.strip(),
             effective_date, expire_date, plain_interpretation.strip(), summary.strip(),
             actor, policy_number.strip(), applicable_area.strip(), attachment.strip()),
        )
        kid = cur.lastrowid
        conn.commit()
    log_activity(actor, "创建知识库草稿", "knowledge", kid, title.strip(),
                 module=MODULE, after_value="草稿")
    return kid, ""


def update_knowledge(knowledge_id: int, title: str, category: str,
                     plain_interpretation: str, source: str, keywords: str,
                     effective_date: str, content: str = "", summary: str = "",
                     expire_date: str = "", policy_number: str = "",
                     applicable_area: str = "", attachment: str = "",
                     actor: str = "负责人") -> tuple[bool, str]:
    """修改草稿/审核不通过条目（已发布只能通过新版本修改）。"""
    row = get_knowledge(knowledge_id)
    if not row:
        return False, "知识库条目不存在"
    if row.get("audit_status") not in ("草稿", "审核不通过"):
        return False, f"当前状态「{row.get('audit_status')}」不支持修改，已发布内容请创建新版本"
    err = validate_knowledge_fields(title, category, plain_interpretation, source,
                                    effective_date, expire_date, keywords)
    if err:
        return False, err
    src_err = check_source_rules(source, title, content, plain_interpretation)
    if src_err:
        return False, src_err
    content = apply_source_notice(source, content)
    with get_db() as conn:
        conn.execute(
            "UPDATE knowledge_base SET category=?, title=?, content=?, keywords=?, "
            "source=?, effective_date=?, expire_date=?, plain_interpretation=?, summary=?, "
            "policy_number=?, applicable_area=?, attachment=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (category, title.strip(), content, keywords.strip(), source.strip(),
             effective_date, expire_date, plain_interpretation.strip(), summary.strip(),
             policy_number.strip(), applicable_area.strip(), attachment.strip(), knowledge_id),
        )
        conn.commit()
    log_activity(actor, "修改知识库", "knowledge", knowledge_id, title.strip(),
                 module=MODULE, before_value=row.get("audit_status"), after_value=row.get("audit_status"))
    return True, ""


def delete_knowledge(knowledge_id: int, actor: str = "负责人") -> tuple[bool, str]:
    """删除草稿（仅草稿可删，留痕）。"""
    row = get_knowledge(knowledge_id)
    if not row:
        return False, "知识库条目不存在"
    if row.get("audit_status") != "草稿":
        return False, "仅草稿状态可删除"
    with get_db() as conn:
        conn.execute("DELETE FROM knowledge_base WHERE id=?", (knowledge_id,))
        conn.commit()
    log_activity(actor, "删除知识库草稿", "knowledge", knowledge_id, row.get("title", ""),
                 module=MODULE, before_value="草稿", after_value="已删除")
    return True, ""


def submit_review(knowledge_id: int, auditor: str = "",
                  actor: str = "负责人") -> tuple[bool, str]:
    """提交审核：草稿/审核不通过 → 待审核。审核人不能与发布人相同。"""
    row = get_knowledge(knowledge_id)
    if not row:
        return False, "知识库条目不存在"
    if row.get("audit_status") not in ("草稿", "审核不通过"):
        return False, f"当前状态「{row.get('audit_status')}」不支持提交审核"
    auditor = (auditor or "").strip() or (row.get("auditor") or "").strip()
    if not auditor:
        return False, "请选择审核人"
    if auditor == row.get("publisher"):
        return False, "发布人与审核人不能相同"
    # 重新提交校验必填项（标题、通俗解读、分类、来源、生效日期、关键词）
    err = validate_knowledge_fields(
        row.get("title", ""), row.get("category", ""), row.get("plain_interpretation", ""),
        row.get("source", ""), row.get("effective_date", ""), row.get("expire_date", ""),
        row.get("keywords", ""),
    )
    if err:
        return False, err
    with get_db() as conn:
        conn.execute(
            "UPDATE knowledge_base SET audit_status='待审核', auditor=?, audit_opinion='' WHERE id=?",
            (auditor, knowledge_id),
        )
        conn.commit()
    log_activity(actor, "提交审核", "knowledge", knowledge_id, row.get("title", ""),
                 module=MODULE, before_value=row.get("audit_status"), after_value="待审核",
                 detail=f"审核人：{auditor}")
    return True, ""


def withdraw_review(knowledge_id: int, actor: str = "负责人") -> tuple[bool, str]:
    """撤回待审核 → 草稿（留痕）。"""
    row = get_knowledge(knowledge_id)
    if not row:
        return False, "知识库条目不存在"
    if row.get("audit_status") != "待审核":
        return False, f"当前状态「{row.get('audit_status')}」不支持撤回"
    with get_db() as conn:
        conn.execute("UPDATE knowledge_base SET audit_status='草稿' WHERE id=?", (knowledge_id,))
        conn.commit()
    log_activity(actor, "撤回审核", "knowledge", knowledge_id, row.get("title", ""),
                 module=MODULE, before_value="待审核", after_value="草稿")
    return True, ""


def audit_knowledge(knowledge_id: int, approve: bool, opinion: str = "",
                    actor: str = "负责人") -> tuple[bool, str]:
    """负责人审核：通过 → 已发布（存版本快照、自动下架同政策旧版）；不通过 → 审核不通过（意见必填）。

    发布人不能审核自己发布的内容。
    """
    row = get_knowledge(knowledge_id)
    if not row:
        return False, "知识库条目不存在"
    if row.get("audit_status") != "待审核":
        return False, f"当前状态「{row.get('audit_status')}」不支持审核"
    if actor == row.get("publisher"):
        return False, "发布人不能审核自己发布的内容，请换其他负责人审核"
    if not approve and not (opinion or "").strip():
        return False, "审核不通过必须填写审核意见"

    if approve:
        new_version = row.get("version") or 1
        replaced: list[dict] = []
        with get_db() as conn:
            # 新版本审核通过后自动替换旧版本：沿版本血缘把已发布的旧版本下架
            for aid in _ancestor_chain(conn, knowledge_id)[1:]:
                arow = conn.execute(
                    "SELECT * FROM knowledge_base WHERE id=?", (aid,)
                ).fetchone()
                if not arow or arow["audit_status"] != "已发布":
                    continue
                conn.execute(
                    "UPDATE knowledge_base SET audit_status='已下架', audit_opinion=? WHERE id=?",
                    (f"被V{new_version}替换", aid),
                )
                replaced.append(dict(arow))
            conn.execute(
                "UPDATE knowledge_base SET audit_status='已发布', audit_opinion='' WHERE id=?",
                (knowledge_id,),
            )
            # 发布版本快照（保留血缘字段）
            base_id = _get_base_id(conn, knowledge_id)
            snap = json.dumps({**_knowledge_view(row), "_base_knowledge_id": base_id},
                              ensure_ascii=False)
            exist = conn.execute(
                "SELECT id FROM knowledge_versions WHERE knowledge_id=? ORDER BY id DESC LIMIT 1",
                (knowledge_id,),
            ).fetchone()
            if exist:
                conn.execute(
                    "UPDATE knowledge_versions SET version=?, title=?, content=?, "
                    "plain_interpretation=?, summary=?, source=?, effective_date=?, "
                    "expire_date=?, snapshot_json=? WHERE id=?",
                    (new_version, row.get("title", ""), row.get("content", ""),
                     row.get("plain_interpretation", ""), row.get("summary", ""),
                     row.get("source", ""), row.get("effective_date", ""),
                     row.get("expire_date", ""), snap, exist["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO knowledge_versions (knowledge_id, version, title, content, "
                    "plain_interpretation, summary, source, effective_date, expire_date, "
                    "snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (knowledge_id, new_version, row.get("title", ""), row.get("content", ""),
                     row.get("plain_interpretation", ""), row.get("summary", ""),
                     row.get("source", ""), row.get("effective_date", ""),
                     row.get("expire_date", ""), snap),
                )
            conn.commit()
        for sib in replaced:
            log_activity(actor, "下架知识库（被新版本替换）", "knowledge", sib["id"],
                         sib.get("title", ""), module=MODULE,
                         before_value="已发布", after_value="已下架",
                         detail=f"被V{new_version}替换")
        log_activity(actor, "审核通过并发布", "knowledge", knowledge_id, row.get("title", ""),
                     module=MODULE, before_value="待审核", after_value="已发布",
                     detail=f"V{new_version} 发布，旧版本已自动下架")
        return True, "已发布，可被自动回答引用"
    else:
        with get_db() as conn:
            conn.execute(
                "UPDATE knowledge_base SET audit_status='审核不通过', audit_opinion=? WHERE id=?",
                (opinion.strip(), knowledge_id),
            )
            conn.commit()
        log_activity(actor, "审核不通过", "knowledge", knowledge_id, row.get("title", ""),
                     module=MODULE, before_value="待审核", after_value="审核不通过",
                     detail=opinion.strip())
        return True, "已退回，请修改后重新提交审核"


def create_new_version(knowledge_id: int, title: str, category: str,
                       plain_interpretation: str, source: str, keywords: str,
                       effective_date: str, content: str = "", summary: str = "",
                       expire_date: str = "", policy_number: str = "",
                       applicable_area: str = "", attachment: str = "",
                       actor: str = "负责人", auditor: str = "") -> tuple[int, str]:
    """在已发布条目基础上创建新版本（Vn+1，草稿态），新版本审核通过后自动替换旧版。"""
    base = get_knowledge(knowledge_id)
    if not base:
        return 0, "知识库条目不存在"
    if base.get("audit_status") != "已发布":
        return 0, "只能在已发布条目上创建新版本"
    err = validate_knowledge_fields(title, category, plain_interpretation, source,
                                    effective_date, expire_date, keywords)
    if err:
        return 0, err
    src_err = check_source_rules(source, title, content, plain_interpretation)
    if src_err:
        return 0, src_err
    content = apply_source_notice(source, content)
    auditor = (auditor or "").strip() or (base.get("auditor") or "").strip()
    with get_db() as conn:
        chain = _ancestor_chain(conn, knowledge_id)
        max_v = base.get("version") or 1
        for aid in chain:
            r = conn.execute("SELECT version FROM knowledge_base WHERE id=?", (aid,)).fetchone()
            if r and r["version"]:
                max_v = max(max_v, r["version"])
        new_version = max_v + 1
        cur = conn.execute(
            "INSERT INTO knowledge_base (category, title, content, keywords, audit_status, "
            "source, effective_date, expire_date, version, plain_interpretation, summary, "
            "publisher, auditor, policy_number, applicable_area, attachment) "
            "VALUES (?,?,?,?,'草稿',?,?,?,?,?,?,?,?,?,?,?)",
            (category, title.strip(), content, keywords.strip(), source.strip(),
             effective_date, expire_date, new_version, plain_interpretation.strip(),
             summary.strip(), actor, auditor, policy_number.strip(),
             applicable_area.strip(), attachment.strip()),
        )
        kid = cur.lastrowid
        # 版本血缘：记录该版本基于哪个版本创建（发布时快照补全并保留血缘）
        conn.execute(
            "INSERT INTO knowledge_versions (knowledge_id, version, title, content, "
            "plain_interpretation, summary, source, effective_date, expire_date, snapshot_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (kid, new_version, title.strip(), content, plain_interpretation.strip(),
             summary.strip(), source.strip(), effective_date, expire_date,
             json.dumps({"_base_knowledge_id": knowledge_id}, ensure_ascii=False)),
        )
        conn.commit()
    log_activity(actor, "创建新版本", "knowledge", kid, title.strip(), module=MODULE,
                 after_value="草稿", detail=f"V{new_version}（基于 #{knowledge_id}）")
    return kid, ""


def take_down_knowledge(knowledge_id: int, reason: str,
                        actor: str = "负责人") -> tuple[bool, str]:
    """手动下架已发布条目（原因必填，二次确认由 UI 层负责）。"""
    reason = (reason or "").strip()
    if not reason:
        return False, "下架原因必填"
    row = get_knowledge(knowledge_id)
    if not row:
        return False, "知识库条目不存在"
    if row.get("audit_status") != "已发布":
        return False, f"当前状态「{row.get('audit_status')}」不支持下架"
    with get_db() as conn:
        conn.execute(
            "UPDATE knowledge_base SET audit_status='已下架', audit_opinion=? WHERE id=?",
            (reason, knowledge_id),
        )
        conn.commit()
    log_activity(actor, "下架知识库", "knowledge", knowledge_id, row.get("title", ""),
                 module=MODULE, before_value="已发布", after_value="已下架", detail=reason)
    return True, ""


def auto_expire_knowledge(actor: str = "系统") -> list[dict]:
    """时效管理：失效日期到达自动下架（幂等留痕，不重复记录）。"""
    expired: list[dict] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_base WHERE audit_status='已发布' AND expire_date != '' "
            "AND date(expire_date) < date('now','localtime')"
        ).fetchall()
        for r in rows:
            e = dict(r)
            exists = conn.execute(
                "SELECT COUNT(*) c FROM activity_log WHERE module=? AND target_type='knowledge' "
                "AND target_id=? AND action='自动下架（到期）'",
                (MODULE, e["id"]),
            ).fetchone()["c"]
            if exists:
                continue
            conn.execute(
                "UPDATE knowledge_base SET audit_status='已下架', audit_opinion='到期下架' WHERE id=?",
                (e["id"],),
            )
            expired.append(e)
        conn.commit()
    for e in expired:
        log_activity(actor, "自动下架（到期）", "knowledge", e["id"], e.get("title", ""),
                     module=MODULE, before_value="已发布", after_value="已下架",
                     detail=f"失效日期 {e.get('expire_date')}")
    return expired


def get_expiring_knowledge(days: int = 7) -> list[dict]:
    """到期前 N 天提醒更新/下架（供负责人查看）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_base WHERE audit_status='已发布' AND expire_date != '' "
            "AND date(expire_date) >= date('now','localtime') "
            "AND date(expire_date) <= date('now','localtime', ? || ' days') ORDER BY expire_date",
            (str(days),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_published_options() -> list[dict]:
    """人工回复时可引用的知识库条目（已发布且未失效）。"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM knowledge_base").fetchall()
    out = []
    for r in rows:
        e = dict(r)
        if e.get("audit_status") == "已发布" and _is_effective(e):
            out.append({
                "id": e["id"],
                "label": f"「{e.get('title')}」V{e.get('version') or 1} · {e.get('category')}",
            })
    return out


def get_version_history(knowledge_id: int) -> list[dict]:
    """同政策全部版本行（沿版本血缘，含当前），按版本号降序，标记当前生效。"""
    row = get_knowledge(knowledge_id)
    if not row:
        return []
    with get_db() as conn:
        chain = _ancestor_chain(conn, knowledge_id)
        all_rows = [dict(r) for r in conn.execute("SELECT * FROM knowledge_base").fetchall()]
        ids = set(chain)
        for r in all_rows:
            if knowledge_id in _ancestor_chain(conn, r["id"]):
                ids.add(r["id"])
    versions = [r for r in all_rows if r["id"] in ids]
    for v in versions:
        v["is_current"] = (v["id"] == knowledge_id and v.get("audit_status") == "已发布")
    versions.sort(key=lambda x: -(x.get("version") or 0))
    return versions


def get_knowledge_activity(knowledge_id: int, limit: int = 10) -> list[dict]:
    """知识库操作留痕时间线（最近在前）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE module=? AND target_type='knowledge' AND target_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (MODULE, knowledge_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------- 提问与自动回答

def get_question(question_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM policy_questions WHERE id=?", (question_id,)).fetchone()
        return dict(row) if row else None


def ask_question(user_id: int, question: str, source: str = "居民端",
                 category: str | None = None, actor: str | None = None) -> dict:
    """提问并自动回答。匹配成功落提问记录（已自动回答），失败只留痕不落记录。

    返回 dict：matched=True 时含 question_id/auto_answer/knowledge/score；
    matched=False 时 reason 为 no_knowledge / low_score / empty / too_long。
    """
    q = (question or "").strip()
    if not q:
        return {"matched": False, "reason": "empty"}
    if len(q) > 200:
        return {"matched": False, "reason": "too_long"}
    summary = q[:30]
    q_type = classify_question(q)
    actor = actor or masked_nickname(user_id)

    results = search_published_knowledge(q, top_k=5, category=category)
    if not results and category:
        results = search_published_knowledge(q, top_k=5)  # 指定分类没命中，放宽全库
    if not results:
        log_activity(actor, "自动回答失败", "policy_question", None, summary,
                     module=MODULE, after_value="匹配失败",
                     detail=f"{q_type} · 无匹配条目 · {q[:50]}")
        return {"matched": False, "reason": "no_knowledge", "question": q,
                "summary": summary, "q_type": q_type}
    best = results[0]
    if best["score"] < _match_threshold:
        log_activity(actor, "自动回答失败", "policy_question", None, summary,
                     module=MODULE, after_value="匹配失败",
                     detail=f"{q_type} · 匹配度 {best['score']} 低于阈值 {_match_threshold} · {q[:50]}")
        return {"matched": False, "reason": "low_score", "question": q,
                "summary": summary, "q_type": q_type, "best_score": best["score"]}

    auto_answer = format_knowledge_answer(best)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO policy_questions (user_id, question, summary, q_type, source, status, "
            "auto_answer, cited_knowledge_id) VALUES (?,?,?,?,?,'已自动回答',?,?)",
            (user_id, q, summary, q_type, source, auto_answer, best["id"]),
        )
        qid = cur.lastrowid
        conn.execute("UPDATE knowledge_base SET cite_count = cite_count + 1 WHERE id=?",
                     (best["id"],))
        conn.commit()
    log_activity(actor, "提问并自动回答", "policy_question", qid, summary, module=MODULE,
                 after_value="已自动回答",
                 detail=f"引用 #{best['id']} {best.get('title')}（V{best.get('version') or 1}）")
    return {
        "matched": True, "question_id": qid, "question": q, "summary": summary,
        "q_type": q_type, "auto_answer": auto_answer, "knowledge_id": best["id"],
        "knowledge": _knowledge_view(best), "score": best["score"],
    }


def _notify_managers(qid: int, summary: str) -> None:
    """转人工后通知负责人（有新的待回复提问，spec 07）。"""
    try:
        from data.db_user import list_users
        from data.db_notifications import create_notification
        for u in list_users(role="grid"):
            create_notification(
                u["id"], "policy_question", "有新的政策问答待回复",
                f"提问「{summary[:20]}」已转人工，请在24小时内回复。",
                related_id=qid,
            )
    except Exception:
        pass


def transfer_to_human(question_id: int | None = None, user_id: int | None = None,
                      question: str = "", summary: str = "", q_type: str = "",
                      source: str = "居民端", actor: str = "居民") -> tuple[bool, str, int]:
    """转人工：自动匹配失败新建记录，或把已自动回答记录转为已转人工。"""
    if question_id:
        row = get_question(question_id)
        if not row:
            return False, "提问不存在", 0
        if row["status"] in ("已转人工", "已回复"):
            return False, "该提问已在人工处理中", question_id
        if row["status"] not in ("已自动回答",):
            return False, f"当前状态「{row['status']}」不支持转人工", question_id
        with get_db() as conn:
            conn.execute("UPDATE policy_questions SET status='已转人工' WHERE id=?",
                         (question_id,))
            conn.commit()
        log_activity(actor, "转人工", "policy_question", question_id, row["summary"],
                     module=MODULE, before_value=row["status"], after_value="已转人工")
        _notify_managers(question_id, row["summary"])
        return True, "已转人工，负责人将在24小时内回复您", question_id

    q = (question or "").strip()
    if not q:
        return False, "提问内容不能为空", 0
    if len(q) > 200:
        return False, "提问最长 200 字", 0
    if not user_id:
        return False, "缺少提问人", 0
    summary = summary or q[:30]
    q_type = q_type or classify_question(q)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO policy_questions (user_id, question, summary, q_type, source, status) "
            "VALUES (?,?,?,?,?,'已转人工')",
            (user_id, q, summary, q_type, source),
        )
        qid = cur.lastrowid
        conn.commit()
    log_activity(actor, "提问并转人工", "policy_question", qid, summary,
                 module=MODULE, after_value="已转人工")
    _notify_managers(qid, summary)
    return True, "已转人工，负责人将在24小时内回复您", qid


def reply_question(question_id: int, reply: str, actor: str = "负责人",
                   cited_knowledge_id: int | None = None) -> tuple[bool, str, int]:
    """负责人人工回复。引用知识库时自动附带「参考：XX政策」；引用已下架提示重新选择。"""
    r = (reply or "").strip()
    if not r:
        return False, "回复内容不能为空", 0
    if len(r) > 2000:
        return False, "回复内容最长 2000 字", 0
    row = get_question(question_id)
    if not row:
        return False, "提问不存在", 0
    if row["status"] not in ("已转人工", "超时未回复", "继续回复"):
        return False, f"当前状态「{row['status']}」不支持回复", question_id

    answer = r
    cite_note = "文字回复"
    if cited_knowledge_id:
        kb = get_knowledge(cited_knowledge_id)
        if not kb:
            return False, "引用的知识库条目不存在", question_id
        if kb.get("audit_status") != "已发布" or not _is_effective(kb):
            return False, "该内容已下架，请重新选择", question_id
        answer = f"{r}\n\n参考：{kb.get('title')}（V{kb.get('version') or 1}）"
        cite_note = f"引用知识库 #{kb['id']} {kb.get('title')}（V{kb.get('version') or 1}）"
    with get_db() as conn:
        conn.execute(
            "UPDATE policy_questions SET status='已回复', answer=?, answered_by=?, "
            "answered_at=CURRENT_TIMESTAMP WHERE id=?",
            (answer, actor, question_id),
        )
        conn.commit()
    log_activity(actor, "人工回复", "policy_question", question_id, row["summary"],
                 module=MODULE, before_value="已转人工", after_value="已回复", detail=cite_note)
    return True, "回复成功", question_id


def feedback_question(question_id: int, satisfied: bool, reason: str = "",
                      actor: str = "居民") -> tuple[bool, str, int]:
    """居民反馈。

    - 已自动回答：有帮助 / 无帮助（无帮助只记录，不自动转人工）。
    - 已回复：已解决 → 已结束；未解决 → 退回已转人工继续回复（最多 3 次循环，
      超过自动标记「需线下沟通」停止循环）。
    返回 msg 为 '感谢反馈' / 'unhelpful' / '已结束' / 'loop' / 'offline' / 错误信息。
    """
    row = get_question(question_id)
    if not row:
        return False, "提问不存在", 0
    old = row["status"]

    if old == "已自动回答":
        fb = "有帮助" if satisfied else "无帮助"
        with get_db() as conn:
            conn.execute(
                "UPDATE policy_questions SET feedback=?, feedback_reason=?, feedback_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (fb, reason, question_id),
            )
            conn.commit()
        log_activity(actor, fb, "policy_question", question_id, row["summary"],
                     module=MODULE, detail=reason or "")
        return True, "感谢反馈" if satisfied else "unhelpful", question_id

    if old == "已回复":
        if satisfied:
            with get_db() as conn:
                conn.execute(
                    "UPDATE policy_questions SET status='已结束', feedback='已解决', "
                    "feedback_reason='', feedback_at=CURRENT_TIMESTAMP WHERE id=?",
                    (question_id,),
                )
                conn.commit()
            log_activity(actor, "反馈已解决", "policy_question", question_id, row["summary"],
                         module=MODULE, before_value="已回复", after_value="已结束")
            return True, "已结束", question_id
        reason = (reason or "").strip()
        if not reason:
            return False, "请填写未解决原因", question_id
        if row["loop_count"] >= MAX_LOOP:
            with get_db() as conn:
                conn.execute(
                    "UPDATE policy_questions SET status='需线下沟通', feedback='未解决', "
                    "feedback_reason=?, feedback_at=CURRENT_TIMESTAMP WHERE id=?",
                    (reason, question_id),
                )
                conn.commit()
            log_activity(actor, "超过3次循环转线下沟通", "policy_question", question_id,
                         row["summary"], module=MODULE, before_value="已回复",
                         after_value="需线下沟通", detail=reason)
            return True, "offline", question_id
        new_loop = row["loop_count"] + 1
        with get_db() as conn:
            conn.execute(
                "UPDATE policy_questions SET status='已转人工', loop_count=?, feedback='未解决', "
                "feedback_reason=?, feedback_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_loop, reason, question_id),
            )
            conn.commit()
        log_activity(actor, "反馈未解决退回人工", "policy_question", question_id,
                     row["summary"], module=MODULE, before_value="已回复",
                     after_value="已转人工", detail=f"第{new_loop}次循环 · {reason}")
        return True, "loop", question_id

    return False, f"当前状态「{old}」不支持反馈", question_id


def delete_question(question_id: int, user_id: int,
                    actor: str | None = None) -> tuple[bool, str, int]:
    """居民删除自己的提问记录（仅「已结束」或「已自动回答且未转人工」；处理中拦截）。"""
    row = get_question(question_id)
    if not row:
        return False, "提问不存在", 0
    if row["user_id"] != user_id:
        return False, "只能删除自己的提问记录", 0
    if row["status"] not in ("已结束", "已自动回答"):
        return False, "该提问正在处理中，暂不能删除，可等待处理或联系负责人", question_id
    with get_db() as conn:
        conn.execute("DELETE FROM policy_questions WHERE id=?", (question_id,))
        conn.commit()
    log_activity(actor or masked_nickname(user_id), "删除提问记录", "policy_question",
                 question_id, row["summary"], module=MODULE,
                 detail=f"原状态：{row['status']}")
    return True, "已删除", question_id


# ---------------------------------------------------------------- 查询

def get_my_questions(user_id: int, limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM policy_questions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_questions(status: str | None = None, user_id: int | None = None,
                  limit: int = 200) -> list[dict]:
    q = "SELECT * FROM policy_questions WHERE 1=1"
    args: list = []
    if status:
        q += " AND status=?"
        args.append(status)
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_pending_reply_questions(limit: int = 100) -> list[dict]:
    """人工待回复列表（最早提问的排前面，最紧急）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM policy_questions WHERE status='已转人工' "
            "ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_question_deadline_info(question: dict) -> dict:
    """24 小时时限：初始转人工从 created_at 起算，循环后从 feedback_at（未解决反馈）起算。"""
    start = None
    if (question.get("loop_count") or 0) > 0 and question.get("feedback_at"):
        start = question.get("feedback_at")
    elif question.get("created_at"):
        start = question.get("created_at")
    if not start:
        return {"deadline": "", "remaining_hours": None, "overdue": False}
    try:
        start_dt = datetime.fromisoformat(str(start).replace("Z", ""))
        deadline = start_dt + timedelta(hours=REPLY_HOURS)
        remaining = (deadline - datetime.now()).total_seconds() / 3600.0
        return {
            "deadline": deadline.strftime("%m-%d %H:%M"),
            "remaining_hours": round(remaining, 1),
            "overdue": remaining < 0,
        }
    except Exception:
        return {"deadline": "", "remaining_hours": None, "overdue": False}


def mark_overdue_questions(actor: str = "系统") -> list[dict]:
    """扫描已转人工且超过 24 小时未回复的提问，标记「超时未回复」并留痕（幂等）。"""
    marked: list[dict] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM policy_questions WHERE status='已转人工'"
        ).fetchall()
        for r in rows:
            q = dict(r)
            info = get_question_deadline_info(q)
            if not info["overdue"]:
                continue
            exists = conn.execute(
                "SELECT COUNT(*) c FROM activity_log WHERE module=? AND target_type='policy_question' "
                "AND target_id=? AND action='超时未回复'",
                (MODULE, q["id"]),
            ).fetchone()["c"]
            if exists:
                continue
            marked.append(q)
        conn.commit()
    for q in marked:
        info = get_question_deadline_info(q)
        with get_db() as conn:
            conn.execute("UPDATE policy_questions SET status='超时未回复' WHERE id=?", (q["id"],))
            conn.commit()
        log_activity(actor, "超时未回复", "policy_question", q["id"], q["summary"],
                     module=MODULE, before_value="已转人工", after_value="超时未回复",
                     detail=f"超时 {info['remaining_hours']:.1f} 小时")
    return marked


def auto_close_stale_questions(actor: str = "系统") -> list[dict]:
    """人工回复后 7 天未反馈自动「已结束」（幂等留痕）。"""
    closed: list[dict] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM policy_questions WHERE status='已回复' AND feedback='' "
            "AND answered_at IS NOT NULL "
            "AND julianday('now','localtime') - julianday(answered_at) > ?",
            (AUTO_CLOSE_DAYS,),
        ).fetchall()
        for r in rows:
            q = dict(r)
            exists = conn.execute(
                "SELECT COUNT(*) c FROM activity_log WHERE module=? AND target_type='policy_question' "
                "AND target_id=? AND action='自动结束（7天未反馈）'",
                (MODULE, q["id"]),
            ).fetchone()["c"]
            if exists:
                continue
            conn.execute("UPDATE policy_questions SET status='已结束' WHERE id=?", (q["id"],))
            closed.append(q)
        conn.commit()
    for q in closed:
        log_activity(actor, "自动结束（7天未反馈）", "policy_question", q["id"], q["summary"],
                     module=MODULE, before_value="已回复", after_value="已结束")
    return closed


def get_question_timeline(question_id: int, limit: int = 20) -> list[dict]:
    """提问留痕时间线（最近在前）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE module=? AND target_type='policy_question' "
            "AND target_id=? ORDER BY created_at DESC LIMIT ?",
            (MODULE, question_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------- 高频统计

def get_frequency_stats(days: int | None = None) -> dict:
    """高频统计。days=None 全部，7 近7天，30 近30天。

    自动回答失败分「匹配失败」（activity_log）和「居民点无帮助」（activity_log）两类，
    均以留痕统计，不受提问记录删除影响。
    """
    dsql = ""
    dargs: list = []
    if days:
        dsql = " AND created_at >= datetime('now', ? || ' days', 'localtime')"
        dargs = [f"-{days}"]
    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) c FROM policy_questions WHERE 1=1{dsql}", dargs
        ).fetchone()["c"]
        auto = conn.execute(
            f"SELECT COUNT(*) c FROM policy_questions WHERE auto_answer != ''{dsql}", dargs
        ).fetchone()["c"]
        trans = conn.execute(
            f"SELECT COUNT(*) c FROM policy_questions "
            f"WHERE status IN ('已转人工','已回复','已结束','需线下沟通'){dsql}", dargs
        ).fetchone()["c"]
        unhelp = conn.execute(
            f"SELECT COUNT(*) c FROM policy_questions WHERE feedback='无帮助'{dsql}", dargs
        ).fetchone()["c"]
        avg_row = conn.execute(
            f"SELECT ROUND(AVG((julianday(answered_at) - julianday(created_at)) * 24), 1) a "
            f"FROM policy_questions WHERE answered_at IS NOT NULL AND status='已回复'{dsql}", dargs
        ).fetchone()
        avg_reply_hours = avg_row["a"] if avg_row and avg_row["a"] is not None else None

        # 匹配失败（activity_log）
        fsql = ""
        fargs: list = [MODULE]
        if days:
            fsql = " AND created_at >= datetime('now', ? || ' days', 'localtime')"
            fargs.append(f"-{days}")
        fails = conn.execute(
            "SELECT actor, detail, created_at FROM activity_log "
            "WHERE module=? AND action='自动回答失败'" + fsql +
            " ORDER BY created_at DESC LIMIT 50", fargs
        ).fetchall()

        # 居民点无帮助（activity_log 留痕统计，后续反馈覆盖 feedback 字段也不丢次数）
        ufsql = ""
        ufargs: list = [MODULE]
        if days:
            ufsql = " AND created_at >= datetime('now', ? || ' days', 'localtime')"
            ufargs.append(f"-{days}")
        unhelp_rows = conn.execute(
            "SELECT actor, target_title, detail, created_at FROM activity_log "
            "WHERE module=? AND action='无帮助'" + ufsql +
            " ORDER BY created_at DESC LIMIT 50", ufargs
        ).fetchall()
        unhelp = len(unhelp_rows)

        # 近 7 天提问量趋势（0 填充）
        trend_rows = conn.execute(
            "SELECT DATE(created_at, 'localtime') d, COUNT(*) c FROM policy_questions "
            "WHERE created_at >= datetime('now','-7 days','localtime') GROUP BY d"
        ).fetchall()
        by_day = {r["d"]: r["c"] for r in trend_rows}
        trend = []
        for i in range(7, -1, -1):
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            trend.append({"day": day, "count": by_day.get(day, 0)})

        top = conn.execute(
            "SELECT summary, COUNT(*) c FROM policy_questions GROUP BY summary "
            "ORDER BY c DESC LIMIT 10"
        ).fetchall()

        expiring = conn.execute(
            "SELECT id, title, expire_date FROM knowledge_base WHERE audit_status='已发布' "
            "AND expire_date != '' AND date(expire_date) >= date('now','localtime') "
            "AND date(expire_date) <= date('now','localtime','+7 days') ORDER BY expire_date"
        ).fetchall()

    return {
        "total_questions": total,
        "auto_success": auto,
        "transferred": trans,
        "unhelpful": unhelp,
        "match_failed": len(fails),
        "avg_reply_hours": avg_reply_hours,
        "trend": trend,
        "top_questions": [dict(r) for r in top],
        "match_failed_list": [dict(r) for r in fails],
        "unhelpful_list": [dict(r) for r in unhelp_rows],
        "expiring": [dict(r) for r in expiring],
    }


def get_common_questions(limit: int = 10) -> list[dict]:
    """常见问题（按提问次数倒序），居民端/负责人端展示。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT summary, COUNT(*) c FROM policy_questions GROUP BY summary "
            "ORDER BY c DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------- 匹配阈值

def get_match_threshold() -> float:
    """自动回答匹配阈值（存 settings 表持久化，重启不丢）。"""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='match_threshold'"
            ).fetchone()
            if row and row["value"]:
                return float(row["value"])
    except Exception:
        pass
    return _match_threshold


def set_match_threshold(value: float, actor: str = "负责人") -> tuple[bool, str]:
    """负责人调整自动回答匹配阈值（立即生效，留痕；持久化到 settings）。"""
    global _match_threshold
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, "阈值必须是数字"
    if not (0.1 <= v <= 10):
        return False, "阈值范围 0.1 ~ 10"
    old = _match_threshold
    _match_threshold = v
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('match_threshold', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(v),),
            )
            conn.commit()
    except Exception:
        pass  # 持久化失败不影响进程内生效
    log_activity(actor, "调整自动回答阈值", "knowledge", None, "",
                 module=MODULE, before_value=str(old), after_value=str(v))
    return True, ""


# ---------------------------------------------------------------- 视图

def _knowledge_view(e: dict) -> dict:
    return {
        "id": e["id"], "title": e.get("title", ""), "category": e.get("category", ""),
        "version": e.get("version") or 1, "source": e.get("source") or "",
        "effective_date": e.get("effective_date") or "", "expire_date": e.get("expire_date") or "",
        "content": e.get("content") or "", "plain_interpretation": e.get("plain_interpretation") or "",
        "summary": e.get("summary") or "", "policy_number": e.get("policy_number") or "",
        "applicable_area": e.get("applicable_area") or "", "attachment": e.get("attachment") or "",
        "publisher": e.get("publisher") or "", "auditor": e.get("auditor") or "",
        "audit_status": e.get("audit_status") or "", "audit_opinion": e.get("audit_opinion") or "",
        "keywords": e.get("keywords") or "", "cite_count": e.get("cite_count") or 0,
        "is_community": (e.get("source") or "").strip() == SELF_MADE_SOURCE,
    }
