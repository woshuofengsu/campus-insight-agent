# scripts/scheduler.py
"""后台调度器 — 让 spec 要求的「系统自动触发」（A 类停机点）真正自动执行。

不依赖有人打开页面。用法：
  python scripts/scheduler.py      # 独立运行（本地 / Docker）
或由 app.py 启动后台守护线程。

所有任务都是幂等的（同日/同事件去重），重复执行安全。
"""
import logging
import threading
import time

_log = logging.getLogger(__name__)


def _safe(name: str, fn) -> object:
    """执行任务并记录失败到异常日志（不拖累其他任务）。"""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        _log.warning("%s 自动任务失败: %s", name, e)
        try:
            from data.db_notifications import log_exception
            log_exception(name, f"自动任务失败: {e}")
        except Exception:  # noqa: BLE001
            pass
        return None


def _clean_exceptions():
    from data.db_notifications import clean_exception_log
    return clean_exception_log(days=7)


# 天气定时刷新节流（实时每 10 分钟刷新一次，预报每天早 8 点/晚 8 点重取）
_last_weather_refresh = 0.0
_WEATHER_REFRESH_INTERVAL = 600  # 10 分钟


def _weather_tasks(db_weather) -> dict:
    """天气自动任务：定时刷新（节流）+ 新鲜度监测 + 降级时暂停新预警触发。"""
    global _last_weather_refresh
    out: dict = {}
    now = time.time()
    if now - _last_weather_refresh >= _WEATHER_REFRESH_INTERVAL:
        _last_weather_refresh = now
        try:
            r = db_weather.refresh_weather()
            out["refresh"] = ("real" if r.get("is_real") else
                              "degraded" if r.get("is_degraded") else "mock")
        except Exception as e:  # noqa: BLE001
            out["refresh"] = f"error:{e}"
    # 新鲜度监测：>15 分钟提示延迟，>30 分钟进入降级（状态变化才留痕，不会刷屏）
    try:
        fresh = db_weather.check_cache_freshness()
        out["freshness"] = fresh.get("state")
    except Exception as e:  # noqa: BLE001
        out["freshness"] = f"error:{e}"
    # 预警检测：降级时暂停新预警触发（spec：API 故障时暂停新预警）
    degraded = out.get("freshness") == "degraded"
    out["detect"] = db_weather.run_alert_detection(degraded=degraded)
    return out


def _health_linkage_tasks(db_weather, db_health) -> list[dict]:
    """健康天气联动自动触发：对生效窗口内（≤12h）的 active 预警逐条联动（每日去重）。

    天气数据降级（>30 分钟未更新）时暂停新联动触发（spec #39：API 异常暂停新联动）。

    **多租户（B7）**：联动阈值可以按社区分别配置，所以这里必须**按社区逐个判定**——
    只调一次（不带社区）会让"按社区配阈值"永远不生效，属本项目最忌讳的"做了但不生效"。
    预警源（`weather_alerts`）本身没有社区维度（是全国/城市级），因此同一预警对
    每个社区各判一次：阈值不同 → 触发结果天然不同（朝阳把高温阈值调到 30℃ 时，
    32℃ 的天气只触发朝阳的联动）。`all_tenants()` 为空（例如库里还没用户）时，
    保留一次不带社区（全局口径）的调用作为兜底，避免演示环境静默什么都不做。
    """
    out: list[dict] = []
    try:
        # 降级检查：缓存数据超过 30 分钟 → 暂停新联动（已触发保留）
        try:
            _fresh = db_weather.check_cache_freshness()
            if _fresh.get("state") == "degraded":
                db_health._log_once("联动暂停", "天气数据缓存降级，暂停新的健康天气联动触发",
                                    "weather_linkage", "系统")
                return out
        except Exception:
            pass
        from datetime import datetime as _dt, timedelta as _td
        from utils.tenant import all_tenants
        cutoff = (_dt.now() + _td(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        tenants: list[str | None] = list(all_tenants()) or [None]
        for a in db_weather.get_active_alerts():
            eff = (a.get("effective_time") or "")
            if eff and eff > cutoff:
                continue  # 生效时间 >12h 不触发（与预警触发规则一致）
            ev = {
                "alert_type": a.get("alert_type", ""),
                "level": a.get("level", ""),
                "effective_time": eff,
                "expire_time": a.get("expire_time", ""),
            }
            for tenant in tenants:
                out.append(db_health.trigger_weather_linkage(ev, actor="系统", tenant=tenant))
    except Exception as e:  # noqa: BLE001
        _log.warning("健康天气联动任务失败: %s", e)
        try:
            from data.db_notifications import log_exception
            log_exception("疾病预防", f"健康天气联动自动触发失败: {e}")
        except Exception:
            pass
    return out


def _sos_escalations() -> int:
    """SOS 未响应升级：**按社区逐个跑**（安全链路上的一环，不能静默失效）。

    ⚠️ 2026-09-29 修（外部评审第十一轮提示 + 本机在库副本上逐个任务探测确认）：
    原来直接 `get_sos_calls(status="求助中")` **不传社区** → 撞上多租户 fail-closed
    （`ValueError: 跨用户列表/聚合查询必须显式提供 tenant=`）→ `_safe` 只记一条 warning，
    于是**这个任务从来没跑成过**，而界面上完全看不出来（老人 SOS 无人响应升级 = 静默丢失）。

    做法照 B7（天气联动）的规矩：用 `utils.tenant.all_tenants()` 枚举社区逐个判定；
    另外单独数一遍"没有租户归属"的历史行并**明确告警**——宁可日志里吵，也不能把人漏掉。
    """
    from data import db_elderly_care as _ec
    from utils.tenant import all_tenants
    total = 0
    tenants = all_tenants()
    for t in tenants:
        for s in _ec.get_sos_calls(status="求助中", limit=50, tenant=t):
            if _ec.escalate_sos(s["id"], actor="系统")[0]:
                total += 1
    # 无归属的历史行：说明清楚（当前演示库为 0 条；一旦出现就要有人处理，而不是静默跳过）
    try:
        from data.db_core import get_db
        with get_db() as conn:
            orphan = conn.execute(
                "SELECT COUNT(*) c FROM emergency_calls "
                "WHERE call_type='sos' AND status='求助中' AND COALESCE(tenant_id,'')=''"
            ).fetchone()["c"]
        if orphan:
            _log.warning("SOS升级：有 %s 条求助记录没有社区归属（历史数据），按社区跑不到它们，"
                         "需要补盖租户章：utils.tenant.stamp_tenant(...)", orphan)
    except Exception as e:  # noqa: BLE001 — 统计失败不影响已经做完的升级，但必须留痕
        _log.warning("SOS升级：无归属行统计失败：%s", e)
    return total


def scheduled_tasks() -> dict:
    """**任务清单的唯一来源**：`{结果键: (中文名, 无参可调用)}`。

    `run_all()` 按它执行；`tests/test_scheduler_health.py` 也按它逐个跑一遍——
    任务清单只留一份，就不会出现"测试里抄的那份先过期"（这正是本轮要防的那类问题）。
    """
    from data import db_notice, db_proposal, db_health_content, db_weather
    from data import db_policy as _pol, db_elderly_care as _ec, db_repair as _rep
    from data import db_dispatch as _dispatch
    return {
        "notice": ("通知", db_notice.run_auto_tasks),
        "auto_dispatch": ("自动分派", lambda: len(_dispatch.discover_and_dispatch(limit=20))),
        "weather": ("天气自动任务", lambda: _weather_tasks(db_weather)),
        "weather_overdue": ("天气超时", db_weather.mark_overdue_tasks),
        # 天气升级：**不传**名单 → 由 escalate_overdue_tasks 按每个任务所属社区取
        # （settings `senior_manager_ids@社区`，未配置则走"无法升级"分支）。
        # 传一个全局名单会让"社区级配置"永远不生效——B7 的教训。
        "weather_escalated": ("天气升级", db_weather.escalate_overdue_tasks),
        "weather_expired": ("天气预警解除", db_weather.expire_alerts),
        "proposal_confirm": ("提案确认", db_proposal.auto_confirm_overdue),
        "proposal_end": ("提案反馈", db_proposal.auto_end_unfeedback),
        "consult_overdue": ("咨询超时", db_health_content.mark_overdue_consults),
        "consult_close": ("咨询关闭", db_health_content.auto_close_stale_consults),
        "content_expire": ("内容到期", db_health_content.expire_contents),
        "unpin": ("置顶取消", db_health_content.auto_unpin_expired),
        "monthly": ("月度提醒", db_health_content.monthly_update_reminder),
        "resubmit_remind": ("退回修改提醒", db_health_content.resubmit_reminder),
        "health_linkage": ("健康天气联动",
                           lambda: _health_linkage_tasks(db_weather, db_health_content)),
        "policy_expire": ("政策到期", _pol.auto_expire_knowledge),
        "policy_remind": ("政策更新提醒", lambda: len(_pol.remind_knowledge_updates())),
        "policy_overdue": ("政策超时", _pol.mark_overdue_questions),
        "policy_close": ("政策关闭", _pol.auto_close_stale_questions),
        "sos_escalated": ("SOS升级", _sos_escalations),
        "med_remind": ("用药审核提醒", lambda: len(_ec.remind_unreviewed_medications())),
        "issue_overdue": ("报修超时", lambda: len(_rep.mark_issue_overdue_notice())),
        "draft_cleaned": ("草稿清理", lambda: _rep.clean_issue_drafts(days=7)),
        "agent_draft_cleaned": ("Agent草稿清理", lambda: _draft_clean()),
        "kb_query_cleaned": ("知识库查询日志清理", lambda: _kb_query_clean()),
        "care_event_cleaned": ("关怀事件日志清理", lambda: _care_event_clean()),
        "exception_cleaned": ("异常清理", _clean_exceptions),
        "proactive_followup": ("主动关怀-办结回访", lambda: _proactive_care()),
        "elderly_safety": ("老人安全巡检", lambda: _elderly_safety()),
        # 诚实呼叫（§6-B2）：没回填结果的拨打记录 → 如实标「结果未知」，不让它悬成"待确认"
        "contact_call_resolved": ("联系拨打结果未知标注",
                                  lambda: _ec.resolve_stale_contact_calls(minutes=5)),
        # 卡9：补发"当时没发出去"的通知（业务事实早已提交，这里只负责把该收的人补齐）
        "outbox_sent": ("通知补发", _flush_outbox),
        "outbox_cleaned": ("通知队列清理", _clean_outbox),
    }


def run_all() -> dict:
    """跑一遍全部自动任务，返回每类结果摘要。任务本身幂等，失败记录到异常日志。"""
    results: dict = {}
    for key, (label, fn) in scheduled_tasks().items():
        results[key] = _safe(label, fn)
    return results



def _flush_outbox() -> int:
    """补发待重试通知，返回成功条数。"""
    try:
        from data.db_outbox import flush
        return flush(limit=100).get("sent", 0)
    except Exception:
        _log.warning("通知补发失败", exc_info=True)
        return 0


def _clean_outbox() -> int:
    """清理已完成的队列行（30 天）。"""
    try:
        from data.db_outbox import clean_finished
        return clean_finished(days=30)
    except Exception:
        _log.warning("通知队列清理失败", exc_info=True)
        return 0


def _draft_clean() -> int:
    """清理 Agent 草稿/会话（7/30 天）。"""
    try:
        from data.db_draft import clean_drafts
        from data.db_agent import clean_sessions
        n = clean_drafts(days=7)
        clean_sessions(days=30)
        return n
    except Exception:
        return 0


def _kb_query_clean() -> int:
    """清理知识库查询日志（U3：保留 90 天，供命中率/零命中趋势统计）。"""
    try:
        from data.db_kb_metrics import clean_kb_query_log
        return clean_kb_query_log(days=90)
    except Exception:
        return 0


def _care_event_clean() -> int:
    """清理关怀事件日志（U4：保留 180 天，供关怀量化趋势）。"""
    try:
        from data.db_care_metrics import clean_care_event_log
        return clean_care_event_log(days=180)
    except Exception:
        return 0


def _proactive_care() -> int:
    """M4：主动关怀——办结回访（含静默时段仅生成待办不打扰）。"""
    try:
        from data.db_care_proactive import run_proactive_care
        return run_proactive_care().get("followup", 0)
    except Exception:
        return 0


def _elderly_safety() -> int:
    """P3 安全闭环：老人安全巡检——超过阈值未互动 → 通知网格员（24h 去重）。

    ⚠️ 2026-09-24 修：`data/db_elderly.notify_inactive_elders()` 早就写好了，但**没人按计划调它**，
    过去只在 Agent 聊天观察阶段顺带跑（`agent/engine.py`）→ "无人应答检测"实际是文案 + 偶发。
    现在按调度跑（默认 60 秒一轮；函数自带 24h 去重，重复跑不会重复打扰）。
    """
    try:
        from data.db_elderly import notify_inactive_elders
        return notify_inactive_elders()
    except Exception:
        _log.warning("老人安全巡检失败", exc_info=True)
        return 0


class Scheduler:
    """后台调度器守护线程。"""

    def __init__(self, interval: int = 60):
        self.interval = max(10, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动调度线程（幂等：已运行则跳过）。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()
        _log.info("调度器已启动，每 %ds 轮询一次", self.interval)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        run_all()  # 启动先跑一遍
        while not self._stop.wait(self.interval):
            run_all()


# 进程级单例标记（Streamlit 多 session 共享全局，防止重复启动线程）
_started = False
_scheduler: Scheduler | None = None


def ensure_scheduler_started(interval: int = 60) -> Scheduler:
    """确保调度器已启动（进程内只启动一次）。"""
    global _started, _scheduler
    if _started:
        return _scheduler
    _scheduler = Scheduler(interval=interval)
    _scheduler.start()
    _started = True
    return _scheduler


def main() -> None:
    import config
    from data import db_core

    db_core.init_db(config.DB_PATH)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [scheduler] %(message)s",
    )
    _log.info("调度器独立运行模式，数据库：%s", config.DB_PATH)
    scheduler = Scheduler(interval=60)
    scheduler.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        scheduler.stop()
        _log.info("调度器已停止")


if __name__ == "__main__":
    main()
