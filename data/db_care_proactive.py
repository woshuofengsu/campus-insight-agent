# data/db_care_proactive.py
"""主动关怀（M4）：办结 24h 回访 + 久未活跃老人提醒。

纯查询 + 写通知，不新建表、不喧宾夺主；办结回访用 activity_log 去重（跨 tick 幂等）。

时间口径：**库内时间列一律 UTC**；`now` 形参与静默时段判断用**本地时间**，
两者之间用 `utils.timeutil.local_to_utc_naive` 显式换算（2026-09-24 修的时区去重 bug）。
"""
import logging
from datetime import date, datetime, timedelta

from data.database import get_db
from utils.timeutil import local_to_utc_naive, utcnow

_log = logging.getLogger(__name__)

# 办结回访：锁定"昨日办结"的工单
DONE_STATUSES = ("已完成", "已解决", "已办结")

# 主动关怀静默时段（本地时间）：21:00–次日8:00 只生成待办，不额外打扰
QUIET_START_HOUR = 21
QUIET_END_HOUR = 8


def _is_quiet_hour(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    h = now.hour
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def run_followup(now: datetime | None = None) -> int:
    """昨日办结且未回访 → 给居民发一条回访通知。返回新增回访数。

    静默时段（21:00–8:00，**本地时间**）不生成回访（7:00 前跑，等 8 点后 scheduler 下一分钟自然补发，不会漏）。

    ⚠️ 时间口径（2026-09-24 修）：`now` 是**本地时间**（与 `_is_quiet_hour` 一致），
    而库里的时间列统一是 **UTC**。所以：
    ① 去重日期与「昨日」都必须换算成 UTC 再比；
    ② 插入 activity_log 时**显式写入 UTC 时间戳**，不再依赖 `CURRENT_TIMESTAMP`
    （否则测试传入的 `now` 与库里的真实时间对不上，去重永远失败）。
    修前实测：本地 0:00–8:00 期间 UTC 还在前一天，去重失效 → 重复给居民发回访。
    """
    now = now or datetime.now()
    if _is_quiet_hour(now):  # M4：夜间静默，只生成待办不打扰；次日自动补发
        return 0
    now_utc = local_to_utc_naive(now)
    yesterday = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")
    today_utc = now_utc.strftime("%Y-%m-%d")
    stamp = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    created = 0
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, reporter_id, title FROM community_issues "
                "WHERE status IN (?,?,?) AND "
                "(date(resolved_at)=? OR (resolved_at IS NULL AND date(reported_at)=?))",
                (*DONE_STATUSES, yesterday, yesterday)).fetchall()
            for r in rows:
                if not r["reporter_id"]:
                    continue
                # 回访对象须为真实用户（notifications.user_id 外键约束）
                u = conn.execute("SELECT 1 FROM user_profile WHERE id=?", (r["reporter_id"],)).fetchone()
                if not u:
                    continue
                # 去重：该工单今日已回访过则跳过（按 UTC 日期比，与库内口径一致）
                done = conn.execute(
                    "SELECT 1 FROM activity_log WHERE module='主动关怀' AND action='办结回访' "
                    "AND target_type='community_issue' AND target_id=? "
                    "AND substr(created_at,1,10)=? LIMIT 1",
                    (r["id"], today_utc)).fetchone()
                if done:
                    continue
                try:
                    from data.db_notifications import create_notification
                    create_notification(
                        r["reporter_id"], "followup",
                        f"昨天报的「{r['title'][:20]}」现在还好吗？",
                        "没好利索的话点这里，我再帮您跟进。", related_id=r["id"])
                    conn.execute(
                        "INSERT INTO activity_log (module, action, target_type, target_id, detail, created_at) "
                        "VALUES ('主动关怀','办结回访','community_issue',?,?,?)",
                        (r["id"], "昨日已办结工单回访（1 次）", stamp))
                    conn.commit()
                    created += 1
                except Exception as e:  # noqa: BLE001
                    _log.warning("办结回访失败 issue#%s: %s", r["id"], e)
    except Exception as e:  # noqa: BLE001
        _log.warning("run_followup 异常：%s", e)
    return created


def list_inactive_elderly(days: int = 5, limit: int = 20) -> list[dict]:
    """返回最近 days 天无活动的老年用户（供网格员端顶部"关怀提示"）。

    ⚠️ 截止时间用 **UTC**：被比较的 `agent_dialogs.created_at` / `community_issues.reported_at` /
    `medication_intake_log.taken_at` 都是库内 UTC 时间；之前这里用本地 `datetime.now()`，
    会带来 8 小时偏差（临界点上把"刚活跃过的老人"误判为久未活跃）。
    """
    cutoff = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    out = []
    try:
        with get_db() as conn:
            elders = conn.execute(
                "SELECT p.user_id, u.name FROM elderly_profile p "
                "LEFT JOIN user_profile u ON u.id = p.user_id WHERE u.name != ''").fetchall()
            for e in elders:
                uid = e["user_id"]
                last = conn.execute(
                    "SELECT MAX(t) m FROM ("
                    "SELECT MAX(created_at) t FROM agent_dialogs WHERE user_id=? "
                    "UNION ALL SELECT MAX(reported_at) t FROM community_issues WHERE reporter_id=? "
                    "UNION ALL SELECT MAX(taken_at) t FROM medication_intake_log WHERE user_id=?)",
                    (uid, uid, uid)).fetchone()["m"]
                if not last or str(last) < cutoff:
                    out.append({"user_id": uid, "name": e["name"], "days_inactive": days})
                if len(out) >= limit:
                    break
    except Exception as e:  # noqa: BLE001
        _log.warning("list_inactive_elderly 异常：%s", e)
    return out


def run_proactive_care() -> dict:
    """调度器入口：回访 + （久未活跃仅为查询展示，此处只触发回访）。"""
    return {"followup": run_followup()}
