"""疾病防治模块 — 季节模型 + 天气关联 + 社区人流密度 + 风险评分。

  数据来源与模拟说明:
  本模块生成的是模拟/估计数据，不是真实流行病学报告。
  风险评分基于三层模型叠加：
    1. 季节先验 — 基于国家疾控局月度公报中公布的
       中国北方地区季节性传染病流行趋势，提取各月份疾病基线风险。
    2. 天气关联 — 温度骤降、湿度变化、空气质量事件与呼吸道/胃肠道疾病
       发病率的已知统计相关性。
    3. 社区人流密度 — 流感高发季、换季时节等人员聚集场景下的传播风险推断。
  综合风险评分 = 季节基线 × 天气修正 + 密度修正 → 4级风险等级。

  重要提示：本模块输出的是模拟估算值，基于公共卫生公报 + 季节模型 + 天气关联，
  不是真实流行病学监测数据，不能用于临床或公共卫生决策。

架构:
  SeasonModel       — 按月份的病种风险先验（北方地区）
  WeatherCorrelator — 降温 / 湿度变化触发
  CommunityDensity     — 考试周、活动密度 → 传播风险
  HealthRiskEngine  — 把上面三层汇总成 4 级风险

用法:
  from data.db_health_alerts import HealthRiskEngine
  engine = HealthRiskEngine()
  risk = engine.evaluate()          # 完整评估
  alerts = engine.active_alerts()   # 只取超过阈值的告警
"""
import json
import logging
from datetime import datetime
from data.database import get_db

_log = logging.getLogger(__name__)


# 1. 季节模型：北方地区的按月先验

_SEASON_DISEASES = {
    # (开始月, 结束月): [(病名, 基础风险分0-100, 症状, 建议)]
    # 全年基础风险 — 任何时候都需要关注
    (1, 12): [
        ("甲型流感", 35, "高热、咳嗽、咽痛、全身酸痛、乏力",
         "秋冬高发，建议接种流感疫苗。单元楼每日通风，出现症状及时就医并佩戴口罩"),
        ("乙型流感", 25, "发热、咳嗽、咽痛、肌肉酸痛、乏力",
         "症状通常较甲流轻，但仍需注意休息、多饮水、及时就医"),
    ],
    # 冬春季高发 (11月-3月)
    (11, 3): [
        ("甲型流感·高峰", 75, "高热、咳嗽、咽痛、全身酸痛、乏力",
         "流感高峰期！接种疫苗是最佳预防手段，单元楼每日通风，出现症状及时就医"),
        ("乙型流感·高峰", 45, "发热、咳嗽、咽痛、肌肉酸痛、乏力",
         "乙流高峰通常略晚于甲流，注意休息、多饮水、及时就医"),
        ("呼吸道感染", 60, "鼻塞、流涕、咳嗽、低热",
         "注意保暖，多喝温水，避免长时间待在密闭空调房"),
        ("诺如病毒感染", 40, "呕吐、腹泻、腹痛",
         "注意手部卫生，不共用餐具，助餐点加强食品安全管理"),
    ],
    (3, 5): [
        ("过敏性鼻炎", 55, "打喷嚏、流清涕、鼻痒、眼痒",
         "花粉季减少户外活动，关闭单元楼窗户，必要时使用抗过敏药物"),
        ("过敏性哮喘", 20, "喘息、胸闷、咳嗽",
         "随身携带药物，避免接触花粉和粉尘，出现喘息及时就医"),
        ("水痘", 30, "发热、皮疹、瘙痒",
         "春季为水痘高发期，注意个人卫生，出现皮疹立即就医并隔离"),
    ],
    (6, 9): [
        ("急性胃肠炎", 50, "恶心、呕吐、腹痛、腹泻",
         "注意饮食卫生，不食用来历不明外卖，助餐点加强冷链管理"),
        ("中暑", 45, "头晕、恶心、大量出汗或皮肤干热",
         "避免高温时段户外活动，多饮水，单元楼保持通风"),
        ("登革热", 10, "高热、头痛、肌肉关节痛、皮疹",
         "清理积水、防蚊灭蚊，南方小区需特别注意"),
    ],
    (9, 11): [
        ("季节性流感（秋冬季）", 65, "含甲型/乙型流感，突发高热、咳嗽、咽痛、肌肉酸痛",
         "接种流感疫苗是最佳预防手段，单元楼每日通风30分钟以上"),
        ("普通感冒", 50, "鼻塞、流涕、打喷嚏、轻微咽痛",
         "注意天气变化及时增减衣物，保持充足睡眠增强免疫力"),
    ],
}


def _month_in_range(month: int, start: int, end: int) -> bool:
    """判断月份是否落在 [start, end] 区间，跨年也算。"""
    if start <= end:
        return start <= month <= end
    else:
        return month >= start or month <= end


def get_seasonal_diseases(month: int | None = None) -> list[dict]:
    """返回指定月份（默认现在）有哪些疾病风险。"""
    if month is None:
        month = datetime.now().month

    results: list[dict] = []
    for (start, end), diseases in _SEASON_DISEASES.items():
        if _month_in_range(month, start, end):
            for name, base_risk, symptoms, advice in diseases:
                results.append({
                    "name": name,
                    "base_risk": base_risk,
                    "symptoms": symptoms,
                    "advice": advice,
                    "season": f"{start}月-{end}月",
                })
    return results


# 2. 天气关联

def _get_weather_risk_modifiers() -> dict:
    """取当前天气，算出疾病风险修正项。

    返回 dict，键有 temp_drop、humidity、air_quality、modifiers。
    每个修正项是往基础风险上加的增量（正数 = 风险更高）。
    """
    modifiers: dict[str, int] = {}
    details: dict = {"temp_drop": 0, "humidity": 50, "air_quality": "未知",
                     "temp_high": 25, "temp_low": 15}

    try:
        from tools.query_weather import get_today_weather
        days, _, _ = get_today_weather()
        if days:
            d = days[0]
            temp_high = d.get("temp_high", 25)
            temp_low = d.get("temp_low", 15)
            rain_prob = d.get("rain_prob", 0)
            condition = d.get("condition", "")
            details["temp_high"] = temp_high
            details["temp_low"] = temp_low
            details["rain_prob"] = rain_prob
            details["condition"] = condition

            # 1. 温度风险：昼夜温差大 → 感冒风险升高
            #    极冷（<5°C）或极热（>35°C）也会抬高基线
            temp_range = temp_high - temp_low
            if temp_range > 12:
                modifiers["昼夜温差大→感冒风险"] = 20
            elif temp_range > 8:
                modifiers["昼夜温差较大→感冒风险"] = 10

            if temp_high > 35:
                modifiers["极端高温→中暑风险"] = 30
            elif temp_high > 30:
                modifiers["高温天气→中暑风险"] = 15

            if temp_low < 0:
                modifiers["严寒天气→呼吸道疾病"] = 20
            elif temp_low < 5:
                modifiers["低温天气→呼吸道疾病"] = 10

            # 2. 湿度风险：湿度过高 → 呼吸道
            if rain_prob >= 80:
                modifiers["高湿预警→呼吸道疾病"] = 15
            elif rain_prob >= 60:
                modifiers["湿度偏高→呼吸道疾病"] = 8

            # 3. 特殊天气事件
            if condition in ("沙尘暴", "霾", "浮尘"):
                modifiers["空气污染→呼吸道疾病"] = 25
            elif condition in ("雾", "扬沙"):
                modifiers["空气污染→呼吸道疾病"] = 12

            details["modifier_reasons"] = list(modifiers.keys())
    except Exception:  # 尽力而为，失败就算了
        _log.debug("天气风险 modifier 查询失败", exc_info=True)
        pass

    return {"details": details, "total_modifier": sum(modifiers.values()),
            "breakdown": modifiers}


# 3. 社区人流密度模型

def _get_community_density_risk() -> dict:
    """估社区人流聚集度 → 疾病传播风险。

    两层模型：
      1. 时间感知：一天中的时段 × 周几 → 分区域密度
         （单元楼、助餐点、活动室）
      2. 日历事件：季节性高峰、换季、假期返程
    """
    now = datetime.now()
    month = now.month
    day = now.day
    hour = now.hour
    weekday = now.weekday()  # 0=周一 ... 6=周日
    is_weekend = weekday >= 5

    density_score = 0
    reasons: list[str] = []

    # 第1层：时段 × 星期几 的密度

    if is_weekend:
        # 周末：整体松弛，但单元楼/活动室还有人
        if 9 <= hour < 12:
            density_score += 5
            reasons.append("周末上午，活动室中等密集")
        elif 12 <= hour < 13:
            density_score += 6
            reasons.append("周末午餐时段，助餐点中等密集")
        elif 13 <= hour < 18:
            density_score += 4
            reasons.append("周末下午，小区整体人流分散")
        elif 18 <= hour < 19:
            density_score += 5
            reasons.append("周末晚餐时段")
        elif 19 <= hour < 22:
            density_score += 5
            reasons.append("周末晚间，楼栋区活跃")
        else:
            density_score += 2
            reasons.append("周末深夜，小区低密度")
    else:
        # 工作日：跟着上下班节奏走
        if 7 <= hour < 8:
            density_score += 8
            reasons.append("早高峰，单元楼/助餐点人流集中")
        elif 8 <= hour < 12:
            density_score += 12
            reasons.append("上午时段，单元楼人员密集")
        elif 12 <= hour < 13:
            density_score += 10
            reasons.append("午餐高峰，助餐点人员高度密集")
        elif 13 <= hour < 14:
            density_score += 6
            reasons.append("午休时段，人员分散")
        elif 14 <= hour < 17:
            density_score += 12
            reasons.append("下午时段，单元楼人员密集")
        elif 17 <= hour < 18:
            density_score += 8
            reasons.append("休闲活动，社区人流中等")
        elif 18 <= hour < 19:
            density_score += 10
            reasons.append("晚餐高峰，助餐点人员密集")
        elif 19 <= hour < 22:
            density_score += 10
            reasons.append("晚间休闲活动，活动室/单元楼中等密集")
        elif 22 <= hour < 24:
            density_score += 6
            reasons.append("晚间，楼栋区活跃")
        else:
            density_score += 2
            reasons.append("深夜，小区低密度")

    # 工作日高峰时段加一点
    if not is_weekend:
        # 周一早高峰，全小区都动起来
        if weekday == 0 and 7 <= hour < 12:
            density_score += 3
            reasons.append("周一早高峰，全小区人流集中")

    # 第2层：日历事件（季节高峰等）

    # 季节性人流高峰（冬季流感 / 夏季过渡）
    peak_windows = [
        ((12, 25), (1, 10)),   # 冬季高峰
        ((6, 20), (7, 5)),     # 夏季高峰
    ]
    for (sm, sd), (em, ed) in peak_windows:
        if (month == sm and day >= sd) or (month == em and day <= ed):
            density_score += 15
            reasons.append("流感高发季，活动室/单元楼人员高度密集")
            break

    # 高峰前两周的爬坡期
    pre_peak_windows = [
        ((12, 10), (1, 10)),   # 冬季爬坡+高峰
        ((6, 5), (7, 5)),      # 夏季爬坡+高峰
    ]
    in_peak = False
    for (sm, sd), (em, ed) in peak_windows:
        if (month == sm and day >= sd) or (month == em and day <= ed):
            in_peak = True
            break
    if not in_peak:
        for (sm, sd), (em, ed) in pre_peak_windows:
            if (month == sm and day >= sd) or (month == em and day <= ed):
                density_score += 8
                reasons.append("换季时节，活动室人员密集")
                break

    # 换季过渡
    if (month == 9 and 1 <= day <= 15) or (month == 2 and 20 <= day <= 28):
        density_score += 10
        reasons.append("换季时节，人员流动频繁")

    # 长假返程（国庆、五一）
    if (month == 10 and 5 <= day <= 10) or (month == 5 and 1 <= day <= 7):
        density_score += 5
        reasons.append("长假返程，人员流动增加")

    # 封顶 30 分
    density_score = min(30, density_score)

    return {"score": density_score, "reasons": reasons}


# 4. 健康风险引擎：汇总所有信号

class HealthRiskEngine:
    """把季节、天气、社区密度三类信号汇总成风险分。"""

    def __init__(self):
        self.now = datetime.now()
        self.month = self.now.month
        self.weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][self.now.weekday()]

    def evaluate(self) -> dict:
        """跑一遍完整评估 — 返回结构化风险报告。

        Returns:
            {
                "overall_level": "low" | "moderate" | "high" | "critical",
                "overall_score": 0-100,
                "diseases": [...],
                "weather_modifiers": {...},
                "community_density": {...},
                "alerts": [...],
                "advice_summary": str,
            }
        """
        # 第1层：季节基线
        seasonal = get_seasonal_diseases(self.month)

        # 第2层：天气修正
        weather = _get_weather_risk_modifiers()

        # 第3层：社区密度
        density = _get_community_density_risk()

        # 逐病种算风险
        # v2：季节模型和国家真实监测数据融合，监测权重 0.6（六成真实、四成先验）。
        #     监测表是空的就退回纯季节模型。
        try:
            from data.db_surveillance import blend_risk as _blend, seed_surveillance as _seed_surv
            _seed_surv(force=True)  # 强制重灌，好让新增的病名生效
            _use_surveillance = True
        except Exception:
            _log.debug("加载 surveillance 模块失败，退回纯季节模型", exc_info=True)
            _use_surveillance = False

        diseases = []
        total_risk = 0
        for d in seasonal:
            # 第1步：拿到数据驱动的基础风险（和监测数据融合过）
            if _use_surveillance:
                blended_base, surv_meta = _blend(d["name"], d["base_risk"], surveillance_weight=0.6)
            else:
                blended_base = d["base_risk"]
                surv_meta = {"surveillance_available": False}

            # 第2步：叠加上天气和密度修正
            adjusted = blended_base + weather["total_modifier"] + density["score"]
            adjusted = max(0, min(100, adjusted))
            diseases.append({
                "name": d["name"],
                "base_risk": d["base_risk"],
                "blended_base_risk": round(blended_base, 1),  # 融合监测数据后的基础风险
                "adjusted_risk": adjusted,
                "symptoms": d["symptoms"],
                "advice": d["advice"],
                "season": d["season"],
                "surveillance": surv_meta,  # 里面带 trend_risk、方向、数据来源
            })
            total_risk += adjusted

        # 总分（加权平均，封顶）
        n = len(diseases) or 1
        overall = round(sum(d["adjusted_risk"] for d in diseases) / n)

        # 风险等级
        if overall >= 70:
            level, emoji, color = "critical", "🔴", "danger"
        elif overall >= 50:
            level, emoji, color = "high", "🟠", "warning"
        elif overall >= 30:
            level, emoji, color = "moderate", "🟡", "warning"
        else:
            level, emoji, color = "low", "🟢", "success"

        # 取风险最高的几条告警
        top_diseases = sorted(diseases, key=lambda x: -x["adjusted_risk"])[:3]
        alerts = [
            {
                "title": f"{d['name']}风险{d['adjusted_risk']}分",
                "message": f"症状：{d['symptoms']}。{d['advice']}",
                "emoji": "🤒" if d["adjusted_risk"] >= 60 else "😷" if d["adjusted_risk"] >= 40 else "💊",
                "level": "critical" if d["adjusted_risk"] >= 70 else "high" if d["adjusted_risk"] >= 50 else "moderate",
            }
            for d in top_diseases
        ]

        # 建议汇总
        advice_parts = []
        if weather["total_modifier"] >= 15:
            advice_parts.append("🌡️ 近期天气变化较大，注意增减衣物")
        if density["score"] >= 10:
            advice_parts.append("👥 人员密集期，建议佩戴口罩、勤洗手")
        if level in ("high", "critical"):
            advice_parts.append("⚠️ 请各网格员转发健康提醒给居民")
        if any(d["adjusted_risk"] >= 50 for d in diseases):
            advice_parts.append("💉 建议未接种流感疫苗的居民尽快接种")

        advice_summary = "；".join(advice_parts) if advice_parts else "🌿 当前社区健康风险较低，保持良好卫生习惯即可。"

        # 监测数据来源备注
        surv_summary = {}
        try:
            from data.db_surveillance import get_surveillance_summary as _surv_summary
            surv_summary = _surv_summary()
            if surv_summary.get("available") and not advice_parts:
                pass  # 风险低，不用额外建议
        except Exception:
            _log.debug("加载 surveillance 摘要失败", exc_info=True)
            surv_summary = {"available": False}

        return {
            "overall_level": level,
            "overall_emoji": emoji,
            "overall_color": color,
            "overall_score": overall,
            "diseases": diseases,
            "top_alerts": alerts,
            "weather_details": weather["details"],
            "weather_mod_total": weather["total_modifier"],
            "weather_breakdown": weather["breakdown"],
            "community_density": density,
            "advice_summary": advice_summary,
            "surveillance": surv_summary,       # 疾控数据状态
            "source_note": "基于国家疾控局月度公报（近似值） × 季节模型 × 实时天气模拟 · 仅供参考，不构成医疗建议",
            "evaluated_at": self.now.strftime("%Y-%m-%d %H:%M"),
            "weekday": self.weekday,
        }

    def active_alerts(self) -> list[dict]:
        """只返回超过 moderate 阈值的告警，给通知角标用。"""
        report = self.evaluate()
        return [a for a in report["top_alerts"] if a["adjusted_risk"] >= 40]

    def risk_badge_html(self) -> str:
        """返回一个内联 HTML 徽章，给侧边栏/页头展示。"""
        report = self.evaluate()
        emoji = report["overall_emoji"]
        level_cn = {"low": "低风险", "moderate": "注意", "high": "警示", "critical": "高危"}
        label = level_cn.get(report["overall_level"], "—")
        return (
            f'<span style="font-size:0.78em;padding:2px 10px;border-radius:99px;'
            f'font-weight:600;white-space:nowrap;">'
            f'{emoji} 健康·{label}</span>'
        )


# 5. 便捷缓存函数

def cached_health_risk() -> dict:
    """健康风险评估。名字保留给老代码用——其实已经不做缓存了。"""
    engine = HealthRiskEngine()
    return engine.evaluate()
