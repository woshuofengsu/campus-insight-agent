# data/db_opinion.py
"""舆情监测数据层（P3-01）：录入/分级/转工单/简报。

外部源（12345 API/媒体抓取）需申请接口权限——适配说明：本实现支持手动录入 + 关键词分级 +
一键转工单 + 简报，外部 API 接入点留 `auto_ingest` 占位。
"""
import logging

from data.database import get_db

_log = logging.getLogger(__name__)

# 关键词分级规则（内容命中即升级级别）
_RULES = [
    ("红色", ("火灾", "爆炸", "群体", "事故", "伤亡", "维权聚集", "停水停电")),
    ("橙色", ("投诉", "纠纷", "物业", "垃圾", "噪音", "扰民", "漏水")),
    ("黄色", ("关注", "反映", "咨询", "建议")),
    ("蓝色", ("表扬", "感谢", "优秀", "点赞")),
]


def _classify(content: str) -> str:
    """关键词分级：红色 > 橙色 > 黄色 > 蓝色。"""
    for level, kws in _RULES:
        if any(k in (content or "") for k in kws):
            return level
    return "黄色"


def add_opinion(content: str, source: str = "手动录入", created_by: str = "负责人",
                level: str = "") -> int:
    """录入一条舆情（自动分级：level 空则按关键词）。"""
    level = level or _classify(content)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO public_opinion (source, content, keywords, level, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, (content or "")[:500], "、".join(k for _, ks in _RULES for k in ks if k in content),
             level, created_by),
        )
        conn.commit()
        return cur.lastrowid


def list_opinions(level: str = "", status: str = "", limit: int = 100) -> list[dict]:
    with get_db() as conn:
        q = "SELECT * FROM public_opinion WHERE 1=1"
        args: list = []
        if level:
            q += " AND level=?"
            args.append(level)
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def convert_to_issue(opinion_id: int, actor: str = "负责人") -> tuple[bool, str, int | None]:
    """舆情一键转工单（自动填充描述+来源）。"""
    from data.db_repair import submit_issue
    row = None
    with get_db() as conn:
        r = conn.execute("SELECT * FROM public_opinion WHERE id=?", (opinion_id,)).fetchone()
        row = dict(r) if r else None
    if not row:
        return False, "舆情不存在", None
    iid, _ = submit_issue(
        title=(row["content"] or "")[:40], category="其他", issue_type="室外",
        location="社区", description=f"[舆情·{row['source']}] {row['content']}",
        urgency="紧急" if row["level"] in ("红色", "橙色") else "一般",
        reporter_name="舆情系统", reporter_phone="13900000000", reporter_id=0,
    )
    if iid <= 0:
        return False, "转工单失败", None
    with get_db() as conn:
        conn.execute("UPDATE public_opinion SET status='已转工单', related_issue_id=? WHERE id=?",
                     (iid, opinion_id))
        conn.commit()
    return True, f"已转工单 #{iid}", iid


def build_brief(days: int = 7) -> dict:
    """舆情简报：分级统计 + 高优先级列表。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT level, COUNT(*) c FROM public_opinion "
            "WHERE created_at >= datetime('now', ? || ' days') GROUP BY level",
            (f"-{days}",),
        ).fetchall()
        counts = {r["level"]: r["c"] for r in rows}
        hot = conn.execute(
            "SELECT * FROM public_opinion WHERE level IN ('红色', '橙色') AND status='待关注' "
            "ORDER BY id DESC LIMIT 5").fetchall()
    return {"days": days, "counts": counts,
            "urgent": [dict(r) for r in hot],
            "total": sum(counts.values())}
