"""给社区治理比赛 demo 生成演示数据。

海淀小区 · 接诉即办 社区治理叙事线：
  1. 电梯安全: 诉求 → 提案(加装电梯) → 讨论中
  2. 消防隐患: 多诉求 → 议事话题 → 提案(充电桩) → 已采纳
  3. 停车难: 诉求 → 提案(错峰停车) → 已采纳
  4. 老年关怀: 诉求 → AI 话题 → 意见 → 提案(助餐) → 讨论中
"""
import hashlib
import logging
from datetime import datetime, timedelta
from data.database import init_db, get_db

_log = logging.getLogger(__name__)


def _stable_hash(text: str, mod: int = 4) -> int:
    """确定性哈希 — 跨 Python 会话结果稳定（内置 hash() 不行）。"""
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(h, 16) % mod


def _seed_users():
    """种演示账号 — 居民 + 网格员，比赛 demo 用。"""
    users = [
        ("demo_resident", "", "resident", "海淀小区", "3号楼", "2单元501", "王阿姨", "HD0302501", "13800138000"),
        ("demo_grid", "demo123", "grid", "海淀小区", "网格一组", "", "刘网格员", "G2026001", "13900139000"),
        ("demo_grid2", "demo123", "grid", "海淀小区", "物业", "", "王物业", "G2026002", "13900139001"),
        ("demo_elderly", "", "elderly", "海淀小区", "11号楼", "3单元301", "张大爷", "HD1103301", "13700137000"),
        # 第二演示社区（属地化对比用）：同一句话在朝阳试点社区会命中「北京市」级政策，
        # 而海淀小区用户会命中社区/区级指引 —— 见 docs/competition/演示脚本.md 场景 2。
        # ⚠ 必须放在海淀账号之后：/auth/demo 取该角色第一个账号，顺序变了演示首页就换人了。
        ("demo_resident_cy", "demo123", "resident", "朝阳试点社区", "2号楼", "1单元101", "李叔", "CY0201101", "13600136000"),
    ]
    with get_db() as conn:
        try:
            from data.db_repair import _enc_phone
        except Exception:
            _enc_phone = lambda p: p  # 兜底：加密不可用时写明文（不阻断 seed）
        for username, pw, role, community, building, unit, name, rid, phone in users:
            existing = conn.execute(
                "SELECT id FROM user_profile WHERE username = ?", (username,)
            ).fetchone()
            if existing:
                # 老库补手机号（加密落库，防明文）
                conn.execute(
                    "UPDATE user_profile SET phone='', phone_enc=? WHERE username=? AND (phone_enc IS NULL OR phone_enc='')",
                    (_enc_phone(phone), username),
                )
                # 已有密文却残留明文（历史迁移漏网/回滚）→ 一并清掉明文列（第七轮复审：实测 4 条 demo 账号）
                conn.execute(
                    "UPDATE user_profile SET phone='' WHERE username=? AND length(COALESCE(phone,''))>0 "
                    "AND length(COALESCE(phone_enc,''))>0",
                    (username,),
                )
                continue
            pw_hash = ""
            if pw:
                from data.db_core import _hash_password
                pw_hash = _hash_password(pw)
            conn.execute(
                "INSERT INTO user_profile (username, password_hash, role, community, building, "
                "unit, name, resident_id, phone, phone_enc, onboarding_done) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                (username, pw_hash, role, community, building, unit, name, rid, "", _enc_phone(phone)),
            )
        conn.commit()


def _seed_elderly_profile():
    """Seed 老年关怀档案（demo_elderly 张大爷，独居 + 高血压 + 降压药 + 子女电话）。"""
    try:
        from data.db_elderly import (
            set_health_info, set_medication_reminders, set_emergency_contact,
            set_living_alone, get_profile,
        )
        with get_db() as conn:
            row = conn.execute(
                "SELECT id FROM user_profile WHERE username = 'demo_elderly'"
            ).fetchone()
        if not row:
            return
        uid = row["id"]
        if get_profile(uid):  # 已有档案则不覆盖（幂等）
            return
        set_health_info(uid, {
            "chronic": ["高血压"],
            "allergy": "无",
            "blood_type": "A型",
            "care_notes": "独居老人，需每日平安打卡，网格员重点关注",
            "blood_pressure": [{"date": "2026-08-12", "sys": 152, "dia": 92}],
        })
        set_medication_reminders(uid, [
            {"name": "降压药", "dosage": "1片", "times": ["08:00", "20:00"]},
        ])
        set_emergency_contact(uid, [
            {"name": "张小明", "relation": "儿子", "phone": "13900001111"},
        ])
        set_living_alone(uid, True)
    except Exception as e:
        _log.debug("seed 老人档案失败：%s", e, exc_info=True)


def _seed_knowledge():
    """种知识库：通知、治理指南、社区政策。"""
    entries = [
        ("event", "3号楼电梯停运检修通知",
         "8月15日（周六）8:00-12:00 对3号楼2单元电梯进行年度检修，期间电梯停运，请提前安排出行。检修电话：62319876。",
         "电梯,检修,停运,3号楼"),
        ("event", "小区夏季灭蚊蝇消杀通知",
         "8月12日-14日 下午17:00-19:00 对小区绿化带、垃圾点、下水道井口进行集中消杀，请关好门窗、看护好儿童与宠物。",
         "消杀,蚊虫,卫生,夏季"),
        ("notice", "海淀小区垃圾分类驿站正式启用",
         "应居民议事提案要求，小区新建三处垃圾分类驿站（南门、东门、中心花园），配有督导员和积分兑换机。请按厨余/可回收/其他/有害四分类投放。",
         "垃圾分类,驿站,环保,投放"),
        ("notice", "老旧小区加装电梯政策宣讲会",
         "街道办定于8月20日晚19:00在社区活动室召开加装电梯政策宣讲会，讲解费用分摊、低层补偿、施工流程，欢迎4-12号楼居民参加。",
         "加装电梯,政策,宣讲,老旧小区"),
        ("calendar", "海淀小区 2026 年社区活动安排",
         "8月：暑期青少年托管班、纳凉晚会；9月：中秋邻里节、老年体检；10月：重阳敬老周、消防演练；11月：供暖前检修；12月：新年联欢会。",
         "活动,社区,日程,安排"),
        ("governance", "小区问题上报指南",
         "发现小区问题，在聊天框用自然语言描述即可。Agent 自动分类（设施维修/环境卫生/安全隐患/停车管理/噪音扰民/物业服务/邻里矛盾/社区事务）并评估紧急程度，生成诉求工单全程可追踪。\n\n"
         "📱 紧急问题请同步拨打：社区网格员 62319876 · 物业 24h 62310086",
         "上报,接诉即办,诉求,治理,工单"),
        ("governance", "社区治理反馈渠道",
         "💬 日常诉求：通过本 Agent「接诉即办」上报，自动生成工单追踪\n"
         "🔧 紧急维修：物业 62310086（24h）\n"
         "🗣️ 邻里议事：通过「邻里议事」提交提案、附议他人\n"
         "🚨 紧急救助：110 / 119 / 120\n"
         "🏢 社区居委会：62310001（工作日 9:00-17:00）",
         "反馈,12345,网格员,渠道,物业,居委会"),
        ("governance", "基层治理 OODA 工作法",
         "OODA = Observe(观察) → Orient(定位) → Decide(决策) → Act(行动) → Reflect(反思)。\n"
         "社区先知 Agent 的底层工作流：感知问题→分析归因→制定方案→执行处置→复盘改进。\n"
         "海淀小区作为基层接诉即办试点，通过 OODA 闭环实现社区诉求「发现-上报-处理-反馈」全流程数字化。",
         "OODA,治理,流程,闭环,接诉即办"),
        ("faq", "社区常用电话与网格员信息",
         "🏢 居委会：62310001（工作日 9:00-17:00）\n"
         "🔧 物业报修：62310086（24h）\n"
         "👮 网格员刘姐：62319876（接诉即办）\n"
         "🏥 家庭医生签约：62310231\n"
         "🚌 社区助餐点：中心花园东侧（11:00-13:00）\n"
         "♻️ 垃圾分类驿站：南门/东门/中心花园（7:00-20:00）",
         "电话,网格员,物业,家庭医生,助餐,居委会"),
        ("health", "秋冬季流感预防指南",
         "每年11月至次年3月为流感高发季。建议：①老年人优先接种流感疫苗（社区每年10月组织，电话 62310231）②室内每日通风3次，每次≥30分钟 ③出现发热、咳嗽等症状及时就医并佩戴口罩 ④勤洗手、不共用餐具。",
         "流感,预防,疫苗,冬季,健康"),
        ("health", "春季花粉过敏防护",
         "3-5月花粉季，过敏性鼻炎和哮喘高发。建议：①花粉浓度高的晴天减少外出 ②外出佩戴口罩和护目镜 ③回家后关闭窗户，使用空气净化器 ④随身携带抗过敏药物。家庭医生可进行过敏原检测。",
         "过敏,花粉,春季,鼻炎,健康"),
        ("health", "夏季防暑与肠道疾病预防",
         "6-9月高温天气，中暑和急性胃肠炎高发。建议：①避免高温时段（11:00-15:00）户外活动 ②每日饮水≥2000ml ③注意饮食卫生，不吃隔夜剩菜 ④独居老人注意降温防暑。中暑急救：转移至阴凉处→物理降温→补充淡盐水→严重时立即就医。",
         "中暑,肠道,夏季,防暑,健康"),
        ("health", "独居老人居家安全与关爱",
         "独居老人注意：①家中安装一键呼叫装置，突发情况及时联系网格员（62319876）②定期与子女、邻居保持联系 ③楼道不要堆放杂物，保持消防通道畅通 ④社区志愿者定期上门探访，可主动登记需求。",
         "独居,老人,安全,关爱,呼叫"),
        ("health", "社区养老助餐与家庭医生",
         "海淀小区为60岁以上老人提供助餐服务和家庭医生签约。助餐点：中心花园东侧（11:00-13:00），可送餐上门。家庭医生签约后可享受定期随访、健康咨询、慢病管理。签约电话：62310231。",
         "养老,助餐,家庭医生,慢病,签约"),
    ]
    with get_db() as conn:
        for cat, title, content, keywords in entries:
            conn.execute(
                "INSERT INTO knowledge_base (category, title, content, keywords) VALUES (?,?,?,?)",
                (cat, title, content, keywords),
            )
        conn.commit()


def _seed_issues():
    """种 38 条居民诉求，带上报人，好展示「我的」足迹。"""
    today = datetime.now()
    d = lambda n: (today - timedelta(days=n)).strftime("%Y-%m-%d")

    authors = ["王阿姨", "李叔", "张大爷", "赵先生", "孙女士", "刘女士", "陈先生", "周先生", "吴大爷"]

    issues = [
        # 叙事线1：电梯安全（高层痛点）
        ("3号楼2单元电梯困人频发", "安全隐患", "3号楼2单元",
         "本月电梯已两次困人，最长一次40分钟，老人孩子都吓坏了。物业检修后仍反复，必须彻底解决。",
         "紧急", "处理中", d(2), authors[0]),
        ("3号楼1单元电梯年检标识过期", "安全隐患", "3号楼1单元",
         "电梯内的年检合格证还是去年6月的，早已过期，居民每天乘坐心里没底。",
         "紧急", "待处理", d(3), authors[1]),
        ("1号楼货梯运行时异响严重", "设施维修", "1号楼货梯",
         "货梯上下运行时发出刺耳金属摩擦声，门关合也有延迟，有次差点夹到人。",
         "普通", "待处理", d(1), authors[2]),
        ("2号楼2单元电梯按钮面板失灵", "设施维修", "2号楼2单元",
         "电梯内多个楼层按钮按下无反应，有次直接跳过5楼，老人按错楼层干着急。",
         "普通", "已解决", d(7), authors[3]),
        # 叙事线2：消防隐患
        ("3号楼楼道堆放杂物堵塞消防通道", "安全隐患", "3号楼2单元楼道",
         "楼道堆满旧家具和纸箱，消防通道被堵了大半，一旦着火逃生通道都没了。",
         "紧急", "处理中", d(2), authors[0]),
        ("12号楼楼下电动车飞线充电", "安全隐患", "12号楼前",
         "有人从五楼拉电线给电动车充电，电线裸露在外，下雨天极其危险，上个月隔壁小区就因此着了火。",
         "紧急", "待处理", d(1), authors[4]),
        ("5号楼单元门口电动车堵门", "安全隐患", "5号楼1单元",
         "电动车停满单元门口，进出都得侧身，婴儿车和轮椅根本过不去。",
         "普通", "待处理", d(3), authors[1]),
        ("消防栓前堆满纸箱杂物", "安全隐患", "8号楼1层消防栓",
         "消防栓被一堆废纸箱围住，紧急情况根本没法取用，灭火器也早已过期。",
         "极急", "处理中", d(0), authors[0]),
        # 叙事线3：停车难
        ("小区车位不足夜间乱停", "停车管理", "小区主干道",
         "晚上回来车位全满，只能停路边，早上又挡住别人出不去，天天吵架。",
         "普通", "待处理", d(4), authors[3]),
        ("7号楼前有人私装地锁", "停车管理", "7号楼前空地",
         "有人私自安装地锁霸占车位，引发邻里纠纷，公共车位凭什么私有？",
         "普通", "已解决", d(9), authors[4]),
        ("外来车辆长期占位", "停车管理", "小区东门附近",
         "几辆外地牌照车长期占用公共车位，本地居民反而没地方停，建议设门禁识别。",
         "普通", "待处理", d(2), authors[1]),
        # 叙事线4：环境卫生
        ("小区东南角垃圾桶满溢", "环境卫生", "东南角垃圾点",
         "垃圾桶三天没清运，垃圾堆到路边，异味和蚊蝇都来了，夏天实在难熬。",
         "普通", "已解决", d(8), authors[0]),
        ("4号楼2单元楼道长期堆物", "环境卫生", "4号楼2单元",
         "楼道堆满旧鞋柜和杂物，落满灰尘还有异味，进出都不方便。",
         "普通", "待处理", d(5), authors[2]),
        ("小区绿化带杂草丛生蚊虫多", "环境卫生", "中心花园",
         "绿化带快成野草地了，蚊虫特别多，晚上都不敢带孩子去花园。",
         "普通", "待处理", d(6), authors[3]),
        ("宠物粪便无人清理", "环境卫生", "小区步道",
         "遛狗不清理粪便，步道上到处都是，已经踩到过好几次，太恶心了。",
         "普通", "待处理", d(2), authors[4]),
        # 叙事线5：噪音扰民
        ("广场舞音响音量过大", "噪音扰民", "中心广场",
         "晚上7-9点广场舞音响开得震天响，家里孩子写作业都受影响，窗户都不敢开。",
         "普通", "待处理", d(3), authors[3]),
        ("6号楼2单元装修噪音超时", "噪音扰民", "6号楼2单元",
         "装修队晚上8点还在用电钻，跟规定时间不符，楼里老人和婴儿受不了。",
         "普通", "处理中", d(1), authors[1]),
        ("深夜施工噪音扰民", "噪音扰民", "小区北门附近",
         "北门外工地深夜还在施工，混凝土搅拌车声音持续到凌晨，整栋楼睡不好。",
         "普通", "待处理", d(2), authors[0]),
        # 叙事线6：管道老化
        ("4号楼1单元下水道堵塞", "设施维修", "4号楼1单元",
         "一楼厨房下水道返水，污水流得满地都是，一股恶臭，家里没法待。",
         "紧急", "处理中", d(1), authors[2]),
        ("2号楼3单元卫生间反味严重", "环境卫生", "2号楼3单元",
         "卫生间长期有下水道反味，夏天尤其严重，影响整栋楼生活。",
         "普通", "待处理", d(5), authors[4]),
        ("9号楼2单元厨房管道漏水", "设施维修", "9号楼2单元",
         "厨房顶部管道持续渗水，天花板都泡起皮了，怀疑楼上管道老化破裂。",
         "普通", "处理中", d(2), authors[3]),
        # 叙事线7：老年关怀
        ("独居老人张大爷三天未出门", "社区事务", "11号楼3单元301",
         "独居张大爷三天没见出门，邻居敲门无人应，希望社区赶紧上门看看，担心出事。",
         "紧急", "处理中", d(0), authors[0]),
        ("多层楼栋无障碍坡道缺失", "设施维修", "4-12号楼单元口",
         "老人坐轮椅上下楼没有坡道，进出单元全靠家人抬，太不方便也不安全。",
         "普通", "待处理", d(6), authors[1]),
        ("老年助餐点餐品单一", "社区事务", "社区助餐点",
         "助餐点每天就两三个菜，老人反映吃腻了，希望能丰富菜品、增加营养搭配。",
         "普通", "待处理", d(3), authors[2]),
        # 叙事线8：物业服务
        ("物业报修响应慢", "物业服务", "全小区",
         "报修快一周了都没人上门，打电话催总说“在安排”，服务效率太低。",
         "普通", "待处理", d(2), authors[4]),
        ("小区路灯损坏多日无人修", "设施维修", "小区西侧步道",
         "西侧步道三盏路灯坏了快一周，晚上一片漆黑，老人散步很危险。",
         "普通", "已解决", d(6), authors[0]),
        ("楼道卫生打扫不及时", "物业服务", "3号楼",
         "楼道一个多月没见保洁来打扫，扶手一层灰，楼梯角落还有烟头。",
         "普通", "待处理", d(4), authors[3]),
        ("小区监控多处失效", "物业服务", "小区各出入口",
         "东门和北门监控坏了，丢过快递也查不到，居民没有安全感。",
         "普通", "待处理", d(3), authors[1]),
        # 更多场景
        ("12号楼顶层屋面漏水", "设施维修", "12号楼顶层",
         "顶楼住户反映一下雨就漏水，墙面都发霉了，雨季快到了急需处理。",
         "紧急", "处理中", d(1), authors[2]),
        ("小区南门快递柜损坏", "设施维修", "南门快递柜",
         "南门快递柜屏幕坏了，取件只能等快递员手动操作，排队排得很长。",
         "普通", "待处理", d(2), authors[4]),
        ("8号楼外墙瓷砖脱落风险", "安全隐患", "8号楼外立面",
         "外墙有几处瓷砖鼓包，摇摇欲坠，楼下就是人行通道，路过提心吊胆。",
         "紧急", "处理中", d(1), authors[0]),
        ("健身器材年久失修", "设施维修", "中心花园健身区",
         "好几台健身器材生锈松动，老人锻炼时晃动，有安全隐患。",
         "普通", "待处理", d(7), authors[1]),
        ("小区东门门禁失灵", "物业服务", "东门",
         "东门门禁坏了一周，什么人都能进出，治安没保障。",
         "普通", "已解决", d(5), authors[3]),
        ("楼上空调外机滴水", "邻里矛盾", "5号楼",
         "楼上空调外机排水管滴水，滴到楼下窗台和晾晒的衣服上，两家闹得很僵。",
         "普通", "待处理", d(2), authors[4]),
        ("楼道宠物狗半夜狂叫", "噪音扰民", "7号楼1单元",
         "某户养的狗每天半夜狂叫，整栋楼都睡不好，多次沟通无果。",
         "普通", "处理中", d(2), authors[1]),
        ("自行车棚堆放僵尸车", "社区事务", "小区自行车棚",
         "车棚里堆满废旧自行车和杂物，正常停车的都没位置，建议集中清理。",
         "普通", "待处理", d(4), authors[0]),
        ("中心花园儿童滑梯破损", "设施维修", "中心花园",
         "儿童滑梯有处塑料开裂，边缘锋利，已经划伤过孩子的手。",
         "普通", "待处理", d(3), authors[3]),
        ("6号楼2单元声控灯失灵", "设施维修", "6号楼2单元",
         "声控灯坏了，晚上上下楼要打手电，老人夜里很危险。",
         "普通", "已解决", d(8), authors[2]),
    ]
    def _map_status(old: str, title: str) -> str:
        """旧三态 → 新 11 状态机（演示审核/派单/处理/反馈全流程）。"""
        if old == "已解决":
            return "处理结束"
        if old == "处理中":
            return "处理中"
        # 待处理分散到「待审核/已审核待派单」，演示审核与派单阶段
        return "待审核" if _stable_hash(title, 3) == 0 else "已审核待派单"

    def _map_urgency(old: str) -> str:
        return {"极急": "紧急", "紧急": "紧急", "普通": "一般"}.get(old, "一般")

    with get_db() as conn:
        for title, cat, loc, desc, urg, status, rd, author in issues:
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, urgency, status, reported_at, author) VALUES (?,?,?,?,?,?,?,?)",
                (title, cat, loc, desc, _map_urgency(urg), _map_status(status, title), rd, author),
            )
            if status == "已解决":
                resolve_delay = 1 + _stable_hash(title, 4)
                conn.execute(
                    f"UPDATE community_issues SET resolved_at = date(?, '+{resolve_delay} days') WHERE title = ?",
                    (rd, title),
                )
        conn.commit()


def _seed_proposals():
    """种 19 条社区提案，带作者。"""
    authors = ["王阿姨", "李叔", "张大爷", "赵先生", "孙女士", "刘女士", "陈先生", "周先生"]

    proposals = [
        ("建议为多层楼栋加装电梯",
         "4-12号楼都是6层无电梯，老人上下楼非常困难。建议推进老旧小区加装电梯改造，优先试点4号楼，费用可采取政府补贴+居民分摊。",
         "设施维修", 96, "讨论中", "", authors[1]),
        ("建设小区集中式电动车充电桩",
         "飞线充电、电动车上楼问题频发，存在严重消防隐患。建议在小区南门东侧建设集中充电桩+停车棚，扫码充电、按次计费。",
         "安全隐患", 87, "已采纳", "已纳入街道老旧小区改造计划，拟在南门东侧建设40个充电位，预计年底前完工。", authors[0]),
        ("推行错峰停车共享车位",
         "白天上班车位空着，晚上回来没地方停。建议推出错峰共享，白天车位租给周边写字楼，收入反哺小区公共维修基金。",
         "停车管理", 65, "已采纳", "社区已与周边写字楼达成错峰停车协议，白天开放120个共享车位，收益公示。", authors[3]),
        ("增设社区老年助餐点",
         "目前助餐点菜品单一、送餐慢，老人吃饭难。建议增加助餐点位并开通送餐上门服务，针对糖尿病高血压老人推出健康餐。",
         "社区事务", 73, "讨论中", "", authors[2]),
        ("小区快递柜扩容改造",
         "南门快递柜损坏且柜格不足，取件不便。建议升级扩容并增设一组在东门附近。",
         "设施维修", 41, "已回应", "已联系快递柜运营商，下周更换南门新柜，东门点位正在选址。", authors[4]),
        ("中心花园绿化改造",
         "绿化带荒废、蚊虫多，孩子没地方玩。建议重新规划种植、增设灭蚊灯和儿童活动区。",
         "环境卫生", 58, "讨论中", "", authors[0]),
        ("垃圾分类驿站优化",
         "垃圾桶经常满溢、清运不及时。建议增设分类驿站并加密清运频次，推行积分兑换。",
         "环境卫生", 44, "已回应", "已增加清运班次，三处分类驿站已启用，积分兑换机已到位。", authors[3]),
        ("多层楼栋无障碍坡道改造",
         "老人轮椅进出困难，建议各单元口增设无障碍坡道，方便行动不便的居民。",
         "设施维修", 52, "讨论中", "", authors[1]),
        ("开设社区活动室",
         "老人孩子没地方活动，建议将闲置用房改造成社区活动室，设置图书角、棋牌区。",
         "社区事务", 39, "讨论中", "", authors[0]),
        ("规范小区宠物管理",
         "宠物粪便、半夜犬吠问题频发。建议制定文明养宠公约，设置宠物便袋箱，违规者纳入信用管理。",
         "社区事务", 47, "讨论中", "", authors[4]),
        ("升级小区智慧门禁",
         "门禁老旧、治安有隐患。建议升级刷脸/门禁卡系统，外来人员登记进入。",
         "物业服务", 61, "已回应", "物业已启动门禁升级，预计下月完成东门、南门改造。", authors[3]),
        ("更新小区消防设施",
         "消防栓前堆物、灭火器过期问题突出。建议全面排查更新消防设施，清理消防通道。",
         "安全隐患", 88, "已采纳", "已开展消防大排查，更换过期灭火器32具，清理消防通道6处。", authors[0]),
        ("增设夜间照明",
         "西侧步道路灯损坏，老人夜间出行不安全。建议全面检修并增设太阳能路灯。",
         "设施维修", 43, "已回应", "已修复西侧步道路灯，计划再增设8盏太阳能灯。", authors[1]),
        ("引入社区医疗点与家庭医生",
         "老人看病不便。建议引入社区医疗点，推广家庭医生签约，定期上门随访。",
         "社区事务", 55, "讨论中", "", authors[2]),
        ("规范外卖快递配送",
         "外卖快递随意进出，存在安全隐患。建议设智能取件柜并落实访客登记。",
         "物业服务", 33, "讨论中", "", authors[4]),
        ("更新健身器材",
         "健身器材老化松动，老人锻炼有隐患。建议更新换代并建立定期维护机制。",
         "设施维修", 38, "已回应", "已全面排查，年内更新中心花园健身器材并落实月度巡检。", authors[1]),
        ("建立邻里互助平台",
         "独居老人需要关爱。建议建立邻里互助/志愿帮扶机制，定期探访独居老人。",
         "社区事务", 46, "讨论中", "", authors[0]),
        ("增设儿童活动场地",
         "孩子没地方玩。建议在中心花园增设儿童游乐设施和沙池。",
         "设施维修", 29, "讨论中", "", authors[3]),
        ("规范广场舞管理",
         "广场舞噪音扰民。建议划定活动区域、限定时段，安装分贝监测，平衡健身与休息需求。",
         "噪音扰民", 51, "已回应", "已划定活动区域，晚9点后禁止高音喇叭，安装分贝监测仪实时提醒。", authors[0]),
    ]
    def _map_prop_status(old: str, title: str) -> str:
        """旧状态 → 新提案状态机（审核/公示/执行/反馈闭环）。"""
        if old == "已采纳":
            return "已完成"
        if old == "已回应":
            return "执行中"
        # 讨论中分散到「公示中/待确认公示·私有」，演示公示与确认阶段
        return "公示中" if _stable_hash(title, 2) == 0 else "待确认公示/私有"

    with get_db() as conn:
        for title, desc, cat, supporters, status, response, author in proposals:
            new_status = _map_prop_status(status, title)
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, status, "
                "response_text, author, is_public, reporter_name, audit_status) VALUES (?,?,?,?,?,?,?,1,?,'')",
                (title, desc, cat, supporters, new_status, response, author, author),
            )
            if new_status == "公示中":
                conn.execute(
                    "UPDATE proposals SET voting_started_at=datetime('now','-3 days'), "
                    "voting_ended_at=datetime('now','+4 days') WHERE title=? AND status='公示中'",
                    (title,),
                )
            if new_status == "已完成":
                conn.execute(
                    "UPDATE proposals SET resolved_at=datetime('now','-2 days'), "
                    "satisfaction='满意' WHERE title=? AND status='已完成'",
                    (title,),
                )
        conn.commit()


def _seed_topics():
    """种讨论话题和居民意见。"""
    topics = [
        ("加装电梯你支持吗？",
         "4-12号楼无电梯，老人上下楼困难。有居民提议加装电梯。你支持吗？费用怎么分摊？一楼住户的顾虑如何化解？",
         "设施维修", True),
        ("停车难怎么破？",
         "小区车位不足、乱停占位问题长期存在。错峰停车、立体车位、清理地锁……你有什么好建议？",
         "停车管理", True),
        ("电动车充电安全大家怎么看？",
         "飞线充电、电动车上楼隐患大。集中充电桩建设正在进行，你希望怎么收费、怎么管理？",
         "安全隐患", True),
        ("广场舞噪音如何平衡？",
         "老人要健身、居民要休息，广场舞噪音如何平衡？划定区域、限时、分贝管控，你的意见是？",
         "噪音扰民", True),
        ("垃圾分类怎么做更好？",
         "垃圾分类驿站已启用，但清运不及时、分类指引不够。你觉得还能怎么优化？",
         "环境卫生", True),
        ("老年助餐需要什么？",
         "助餐点菜品单一、送餐慢。老人真正需要什么样的助餐服务？价格、菜品、送餐，你怎么看？",
         "社区事务", True),
        ("物业服务质量怎么提升？",
         "报修响应慢、保洁不及时、物业费不透明。你觉得物业最该改进什么？",
         "物业服务", False),
    ]
    opinions = [
        (1, "我们楼老人多，坚决支持加装，就是费用分摊要公平", "匿名居民"),
        (1, "一楼住户可能不同意，采光会受影响，得想好补偿方案", "匿名居民"),
        (1, "支持！我婆婆腿脚不好，爬六楼太遭罪了", "匿名居民"),
        (1, "加装电梯是好事，但施工期间的噪音和通行要安排好", "匿名居民"),
        (2, "小区车位确实不够，建议把东边空地改造成立体停车", "匿名居民"),
        (2, "地锁太气人了，建议物业统一清理", "匿名居民"),
        (2, "错峰停车这个主意不错，白天车位闲着也是闲着", "匿名居民"),
        (2, "建议给老弱病残住户留几个专用车位", "匿名居民"),
        (3, "飞线充电太危险了，上个月隔壁小区就着火了", "匿名居民"),
        (3, "希望充电桩便宜点，有的小区一度电收2块太贵", "匿名居民"),
        (3, "车棚要装监控，不然电瓶被偷", "匿名居民"),
        (3, "建议充电位别占绿化，绿化本来就少", "匿名居民"),
        (4, "跳舞可以理解，但9点后真的要停，孩子要睡觉", "匿名居民"),
        (4, "建议统一用蓝牙耳机，或者音量降到规定分贝", "匿名居民"),
        (4, "老人们也需要活动，希望别一刀切，划好区域就行", "匿名居民"),
        (4, "装个分贝仪，超了就提醒，这样最公平", "匿名居民"),
        (5, "垃圾桶经常满，清运不及时是最大的问题", "匿名居民"),
        (5, "建议发分类指引，很多老人分不清厨余和其他垃圾", "匿名居民"),
        (5, "驿站选址要方便，别设太远", "匿名居民"),
        (5, "积分兑换能提高积极性，建议搞起来", "匿名居民"),
        (6, "我爸妈两个人吃饭，助餐点很需要，就是菜品太单一", "匿名居民"),
        (6, "希望送餐上门，有些老人出不了门", "匿名居民"),
        (6, "价格要实惠，老人退休金不多", "匿名居民"),
        (6, "建议针对糖尿病高血压老人出健康餐", "匿名居民"),
        (7, "报修响应太慢，建议设个48小时办结承诺", "匿名居民"),
        (7, "保洁频率太低，楼道一层灰", "匿名居民"),
        (7, "物业费跟服务质量不匹配，建议公开服务清单", "匿名居民"),
        (7, "网格员挺负责的，就是物业公司不给力", "匿名居民"),
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
    """种反馈条目，供情感分析用。"""
    feedbacks = [
        ("电梯安全", "电梯困人太吓人了，希望能彻底修好", "用户反馈", "负面"),
        ("电梯安全", "上周物业派人检修了，最近没再困人", "用户反馈", "正面"),
        ("停车管理", "地锁被清理了，停车终于有点秩序", "用户反馈", "正面"),
        ("停车管理", "晚上还是没地方停，车位根本不够", "用户反馈", "负面"),
        ("停车管理", "错峰停车如果真能落地就好了", "用户反馈", "中性"),
        ("消防隐患", "飞线充电看着就害怕，希望快点建充电桩", "用户反馈", "负面"),
        ("消防隐患", "消防通道清理后敞亮多了，物业这次动作快", "用户反馈", "正面"),
        ("环境卫生", "垃圾桶老满，夏天味道大", "用户反馈", "负面"),
        ("环境卫生", "绿化改造方案公示了，期待", "用户反馈", "中性"),
        ("环境卫生", "宠物便袋箱装上了，遛狗方便多了", "用户反馈", "正面"),
        ("噪音扰民", "广场舞9点后还在跳，分贝仪形同虚设", "用户反馈", "负面"),
        ("噪音扰民", "装修噪音有人管了，网格员上门了", "用户反馈", "正面"),
        ("老年关怀", "独居老人有人定期上门了，心里踏实", "用户反馈", "正面"),
        ("老年关怀", "助餐点菜品太少，吃腻了", "用户反馈", "负面"),
        ("老年关怀", "希望无障碍坡道快点修，轮椅进出太难", "用户反馈", "中性"),
        ("物业服务", "报修一周没人来，物业效率太低", "用户反馈", "负面"),
        ("物业服务", "门禁升级了，进出要刷卡，安全感强了", "用户反馈", "正面"),
        ("物业服务", "物业费到底花在哪了，建议公开", "用户反馈", "中性"),
        ("邻里矛盾", "楼上漏水拖了半个月，两家闹得很僵", "用户反馈", "负面"),
        ("邻里矛盾", "网格员调解后，楼上终于修了，感谢", "用户反馈", "正面"),
        ("管道老化", "下水道返水太糟心了，老小区管道该统一换了", "用户反馈", "负面"),
        ("管道老化", "反味问题终于解决了，换了地漏", "用户反馈", "正面"),
        ("社区事务", "快递柜换新了，取件不用排队了", "用户反馈", "正面"),
        ("社区事务", "僵尸车该清理了，车棚都被占满", "用户反馈", "负面"),
        ("社区事务", "社区活动室什么时候能开？孩子没地方去", "用户反馈", "中性"),
        ("老年关怀", "家庭医生签约挺方便，老人在家就能问诊", "用户反馈", "正面"),
        ("设施维修", "路灯修好了，晚上散步安心多了", "用户反馈", "正面"),
        ("设施维修", "外墙瓷砖鼓包吓人，希望尽快处理", "用户反馈", "负面"),
    ]
    with get_db() as conn:
        for topic, opinion, source, sentiment in feedbacks:
            conn.execute(
                "INSERT INTO feedback_items (topic, opinion, source, sentiment) VALUES (?,?,?,?)",
                (topic, opinion, source, sentiment),
            )
        conn.commit()


def _seed_care_events():
    """种演示用关怀事件（U4：让大屏「关怀触达率」卡有数据，而不是 0）。

    **只种标签，不种任何 PII**（无原文、无手机号、无姓名）：emotion_tag / scene / status 而已。
    幂等：仅当 `care_event_log` 为空时写入；跨最近 7 天分布，便于周维度统计。
    """
    from datetime import datetime, timedelta
    # (天数前, 情绪标签, 是否安抚, 场景, 是否共情, 意图, 状态)
    rows = [
        (0, "着急", 1, "repair_ok", 1, "repair_dispatch", "成功"),
        (0, "担忧", 1, "repair_ok", 1, "health_advisor", "成功"),
        (1, "不满", 1, "sos", 1, "handoff", "transferred_to_human"),
        (1, "着急", 1, "repair_ok", 1, "repair_dispatch", "成功"),
        (2, "焦虑", 1, "sos", 1, "health_advisor", "transferred_to_human"),
        (2, None, 0, "fail", 1, "policy_expert", "失败"),
        (3, "担忧", 1, "repair_ok", 1, "repair_dispatch", "成功"),
        (4, "着急", 1, "repair_ok", 1, "repair_dispatch", "成功"),
        (4, None, 0, "repair_ok", 1, "proposal_collab", "成功"),
        (5, "不满", 1, "sos", 1, "handoff", "transferred_to_human"),
        (5, "担忧", 1, "repair_ok", 1, "notification_manager", "成功"),
        (6, "焦虑", 1, "repair_ok", 1, "health_advisor", "成功"),
        (6, "着急", 1, "repair_ok", 1, "repair_dispatch", "成功"),
    ]
    try:
        with get_db() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM care_event_log").fetchone()[0]
            # 守卫：库里已有 ≥5 条就认为数据足够（避免覆盖真实使用中积累的数据）；
            # 空库或仅零星几条（如演示前有人试聊过）时补种，保证大屏卡片不空。
            if existing >= 5:
                return 0
            now = datetime.now()
            for days_ago, emo, comfort, scene, scene_line, intent, status in rows:
                ts = (now - timedelta(days=days_ago, hours=(days_ago * 3) % 12)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO care_event_log (user_id, role, emotion_tag, comfort_used, "
                    "scene, scene_line_used, intent, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (0, "resident", emo or "", comfort, scene, scene_line, intent, status, ts),
                )
            conn.commit()
            return len(rows)
    except Exception as e:  # noqa: BLE001
        _log.debug("种关怀事件失败：%s", e, exc_info=True)
        return 0


def _seed_notices():
    """种演示用通知（修复演示数据缺口：notices 表为空 → 三处通知功能都演示不出来）。

    缺口证据：全项目审查时实测 `SELECT COUNT(*) FROM notices` = **0**，导致
      ① 居民端「通知」页永远空列表；② 老年端「听通知」空列表（适老旗舰功能之一）；
      ③ 网格端「通知管理」无历史可管；④ 对话里问「最近有什么通知」只能答"最近没有新通知"。
    这里种 6 条覆盖四种类型 + 两种状态（已发布/草稿），**全部为虚构演示内容，不含任何真实个人信息**。
    幂等：`notices` 已有 ≥3 条就跳过（不覆盖真实使用中积累的数据）。
    """
    from datetime import datetime, timedelta

    rows = [
        # (标题, 类型, 范围, 正文, 老年版摘要, 状态, 是否紧急, 是否置顶, 发布天数前)
        ("关于3号楼电梯停运检修的通知", "停水停电通知", "全体居民",
         "3号楼2单元电梯因年检停运检修，时间为本周六 09:00-16:00，期间请使用楼梯。行动不便的居民可联系社区协助。",
         "3号楼电梯周六白天检修，坐不了电梯，请走楼梯。", "已发布", 0, 1, 1),
        ("小区夏季灭蚊蝇消杀安排", "社区公告", "全体居民",
         "本周四上午对小区绿化带、垃圾驿站、楼道进行消杀，请居民关好门窗，看管好宠物与儿童。",
         "周四上午小区打药，请关好门窗、看好孩子和宠物。", "已发布", 0, 0, 2),
        ("老旧小区加装电梯政策宣讲会", "活动通知", "全体居民",
         "下周三 14:00 在社区服务中心二楼举办加装电梯政策宣讲，介绍申请条件、表决比例与补贴标准，欢迎有需求的居民参加。",
         "下周三下午两点，社区讲装电梯的政策，欢迎大家来听。", "已发布", 0, 0, 3),
        ("海淀小区垃圾分类驿站正式启用", "社区公告", "全体居民",
         "小区东门垃圾分类驿站已完成改造并启用，开放时间 06:30-20:30，支持厨余、可回收、有害、其他四类投放。",
         "东门垃圾分类站已经开了，早上六点半到晚上八点半可以用。", "已发布", 0, 0, 5),
        ("【紧急】暴雨橙色预警，请减少外出", "紧急通知", "全体居民",
         "气象台发布暴雨橙色预警，预计今日 16:00-22:00 有强降雨并伴短时大风。请减少外出、收好窗外物品；如遇积水或房屋漏水请及时在平台报修。",
         "今天下午到晚上有暴雨，尽量别出门，屋外东西收进来。有漏水就点报修。", "已发布", 1, 0, 0),
        ("社区老年助餐点试运行征求意见", "政策通知", "全体居民",
         "社区拟在服务中心一层设立老年助餐点（试运行），现征求居民意见，可在本平台「邻里议事」提交建议。",
         "社区想办老年助餐点，正在问大家意见。", "草稿", 0, 0, 0),
    ]
    try:
        with get_db() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
            if existing >= 3:
                return 0
            now = datetime.now()
            for title, ntype, scope, body, summary, status, urgent, pinned, days_ago in rows:
                ts = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO notices (title, notice_type, publish_scope, body, elderly_summary, "
                    "publisher, scheduled_at, published_at, is_pinned, pinned_at, is_urgent, "
                    "scope_target_json, attachment_json, status, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,'社区服务中心',?,?,?,?,?,'[]','[]',?,?,?)",
                    (title, ntype, scope, body, summary, ts,
                     ts if status == "已发布" else None,
                     pinned, ts if pinned else None, urgent, status, ts, ts),
                )
            conn.commit()
            return len(rows)
    except Exception as e:  # noqa: BLE001
        _log.debug("种演示通知失败：%s", e, exc_info=True)
        return 0


def _seed_region_policies() -> int:
    """种 3 条**属地政策**（地区识别 WS5），与全国/北京市条目形成"本地优先、全国兜底"对照。

    为什么必须有：库里现有 `applicable_area` 分布是 北京市×39 / 空×19 / 北京市海淀区×1 ——
    区级条目只有 1 条，属地优先的效果**几乎看不见**。这里补 3 条不同层级，让演示能一眼看出差别。

    幂等：按标题判重（已存在则跳过）；不动 schema。
    """
    entries = [
        # 区级：与"北京市/全国"的养老政策同主题，用于演示"本区细则排前面"
        ("北京市海淀区高龄老人津贴申领实施细则",
         "海淀区户籍、年满 80 周岁老人可申领高龄津贴：80-89 岁每人每月 200 元，90-99 岁 500 元，"
         "100 岁以上 800 元。办理材料：身份证、户口簿、本人名下银行卡（可他人代办，需代办人身份证）。"
         "办理地点：海淀小区社区服务站（工作日 9:00-17:00，电话 62310001），也可在「北京通」APP 线上申请。"
         "注意：津贴按季度发放，跨区迁入的从迁入当季起算。",
         "高龄,津贴,补贴,老人,80岁,海淀,申领,办理,材料,养老,季度,高龄补贴,养老补贴,高龄津贴,怎么领,多少钱",
         "北京市海淀区"),
        # 社区级（本社区）：最具体一级
        ("海淀小区社区助餐补贴与代办服务指引",
         "本小区 60 岁以上居民在中心花园助餐点就餐可享社区补贴 2 元/餐（每人每日限 2 餐），"
         "需携带身份证到助餐点登记一次；行动不便可申请送餐上门（每餐加收 1 元，电话 62310086）。"
         "另：社区服务站可代办公交老年卡年审、高龄津贴材料代收，每周二、四上午办理。",
         "助餐,补贴,送餐,代办,登记,老年卡,社区,老人,就餐,驿站",
         "海淀小区"),
        # 市级：中间层级
        ("北京市老旧小区加装电梯财政补贴办法",
         "北京市对老旧小区增设电梯项目给予财政补贴：每部电梯市级补贴 24 万元，区级按 1:1 配套，"
         "居民自筹部分可按楼层系数分摊（一层不出资、二层 5%、逐层递增）。"
         "申请须经本单元 2/3 以上业主同意，由街道办统一受理并公示 7 天。",
         "加装电梯,电梯,补贴,增设电梯,分摊,申请,老旧小区,费用",
         "北京市"),
    ]
    added = 0
    with get_db() as conn:
        for title, content, keywords, area in entries:
            hit = conn.execute("SELECT id FROM knowledge_base WHERE title=?", (title,)).fetchone()
            if hit:
                continue
            conn.execute(
                "INSERT INTO knowledge_base (category, title, content, keywords, "
                "audit_status, applicable_area, source) VALUES (?,?,?,?,?,?,?)",
                ("社保医保" if "津贴" in title or "电梯" in title else "社区服务",
                 title, content, keywords, "已发布", area, "社区整理"),
            )
            added += 1
        conn.commit()
    return added


def seed_all(db_path: str):
    """往库里种治理演示数据。只在库空的时候种——绝不删已有数据。"""
    init_db(db_path)
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM community_issues").fetchone()[0]
    if count > 0:
        # 已有数据：只确保 demo 账号 + 老年档案 + 演示用关怀事件/通知存在（幂等），绝不重灌工单
        _seed_users()
        _seed_elderly_profile()
        n = _seed_care_events()
        if n:
            print(f"[seed] Care events seeded: {n} rows")
        m = _seed_notices()
        if m:
            print(f"[seed] Notices seeded: {m} rows")
        r = _seed_region_policies()
        if r:
            print(f"[seed] Region policies seeded: {r} rows")
        print(f"[seed] Database already has {count} issues, ensuring demo accounts only")
        return
    print("[seed] Empty database — seeding community governance demo data (narrative edition)...")
    _seed_users()
    _seed_elderly_profile()
    _seed_knowledge()
    _seed_issues()
    _seed_proposals()
    _seed_topics()
    _seed_feedback()
    _seed_care_events()
    _seed_notices()
    _seed_region_policies()
    # 疾控监测数据（国家疾控局月度公报）
    try:
        from data.db_surveillance import seed_surveillance
        surv_result = seed_surveillance()
        print(f"[seed] Health surveillance: {surv_result['msg']}")
    except Exception as e:
        _log.debug("种 health surveillance 数据失败：%s", e, exc_info=True)
        print(f"[seed] Health surveillance seeding skipped: {e}")
    # 用现有种子数据回填活动日志
    try:
        from data.db_notifications import seed_activity_from_existing
        act_result = seed_activity_from_existing()
        print(f"[seed] Activity log backfill: {act_result}")
    except Exception as e:
        _log.debug("回填活动日志失败：%s", e, exc_info=True)
        print(f"[seed] Activity log backfill skipped: {e}")
    # 汇报**实际入库量**（从库里数，不写死——写死的数字迟早和库内容对不上）
    rows = [("knowledge_base", "条知识"), ("community_issues", "条工单"),
            ("proposals", "条提案"), ("discussion_topics", "个议题"),
            ("topic_opinions", "条意见"), ("feedback_items", "条反馈"),
            ("health_surveillance", "条疾控监测")]
    parts: list[str] = []
    with get_db() as conn:
        for table, unit in rows:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                parts.append(f"{n} {unit}")
            except Exception as e:  # noqa: BLE001 — 统计失败不该影响种子结果
                _log.debug("统计 %s 失败：%s", table, e, exc_info=True)
    print("[seed] Done! 实际入库：" + "，".join(parts))


if __name__ == "__main__":
    from config import DB_PATH
    seed_all(DB_PATH)
