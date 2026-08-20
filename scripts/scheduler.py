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


def run_all() -> dict:
    """跑一遍全部自动任务，返回每类结果摘要。

    每个任务单独 try，一个失败不拖累其他。任务本身幂等。
    """
    from data import db_notice, db_proposal, db_health_content, db_weather

    results: dict = {}
    try:
        results["notice"] = db_notice.run_auto_tasks()  # 定时发布 / 到期取消置顶 / 紧急通知到期
    except Exception as e:  # noqa: BLE001
        _log.warning("通知自动任务失败: %s", e)
    try:
        results["weather_detect"] = db_weather.run_alert_detection()  # 极端天气预警检测
        results["weather_overdue"] = db_weather.mark_overdue_tasks()  # 检查任务超时标记
        db_weather.escalate_overdue_tasks()  # 超时升级（在线负责人未建模，默认全网格员）
    except Exception as e:  # noqa: BLE001
        _log.warning("天气自动任务失败: %s", e)
    try:
        results["proposal_confirm"] = db_proposal.auto_confirm_overdue()  # 逾期默认确认公开/私有
        results["proposal_end"] = db_proposal.auto_end_unfeedback()  # 逾期未反馈视为满意
    except Exception as e:  # noqa: BLE001
        _log.warning("提案自动任务失败: %s", e)
    try:
        results["consult_overdue"] = db_health_content.mark_overdue_consults()  # 咨询 24h 超时
        results["consult_close"] = db_health_content.auto_close_stale_consults()  # 咨询 7 天未反馈
        results["content_expire"] = db_health_content.expire_contents()  # 疫苗类到期下架
        results["unpin"] = db_health_content.auto_unpin_expired()  # 置顶超 7 天取消
        results["monthly"] = db_health_content.monthly_update_reminder()  # 月度更新提醒
    except Exception as e:  # noqa: BLE001
        _log.warning("疾病预防自动任务失败: %s", e)
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
