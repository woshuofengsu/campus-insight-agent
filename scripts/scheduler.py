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
        cutoff = (_dt.now() + _td(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
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
            out.append(db_health.trigger_weather_linkage(ev, actor="系统"))
    except Exception as e:  # noqa: BLE001
        _log.warning("健康天气联动任务失败: %s", e)
        try:
            from data.db_notifications import log_exception
            log_exception("疾病预防", f"健康天气联动自动触发失败: {e}")
        except Exception:
            pass
    return out


def run_all() -> dict:
    """跑一遍全部自动任务，返回每类结果摘要。任务本身幂等，失败记录到异常日志。"""
    from data import db_notice, db_proposal, db_health_content, db_weather
    from data import db_policy as _pol, db_elderly_care as _ec, db_repair as _rep
    from data import db_dispatch as _dispatch

    results: dict = {}
    results["notice"] = _safe("通知", db_notice.run_auto_tasks)
    results["auto_dispatch"] = _safe("自动分派", lambda: len(_dispatch.discover_and_dispatch(limit=20)))
    results["weather"] = _safe("天气自动任务", lambda: _weather_tasks(db_weather))
    results["weather_overdue"] = _safe("天气超时", db_weather.mark_overdue_tasks)
    # 天气升级：传入可配置的「更高级负责人」名单（settings senior_manager_ids，未配置则走无法升级分支）
    _safe("天气升级", lambda: db_weather.escalate_overdue_tasks(
        senior_user_ids=db_weather.get_senior_manager_ids()))
    _safe("天气预警解除", db_weather.expire_alerts)
    results["proposal_confirm"] = _safe("提案确认", db_proposal.auto_confirm_overdue)
    results["proposal_end"] = _safe("提案反馈", db_proposal.auto_end_unfeedback)
    results["consult_overdue"] = _safe("咨询超时", db_health_content.mark_overdue_consults)
    results["consult_close"] = _safe("咨询关闭", db_health_content.auto_close_stale_consults)
    results["content_expire"] = _safe("内容到期", db_health_content.expire_contents)
    results["unpin"] = _safe("置顶取消", db_health_content.auto_unpin_expired)
    results["monthly"] = _safe("月度提醒", db_health_content.monthly_update_reminder)
    results["resubmit_remind"] = _safe("退回修改提醒", db_health_content.resubmit_reminder)
    results["health_linkage"] = _safe("健康天气联动", lambda: _health_linkage_tasks(db_weather, db_health_content))
    results["policy_expire"] = _safe("政策到期", _pol.auto_expire_knowledge)
    results["policy_remind"] = _safe("政策更新提醒", lambda: len(_pol.remind_knowledge_updates()))
    results["policy_overdue"] = _safe("政策超时", _pol.mark_overdue_questions)
    results["policy_close"] = _safe("政策关闭", _pol.auto_close_stale_questions)
    results["sos_escalated"] = _safe("SOS升级", lambda: sum(
        1 for s in _ec.get_sos_calls(status="求助中", limit=50)
        if _ec.escalate_sos(s["id"], actor="系统")[0]))
    results["med_remind"] = _safe("用药审核提醒", lambda: len(_ec.remind_unreviewed_medications()))
    results["issue_overdue"] = _safe("报修超时", lambda: len(_rep.mark_issue_overdue_notice()))
    results["draft_cleaned"] = _safe("草稿清理", lambda: _rep.clean_issue_drafts(days=7))
    results["exception_cleaned"] = _safe("异常清理", _clean_exceptions)
    return results


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


def ensure_scheduler_started(interval: int = 60) -> Scheduler:
    """确保调度器已启动（进程内只启动一次）。"""
    global _started
    if _started:
        return _scheduler
    _scheduler = Scheduler(interval=interval)
    _scheduler.start()
    _started = True
    return _scheduler


_scheduler: Scheduler | None = None


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
