# data/seed.py
"""Generate demo data for campus governance competition demo.

Narrative threads:
  1. 操场照明: issue → proposal → status:discussing
  2. 图书馆: multiple issues → proposal adopted → extended hours
  3. 食堂: issues → AI discussion topic → opinions → proposal → processing
  4. 校园网: persistent issues → feedback → AI topic
"""
import hashlib
from datetime import datetime, timedelta
from data.database import init_db, get_db


def _stable_hash(text: str, mod: int = 4) -> int:
    """Deterministic hash — stable across Python sessions (unlike built-in hash())."""
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(h, 16) % mod


def _seed_users():
    """Seed demo users — student + teacher for competition demo."""
    users = [
        ("demo_student", "", "student", "北京工商大学", "大三", "计算机科学与技术", "小明", "20240001"),
        ("demo_teacher", "demo123", "teacher", "北京工商大学", "后勤管理处", "", "张老师", "T2024001"),
    ]
    with get_db() as conn:
        for username, pw, role, school, grade, major, name, sid in users:
            existing = conn.execute(
                "SELECT id FROM user_profile WHERE username = ?", (username,)
            ).fetchone()
            if existing:
                continue
            pw_hash = ""
            if pw:
                from data.db_core import _hash_password
                pw_hash = _hash_password(pw)
            conn.execute(
                "INSERT INTO user_profile (username, password_hash, role, school, grade, "
                "major, name, student_id, onboarding_done) VALUES (?,?,?,?,?,?,?,?,1)",
                (username, pw_hash, role, school, grade, major, name, sid),
            )
        conn.commit()


def _seed_knowledge():
    """Seed knowledge base: calendar, notices, governance guides."""
    today = datetime.now()
    entries = [
        ("event", "良乡校区停水检修通知",
         "7月30日（周三）8:00-18:00 良乡校区全校停水进行管道检修，请提前储水。涉及区域：文二楼+学生公寓区。报修：81353578。",
         "停水,检修,通知,良乡"),
        ("event", "BTBU 秋季学期选课通知",
         "2026-2027学年第一学期选课：8月25-28日。选课系统：jw.btbu.edu.cn。请提前查看培养方案和课程目录。",
         "选课,校历,教务,秋季"),
        ("notice", "中区图书馆延长开放至23:00",
         "应学生提案要求，中区图书馆自下周一起延长开放至23:00（原22:00）。东区图书馆维持原时间。感谢提案同学！",
         "图书馆,开放时间,提案,延长,中区"),
        ("notice", "学生公寓区快递柜安装工程",
         "良乡校区学生公寓区智能快递柜安装已获批准，预计8月中旬施工，11月前投入使用。施工期间请留意通行安排。",
         "快递柜,宿舍,施工,通知,良乡"),
        ("calendar", "2026-2027学年 BTBU 校历",
         "秋季学期：9月14日报到，9月15日上课，1月25日放寒假（18周）。选课：8月25-28日。考试周：1月11-24日。春季学期：3月1日报到，3月2日上课，7月初放暑假。",
         "校历,开学,选课,考试,秋季,春季"),
        ("governance", "校园问题上报指南",
         "发现校园问题，在聊天框用自然语言描述即可。Agent 自动分类（设施维修/环境卫生/安全隐患/教学设备/网络服务/餐饮问题/校园管理）并评估紧急程度。\n\n"
         "📱 也可通过「掌上北工商」App 报修。\n"
         "🚨 紧急问题请同步拨打：保卫处 81351110（24h）· 报修 81353578（24h）",
         "上报,报修,问题,治理,掌上北工商"),
        ("governance", "校园治理反馈渠道",
         "💬 日常建议：通过本 Agent「有话说」提交提案\n"
         "🔧 紧急报修：拨 81353578（24h 维修）或掌上北工商 App\n"
         "🍽️ 食堂投诉：饮食服务中心 81351828\n"
         "🛡️ 安全事件：保卫处 81351110（钟楼一层 24h）\n"
         "🏥 就医：校医院 17810690120",
         "反馈,报修,电话,后勤,渠道,保卫处"),
        ("governance", "基层治理 OODA 工作法",
         "OODA = Observe(观察) → Orient(定位) → Decide(决策) → Act(行动) → Reflect(反思)。\n"
         "校园先知 Agent 的底层认知架构：感知问题→分析归因→制定方案→执行处置→复盘改进。\n"
         "北京工商大学良乡校区作为基层综治试点，通过 OODA 闭环实现校园问题「发现-上报-处理-反馈」全流程数字化。",
         "OODA,治理方法,流程,闭环,良乡"),
        ("faq", "校园常用部门电话（良乡校区）",
         "🏫 保卫处 24h：81351110 / 81353386（钟楼一层）\n"
         "🔧 报修电话：81353578（24h，学生公寓2号楼8单元一层）\n"
         "🏥 校医院值班：17810690120\n"
         "🍽️ 食堂值班：81351828\n"
         "🏠 公寓服务中心：81353581\n"
         "💳 一卡通挂失：81353262\n"
         "📚 图书馆：中区图书馆 8:00-22:00",
         "电话,保卫处,校医院,报修,一卡通,图书馆"),
        ("health", "秋冬季流感预防指南",
         "每年11月至次年3月为流感高发季。建议：①接种流感疫苗（校医院每年10月组织免费接种，电话 17810690120）②教室每日通风3次以上，每次≥30分钟 ③出现发热、咳嗽等症状及时就医并佩戴口罩 ④勤洗手、不共用餐具。",
         "流感,预防,疫苗,冬季,健康,校医院"),
        ("health", "春季过敏防护",
         "3-5月花粉季，过敏性鼻炎和哮喘高发。建议：①花粉浓度高的晴天减少户外活动 ②外出佩戴口罩和护目镜 ③宿舍关闭窗户，使用空气净化器 ④随身携带抗过敏药物。校医院可进行过敏原检测。",
         "过敏,花粉,春季,鼻炎,健康"),
        ("health", "夏季防暑与肠道疾病预防",
         "6-9月高温天气，中暑和急性胃肠炎高发。建议：①避免高温时段（11:00-15:00）户外活动 ②每日饮水≥2000ml ③注意饮食卫生，不食用来历不明外卖 ④食堂加强冷链管理和食材检验。中暑急救：转移至阴凉处→物理降温→补充淡盐水→严重时立即就医。",
         "中暑,肠道,夏季,防暑,健康"),
        ("health", "校园传染病报告流程",
         "发现疑似传染病例时：①立即报告辅导员和校医院（17810690120）②患者佩戴口罩并前往校医院就诊 ③同宿舍/同班同学观察症状 ④校医院判断是否需要隔离并向房山区疾控中心报告。早发现、早报告、早隔离、早治疗。",
         "传染病,报告,流程,隔离,健康,校医院"),
        ("health", "考试周健康提醒",
         "期末备考期间免疫力易下降。建议：①保证每天6-8小时睡眠，避免通宵 ②均衡饮食，适当补充维生素 ③每学习1小时起身活动5-10分钟 ④出现不适及时就医，不要硬撑。校医院在考试周增设晚间门诊。",
         "考试,健康,睡眠,免疫力,备考"),
    ]
    with get_db() as conn:
        for cat, title, content, keywords in entries:
            conn.execute(
                "INSERT INTO knowledge_base (category, title, content, keywords) VALUES (?,?,?,?)",
                (cat, title, content, keywords),
            )
        conn.commit()


def _seed_issues():
    """Seed 22 campus issues with authors for personal footprint demo."""
    today = datetime.now()
    d = lambda n: (today - timedelta(days=n)).strftime("%Y-%m-%d")

    authors = ["张三", "李四", "王五", "赵六", "陈同学", "刘同学", "杨同学", "周同学", "吴同学"]

    issues = [
        # ── Storyline 1: 操场照明 ──
        ("良乡操场跑道夜间照明不足", "安全隐患", "良乡校区操场跑道",
         "操场西南角约50米跑道完全没有路灯，晚上8点后一片漆黑，跑步很不安全。已有多位同学反映。",
         "普通", "已解决", d(12), authors[4]),
        ("操场南入口路灯损坏", "设施维修", "良乡校区操场南入口",
         "操场南门路灯已熄灭一周，入口处非常暗。",
         "普通", "已解决", d(8), authors[0]),
        ("操场看台座椅锈蚀严重", "设施维修", "良乡校区操场看台",
         "东侧看台前排座椅锈蚀，多处螺丝松动，运动会前急需维修。",
         "普通", "待处理", d(2), authors[5]),
        # ── Storyline 2: 图书馆 ──
        ("中区图书馆二楼走廊顶灯闪烁", "设施维修", "中区图书馆2F走廊",
         "第三个顶灯持续闪烁，影响阅读区光线。",
         "普通", "已解决", d(10), authors[1]),
        ("中区图书馆空调温度过低", "环境卫生", "中区图书馆阅览区",
         "三楼南侧阅览区空调设定16度，体感太冷，建议调到24度。",
         "普通", "已解决", d(8), authors[6]),
        ("中区图书馆一楼饮水机故障", "设施维修", "中区图书馆1F",
         "一楼西侧饮水机不出热水，考试周影响较大。",
         "普通", "已解决", d(6), authors[2]),
        ("中区图书馆自习区插座不足", "设施维修", "中区图书馆3F",
         "三楼自习区306-310座位附近无可用插座，笔记本续航困难。",
         "普通", "处理中", d(2), authors[7]),
        # ── Storyline 3: 食堂 ──
        ("中区食堂后面垃圾桶溢出", "环境卫生", "中区食堂后门",
         "垃圾桶两天没清理，有异味，夏天尤甚。",
         "普通", "已解决", d(9), authors[0]),
        ("中区食堂一楼打饭窗口排队过长", "餐饮问题", "中区食堂1F",
         "中午12点高峰期排队超过20分钟，学生意见较大。",
         "普通", "已解决", d(7), authors[3]),
        ("勤苑餐厅麻辣烫涨价", "餐饮问题", "勤苑餐厅麻辣烫窗口",
         "麻辣烫从8元涨到10元，但分量没变，多名同学反映。",
         "普通", "待处理", d(3), authors[8]),
        ("中区食堂餐具清洗不干净", "环境卫生", "中区食堂1F",
         "发现多个餐盘和碗有油渍残留，卫生状况堪忧。",
         "紧急", "处理中", d(2), authors[1]),
        ("民族餐厅空调不制冷", "设施维修", "民族餐厅就餐区",
         "就餐区空调出风口无风，30度天吃饭像蒸桑拿。",
         "普通", "待处理", d(1), authors[2]),
        # ── Storyline 4: 校园网 ──
        ("良乡校区宿舍区晚间频繁断网", "网络服务", "学生公寓区",
         "每天晚上8-10点网络频繁断开，影响学习和娱乐。",
         "普通", "已解决", d(11), authors[6]),
        ("学生公寓5号楼WiFi信号极弱", "网络服务", "学生公寓5号楼",
         "5号楼3层以上WiFi信号几乎为零，只能用流量。",
         "普通", "已解决", d(9), authors[3]),
        ("文二楼多媒体设备网络不稳定", "网络服务", "文二楼多媒体教室",
         "上课期间频繁断网，影响教学。",
         "紧急", "处理中", d(3), authors[0]),
        ("图书馆电子资源访问慢", "网络服务", "中区图书馆",
         "知网和万方数据库加载缓慢，论文下载需要等很久。",
         "普通", "待处理", d(1), authors[7]),
        # ── Other issues ──
        ("文二楼二楼男厕水龙头漏水", "设施维修", "文二楼2F男厕",
         "第三个水龙头持续滴水，地上已有积水。",
         "普通", "已解决", d(8), authors[1]),
        ("文二楼多媒体教室投影仪偏色", "教学设备", "文二楼305",
         "投影画面整体偏黄，影响课件展示，多名教师反馈。",
         "普通", "已解决", d(7), authors[8]),
        ("良乡校区共享单车乱停乱放", "校园管理", "校门口+各教学楼前",
         "共享单车随意停放，阻碍通道，影响校园环境和通行。",
         "普通", "已解决", d(6), authors[2]),
        ("学生公寓5号楼北侧围墙裂缝", "安全隐患", "学生公寓5号楼北侧",
         "围墙裂缝约30cm长，有倒塌风险，需紧急处理。",
         "紧急", "处理中", d(2), authors[4]),
        ("文二楼一楼自动售货机故障", "设施维修", "文二楼1F大厅",
         "自动售货机频繁吞币不出货，已收到多位同学投诉。",
         "普通", "待处理", d(1), authors[3]),
        ("行政楼至图书馆路段路面坑洼", "设施维修", "行政楼至中区图书馆路段",
         "主干道有两处直径约30cm的坑洼，雨天积水严重，骑车易摔倒。",
         "普通", "待处理", d(0), authors[5]),
    ]
    with get_db() as conn:
        for title, cat, loc, desc, urg, status, rd, author in issues:
            conn.execute(
                "INSERT INTO campus_issues (title, category, location, description, urgency, status, reported_at, author) VALUES (?,?,?,?,?,?,?,?)",
                (title, cat, loc, desc, urg, status, rd, author),
            )
            if status == "已解决":
                resolve_delay = 1 + _stable_hash(title, 4)
                conn.execute(
                    f"UPDATE campus_issues SET resolved_at = date(?, '+{resolve_delay} days') WHERE title = ?",
                    (rd, title),
                )
        conn.commit()


def _seed_proposals():
    """Seed 12 campus proposals with authors."""
    authors = ["张三", "李四", "王五", "陈同学", "刘同学", "杨同学", "周同学", "吴同学"]

    proposals = [
        ("建议在操场和校园道路增加夜间照明",
         "操场西南角完全没有路灯，多条校园道路路灯间距过大。建议在操场四角增设LED照明灯，道路每隔30米增设一盏。已有10+条相关安全问题上报。",
         "安全隐患", 56, "讨论中", "", authors[3]),
        ("建议图书馆延长闭馆时间到23:00",
         "现在22:30闭馆太早了，考试周复习时间不够。建议延长到23:00，可以只开放一楼自习区，非考试周恢复原时间。",
         "校园管理", 73, "已采纳", "图书馆已决定从下周起延长开放至23:00，请关注公众号通知。", authors[0]),
        ("图书馆增设自习区充电插座",
         "三楼自习区多个座位无可用插座，建议在每排座位后方安装USB充电接口。",
         "设施维修", 34, "已回应", "已纳入下学期后勤改造计划，预计9月开学前完成。", authors[4]),
        ("食堂增加素食和民族窗口",
         "目前中区食堂和勤苑餐厅菜品选择偏少，素食者和民族需求学生选择困难。建议每个食堂至少设置1-2个素食/民族窗口。",
         "餐饮问题", 41, "已采纳", "中区食堂二层将设立素食+民族专窗，8月中旬试运营。", authors[1]),
        ("建立食堂菜品价格公示制度",
         "近期中区食堂部分窗口涨价，学生不清楚依据。建议各食堂在入口处公示所有菜品价格及成本构成，涨跌有依据。",
         "餐饮问题", 27, "讨论中", "", authors[5]),
        ("升级良乡校区学生公寓校园网带宽",
         "学生公寓晚间高峰期网络严重卡顿，已有多条工单反馈。建议将公寓区带宽从100M升级到500M。",
         "网络服务", 48, "讨论中", "", authors[2]),
        ("建议在学生公寓区增设快递柜",
         "快递在校门口堆放，取件不便且容易丢失。建议每栋学生公寓楼下增设智能快递柜，凭取件码自取。",
         "校园管理", 62, "已采纳", "已获批准，预计8月中旬施工，11月前投入使用。", authors[6]),
        ("建立 BTBU 校园二手物品交易平台",
         "毕业季大量物品被丢弃，建议学校建立线上二手交易平台，既环保又方便。",
         "校园管理", 19, "讨论中", "", authors[0]),
        ("增设良乡校区自行车停车棚",
         "共享单车和私人自行车缺乏遮雨棚，雨天电动车充电也不安全。文二楼和中区食堂周边尤其需要。",
         "校园管理", 13, "讨论中", "", authors[1]),
        ("文二楼和轻工食品大楼增设饮水机",
         "文二楼和轻工食品大楼部分楼层没有饮水机，课间喝水需要上下楼很麻烦。",
         "设施维修", 22, "已回应", "后勤管理处已实地考察，计划在文二楼2F、轻工食品大楼3F各增设一台饮水机。", authors[7]),
        ("延长良乡校区体育场馆开放时间",
         "目前体育馆晚上9点关门，很多同学晚上才有时间锻炼。建议延长到22:30。",
         "校园管理", 10, "讨论中", "", authors[2]),
        ("校医院增加晚间急诊服务",
         "目前校医院下午5点下班，夜间突发不适只能去良乡医院，很不方便。建议延长到22:00。校医院值班：17810690120。",
         "校园管理", 7, "讨论中", "", authors[0]),
    ]
    with get_db() as conn:
        for title, desc, cat, supporters, status, response, author in proposals:
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, status, response_text, author) VALUES (?,?,?,?,?,?,?)",
                (title, desc, cat, supporters, status, response, author),
            )
        conn.commit()


def _seed_topics():
    """Seed discussion topics with more opinions."""
    topics = [
        ("食堂菜品价格最近涨了，你怎么看？",
         "近期收到多位同学反馈食堂部分窗口涨价。你觉得价格合理吗？有什么建议？",
         "餐饮问题", True),
        ("图书馆占座问题怎么解决？",
         "考试周图书馆占座现象严重。有同学提议引入预约+定时清座机制。你觉得可行吗？",
         "校园管理", True),
        ("校园网晚间卡顿——你的体验如何？",
         "多位同学反映晚上8-10点校园网卡顿。你遇到了吗？对网络改善有什么期待？",
         "网络服务", True),
        ("操场和道路照明改善大家有什么建议？",
         "已有多条关于操场和道路照明的上报，有同学提了提案。你觉得哪些区域最需要加灯？",
         "安全隐患", True),
    ]
    opinions = [
        (1, "一楼麻辣烫涨了2块钱，但分量也变多了，还可以接受", "匿名学生"),
        (1, "打饭窗口确实涨了，原来8块的套餐现在10块了，但是量没变，有点过分", "匿名学生"),
        (1, "希望学校公示菜品价格标准，涨价有依据、有上限，不然每次都偷偷涨", "匿名学生"),
        (1, "二楼小炒没涨价品质也稳定，推荐大家去二楼", "匿名学生"),
        (1, "涨价可以理解，物价确实在涨。但建议食堂公开成本构成，让我们知道钱花在哪了", "匿名学生"),
        (2, "支持预约制！图书馆座位本来就紧张，占座太不道德了", "匿名学生"),
        (2, "预约可以，但给临时离开留15分钟缓冲。上个厕所就被清座太冤了", "匿名学生"),
        (2, "考试周座位不够才是根本问题，建议开放教一楼空教室作为临时自习室", "匿名学生"),
        (2, "建议引入'占座举报'功能，拍照上传，超过30分钟无人直接清座", "匿名学生"),
        (3, "宿舍区晚上8-10点打游戏延迟巨高，看视频也加载不出来", "匿名学生"),
        (3, "我们宿舍买了个路由器，速度和稳定性都比校园WiFi好多了，建议学校直接升级硬件", "匿名学生"),
        (3, "教学楼和图书馆的网络还行，就是宿舍区有问题", "匿名学生"),
        (4, "操场西南角是真的一点灯都没有，晚上跑步像闯鬼屋", "匿名学生"),
        (4, "校门口进来的那条路也很暗，建议优先解决主干道照明", "匿名学生"),
        (4, "支持提案！已经附议了，希望早日动工", "匿名学生"),
    ]
    with get_db() as conn:
        for title, desc, cat, by_agent in topics:
            conn.execute(
                "INSERT INTO discussion_topics (title, description, category, created_by_agent) VALUES (?,?,?,?)",
                (title, desc, cat, int(by_agent)),
            )
        conn.commit()

        for topic_id, content, label in opinions:
            conn.execute(
                "INSERT INTO topic_opinions (topic_id, content, participant_label) VALUES (?,?,?)",
                (topic_id, content, label),
            )
            conn.execute(
                "UPDATE discussion_topics SET participant_count = participant_count + 1 WHERE id = ?",
                (topic_id,),
            )
        conn.commit()


def _seed_feedback():
    """Seed feedback items for sentiment analysis."""
    feedbacks = [
        ("食堂菜品价格", "新开的麻辣烫窗口不错，价格也合理", "用户反馈", "正面"),
        ("食堂菜品价格", "一楼打饭排队时间太长了，建议增加窗口", "用户反馈", "负面"),
        ("食堂菜品价格", "希望增加素食和清真选项", "用户反馈", "中性"),
        ("食堂菜品价格", "二楼小炒品质一直稳定，推荐！", "用户反馈", "正面"),
        ("图书馆开放时间", "考试周延长到23:00是真的好，不然复习时间根本不够", "用户反馈", "正面"),
        ("图书馆开放时间", "新装的护眼台灯很实用，好评！", "用户反馈", "正面"),
        ("图书馆设施", "饮水机终于修好了，点赞", "用户反馈", "正面"),
        ("校园网速", "最近宿舍WiFi每天晚上8-10点特别卡", "用户反馈", "负面"),
        ("校园网速", "新校园网套餐比以前便宜速度也更快了", "用户反馈", "正面"),
        ("校园网速", "5号楼WiFi信号几乎没有，希望尽快解决", "用户反馈", "负面"),
        ("校园安全", "夜间操场灯光太暗希望增加照明", "用户反馈", "中性"),
        ("校园安全", "围墙裂缝终于有人管了，之前路过都害怕", "用户反馈", "正面"),
        ("校园交通", "共享单车经常堆在校门口影响出行", "用户反馈", "负面"),
        ("校园交通", "建议规划专门的共享单车停放区域", "用户反馈", "中性"),
        ("快递服务", "校门口取快递太不方便了，赶紧装快递柜吧", "用户反馈", "负面"),
    ]
    with get_db() as conn:
        for topic, opinion, source, sentiment in feedbacks:
            conn.execute(
                "INSERT INTO feedback_items (topic, opinion, source, sentiment) VALUES (?,?,?,?)",
                (topic, opinion, source, sentiment),
            )
        conn.commit()


def seed_all(db_path: str):
    """Seed the database with governance demo data. Only seeds if DB is empty — NEVER deletes existing data."""
    init_db(db_path)
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM campus_issues").fetchone()[0]
    if count > 0:
        print(f"[seed] Database already has {count} issues, skipping seed (preserving user data)")
        return
    print("[seed] Empty database — seeding governance demo data (narrative edition)...")
    _seed_users()
    _seed_knowledge()
    _seed_issues()
    _seed_proposals()
    _seed_topics()
    _seed_feedback()
    # ── Surveillance data (CDC monthly bulletin) ──
    try:
        from data.db_surveillance import seed_surveillance
        surv_result = seed_surveillance()
        print(f"[seed] Health surveillance: {surv_result['msg']}")
    except Exception as e:
        print(f"[seed] Health surveillance seeding skipped: {e}")
    # ── Activity log backfill (from existing seed data) ──
    try:
        from data.db_notifications import seed_activity_from_existing
        act_result = seed_activity_from_existing()
        print(f"[seed] Activity log backfill: {act_result}")
    except Exception as e:
        print(f"[seed] Activity log backfill skipped: {e}")
    print("[seed] Done! Seeded: 9 knowledge entries, 22 campus issues, "
          "12 proposals, 4 discussion topics, 16 opinions, 15 feedback items, "
          "39 health surveillance records")


if __name__ == "__main__":
    from config import DB_PATH
    seed_all(DB_PATH)
