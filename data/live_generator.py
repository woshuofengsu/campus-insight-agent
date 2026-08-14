"""按日期驱动生成演示数据，让 demo 看起来是「活的」。

注意：合成数据，仅用于演示/开发。
    本模块生成的所有事件（问题上报、工单解决、附议增加、反馈条目）
    都是合成数据，生产环境要用真实用户活动数据替代。

每天按日期哈希生成：
  - 1-3 条新工单（随机但同一天结果固定）
  - 自动解决 0-2 条老工单（带处理备注）
  - 给 1-3 条提案加附议数
  - 0-1 条新反馈（模拟居民真实情绪）

会话初始化时调用，制造「社区一直在运转」的错觉。
用确定性哈希，同一天生成的事件永远一样（刷新页面不会重复）。

默认禁用：比赛/生产环境通过 config.DEMO_LIVE_DATA 开关（默认 False）关闭，
只有明确设 DEMO_LIVE_DATA=true 时才生成每日合成数据。一次性 seed_all() 不受影响。
"""
import hashlib
from datetime import datetime, timedelta
from data.database import get_db
from config import DEMO_LIVE_DATA


def _daily_seed() -> int:
    """用今天的日期算一个确定性的伪随机种子。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return int(hashlib.md5(today.encode()).hexdigest()[:8], 16)


def _daily_rng(lo: int, hi: int) -> int:
    """今天用：返回 [lo, hi) 里的一个确定整数。"""
    return lo + (_daily_seed() % (hi - lo))


# 工单模板（按天轮换，30 多条保证不重样）

_ISSUE_TEMPLATES = [
    # 字段顺序: 标题, 分类, 地点, 紧急度, 描述
    # 设施维修
    ("3号楼2单元电梯运行异响", "设施维修", "3号楼2单元", "紧急",
     "电梯运行时有明显金属摩擦异响，门关合也迟缓，居民担心安全。"),
    ("5号楼电梯按钮失灵", "设施维修", "5号楼1单元", "普通",
     "电梯内多个楼层按钮按下无反应，老人按错楼层干着急。"),
    ("2号楼货梯门关合夹人隐患", "设施维修", "2号楼货梯", "紧急",
     "货梯门关合不灵敏，有次差点夹到人，需尽快检修。"),
    ("12号楼顶层屋面漏水", "设施维修", "12号楼顶层", "紧急",
     "一下雨顶层就漏水，墙面都发霉了，雨季快到了急需处理。"),
    ("9号楼2单元厨房管道漏水", "设施维修", "9号楼2单元", "普通",
     "厨房顶部管道持续渗水，天花板都泡起皮了，怀疑楼上管道老化。"),
    ("4号楼1单元下水道堵塞", "设施维修", "4号楼1单元", "紧急",
     "一楼厨房下水道返水，污水流得满地都是，一股恶臭。"),
    ("小区西侧步道路灯损坏", "设施维修", "西侧步道", "普通",
     "西侧步道三盏路灯坏了快一周，晚上一片漆黑，老人散步很危险。"),
    ("6号楼2单元声控灯失灵", "设施维修", "6号楼2单元", "普通",
     "声控灯坏了，晚上上下楼要打手电，老人夜里很危险。"),
    ("中心花园健身器材松动", "设施维修", "中心花园健身区", "普通",
     "好几台健身器材生锈松动，老人锻炼时晃动，有安全隐患。"),
    ("中心花园儿童滑梯破损", "设施维修", "中心花园", "普通",
     "儿童滑梯有处塑料开裂，边缘锋利，已经划伤过孩子的手。"),
    ("南门快递柜屏幕损坏", "设施维修", "南门快递柜", "普通",
     "南门快递柜屏幕坏了，取件只能等快递员手动操作，排队排得很长。"),
    # 环境卫生
    ("小区东南角垃圾桶满溢", "环境卫生", "东南角垃圾点", "紧急",
     "垃圾桶三天没清运，垃圾堆到路边，异味和蚊蝇都来了。"),
    ("4号楼2单元楼道长期堆物", "环境卫生", "4号楼2单元", "普通",
     "楼道堆满旧鞋柜和杂物，落满灰尘还有异味，进出都不方便。"),
    ("中心花园绿化带杂草丛生", "环境卫生", "中心花园", "普通",
     "绿化带快成野草地了，蚊虫特别多，晚上都不敢带孩子去花园。"),
    ("小区步道宠物粪便无人清理", "环境卫生", "小区步道", "普通",
     "遛狗不清理粪便，步道上到处都是，已经踩到过好几次了。"),
    ("2号楼3单元卫生间反味严重", "环境卫生", "2号楼3单元", "普通",
     "卫生间长期有下水道反味，夏天尤其严重，影响整栋楼生活。"),
    # 安全隐患
    ("12号楼前电动车飞线充电", "安全隐患", "12号楼前", "紧急",
     "有人从五楼拉电线给电动车充电，电线裸露在外，下雨天极其危险。"),
    ("3号楼楼道杂物堵塞消防通道", "安全隐患", "3号楼2单元楼道", "紧急",
     "楼道堆满旧家具和纸箱，消防通道被堵了大半，一旦着火逃生通道都没了。"),
    ("8号楼外墙瓷砖脱落风险", "安全隐患", "8号楼外立面", "紧急",
     "外墙有几处瓷砖鼓包，摇摇欲坠，楼下就是人行通道，路过提心吊胆。"),
    ("消防栓前堆满纸箱杂物", "安全隐患", "8号楼1层消防栓", "紧急",
     "消防栓被一堆废纸箱围住，紧急情况根本没法取用，灭火器也早已过期。"),
    ("5号楼单元门口电动车堵门", "安全隐患", "5号楼1单元", "普通",
     "电动车停满单元门口，进出都得侧身，婴儿车和轮椅根本过不去。"),
    # 停车管理
    ("小区车位不足夜间乱停", "停车管理", "小区主干道", "普通",
     "晚上回来车位全满，只能停路边，早上又挡住别人出不去，天天吵架。"),
    ("7号楼前有人私装地锁", "停车管理", "7号楼前空地", "普通",
     "有人私自安装地锁霸占车位，引发邻里纠纷，公共车位凭什么私有？"),
    ("外来车辆长期占用车位", "停车管理", "小区东门附近", "普通",
     "几辆外地牌照车长期占用公共车位，本地居民反而没地方停。"),
    # 噪音扰民
    ("中心广场广场舞音响音量过大", "噪音扰民", "中心广场", "普通",
     "晚上7-9点广场舞音响开得震天响，家里孩子写作业都受影响。"),
    ("6号楼2单元装修噪音超时", "噪音扰民", "6号楼2单元", "普通",
     "装修队晚上8点还在用电钻，跟规定时间不符，楼里老人和婴儿受不了。"),
    ("深夜施工噪音扰民", "噪音扰民", "小区北门附近", "普通",
     "北门外工地深夜还在施工，混凝土搅拌车声音持续到凌晨。"),
    ("7号楼楼道宠物狗半夜狂叫", "噪音扰民", "7号楼1单元", "普通",
     "某户养的狗每天半夜狂叫，整栋楼都睡不好，多次沟通无果。"),
    # 物业服务
    ("物业报修响应慢", "物业服务", "全小区", "普通",
     "报修快一周了都没人上门，打电话催总说“在安排”，服务效率太低。"),
    ("楼道卫生打扫不及时", "物业服务", "3号楼", "普通",
     "楼道一个多月没见保洁来打扫，扶手一层灰，楼梯角落还有烟头。"),
    ("小区监控多处失效", "物业服务", "小区各出入口", "普通",
     "东门和北门监控坏了，丢过快递也查不到，居民没有安全感。"),
    ("小区东门门禁失灵", "物业服务", "东门", "普通",
     "东门门禁坏了一周，什么人都能进出，治安没保障。"),
    # 邻里矛盾
    ("楼上空调外机滴水", "邻里矛盾", "5号楼", "普通",
     "楼上空调外机排水管滴水，滴到楼下窗台和晾晒的衣服上，两家闹得很僵。"),
    # 社区事务
    ("老年助餐点餐品单一", "社区事务", "社区助餐点", "普通",
     "助餐点每天就两三个菜，老人反映吃腻了，希望能丰富菜品。"),
    ("自行车棚堆放僵尸车", "社区事务", "小区自行车棚", "普通",
     "车棚里堆满废旧自行车和杂物，正常停车的都没位置，建议集中清理。"),
    ("独居老人多日未出门", "社区事务", "11号楼3单元", "紧急",
     "独居老人好几天没见出门，邻居敲门无人应，希望社区赶紧上门看看。"),
]

_RESOLVE_NAMES = [
    "物业维修班", "保洁人员", "电工班", "物业管理处",
    "电梯维保公司", "社区网格员", "外包维修公司",
]

_RESOLVE_ACTIONS = [
    "已安排维修人员前往处理，预计今日内完成",
    "配件已采购，待到位后立即更换",
    "已通知相关部门，正在协调处理",
    "维修人员已到现场，正在修复中",
    "已完成维修并验收通过",
    "已清理完毕，恢复正常使用",
    "问题已修复，感谢居民反馈",
    "经检查属实，已列入下周维修计划",
    "临时修复已完成，彻底解决需等假期统一施工",
    "已联系厂家，配件在途，预计3天内修复",
]

_FEEDBACK_TEMPLATES = [
    ("电梯安全", "电梯困人太吓人了，希望能彻底修好", "负面"),
    ("电梯安全", "上周物业派人检修了，最近没再困人", "正面"),
    ("停车管理", "地锁被清理了，停车终于有点秩序", "正面"),
    ("停车管理", "晚上还是没地方停，车位根本不够", "负面"),
    ("停车管理", "错峰停车如果真能落地就好了", "中性"),
    ("环境卫生", "垃圾桶老满，夏天味道大", "负面"),
    ("环境卫生", "绿化改造方案公示了，期待", "中性"),
    ("环境卫生", "宠物便袋箱装上了，遛狗方便多了", "正面"),
    ("噪音扰民", "广场舞9点后还在跳，分贝仪形同虚设", "负面"),
    ("噪音扰民", "装修噪音有人管了，网格员上门了", "正面"),
    ("助餐服务", "助餐点菜品太少，吃腻了", "负面"),
    ("助餐服务", "送餐上门挺方便，独居老人有口热饭", "正面"),
    ("物业服务", "报修一周没人来，物业效率太低", "负面"),
    ("物业服务", "门禁升级了，进出要刷卡，安全感强了", "正面"),
]


def generate_today_events() -> dict:
    """生成今天的社区事件，返回汇总 dict。

    init_session() 里调用——每次页面加载都可以安全调，因为它会先检查今天的
    事件是不是已经生成过（工单按 标题+日期 去重，解决记录看今天有没有解决过）。

    返回的 dict 带 ``generated`` 布尔标记，调用方可以区分合成数据和真实用户活动。
    """
    seed = _daily_seed()
    today_str = datetime.now().strftime("%Y-%m-%d")
    result = {
        "new_issues": 0,
        "resolved_issues": 0,
        "supporter_bumps": 0,
        "new_feedback": 0,
        "day": today_str,
        "generated": True,  # 合成数据 — 有真实用户数据时改成 False
    }

    # 比赛/生产环境默认关闭每日合成数据
    # 只有明确设 DEMO_LIVE_DATA=true 时才生成假工单/假解决/假附议/假反馈。
    # 一次性 seed_all() 的演示样本不受影响。
    if not DEMO_LIVE_DATA:
        result["generated"] = False
        return result

    with get_db() as conn:
        # 看看今天的事件是不是已经生成过了
        already_generated = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues "
            "WHERE author = '系统感知' AND date(reported_at) = date(?)",
            (today_str,)
        ).fetchone()
        today_already_done = (already_generated and already_generated["cnt"] > 0)

        # 顺便看看今天有没有解决过工单
        today_resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues "
            "WHERE status = '已解决' AND date(resolved_at) = date(?)",
            (today_str,)
        ).fetchone()
        today_resolved_done = (today_resolved and today_resolved["cnt"] > 0)

        if today_already_done and today_resolved_done:
            # 今天已经生成过了，跳过但把数量记上
            result["new_issues"] = already_generated["cnt"]
            result["resolved_issues"] = today_resolved["cnt"]
            return result

        # 生成 1-3 条新工单
        if not today_already_done:
            new_count = _daily_rng(1, 4)  # 每天 1-3 条新工单
            for i in range(new_count):
                idx = (seed + i * 73 + i * i * 17) % len(_ISSUE_TEMPLATES)
                title, cat, loc, urgency, desc = _ISSUE_TEMPLATES[idx]
                # 日期稍微错开点（0-2 天前）
                day_offset = (seed + i * 37) % 3
                report_date = (datetime.now() - timedelta(days=day_offset)).strftime("%Y-%m-%d")

                # 查重，别生成重复的
                existing = conn.execute(
                    "SELECT COUNT(*) as cnt FROM community_issues "
                    "WHERE title = ? AND date(reported_at) = date(?)",
                    (title, report_date),
                ).fetchone()
                if existing and existing["cnt"] == 0:
                    conn.execute(
                        """INSERT INTO community_issues
                           (title, category, location, description, urgency, status, reported_at, author)
                           VALUES (?, ?, ?, ?, ?, '待处理', ?, '系统感知')""",
                        (title, cat, loc, f"【自动感知】{desc}（系统于{report_date}自动检测）",
                         urgency, report_date),
                    )
                    result["new_issues"] += 1

        conn.commit()

        # 自动解决 0-2 条老工单
        if not today_resolved_done:
            pending_issues = conn.execute(
                "SELECT id, title, category FROM community_issues "
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
                    "UPDATE community_issues SET status = '已解决', resolved_at = ?, "
                    "description = COALESCE(description, '') || ? WHERE id = ?",
                    (today_str,
                     f"\n\n【{today_str} · {resolver}】{action}",
                     iid),
                )
                result["resolved_issues"] += 1

        conn.commit()

        # 给 1-3 条提案加附议数
        active_proposals = conn.execute(
            "SELECT id, supporter_count FROM proposals "
            "WHERE status = '讨论中' ORDER BY supporter_count DESC LIMIT 10"
        ).fetchall()

        bump_count = min((seed % 3) + 1, len(active_proposals))
        for i in range(bump_count):
            pid = active_proposals[i]["id"]
            bump = (seed + i * 53 + i * 7) % 6 + 1  # 每次加 1 到 6
            conn.execute(
                "UPDATE proposals SET supporter_count = supporter_count + ? WHERE id = ?",
                (bump, pid),
            )
            result["supporter_bumps"] += bump

        conn.commit()

        # 生成 0-1 条反馈
        fb_count = seed % 2  # 0 或 1
        for i in range(fb_count):
            idx = (seed + i * 91) % len(_FEEDBACK_TEMPLATES)
            topic, opinion, sentiment = _FEEDBACK_TEMPLATES[idx]
            # 查重
            dup = conn.execute(
                "SELECT COUNT(*) as cnt FROM feedback_items "
                "WHERE opinion = ? AND topic = ?",
                (opinion, topic),
            ).fetchone()
            if dup and dup["cnt"] == 0:
                conn.execute(
                    "INSERT INTO feedback_items (topic, opinion, source, sentiment) VALUES (?,?,?,?)",
                    (topic, opinion, "居民反馈", sentiment),
                )
                result["new_feedback"] += 1

        conn.commit()

    return result


def get_live_summary() -> str:
    """把今天自动生成的事件拼成一段人话总结。"""
    events = generate_today_events()
    if (events["new_issues"] == 0 and events["resolved_issues"] == 0
            and events["supporter_bumps"] == 0):
        return ""

    parts = []
    if events["new_issues"]:
        parts.append(f"📝 今日自动感知 {events['new_issues']} 件新诉求")
    if events["resolved_issues"]:
        parts.append(f"✅ {events['resolved_issues']} 件工单今日解决")
    if events["supporter_bumps"]:
        parts.append(f"👍 提案今日新增 {events['supporter_bumps']} 个附议")
    if events["new_feedback"]:
        parts.append(f"💬 {events['new_feedback']} 条新反馈")

    return " · ".join(parts)
