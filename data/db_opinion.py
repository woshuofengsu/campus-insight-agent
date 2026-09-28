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


def convert_to_issue(opinion_id: int, actor: str = "负责人",
                     tenant: str = "") -> tuple[bool, str, int | None]:
    """舆情一键转工单（自动填充描述+来源）。

    `tenant`：**转单操作人所在社区**（卡7 扫描时发现的漏洞修复）。
    为什么必须传：舆情源是全局采集的，而这个函数建的是 `community_issues`（**租户表**）。
    原来 `reporter_id=0` → `stamp_tenant` 拿到空租户 → 工单**租户为空**：
    网格端所有按社区过滤的列表都看不到它（B6 那个"自己人也看不见"的老毛病又出现了）。
    现在由调用方把操作人的社区传进来并按值盖章。
    """
    from data.db_repair import submit_issue
    row = None
    with get_db() as conn:
        r = conn.execute("SELECT * FROM public_opinion WHERE id=?", (opinion_id,)).fetchone()
        row = dict(r) if r else None
    if not row:
        return False, "舆情不存在", None
    iid, _ = submit_issue(
        title=(row["content"] or "")[:40], category="其他", issue_type="室外",
        # ⚠️ 原来写 location="社区"、reporter_phone="13900000000"：
        #    · "社区"不是可派单位置（网格员不知道去哪）→ 改成显式"待核实"标记；
        #    · 舆情来源本来就没有报修人电话 → 传空 + allow_missing_phone=True，
        #      **绝不编一个号码**（那会让工单看起来有人可联系，实际打不通）。
        location="（位置待核实·舆情来源）",
        description=f"[舆情·{row['source']}] {row['content']}",
        urgency="紧急" if row["level"] in ("红色", "橙色") else "一般",
        reporter_name="舆情系统（无联系电话）", reporter_phone="", reporter_id=0,
        allow_missing_phone=True,
    )
    if iid <= 0:
        return False, "转工单失败", None
    # 租户盖章：按**操作人所在社区**（无归属人的行用 stamp_tenant_value）
    from utils.tenant import normalize_tenant, stamp_tenant_value
    t = normalize_tenant(tenant)
    if t:
        with get_db() as conn:
            stamp_tenant_value(conn, "community_issues", iid, t)
            conn.commit()
    else:
        _log.warning("舆情转工单 #%s 未拿到操作人社区 → 工单租户为空（网格端按社区过滤时看不到）", iid)
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
