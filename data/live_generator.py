# data/live_generator.py
"""Time-driven data generator — makes demo data feel "alive".

⚠️  SYNTHETIC DATA — FOR DEMO / DEVELOPMENT USE ONLY:
    本模块生成的所有事件（问题上报、工单解决、附议增加、反馈条目）
    均为合成数据 (synthetic / simulated)，用于演示和开发环境。
    生产环境应使用真实用户活动数据替代。

Each day, based on date hash, generates:
  - 1-3 new campus issues (random but deterministic per date)
  - 0-2 auto-resolved old issues (with detailed resolution notes)
  - Increments supporter counts for 1-3 proposals
  - 0-1 new feedback items (simulating organic student sentiment)

Called during session init to create the illusion of continuous campus activity.
Uses deterministic hashing so the same date always produces the same events
(no duplicates across page reloads).
"""
import hashlib
from datetime import datetime, timedelta
from data.database import get_db


def _daily_seed() -> int:
    """Deterministic pseudo-random seed from today's date."""
    today = datetime.now().strftime("%Y-%m-%d")
    return int(hashlib.md5(today.encode()).hexdigest()[:8], 16)


def _daily_rng(lo: int, hi: int) -> int:
    """Return a deterministic integer in [lo, hi) for today."""
    return lo + (_daily_seed() % (hi - lo))


# ── Issue templates (rotated daily, 30+ templates for variety) ──

_ISSUE_TEMPLATES = [
    # title, category, location, urgency, description
    ("图书馆三楼空调漏水", "设施维修", "图书馆三楼", "普通",
     "空调出风口持续滴水，地面已有积水，影响读者通行。"),
    ("食堂一楼筷子消毒柜故障", "设施维修", "一食堂一楼", "紧急",
     "消毒柜指示灯不亮，餐具无法消毒，用餐高峰期影响大。"),
    ("操场跑道塑胶起皮", "设施维修", "操场", "普通",
     "跑道西南段约10米塑胶面层起皮，跑步容易绊倒。"),
    ("教一楼大厅照明灯不亮", "设施维修", "教一楼大厅", "普通",
     "大厅南侧两盏顶灯熄灭多日，晚上光线昏暗。"),
    ("宿舍区垃圾桶溢出未清理", "环境卫生", "宿舍区", "紧急",
     "5号宿舍楼下垃圾桶已满三天未清理，异味严重。"),
    ("教学楼走廊墙皮脱落", "设施维修", "教学楼三楼走廊", "普通",
     "走廊东段墙皮大面积脱落，影响美观且有安全隐患。"),
    ("食堂油烟排放影响周边宿舍", "环境卫生", "食堂", "普通",
     "晚饭时段油烟直排，附近宿舍开窗就有油烟味。"),
    ("校门口共享单车乱停放", "校园管理", "校门口", "普通",
     "共享单车堵塞人行道，早晚高峰期通行困难。"),
    ("实验楼电梯异响", "安全隐患", "实验楼", "紧急",
     "电梯运行时有金属摩擦异响，已持续一周，需紧急检修。"),
    ("图书馆WiFi信号不稳定", "网络服务", "图书馆", "普通",
     "三楼自习区WiFi频繁断连，影响在线学习。"),
    ("教二楼多媒体投影模糊", "教学设备", "教二楼", "普通",
     "305教室投影仪画面偏黄模糊，影响课件展示效果。"),
    ("一食堂麻辣烫窗口涨价未公示", "餐饮问题", "一食堂", "普通",
     "部分同学反映麻辣烫从8元涨到10元，但无任何公示说明。"),
    ("校园主干道路灯损坏", "设施维修", "校园主干道", "普通",
     "行政楼至图书馆路段3盏路灯同时熄灭，夜间行走不安全。"),
    ("操场看台座椅螺丝松动", "安全隐患", "操场看台", "紧急",
     "东看台前排多个座椅螺丝松动摇晃，运动会前急需维修。"),
    ("二食堂二楼排烟不畅", "环境卫生", "二食堂二楼", "普通",
     "高峰期油烟排不出去，整个二楼都是烟味。"),
    ("宿舍热水供应不稳定", "设施维修", "宿舍区", "紧急",
     "5号宿舍楼晚间热水时有时无，影响学生洗漱。"),
    ("教学楼自动售货机吞币", "设施维修", "教学楼一楼", "普通",
     "教一楼大厅售货机频繁吞币不出货，已有多人投诉。"),
    ("图书馆自习区占座严重", "校园管理", "图书馆", "普通",
     "考试周结束后占座现象仍很严重，部分座位长期被占。"),
    ("校园网网速慢影响选课", "网络服务", "全校", "紧急",
     "选课高峰期网络延迟极高，页面加载需要5分钟以上。"),
    ("教学楼厕所门锁损坏", "设施维修", "教三楼二楼男厕", "普通",
     "第二隔间门锁损坏，无法正常使用。"),
    ("篮球场地面开裂", "设施维修", "篮球场", "普通",
     "2号球场地面有裂缝，打球有崴脚风险。"),
    ("一食堂二楼空调不制冷", "设施维修", "一食堂二楼", "普通",
     "天气炎热，空调出热风，就餐体验极差。"),
    ("实验楼天台门锁损坏", "安全隐患", "实验楼", "普通",
     "天台门锁失效，存在安全隐患。"),
    ("绿化带水管破裂", "设施维修", "教学区绿化带", "紧急",
     "水管破裂大量漏水，浪费水资源且影响通行。"),
    ("图书馆应急灯不亮", "安全隐患", "图书馆二楼", "紧急",
     "走廊应急指示灯不亮，消防检查不过关。"),
    ("食堂后厨卫生状况差", "环境卫生", "一食堂后厨", "紧急",
     "有同学路过看到后厨地面油污严重，需要整改。"),
    ("教学楼电梯超载报警失灵", "安全隐患", "教一楼电梯", "紧急",
     "电梯超载不报警，高峰期挤满人仍在运行。"),
    ("快递站包裹堆积无人管", "校园管理", "校门口快递站", "普通",
     "快递堆积如山，部分包裹已放置一周无人领取。"),
    ("宿舍楼防火门常开", "安全隐患", "学生宿舍3号楼", "普通",
     "防火门被石头顶住常开，违反消防规定。"),
    ("公共浴室排水堵塞", "设施维修", "学生宿舍公共浴室", "普通",
     "排水口堵塞，洗澡水漫到更衣区。"),
]

_RESOLVE_NAMES = [
    "后勤维修组", "保洁人员", "信息中心", "电工班",
    "物业管理处", "校维修队", "外包维修公司",
]

_RESOLVE_ACTIONS = [
    "已安排维修人员前往处理，预计今日内完成",
    "配件已采购，待到位后立即更换",
    "已通知相关部门，正在协调处理",
    "维修人员已到现场，正在修复中",
    "已完成维修并验收通过",
    "已清理完毕，恢复正常使用",
    "问题已修复，感谢同学反馈",
    "经检查属实，已列入下周维修计划",
    "临时修复已完成，彻底解决需等假期统一施工",
    "已联系厂家，配件在途，预计3天内修复",
]

_FEEDBACK_TEMPLATES = [
    ("食堂菜品价格", "新窗口味道不错，价格也比外面便宜", "正面"),
    ("食堂菜品价格", "中午高峰期还是太挤了，建议延长供餐时间", "负面"),
    ("图书馆开放时间", "延长到23:00太好了！感谢学校采纳建议", "正面"),
    ("校园网速", "最近宿舍WiFi好多了，看来学校在改善", "正面"),
    ("校园网速", "教五楼信号还是差，希望继续优化", "负面"),
    ("校园安全", "新装的路灯很亮，晚上走路安心多了", "正面"),
    ("快递服务", "快递柜什么时候能装好？每天找快递好麻烦", "中性"),
    ("校园交通", "共享单车清理及时了，校门口终于通了", "正面"),
]


def generate_today_events() -> dict:
    """Generate today's campus events. Returns summary dict.

    Called during init_session() — safe to call every page load because
    it checks if today's events have already been generated (by title+date
    dedup for issues, and by checking if any were already resolved today).

    Returns dict includes a ``generated`` boolean flag so consumers can
    distinguish synthetic data from real user activity.
    """
    seed = _daily_seed()
    today_str = datetime.now().strftime("%Y-%m-%d")
    result = {
        "new_issues": 0,
        "resolved_issues": 0,
        "supporter_bumps": 0,
        "new_feedback": 0,
        "day": today_str,
        "generated": True,  # synthetic data — set to False when real user data is available
    }

    with get_db() as conn:
        # ── Check if today's events already generated ──
        already_generated = conn.execute(
            "SELECT COUNT(*) as cnt FROM campus_issues "
            "WHERE author = '系统感知' AND date(reported_at) = date(?)",
            (today_str,)
        ).fetchone()
        today_already_done = (already_generated and already_generated["cnt"] > 0)

        # Also check if any resolutions happened today
        today_resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM campus_issues "
            "WHERE status = '已解决' AND date(resolved_at) = date(?)",
            (today_str,)
        ).fetchone()
        today_resolved_done = (today_resolved and today_resolved["cnt"] > 0)

        if today_already_done and today_resolved_done:
            # Already generated today, skip but still count
            result["new_issues"] = already_generated["cnt"]
            result["resolved_issues"] = today_resolved["cnt"]
            return result

        # ── Generate 1-3 new issues ──
        if not today_already_done:
            new_count = _daily_rng(1, 4)  # 1-3 new issues per day
            for i in range(new_count):
                idx = (seed + i * 73 + i * i * 17) % len(_ISSUE_TEMPLATES)
                title, cat, loc, urgency, desc = _ISSUE_TEMPLATES[idx]
                # Add slight date variation (0-2 days ago)
                day_offset = (seed + i * 37) % 3
                report_date = (datetime.now() - timedelta(days=day_offset)).strftime("%Y-%m-%d")

                # Check for duplicate
                existing = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE title = ? AND date(reported_at) = date(?)",
                    (title, report_date),
                ).fetchone()
                if existing and existing["cnt"] == 0:
                    conn.execute(
                        """INSERT INTO campus_issues
                           (title, category, location, description, urgency, status, reported_at, author)
                           VALUES (?, ?, ?, ?, ?, '待处理', ?, '系统感知')""",
                        (title, cat, loc, f"【自动感知】{desc}（系统于{report_date}自动检测）",
                         urgency, report_date),
                    )
                    result["new_issues"] += 1

        conn.commit()

        # ── Auto-resolve 0-2 old issues ──
        if not today_resolved_done:
            pending_issues = conn.execute(
                "SELECT id, title, category FROM campus_issues "
                "WHERE status IN ('待处理','处理中') "
                "AND reported_at < date('now', '-2 days') "
                "ORDER BY reported_at ASC LIMIT 10"
            ).fetchall()

            resolve_count = min(seed % 3, len(pending_issues))
            for i in range(resolve_count):
                iid = pending_issues[i]["id"]
                resolver = _RESOLVE_NAMES[(seed + i * 31) % len(_RESOLVE_NAMES)]
                action = _RESOLVE_ACTIONS[(seed + i * 41) % len(_RESOLVE_ACTIONS)]
                conn.execute(
                    "UPDATE campus_issues SET status = '已解决', resolved_at = ?, "
                    "description = COALESCE(description, '') || ? WHERE id = ?",
                    (today_str,
                     f"\n\n【{today_str} · {resolver}】{action}",
                     iid),
                )
                result["resolved_issues"] += 1

        conn.commit()

        # ── Bump supporter counts for 1-3 proposals ──
        active_proposals = conn.execute(
            "SELECT id, supporter_count FROM proposals "
            "WHERE status = '讨论中' ORDER BY supporter_count DESC LIMIT 10"
        ).fetchall()

        bump_count = min((seed % 3) + 1, len(active_proposals))
        for i in range(bump_count):
            pid = active_proposals[i]["id"]
            bump = (seed + i * 53 + i * 7) % 6 + 1  # +1 to +6
            conn.execute(
                "UPDATE proposals SET supporter_count = supporter_count + ? WHERE id = ?",
                (bump, pid),
            )
            result["supporter_bumps"] += bump

        conn.commit()

        # ── Generate 0-1 feedback items ──
        fb_count = seed % 2  # 0 or 1
        for i in range(fb_count):
            idx = (seed + i * 91) % len(_FEEDBACK_TEMPLATES)
            topic, opinion, sentiment = _FEEDBACK_TEMPLATES[idx]
            # Check duplicate
            dup = conn.execute(
                "SELECT COUNT(*) as cnt FROM feedback_items "
                "WHERE opinion = ? AND topic = ?",
                (opinion, topic),
            ).fetchone()
            if dup and dup["cnt"] == 0:
                conn.execute(
                    "INSERT INTO feedback_items (topic, opinion, source, sentiment) VALUES (?,?,?,?)",
                    (topic, opinion, "学生反馈", sentiment),
                )
                result["new_feedback"] += 1

        conn.commit()

    return result


def get_live_summary() -> str:
    """Return a human-readable summary of today's auto-generated events."""
    events = generate_today_events()
    if (events["new_issues"] == 0 and events["resolved_issues"] == 0
            and events["supporter_bumps"] == 0):
        return ""

    parts = []
    if events["new_issues"]:
        parts.append(f"📝 今日自动感知 {events['new_issues']} 件新问题")
    if events["resolved_issues"]:
        parts.append(f"✅ {events['resolved_issues']} 件工单今日解决")
    if events["supporter_bumps"]:
        parts.append(f"👍 提案今日新增 {events['supporter_bumps']} 个附议")
    if events["new_feedback"]:
        parts.append(f"💬 {events['new_feedback']} 条新反馈")

    return " · ".join(parts)
