# data/db_health_alerts.py
"""🏥 疾病防治引擎 — 季节模型 + 天气关联 + 校园密度 + 风险评分.

  数据来源与模拟说明 / Data Provenance:
  ─────────────────────────────────────────────────────────────────
  本模块生成的是模拟/估计数据 (simulated/estimated data)，不是真实流行病学报告。
  风险评分基于三层模型叠加：
    1. 季节先验 — 基于国家疾控局月度公报 (CDC monthly bulletins) 中公布的
       中国北方地区季节性传染病流行趋势，提取各月份疾病基线风险。
    2. 天气关联 — 温度骤降、湿度变化、空气质量事件与呼吸道/胃肠道疾病
       发病率的已知统计相关性。
    3. 校园密度 — 考试周、开学季等人员聚集场景下的传播风险推断。
  综合风险评分 = 季节基线 × 天气修正 + 密度修正 → 4级风险等级。

  ⚠️ 重要提示：本模块输出仅供参考，不构成医疗建议。
  ⚠️ IMPORTANT: This module produces simulated risk estimates based on
     public health bulletins + seasonal models + weather correlation.
     It is NOT real epidemiological surveillance data and must NOT be
     used for clinical or public-health decision-making.

Architecture:
  SeasonModel       — month-based disease risk priors (northern China)
  WeatherCorrelator — temperature-drop / humidity triggers
  CampusDensity     — exam weeks, event density → transmission risk
  HealthRiskEngine  — aggregates above into 4-tier risk levels

Usage:
  from data.db_health_alerts import HealthRiskEngine
  engine = HealthRiskEngine()
  risk = engine.evaluate()          # full evaluation
  alerts = engine.active_alerts()   # only alerts above threshold
"""
import json
import logging
from datetime import datetime
from data.database import get_db

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 1. Season Model — month-based priors for northern China
# ═══════════════════════════════════════════════════════════

_SEASON_DISEASES = {
    # (start_month, end_month): [(disease, base_risk_0_to_100, symptoms, advice)]
    (11, 3): [
        ("甲型流感", 75, "高热、咳嗽、咽痛、全身酸痛、乏力",
         "建议接种流感疫苗，教室每日通风，出现症状及时就医并佩戴口罩"),
        ("乙型流感", 45, "发热、咳嗽、咽痛、肌肉酸痛、乏力",
         "症状通常较甲流轻，但仍需注意休息、多饮水、及时就医"),
        ("呼吸道感染", 60, "鼻塞、流涕、咳嗽、低热",
         "注意保暖，多喝温水，避免长时间待在密闭空调房"),
        ("诺如病毒感染", 40, "呕吐、腹泻、腹痛",
         "注意手部卫生，不共用餐具，食堂加强食品安全管理"),
    ],
    (3, 5): [
        ("过敏性鼻炎", 55, "打喷嚏、流清涕、鼻痒、眼痒",
         "花粉季减少户外活动，关闭宿舍窗户，必要时使用抗过敏药物"),
        ("过敏性哮喘", 20, "喘息、胸闷、咳嗽",
         "随身携带药物，避免接触花粉和粉尘，出现喘息及时就医"),
        ("水痘", 30, "发热、皮疹、瘙痒",
         "春季为水痘高发期，注意个人卫生，出现皮疹立即就医并隔离"),
    ],
    (6, 9): [
        ("急性胃肠炎", 50, "恶心、呕吐、腹痛、腹泻",
         "注意饮食卫生，不食用来历不明外卖，食堂加强冷链管理"),
        ("中暑", 45, "头晕、恶心、大量出汗或皮肤干热",
         "避免高温时段户外活动，多饮水，宿舍保持通风"),
        ("登革热", 10, "高热、头痛、肌肉关节痛、皮疹",
         "清理积水、防蚊灭蚊，南方校区需特别注意"),
    ],
    (9, 11): [
        ("季节性流感（秋冬季）", 65, "含甲型/乙型流感，突发高热、咳嗽、咽痛、肌肉酸痛",
         "接种流感疫苗是最佳预防手段，教室每日通风30分钟以上"),
        ("普通感冒", 50, "鼻塞、流涕、打喷嚏、轻微咽痛",
         "注意天气变化及时增减衣物，保持充足睡眠增强免疫力"),
    ],
}


def _month_in_range(month: int, start: int, end: int) -> bool:
    """Check if month falls in [start, end] range, wrapping across year boundary."""
    if start <= end:
        return start <= month <= end
    else:
        return month >= start or month <= end


def get_seasonal_diseases(month: int | None = None) -> list[dict]:
    """Return disease risks active for the given month (default: now)."""
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


# ═══════════════════════════════════════════════════════════
# 2. Weather Correlator
# ═══════════════════════════════════════════════════════════

def _get_weather_risk_modifiers() -> dict:
    """Fetch current weather and compute disease risk modifiers.

    Returns dict with keys: temp_drop, humidity, air_quality, modifiers
    Each modifier is a delta added to base risk (positive = higher risk).
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

            # 1. Temperature risk: large temp drop → flu/flu susceptibility ↑
            #    Also: extreme cold (<5°C) or extreme heat (>35°C) raises baseline
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

            # 2. Humidity risk: high humidity → mold / respiratory
            if rain_prob >= 80:
                modifiers["高湿预警→呼吸道疾病"] = 15
            elif rain_prob >= 60:
                modifiers["湿度偏高→呼吸道疾病"] = 8

            # 3. Specific weather events
            if condition in ("沙尘暴", "霾", "浮尘"):
                modifiers["空气污染→呼吸道疾病"] = 25
            elif condition in ("雾", "扬沙"):
                modifiers["空气污染→呼吸道疾病"] = 12

            details["modifier_reasons"] = list(modifiers.keys())
    except Exception:  # non-critical: silent pass intended
        _log.debug("Weather risk modifier query failed", exc_info=True)
        pass

    return {"details": details, "total_modifier": sum(modifiers.values()),
            "breakdown": modifiers}


# ═══════════════════════════════════════════════════════════
# 3. Campus Density Model
# ═══════════════════════════════════════════════════════════

def _get_campus_density_risk() -> dict:
    """Estimate campus crowding → disease transmission risk.

    Two-layer model:
      1. Time-aware: hour-of-day × day-of-week → zone-based density
         (teaching buildings, canteens, library, dorms)
      2. Calendar events: exam periods, semester start, holiday returns
    """
    now = datetime.now()
    month = now.month
    day = now.day
    hour = now.hour
    weekday = now.weekday()  # 0=Mon ... 6=Sun
    is_weekend = weekday >= 5

    density_score = 0
    reasons: list[str] = []

    # ═══════════════════════════════════════════════
    # Layer 1: Time-of-day × Day-of-week density
    # ═══════════════════════════════════════════════

    if is_weekend:
        # Weekend: relaxed but dorms + library still active
        if 9 <= hour < 12:
            density_score += 5
            reasons.append("周末上午，图书馆/自习室中等密集")
        elif 12 <= hour < 13:
            density_score += 6
            reasons.append("周末午餐时段，食堂中等密集")
        elif 13 <= hour < 18:
            density_score += 4
            reasons.append("周末下午，校园整体人流分散")
        elif 18 <= hour < 19:
            density_score += 5
            reasons.append("周末晚餐时段")
        elif 19 <= hour < 22:
            density_score += 5
            reasons.append("周末晚间，宿舍区活跃")
        else:
            density_score += 2
            reasons.append("周末深夜，校园低密度")
    else:
        # Weekday: follows class schedule
        if 7 <= hour < 8:
            density_score += 8
            reasons.append("早高峰，教学楼/食堂人流集中")
        elif 8 <= hour < 12:
            density_score += 12
            reasons.append("上午课程时段，教学楼人员密集")
        elif 12 <= hour < 13:
            density_score += 10
            reasons.append("午餐高峰，食堂人员高度密集")
        elif 13 <= hour < 14:
            density_score += 6
            reasons.append("午休时段，人员分散")
        elif 14 <= hour < 17:
            density_score += 12
            reasons.append("下午课程时段，教学楼人员密集")
        elif 17 <= hour < 18:
            density_score += 8
            reasons.append("课间活动，校园人流中等")
        elif 18 <= hour < 19:
            density_score += 10
            reasons.append("晚餐高峰，食堂人员密集")
        elif 19 <= hour < 22:
            density_score += 10
            reasons.append("晚间自习，图书馆/教室中等密集")
        elif 22 <= hour < 24:
            density_score += 6
            reasons.append("晚间，宿舍区活跃")
        else:
            density_score += 2
            reasons.append("深夜，校园低密度")

    # Weekday bonus for known high-traffic times
    if not is_weekend:
        # Monday morning = class start, full campus
        if weekday == 0 and 7 <= hour < 12:
            density_score += 3
            reasons.append("周一早高峰，全校满课")

    # ═══════════════════════════════════════════════
    # Layer 2: Calendar events (exam periods, etc.)
    # ═══════════════════════════════════════════════

    # Exam periods (approximate for Chinese universities)
    exam_windows = [
        ((12, 25), (1, 10)),   # fall semester finals
        ((6, 20), (7, 5)),     # spring semester finals
    ]
    for (sm, sd), (em, ed) in exam_windows:
        if (month == sm and day >= sd) or (month == em and day <= ed):
            density_score += 15
            reasons.append("考试周，图书馆/教室人员高度密集")
            break

    # Pre-exam crunch (2 weeks before exams)
    pre_exam_windows = [
        ((12, 10), (1, 10)),   # fall pre+exam
        ((6, 5), (7, 5)),      # spring pre+exam
    ]
    in_exam = False
    for (sm, sd), (em, ed) in exam_windows:
        if (month == sm and day >= sd) or (month == em and day <= ed):
            in_exam = True
            break
    if not in_exam:
        for (sm, sd), (em, ed) in pre_exam_windows:
            if (month == sm and day >= sd) or (month == em and day <= ed):
                density_score += 8
                reasons.append("期末备考期，自习场所人员密集")
                break

    # Beginning of semester
    if (month == 9 and 1 <= day <= 15) or (month == 2 and 20 <= day <= 28):
        density_score += 10
        reasons.append("开学季，人员流动频繁")

    # Holiday returns (National Day, May Day)
    if (month == 10 and 5 <= day <= 10) or (month == 5 and 1 <= day <= 7):
        density_score += 5
        reasons.append("长假返校，人员流动增加")

    # Cap at 30
    density_score = min(30, density_score)

    return {"score": density_score, "reasons": reasons}


# ═══════════════════════════════════════════════════════════
# 4. Health Risk Engine — aggregates all signals
# ═══════════════════════════════════════════════════════════

class HealthRiskEngine:
    """Aggregate seasonal, weather, and campus-density signals into risk scores."""

    def __init__(self):
        self.now = datetime.now()
        self.month = self.now.month
        self.weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][self.now.weekday()]

    def evaluate(self) -> dict:
        """Run full evaluation — returns a structured risk report.

        Returns:
            {
                "overall_level": "low" | "moderate" | "high" | "critical",
                "overall_score": 0-100,
                "diseases": [...],
                "weather_modifiers": {...},
                "campus_density": {...},
                "alerts": [...],
                "advice_summary": str,
            }
        """
        # ── Layer 1: Seasonal baseline
        seasonal = get_seasonal_diseases(self.month)

        # ── Layer 2: Weather modifiers
        weather = _get_weather_risk_modifiers()

        # ── Layer 3: Campus density
        density = _get_campus_density_risk()

        # ── Compute per-disease risk ──
        # v2: Blend seasonal model with real national surveillance data.
        #     Surveillance weight = 0.6 (60% real data, 40% season prior).
        #     Falls back to pure season model if surveillance table is empty.
        try:
            from data.db_surveillance import blend_risk as _blend, seed_surveillance as _seed_surv
            _seed_surv()  # idempotent — only seeds if empty
            _use_surveillance = True
        except Exception:
            _log.debug("Failed to load surveillance module, using season-only model", exc_info=True)
            _use_surveillance = False

        diseases = []
        total_risk = 0
        for d in seasonal:
            # ── Step 1: Get data-driven base risk (blended with surveillance) ──
            if _use_surveillance:
                blended_base, surv_meta = _blend(d["name"], d["base_risk"], surveillance_weight=0.6)
            else:
                blended_base = d["base_risk"]
                surv_meta = {"surveillance_available": False}

            # ── Step 2: Apply weather + density modifiers on top ──
            adjusted = blended_base + weather["total_modifier"] + density["score"]
            adjusted = max(0, min(100, adjusted))
            diseases.append({
                "name": d["name"],
                "base_risk": d["base_risk"],
                "blended_base_risk": round(blended_base, 1),  # after surveillance blend
                "adjusted_risk": adjusted,
                "symptoms": d["symptoms"],
                "advice": d["advice"],
                "season": d["season"],
                "surveillance": surv_meta,  # contains trend_risk, direction, data source
            })
            total_risk += adjusted

        # ── Overall score (weighted average, capped)
        n = len(diseases) or 1
        overall = round(sum(d["adjusted_risk"] for d in diseases) / n)

        # ── Risk level
        if overall >= 70:
            level, emoji, color = "critical", "🔴", "danger"
        elif overall >= 50:
            level, emoji, color = "high", "🟠", "warning"
        elif overall >= 30:
            level, emoji, color = "moderate", "🟡", "warning"
        else:
            level, emoji, color = "low", "🟢", "success"

        # ── Top alerts
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

        # ── Advice summary
        advice_parts = []
        if weather["total_modifier"] >= 15:
            advice_parts.append("🌡️ 近期天气变化较大，注意增减衣物")
        if density["score"] >= 10:
            advice_parts.append("🏫 人员密集期，建议佩戴口罩、勤洗手")
        if level in ("high", "critical"):
            advice_parts.append("⚠️ 请各班级辅导员转发健康提醒给学生")
        if any(d["adjusted_risk"] >= 50 for d in diseases):
            advice_parts.append("💉 建议未接种流感疫苗的同学尽快接种")

        advice_summary = "；".join(advice_parts) if advice_parts else "🌿 当前校园健康风险较低，保持良好卫生习惯即可。"

        # ── Surveillance data source note ──
        surv_summary = {}
        try:
            from data.db_surveillance import get_surveillance_summary as _surv_summary
            surv_summary = _surv_summary()
            if surv_summary.get("available") and not advice_parts:
                pass  # low risk, no extra advice needed
        except Exception:
            _log.debug("Failed to load surveillance summary", exc_info=True)
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
            "campus_density": density,
            "advice_summary": advice_summary,
            "surveillance": surv_summary,       # CDC data status
            "source_note": "基于国家疾控局月度公报 × 季节模型 × 实时天气模拟 · 仅供参考，不构成医疗建议",
            "evaluated_at": self.now.strftime("%Y-%m-%d %H:%M"),
            "weekday": self.weekday,
        }

    def active_alerts(self) -> list[dict]:
        """Return only alerts above the 'moderate' threshold, for notification badges."""
        report = self.evaluate()
        return [a for a in report["top_alerts"] if a["adjusted_risk"] >= 40]

    def risk_badge_html(self) -> str:
        """Return an inline HTML badge for sidebar / header display."""
        report = self.evaluate()
        emoji = report["overall_emoji"]
        level_cn = {"low": "低风险", "moderate": "注意", "high": "警示", "critical": "高危"}
        label = level_cn.get(report["overall_level"], "—")
        return (
            f'<span style="font-size:0.78em;padding:2px 10px;border-radius:99px;'
            f'font-weight:600;white-space:nowrap;">'
            f'{emoji} 健康·{label}</span>'
        )


# ═══════════════════════════════════════════════════════════
# 5. Cached convenience
# ═══════════════════════════════════════════════════════════

import streamlit as st


@st.cache_data(ttl=1800)  # 30 min cache — bump _V when data changes
def cached_health_risk(_cache_version: int = 2) -> dict:
    """Cached health risk evaluation — recomputes every 30 minutes."""
    engine = HealthRiskEngine()
    return engine.evaluate()
