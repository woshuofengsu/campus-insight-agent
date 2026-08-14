# perception/monitor.py
"""Perception engine — governance-oriented environmental checks."""
from datetime import datetime
from data.database import get_issues
from utils.logger import get_logger

logger = get_logger(__name__)


class PerceptionMonitor:
    """Runs periodic governance checks and generates alert messages when anomalies are detected."""

    def __init__(self):
        self.alerts: list[dict] = []

    def run_all_checks(self):
        """Execute all perception checks in priority order. Returns list of alerts."""
        self.alerts = []

        self._check_weather()
        self._check_issue_hotspots()
        self._check_resolved_issues()
        self._check_health_risk()
        self._check_auto_dispatch()
        self._check_escalation()
        self._check_elderly_safety()
        self._check_demo_worker()

        if self.alerts:
            logger.info(f"Perception check: {len(self.alerts)} alert(s) generated")
        return self.alerts

    def _check_demo_worker(self):
        """演示闭环机器人：自动把新工单办结（处理中→已解决→通知居民）。"""
        try:
            from data.db_demo_worker import process_new_issues
            processed = process_new_issues(limit=1)
            if processed:
                logger.info(f"Demo worker resolved {processed} issue(s)")
        except Exception as e:
            logger.warning(f"Demo worker check failed: {e}")

    def _check_elderly_safety(self):
        """独居老人安全检测：超时未互动 → 通知网格员留意（24h 去重）。"""
        try:
            from data.db_elderly import notify_inactive_elders
            notified = notify_inactive_elders(24)
            if notified:
                logger.info(f"Elderly safety: {notified} inactive elder(s) notified")
        except Exception as e:
            logger.warning(f"Elderly safety check failed: {e}")

    def _check_escalation(self):
        """SLA 升级：将超时 2× 的工单标记为「已升级」并触发邮件通知（best-effort）。"""
        try:
            from data.db_sla import escalate_overdue_issues
            escalated = escalate_overdue_issues(limit=20)
            if escalated:
                summary = "、".join(f"#{e['id']}" for e in escalated[:3])
                logger.info(f"SLA escalation: {len(escalated)} issue(s) escalated ({summary})")
        except Exception as e:
            logger.warning(f"SLA escalation check failed: {e}")

    def _check_auto_dispatch(self):
        """战线二 — 主动派单：扫描未派单开放工单，按类别自动派给网格员。

        Best-effort: 无网格员或无未派单工单时静默跳过，不产生告警。
        """
        try:
            from data.db_dispatch import discover_and_dispatch
            dispatched = discover_and_dispatch(limit=20)
            if dispatched:
                summary = "、".join(
                    f"#{d['issue_id']}→{d['assignee']}" for d in dispatched[:3]
                )
                logger.info(f"Auto-dispatch: {len(dispatched)} issue(s) assigned ({summary})")
        except Exception as e:
            logger.warning(f"Auto-dispatch check failed: {e}")

    def _check_weather(self):
        """Check for severe weather that could affect community safety."""
        try:
            from tools.query_weather import get_today_weather
            days, _, _ = get_today_weather()
            if not days:
                return

            today = days[0]
            if today.get("rain_prob", 0) >= 60 or today.get("condition", "") in (
                "暴雨", "雷阵雨", "大雪", "沙尘暴",
            ):
                self.alerts.append({
                    "title": "恶劣天气预警",
                    "message": (
                        f"今天{today['condition']}，降水概率{int(today.get('rain_prob', 0))}%。"
                        f"气温{today['temp_low']}°C~{today['temp_high']}°C。"
                        f"注意出行安全，发现积水、树木倒伏等安全隐患请随时上报。"
                    ),
                    "emoji": "🌧️",
                })
        except Exception as e:
            logger.warning(f"Weather check failed: {e}")

    def _check_issue_hotspots(self):
        """Alert when a specific category has high volume of pending issues.

        When 5+ issues in a single category, also attempts to auto-create
        a discussion topic via _discover_hot_topic.
        """
        try:
            issues = get_issues(limit=100)
            if not issues:
                return

            # Count pending issues by category
            pending_by_cat: dict[str, int] = {}
            for i in issues:
                if i.get("status") in ("待处理", "处理中"):
                    cat = i.get("category", "其他")
                    pending_by_cat[cat] = pending_by_cat.get(cat, 0) + 1

            # 合并为一条热点提醒（只列 Top 3 积压类别），避免一次刷屏多条
            hot_cats = sorted(
                ((cat, cnt) for cat, cnt in pending_by_cat.items() if cnt >= 3),
                key=lambda x: -x[1],
            )[:3]
            if hot_cats:
                parts = "、".join(f"{cat}({cnt}件)" for cat, cnt in hot_cats)
                total = sum(cnt for _, cnt in hot_cats)
                self.alerts.append({
                    "title": "社区热点提醒",
                    "message": (
                        f"当前热点积压 {total} 件待处理：{parts}。"
                        f"建议优先关注这些类别，如有同类问题请及时上报。"
                    ),
                    "emoji": "📊",
                })

            # Auto-create discussion topic if a category hits threshold
            if max(pending_by_cat.values()) >= 5 if pending_by_cat else False:
                try:
                    from tools.query_topics import _discover_hot_topic
                    hot = _discover_hot_topic()
                    if hot:
                        from data.database import create_topic, get_active_topics
                        existing_topics = get_active_topics(limit=50)
                        existing_titles = {t["title"] for t in existing_topics}
                        if hot["title"] not in existing_titles:
                            create_topic(
                                title=hot["title"],
                                description=hot["description"],
                                category=hot.get("category", ""),
                                created_by_agent=True,
                            )
                            logger.info(f"Auto-created discussion topic: {hot['title']}")
                except Exception as e:
                    logger.warning(f"Auto-topic creation failed: {e}")
        except Exception as e:
            logger.warning(f"Issue hotspot check failed: {e}")

    def _check_health_risk(self):
        """Check community health risk and alert if level is high or critical."""
        try:
            from data.db_health_alerts import HealthRiskEngine
            engine = HealthRiskEngine()
            report = engine.evaluate()
            level = report["overall_level"]

            if level in ("high", "critical"):
                top_disease = report["top_alerts"][0] if report["top_alerts"] else None
                disease_info = ""
                if top_disease:
                    disease_info = f"主要风险：{top_disease['title']}。{top_disease['message'][:80]}"
                self.alerts.append({
                    "title": "社区健康预警",
                    "message": (
                        f"当前社区健康风险等级：{level}（{report['overall_score']}分）。"
                        f"{disease_info}"
                        f"{report['advice_summary']}"
                    ),
                    "emoji": report["overall_emoji"],
                })
        except Exception as e:
            logger.warning(f"Health risk check failed: {e}")

    def _check_resolved_issues(self):
        """Detect recently resolved issues to notify residents of progress."""
        try:
            issues = get_issues(limit=20)
            if not issues:
                return

            # Find recently resolved issues (today)
            today = datetime.now().strftime("%Y-%m-%d")
            recently_resolved = [
                i for i in issues
                if i.get("status") == "已解决" and (i.get("resolved_at") or "")[:10] == today
            ]

            if recently_resolved:
                titles = "、".join(i["title"][:15] for i in recently_resolved[:3])
                self.alerts.append({
                    "title": "问题解决通知",
                    "message": (
                        f"今天有 {len(recently_resolved)} 件社区诉求已解决：{titles}。"
                        f"感谢大家的参与！"
                    ),
                    "emoji": "✅",
                })
        except Exception as e:
            logger.warning(f"Resolved issues check failed: {e}")
