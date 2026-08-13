# agent/workers.py
"""后台 Worker Agent 聚合 — 感知 / 派单 / 审计 协作。

主对话 Agent 可调起这些 worker 并引用其结论（战线二/三的延伸）。Worker 尽量走
规则（省 API 额度）：感知走 perception，派单走 db_dispatch，只有审计深度解读走 LLM。
"""
import logging

_log = logging.getLogger(__name__)


def run_observer() -> dict:
    """感知 Worker（Observer）：运行感知检查，返回告警列表。"""
    from perception.monitor import PerceptionMonitor
    monitor = PerceptionMonitor()
    alerts = monitor.run_all_checks()
    return {"alerts": alerts, "count": len(alerts)}


def run_dispatcher() -> list[dict]:
    """派单 Worker（Dispatcher）：主动扫描未派单工单并自动派单。"""
    from data.db_dispatch import discover_and_dispatch
    return discover_and_dispatch(limit=20)


def run_auditor() -> str:
    """审计 Worker（Auditor）：跨表治理健康审计。"""
    from agent.governance_audit import run_governance_audit
    return run_governance_audit()


def run_all_workers(trigger: str = "") -> dict:
    """Run the cooperative workers and return structured results.

    Auditor only runs when explicitly triggered (含「审计/治理体检」等词) to
    avoid unnecessary LLM cost on every turn.
    """
    result: dict = {}
    try:
        result["observer"] = run_observer()
    except Exception:
        _log.warning("observer worker failed", exc_info=True)
        result["observer"] = {"alerts": [], "count": 0}

    try:
        result["dispatcher"] = run_dispatcher()
    except Exception:
        _log.warning("dispatcher worker failed", exc_info=True)
        result["dispatcher"] = []

    if any(kw in trigger for kw in ("审计", "治理体检", "全面检查", "整体情况")):
        try:
            result["auditor"] = run_auditor()
        except Exception:
            _log.warning("auditor worker failed", exc_info=True)
            result["auditor"] = ""

    return result
