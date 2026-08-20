# data/db_weather.py
"""天气模块数据层 —— 按《03-天气.md》实现缓存降级、极端天气预警、检查任务闭环。

表（schema v18）：
  weather_cache       天气缓存（缓存降级：保留上次成功数据）
  weather_alerts      极端天气预警（8 类，黄色及以上触发，红色加强）
  weather_check_tasks 负责人检查任务（3 小时确认 / 超时未确认可补填 / 超时升级通知）

状态机：
  weather_alerts.status      active → expired（预警解除自动关闭）
  weather_check_tasks.status 待检查 → 已确认 | 超时未确认（保留标记可补填）

约定：
  - 时间统一按 SQLite CURRENT_TIMESTAMP（UTC）口径，内部用 datetime.utcnow() 计算。
  - 所有关键操作（预警检测、提醒分发、缓存降级、超时升级、检查处理等）都走
    log_activity 留痕，module="天气"。
  - 居民查看天气仅记系统访问日志（record_weather_view），不进入业务留痕。
  - 「在线负责人」没有专门的在线表：escalate_overdue_tasks 接受 online_user_ids
    参数，不传时默认通知全部 grid 角色负责人（由 UI/监测端传入真实在线名单）。
"""
import json
import logging
import re
from datetime import datetime, timedelta

from data.db_core import get_db
from data.db_notifications import log_activity

_log = logging.getLogger(__name__)

MODULE = "天气"

# ---------- 极端天气 8 类与等级 ----------

ALERT_TYPES = ["暴雨", "台风", "高温", "寒潮", "大风", "雷电", "冰雹", "大雾"]
LEVELS = ["黄色", "橙色", "红色"]
_LEVEL_RANK = {"黄色": 1, "橙色": 2, "红色": 3}

# 触发时机：生效时间在未来 12 小时内立即触发；超过 12 小时不触发
ALERT_LEAD_HOURS = 12
# 检查任务确认时限（小时）
CHECK_HOURS = 3
# 缓存降级阈值（分钟）
CACHE_DELAY_MIN = 15
CACHE_DEGRADE_MIN = 30
# 升级通知去重窗口（分钟）：同任务在此窗口内不重复发通知，但任务保持最高优先级展示
ESCALATE_DEDUPE_MIN = 30

# 各天气类型检查清单（按《03-天气.md》：不同天气类型匹配具体检查清单）
CHECKLISTS: dict[str, list[str]] = {
    "暴雨": ["排水沟/雨水口是否畅通", "窨井盖是否完好无缺失", "低洼地带是否积水", "地下车库入口挡水设施", "户外广告牌/临时设施牢固度"],
    "台风": ["门窗是否关闭并加固", "阳台花盆/杂物是否收拢", "树木有无倒伏隐患", "广告牌/棚架是否牢固", "电力线路有无脱落风险"],
    "高温": ["户外作业人员防暑安排", "公共活动场所遮阳设施", "老人防暑物资是否到位", "社区饮水点/休息点状态"],
    "寒潮": ["供暖管道是否正常", "水管/水表防冻措施", "老人保暖物资是否到位", "公共区域门窗密封"],
    "大风": ["广告牌/横幅是否牢固", "临时搭建物是否加固", "树木有无断枝隐患", "高空坠物风险排查"],
    "雷电": ["避雷设施是否完好", "户外电子设备是否断电防护", "空旷区域警示牌状态"],
    "冰雹": ["车辆停放区域遮蔽情况", "玻璃/顶棚完好度", "户外设施有无损坏风险"],
    "大雾": ["道路标识/警示灯是否可见", "交通提示牌状态", "老人出行安全提醒落实"],
}

# 各天气类型提醒文案（专属文案，避免通用模板）
ALERT_TEXTS: dict[str, str] = {
    "暴雨": "暴雨天气，请尽量减少外出，远离低洼积水区域，注意出行安全。",
    "台风": "台风来袭，请关好门窗，收好阳台物品，非必要不外出。",
    "高温": "高温天气，注意防暑降温，多饮水，避免午后长时间户外活动。",
    "寒潮": "寒潮来袭，气温骤降，注意添衣保暖，做好防寒防冻措施。",
    "大风": "大风天气，注意高空坠物，远离广告牌和临时搭建物。",
    "雷电": "雷电天气，请远离空旷地带和高大树木，关闭不必要的电器。",
    "冰雹": "冰雹天气，请待在室内，关好门窗，车辆尽量停入遮蔽处。",
    "大雾": "大雾天气，能见度低，出行注意交通安全，老人尽量减少外出。",
}

# 预警默认持续时间（小时，规则检测生成时使用）
_ALERT_DURATION_HOURS = {
    "暴雨": 24, "台风": 36, "高温": 48, "寒潮": 48,
    "大风": 12, "雷电": 12, "冰雹": 6, "大雾": 12,
}

# 规则检测阈值（和风 API 无预警数据时按天气数据推断）
_RULE_LEVEL_THRESHOLDS = {
    "高温": {"红色": 40, "橙色": 37, "黄色": 35},   # 当日最高温（℃）
    "寒潮": {"红色": -15, "橙色": -10, "黄色": -5},  # 当日最低温（℃）
    "大风": {"红色": 11, "橙色": 9, "黄色": 6},      # 风力等级
    "暴雨": {"红色": 120, "橙色": 80, "黄色": 50},   # 降水概率（%）
}
_RED_CONDITIONS = ("特大暴雨", "超强台风", "强台风")
_ORANGE_CONDITIONS = ("大暴雨", "台风", "暴雨")


# ---------- 小工具 ----------

def _now() -> datetime:
    return datetime.utcnow()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _norm_ts(value) -> str:
    """把 datetime / 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM:SS' 统一成 UTC 时间字符串。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _fmt(value)
    s = str(value).strip()
    if not s:
        return ""
    if len(s) == 10:  # 日期 → 当天 0 点
        return f"{s} 00:00:00"
    return s


def _expire_cutoff(value) -> str:
    """日期只给到天的有效期，按当天 23:59:59 处理（当天仍有效，次日过期）。"""
    s = _norm_ts(value)
    if not s:
        return ""
    if len(s) == 10:
        return f"{s} 23:59:59"
    return s


def _parse_wind_scale(wind: str) -> int:
    """从 '北风 5级' / '东北风 3-4级' 解析最大风力等级。"""
    m = re.search(r"(\d+)\s*[-~至]?\s*(\d+)?\s*级", wind or "")
    if not m:
        return 0
    return int(m.group(2) if m.group(2) else m.group(1))


def _level_rank(level: str) -> int:
    return _LEVEL_RANK.get(level or "", 0)


def _level_label(rank: int) -> str:
    for level, r in _LEVEL_RANK.items():
        if r == rank:
            return level
    return "黄色"


# ============================================================
# 一、天气缓存读写（缓存降级）
# ============================================================

def save_weather_cache(city: str, days: list[dict], location: str = "",
                       extra: dict | None = None) -> int:
    """保存一次成功的天气数据（缓存降级用）。返回缓存行 ID。"""
    payload = {
        "days": days,
        "location": location,
        "saved_at": _fmt(_now()),
    }
    if extra:
        payload.update(extra)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM weather_cache WHERE city=? ORDER BY updated_at DESC LIMIT 1",
            (city or "",),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE weather_cache SET data_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), row["id"]),
            )
            cache_id = row["id"]
        else:
            cur = conn.execute(
                "INSERT INTO weather_cache (city, data_json) VALUES (?, ?)",
                (city or "", json.dumps(payload, ensure_ascii=False)),
            )
            cache_id = cur.lastrowid
        conn.commit()
    return cache_id


def get_cached_weather(city: str = "") -> dict | None:
    """取上次成功的天气缓存。返回 {city, data_json, updated_at, days, location} 或 None。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM weather_cache WHERE city=? ORDER BY updated_at DESC LIMIT 1",
            (city or "",),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            payload = json.loads(d.get("data_json") or "{}")
        except (ValueError, TypeError):
            payload = {}
        d["days"] = payload.get("days") or []
        d["location"] = payload.get("location") or ""
        d["saved_at"] = payload.get("saved_at") or d.get("updated_at") or ""
        return d


def _fetch_days(city: str = "") -> tuple[list[dict] | None, str, bool]:
    """取天气数据（真实 API 优先，失败退回模拟）。返回 (days, location, is_real)。"""
    try:
        from tools.query_weather import get_today_weather
        days, location, is_real = get_today_weather()
        return days, location, bool(is_real)
    except Exception:
        _log.warning("获取天气数据失败", exc_info=True)
        return None, "", False


def refresh_weather(city: str = "") -> dict:
    """刷新天气：真实成功 → 写缓存 + 留痕；失败 → 读缓存降级；无缓存 → 返回不可用。

    返回：
      {
        "days": [...], "location": str, "is_real": bool,
        "is_degraded": bool, "is_mock": bool,
        "data_updated_at": str, "note": str,
      }
    """
    days, location, is_real = _fetch_days(city)
    if days is not None and is_real:
        save_weather_cache(city, days, location)
        log_activity("系统", "天气数据更新", "weather_cache", module=MODULE,
                     detail=f"社区天气数据获取成功（{location or city}）")
        return {
            "days": days, "location": location, "is_real": True,
            "is_degraded": False, "is_mock": False,
            "data_updated_at": _fmt(_now()),
            "note": "",
        }
    if days is not None:
        # 真实 API 失败，退回模拟数据（不写缓存；缓存只存"上次成功"的真实数据）
        return {
            "days": days, "location": location, "is_real": False,
            "is_degraded": False, "is_mock": True,
            "data_updated_at": "",
            "note": "天气API请求失败，已切换为模拟数据",
        }
    cache = get_cached_weather(city)
    if cache and cache.get("days"):
        log_activity("系统", "缓存降级", "weather_cache", module=MODULE,
                     detail=f"天气API故障，使用缓存数据（更新于{cache['updated_at']}）")
        return {
            "days": cache["days"], "location": cache.get("location", ""),
            "is_real": False, "is_degraded": True, "is_mock": False,
            "data_updated_at": cache.get("updated_at") or "",
            "note": f"数据更新于{cache.get('updated_at') or ''}，当前不可用",
        }
    return {
        "days": None, "location": "", "is_real": False,
        "is_degraded": True, "is_mock": False,
        "data_updated_at": "", "note": "天气数据不可用",
    }


def _cache_age_minutes(city: str = "") -> int | None:
    cache = get_cached_weather(city)
    if not cache or not cache.get("updated_at"):
        return None
    try:
        updated = datetime.strptime(cache["updated_at"], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    return int((_now() - updated).total_seconds() // 60)


def check_cache_freshness(city: str = "") -> dict:
    """数据更新时间戳监测：>15 分钟提示延迟；>30 分钟按 API 故障处理（缓存降级）。

    状态变化才留痕，避免每轮监测刷日志。
    """
    age = _cache_age_minutes(city)
    state = "fresh"
    note = ""
    if age is None:
        return {"state": "no_cache", "age_minutes": None, "note": "暂无缓存数据"}
    if age > CACHE_DEGRADE_MIN:
        state = "degraded"
        note = f"天气数据超过{CACHE_DEGRADE_MIN}分钟未更新，已按API故障处理，启动缓存降级"
        _log_once("缓存降级", f"{note}（更新于{age}分钟前）", "weather_cache", "故障")
    elif age > CACHE_DELAY_MIN:
        state = "delayed"
        note = "天气数据可能延迟"
        _log_once("天气数据延迟", f"数据超过{CACHE_DELAY_MIN}分钟未更新，页面提示延迟", "weather_cache", "异常")
    return {"state": state, "age_minutes": age, "note": note}


def _log_once(action: str, detail: str, target_type: str, target_id) -> None:
    """同一天同类日志只记一次（监测类日志防刷屏）。"""
    today = _fmt(_now())[:10]
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM activity_log WHERE module=? AND action=? AND target_type=? "
            "AND substr(created_at,1,10)=? ORDER BY id DESC LIMIT 1",
            (MODULE, action, target_type, today),
        ).fetchone()
    if row:
        return
    log_activity("系统", action, target_type, module=MODULE, detail=detail)


def get_weather_for_display(city: str = "") -> dict:
    """统一展示入口：先尝试刷新，失败走缓存降级；附加延迟/降级状态。"""
    result = refresh_weather(city)
    freshness = check_cache_freshness(city)
    if freshness["state"] in ("delayed", "degraded"):
        result["delay"] = freshness["state"] == "delayed"
        result["degraded"] = freshness["state"] == "degraded"
        if not result.get("note"):
            result["note"] = freshness["note"]
    else:
        result["delay"] = False
        result["degraded"] = False
    return result


def get_daily_advice(force: bool = False, city: str = "") -> dict:
    """穿衣/出行建议：按当天天气自动生成，每天生成一次，不使用 AI 自由发挥。"""
    today = _fmt(_now())[:10]
    # 已生成过就直接返回（幂等；force=True 强制重算）
    with get_db() as conn:
        row = conn.execute(
            "SELECT detail FROM activity_log WHERE module=? AND action=? "
            "AND substr(created_at,1,10)=? ORDER BY id DESC LIMIT 1",
            (MODULE, "生成穿衣出行建议", today),
        ).fetchone()
        if row and not force:
            try:
                return json.loads(row["detail"] or "{}")
            except (ValueError, TypeError):
                pass

    result = refresh_weather(city)
    days = result.get("days") or []
    advice = {"date": today, "dress": "", "travel": "", "generated_at": _fmt(_now())}
    if days:
        d = days[0]
        cond = d.get("condition", "")
        high = d.get("temp_high", 0)
        low = d.get("temp_low", 0)
        try:
            high, low = int(high), int(low)
        except (TypeError, ValueError):
            high, low = 0, 0
        # 穿衣建议（规则生成）
        if high >= 35:
            advice["dress"] = "天气炎热，建议穿轻薄透气的短袖衣物，外出注意防晒。"
        elif low <= 5:
            advice["dress"] = "天气寒冷，建议穿羽绒服、棉衣等厚外套，注意保暖。"
        elif high >= 25:
            advice["dress"] = "天气较暖，建议穿单层长袖或薄外套。"
        elif high >= 15:
            advice["dress"] = "天气舒适，建议穿长袖衣裤，早晚可加薄外套。"
        else:
            advice["dress"] = "天气偏凉，建议穿夹克、毛衣等保暖衣物。"
        # 出行建议（规则生成）
        if cond in ("暴雨", "雷阵雨", "冰雹", "台风"):
            advice["travel"] = "极端天气，尽量避免外出，注意安全。"
        elif cond in ("大雨", "中雨", "小雨"):
            advice["travel"] = "有降水，出行记得带伞，注意路面湿滑。"
        elif cond in ("雾", "霾", "大雾"):
            advice["travel"] = "能见度较低，出行注意交通安全，建议佩戴口罩。"
        elif cond in ("大雪", "中雪", "小雪"):
            advice["travel"] = "路面可能结冰，出行注意防滑保暖。"
        elif high >= 35:
            advice["travel"] = "午后高温时段减少户外活动，注意补水防暑。"
        elif low <= 5:
            advice["travel"] = "早晚寒冷，出行注意添衣保暖。"
        else:
            advice["travel"] = "天气适宜出行。"
    log_activity("系统", "生成穿衣出行建议", "weather_cache", module=MODULE,
                 detail=json.dumps(advice, ensure_ascii=False))
    return advice


def get_simplified_weather(city: str = "") -> dict:
    """老年端大字版简化天气：只返回温度、天气现象、预警标签、一句建议。"""
    result = get_weather_for_display(city)
    days = result.get("days") or []
    d = days[0] if days else None
    alerts = get_active_alerts()
    return {
        "city": city or result.get("location", ""),
        "temp": d.get("temp_high") if d else None,
        "temp_low": d.get("temp_low") if d else None,
        "condition": d.get("condition", "") if d else "",
        "emoji": d.get("emoji", "") if d else "",
        "alert_tags": [{"type": a["alert_type"], "level": a["level"]} for a in alerts],
        "advice": (get_daily_advice(city=city).get("dress", "") or "")[:40],
        "updated_at": result.get("data_updated_at", ""),
        "is_degraded": result.get("is_degraded", False),
        "note": result.get("note", ""),
    }


def get_community_weather_overview(limit: int = 50) -> list[dict]:
    """负责人端所有社区天气概况：社区名、当前天气、温度、预警标签。

    预警为社区级（不分社区细分），每条城市行挂当前全部 active 预警标签。
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT city, data_json, updated_at FROM weather_cache "
            "ORDER BY updated_at DESC LIMIT ?", (limit,),
        ).fetchall()
    active_alerts = get_active_alerts()
    alert_tags = [{"type": a["alert_type"], "level": a["level"]} for a in active_alerts]
    overview = []
    for r in rows:
        try:
            payload = json.loads(r["data_json"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        days = payload.get("days") or []
        d = days[0] if days else None
        overview.append({
            "city": r["city"] or payload.get("location", ""),
            "condition": d.get("condition", "") if d else "",
            "temp_high": d.get("temp_high") if d else None,
            "temp_low": d.get("temp_low") if d else None,
            "alert_tags": alert_tags,
            "updated_at": r["updated_at"],
        })
    return overview


def record_weather_view(city: str = "") -> None:
    """居民查看天气：只记系统访问日志，不进入业务留痕（《03-天气.md》留痕规则）。"""
    _log.info("居民查看天气：%s @ %s", city or "默认社区", _fmt(_now()))


# ============================================================
# 二、极端天气预警检测（8 类，黄色及以上触发）
# ============================================================

def _infer_alert_from_day(d: dict, prev_high=None) -> list[dict]:
    """按当天天气数据推断极端天气（和风 API 预警缺失时的规则检测）。"""
    alerts: list[dict] = []
    cond = d.get("condition", "") or ""
    try:
        high = int(d.get("temp_high", 0) or 0)
        low = int(d.get("temp_low", 0) or 0)
    except (TypeError, ValueError):
        high = low = 0
    rain = int(d.get("rain_prob", 0) or 0)
    wind_scale = _parse_wind_scale(d.get("wind", ""))

    now = _now()

    # 暴雨（降水概率高或天气现象含"暴雨"）
    if "暴雨" in cond or rain >= _RULE_LEVEL_THRESHOLDS["暴雨"]["黄色"]:
        level = "红色" if rain >= _RULE_LEVEL_THRESHOLDS["暴雨"]["红色"] or cond in _RED_CONDITIONS \
            else "橙色" if rain >= _RULE_LEVEL_THRESHOLDS["暴雨"]["橙色"] or cond in _ORANGE_CONDITIONS \
            else "黄色"
        alerts.append({"alert_type": "暴雨", "level": level})

    # 台风
    if "台风" in cond:
        level = "红色" if cond in _RED_CONDITIONS else "橙色" if cond in _ORANGE_CONDITIONS else "黄色"
        alerts.append({"alert_type": "台风", "level": level})

    # 高温（黄色及以上）
    if high >= _RULE_LEVEL_THRESHOLDS["高温"]["黄色"]:
        level = "红色" if high >= _RULE_LEVEL_THRESHOLDS["高温"]["红色"] \
            else "橙色" if high >= _RULE_LEVEL_THRESHOLDS["高温"]["橙色"] else "黄色"
        alerts.append({"alert_type": "高温", "level": level})

    # 寒潮（低温或 24 小时降温 ≥8℃）
    temp_drop = (prev_high - high) if prev_high is not None else 0
    if low <= _RULE_LEVEL_THRESHOLDS["寒潮"]["黄色"] or temp_drop >= 8:
        level = "红色" if low <= _RULE_LEVEL_THRESHOLDS["寒潮"]["红色"] or temp_drop >= 12 \
            else "橙色" if low <= _RULE_LEVEL_THRESHOLDS["寒潮"]["橙色"] or temp_drop >= 10 \
            else "黄色"
        alerts.append({"alert_type": "寒潮", "level": level})

    # 大风
    if wind_scale >= _RULE_LEVEL_THRESHOLDS["大风"]["黄色"]:
        level = "红色" if wind_scale >= _RULE_LEVEL_THRESHOLDS["大风"]["红色"] \
            else "橙色" if wind_scale >= _RULE_LEVEL_THRESHOLDS["大风"]["橙色"] else "黄色"
        alerts.append({"alert_type": "大风", "level": level})

    # 雷电
    if "雷" in cond and "暴雨" not in cond:
        alerts.append({"alert_type": "雷电", "level": "黄色"})

    # 冰雹
    if "冰雹" in cond:
        alerts.append({"alert_type": "冰雹", "level": "黄色"})

    # 大雾
    if "雾" in cond or "霾" in cond:
        alerts.append({"alert_type": "大雾", "level": "黄色"})

    for a in alerts:
        a["effective_time"] = now
        a["expire_time"] = now + timedelta(hours=_ALERT_DURATION_HOURS.get(a["alert_type"], 24))
    return alerts


def fetch_hefeng_warnings() -> list[dict]:
    """尽力拉和风天气预警（/v7/warning/now）。失败返回 []，由规则检测兜底。"""
    try:
        import requests
        from config import HEFENG_API_HOST, HEFENG_API_KEY, COMMUNITY_CITY_ID
        if not HEFENG_API_KEY:
            return []
        api_host = HEFENG_API_HOST or "devapi.qweather.com"
        resp = requests.get(
            f"https://{api_host}/v7/warning/now",
            params={"location": COMMUNITY_CITY_ID, "key": HEFENG_API_KEY},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != "200":
            return []
        warnings = []
        for w in data.get("warning") or []:
            type_name = (w.get("typeName") or "").strip()
            level = (w.get("level") or "").strip()
            alert_type = next((t for t in ALERT_TYPES if t in type_name), "")
            if not alert_type or level not in LEVELS:
                continue
            warnings.append({
                "alert_id": str(w.get("id") or ""),
                "alert_type": alert_type,
                "level": level,
                "title": (w.get("title") or ""),
                "effective_time": _norm_ts(w.get("startTime")),
                "expire_time": _norm_ts(w.get("endTime")) or _fmt(_now() + timedelta(
                    hours=_ALERT_DURATION_HOURS.get(alert_type, 24))),
            })
        return warnings
    except Exception:
        _log.debug("和风预警接口请求失败，退回规则检测", exc_info=True)
        return []


def detect_extreme_weather(days: list[dict] | None = None, city: str = "") -> list[dict]:
    """极端天气预警检测：和风 API 预警优先，无则按天气数据规则推断。

    返回标准化预警列表：
      {alert_id, alert_type, level, effective_time, expire_time}
    """
    # 1) 和风官方预警
    warnings = fetch_hefeng_warnings()
    if warnings:
        return warnings

    # 2) 规则检测（用今天的天气 + 昨天缓存的高温算 24h 降温）
    if days is None:
        result = get_weather_for_display(city)
        days = result.get("days") or []
    if not days:
        return []
    prev_high = None
    cache = get_cached_weather(city)
    if cache and cache.get("days"):
        prev = cache["days"][0]
        try:
            prev_high = int(prev.get("temp_high", 0) or 0)
        except (TypeError, ValueError):
            prev_high = None
    return _infer_alert_from_day(days[0], prev_high=prev_high)


def _insert_alert(conn, alert: dict) -> int | None:
    """插入预警（同类型 + 同生效日去重）。返回预警 ID 或 None（已存在）。"""
    effective = _norm_ts(alert.get("effective_time"))
    expire = _norm_ts(alert.get("expire_time"))
    alert_type = alert.get("alert_type", "")
    alert_id = alert.get("alert_id", "")
    dup = conn.execute(
        "SELECT id FROM weather_alerts WHERE alert_type=? AND status='active' "
        "AND substr(effective_time,1,10)=? LIMIT 1",
        (alert_type, effective[:10] if effective else ""),
    ).fetchone()
    if dup:
        return None
    cur = conn.execute(
        "INSERT INTO weather_alerts (alert_id, alert_type, level, effective_time, expire_time, status) "
        "VALUES (?, ?, ?, ?, ?, 'active')",
        (alert_id, alert_type, alert.get("level", "黄色"), effective, expire),
    )
    return cur.lastrowid


def trigger_pending_alerts(city: str = "") -> list[dict]:
    """对"生效时间在未来 12 小时内"的 active 预警触发提醒（居民滚动/负责人任务/老年播报）。

    幂等：已触发过的预警不重复触发（按留痕判断）。返回本次触发的预警列表。
    """
    now = _now()
    cutoff = _fmt(now + timedelta(hours=ALERT_LEAD_HOURS))
    triggered: list[dict] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM weather_alerts WHERE status='active' "
            "AND effective_time!='' AND effective_time<=? AND (expire_time='' OR expire_time>=?) "
            "ORDER BY id", (cutoff, _fmt(now)),
        ).fetchall()
        for r in rows:
            alert = dict(r)
            done = conn.execute(
                "SELECT id FROM activity_log WHERE module=? AND action=? AND target_type=? "
                "AND target_id=? LIMIT 1",
                (MODULE, "触发极端天气提醒", "weather_alert", alert["id"]),
            ).fetchone()
            if done:
                continue
            # 标记触发（先落日志再发通知，留痕优先）
            log_activity("系统", "触发极端天气提醒", "weather_alert", alert["id"],
                         target_title=f"{alert['alert_type']}{alert['level']}预警",
                         module=MODULE, after_value="已触发",
                         detail=ALERT_TEXTS.get(alert["alert_type"], ""))
            # 生成负责人检查任务（黄色及以上都要）
            create_check_task(alert["id"], alert["alert_type"], alert["level"])
            triggered.append(alert)
    return triggered


def run_alert_detection(days: list[dict] | None = None, city: str = "",
                        degraded: bool = False) -> dict:
    """预警检测主入口（监测端每 10 分钟调用）。

    流程：检测 → 入库 → 触发提醒（生效 ≤12h）。缓存降级时暂停新预警触发。
    """
    result: dict = {"detected": [], "inserted": [], "triggered": [], "paused": False}

    # 缓存降级：暂停新的预警触发提醒（已触发的滚动提醒保留）
    if degraded:
        result["paused"] = True
        _log_once("暂停新预警触发", "天气数据缓存降级中，暂停新的预警触发提醒", "weather_alert", "系统")
        return result

    alerts = detect_extreme_weather(days=days, city=city)
    result["detected"] = alerts
    if not alerts:
        return result

    inserted: list[int] = []
    with get_db() as conn:
        for a in alerts:
            aid = _insert_alert(conn, a)
            if aid is not None:
                inserted.append(aid)
        conn.commit()
    result["inserted"] = inserted
    if inserted:
        names = "、".join(f"{a['alert_type']}{a['level']}" for a in alerts if a)
        log_activity("系统", "极端天气预警检测", "weather_alert", module=MODULE,
                     after_value="检测到极端天气", detail=f"检测到极端天气预警：{names}")

    result["triggered"] = trigger_pending_alerts(city=city)
    return result


def get_active_alerts() -> list[dict]:
    """当前生效中的预警（按等级从高到低，同级按发布时间先后）。"""
    now = _fmt(_now())
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM weather_alerts WHERE status='active' "
            "AND (expire_time='' OR expire_time>=?) ORDER BY id", (now,),
        ).fetchall()
    alerts = [dict(r) for r in rows]
    alerts.sort(key=lambda a: (-_level_rank(a.get("level", "")), a.get("created_at", "")))
    return alerts


def get_top_alerts(limit: int = 2) -> list[dict]:
    """老年端播报用：最多两个最高等级预警（同级按发布时间先后）。"""
    return get_active_alerts()[:limit]


def get_alert(alert_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM weather_alerts WHERE id=?", (alert_id,)).fetchone()
        return dict(row) if row else None


def list_alerts(status: str | None = None, alert_type: str | None = None,
                limit: int = 100) -> list[dict]:
    q = "SELECT * FROM weather_alerts WHERE 1=1"
    args: list = []
    if status:
        q += " AND status=?"
        args.append(status)
    if alert_type:
        q += " AND alert_type=?"
        args.append(alert_type)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def expire_alerts() -> list[int]:
    """预警解除：到期预警置为 expired，关闭相关检查任务，留痕。"""
    now = _fmt(_now())
    expired: list[int] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM weather_alerts WHERE status='active' AND expire_time!='' AND expire_time<?",
            (now,),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE weather_alerts SET status='expired' WHERE id=?", (r["id"],))
            expired.append(r["id"])
        conn.commit()
    for aid in expired:
        alert = get_alert(aid)
        log_activity("系统", "预警解除", "weather_alert", aid,
                     target_title=f"{alert['alert_type'] if alert else ''}预警",
                     module=MODULE, before_value="active", after_value="expired")
        _close_tasks_for_alert(aid)
    return expired


def _close_tasks_for_alert(alert_id: int) -> None:
    """预警解除后关闭未处理的检查任务（记录关闭留痕，不代填检查结果）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, status FROM weather_check_tasks WHERE alert_id=? AND status='待检查'",
            (str(alert_id),),
        ).fetchall()
        task_ids = [r["id"] for r in rows]
    for tid in task_ids:
        log_activity("系统", "检查任务随预警解除关闭", "weather_check_task", tid,
                     module=MODULE, before_value="待检查", after_value="已关闭")


# ============================================================
# 三、检查任务：生成 / 确认 / 超时标记 / 超时升级
# ============================================================

def get_checklist(alert_type: str) -> list[str]:
    return list(CHECKLISTS.get(alert_type, ["公共设施巡查"]))


def create_check_task(alert_id: int, alert_type: str, level: str,
                      checklist: list[str] | None = None) -> int | None:
    """为预警生成检查任务（同预警同类型去重）。返回任务 ID 或 None。"""
    items = checklist if checklist is not None else get_checklist(alert_type)
    checklist_json = json.dumps(
        [{"item": it, "status": "未检查", "note": ""} for it in items],
        ensure_ascii=False,
    )
    with get_db() as conn:
        dup = conn.execute(
            "SELECT id FROM weather_check_tasks WHERE alert_id=? AND alert_type=? "
            "AND status IN ('待检查','已确认') LIMIT 1",
            (str(alert_id), alert_type),
        ).fetchone()
        if dup:
            return None
        cur = conn.execute(
            "INSERT INTO weather_check_tasks (alert_id, alert_type, level, checklist_json, status) "
            "VALUES (?, ?, ?, ?, '待检查')",
            (str(alert_id), alert_type, level, checklist_json),
        )
        task_id = cur.lastrowid
        conn.commit()
    log_activity("系统", "生成极端天气检查任务", "weather_check_task", task_id,
                 target_title=f"{alert_type}{level}检查",
                 module=MODULE, after_value="待检查",
                 detail=json.dumps(items, ensure_ascii=False))
    _notify_managers(
        f"⚠️ 极端天气检查任务：{alert_type}{level}预警",
        f"请按检查清单在{CHECK_HOURS}小时内完成公共设施检查并确认。{ALERT_TEXTS.get(alert_type, '')}",
        related_id=task_id,
    )
    return task_id


def get_check_task(task_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM weather_check_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["checklist"] = json.loads(d.get("checklist_json") or "[]")
        except (ValueError, TypeError):
            d["checklist"] = []
        return d


def list_check_tasks(status: str | None = None, alert_type: str | None = None,
                     limit: int = 100) -> list[dict]:
    q = "SELECT * FROM weather_check_tasks WHERE 1=1"
    args: list = []
    if status:
        q += " AND status=?"
        args.append(status)
    if alert_type:
        q += " AND alert_type=?"
        args.append(alert_type)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_check_task_history(alert_type: str | None = None, status: str | None = None,
                           limit: int = 100) -> list[dict]:
    """历史检查任务记录（支持按时间/类型/状态筛选，时间筛选由 UI 传参做）。"""
    return list_check_tasks(status=status, alert_type=alert_type, limit=limit)


def get_task_remaining_hours(task_id: int) -> dict:
    """剩余确认时间（3 小时倒计时）。超时后返回负数。"""
    task = get_check_task(task_id)
    if not task:
        return {"task_id": task_id, "remaining_hours": None, "overdue": False}
    try:
        created = datetime.strptime(task["created_at"], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return {"task_id": task_id, "remaining_hours": None, "overdue": False}
    remaining = CHECK_HOURS - (_now() - created).total_seconds() / 3600.0
    return {
        "task_id": task_id,
        "remaining_hours": round(remaining, 2),
        "overdue": remaining < 0,
        "urgency": "ok" if remaining >= 1 else "urgent" if remaining >= 0 else "overdue",
    }


_CHECK_ITEM_STATUSES = ("已检查", "正常", "异常")


def _validate_check_items(items) -> tuple[bool, str]:
    if not items:
        return False, "检查清单结果不能为空"
    if not isinstance(items, list):
        return False, "检查结果格式错误"
    for it in items:
        if not isinstance(it, dict) or not it.get("item"):
            return False, "检查项格式错误"
        if it.get("status") not in _CHECK_ITEM_STATUSES:
            return False, f"检查项「{it.get('item', '')}」状态必须是{'/'.join(_CHECK_ITEM_STATUSES)}之一"
    return True, ""


def confirm_check_task(task_id: int, checker: str, items: list[dict],
                       note: str = "", actor: str = "") -> tuple[bool, str]:
    """负责人确认已检查。→ 已确认。checker 为确认人。"""
    ok, msg = _validate_check_items(items)
    if not ok:
        return False, msg
    if not checker:
        return False, "请填写检查人"
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, alert_type, level FROM weather_check_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if row is None:
            return False, "检查任务不存在"
        if row["status"] != "待检查":
            return False, f"当前状态「{row['status']}」不支持确认"
        old = row["status"]
        conn.execute(
            "UPDATE weather_check_tasks SET status='已确认', checker=?, result=?, note=?, "
            "checked_at=CURRENT_TIMESTAMP WHERE id=?",
            (checker, json.dumps(items, ensure_ascii=False), note, task_id),
        )
        conn.commit()
    log_activity(actor or checker, "确认极端天气检查", "weather_check_task", task_id,
                 target_title=f"{row['alert_type']}{row['level']}检查",
                 module=MODULE, before_value=old, after_value="已确认",
                 detail=f"检查人：{checker}；备注：{note}")
    return True, ""


def fill_overdue_task(task_id: int, checker: str, items: list[dict],
                      note: str = "", actor: str = "") -> tuple[bool, str]:
    """超时未确认后补填：允许填写检查结果和备注，但保留"超时未确认"标记。"""
    ok, msg = _validate_check_items(items)
    if not ok:
        return False, msg
    if not checker:
        return False, "请填写检查人"
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, alert_type, level FROM weather_check_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if row is None:
            return False, "检查任务不存在"
        if row["status"] != "超时未确认":
            return False, f"当前状态「{row['status']}」不支持补填"
        conn.execute(
            "UPDATE weather_check_tasks SET checker=?, result=?, note=?, "
            "checked_at=CURRENT_TIMESTAMP WHERE id=?",
            (checker, json.dumps(items, ensure_ascii=False), note, task_id),
        )
        conn.commit()
    log_activity(actor or checker, "补填超时检查结果", "weather_check_task", task_id,
                 target_title=f"{row['alert_type']}{row['level']}检查",
                 module=MODULE, before_value="超时未确认", after_value="超时未确认(已补填)",
                 detail=f"检查人：{checker}；备注：{note}")
    return True, ""


def mark_overdue_tasks() -> list[int]:
    """3 小时未确认 → 标记"超时未确认"（留痕；可后续补填）。"""
    overdue: list[int] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, alert_type, level FROM weather_check_tasks "
            "WHERE status='待检查' AND julianday('now') - julianday(created_at) > ?",
            (CHECK_HOURS / 24.0,),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE weather_check_tasks SET status='超时未确认' WHERE id=?", (r["id"],))
            overdue.append(dict(r))
        conn.commit()
    for r in overdue:
        log_activity("系统", "检查任务超时", "weather_check_task", r["id"],
                     target_title=f"{r['alert_type']}{r['level']}检查",
                     module=MODULE, before_value="待检查", after_value="超时未确认",
                     detail=f"超过{CHECK_HOURS}小时未确认，允许补填，保留超时标记")
    return [r["id"] for r in overdue]


def _notify_managers(title: str, content: str, related_id: int | None = None,
                     online_user_ids: list[int] | None = None) -> int:
    """通知负责人（在线名单由调用方传入；默认通知全部 grid 角色负责人）。"""
    try:
        from data.db_notifications import create_notification
        users = []
        if online_user_ids:
            users = [{"id": uid} for uid in online_user_ids]
        else:
            from data.db_user import list_users
            users = list_users(role="grid")
        count = 0
        for u in users:
            try:
                create_notification(u["id"], "weather_check", title, content, related_id)
                count += 1
            except Exception:
                _log.warning("负责人通知发送失败：user_id=%s", u.get("id"), exc_info=True)
        return count
    except Exception:
        _log.warning("负责人通知整体失败", exc_info=True)
        return 0


def _last_escalation_log(task_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM activity_log WHERE module=? AND target_type='weather_check_task' "
            "AND target_id=? AND action LIKE '超时升级%' ORDER BY id DESC LIMIT 1",
            (MODULE, task_id),
        ).fetchone()
        return dict(row) if row else None


def get_escalation_status(task_id: int) -> dict:
    """读取某任务的升级留痕状态（供负责人端展示）。"""
    log_row = _last_escalation_log(task_id)
    if not log_row:
        return {"task_id": task_id, "escalated": False, "state": "", "detail": ""}
    state = "escalated"
    if "无法升级" in (log_row.get("detail") or ""):
        state = "cannot_upgrade"
    elif "失败" in (log_row.get("action") or "") or "失败" in (log_row.get("detail") or ""):
        state = "notify_failed"
    return {
        "task_id": task_id,
        "escalated": True,
        "state": state,
        "detail": log_row.get("detail", ""),
        "escalated_at": log_row.get("created_at", ""),
    }


def escalate_overdue_tasks(online_user_ids: list[int] | None = None,
                           senior_user_ids: list[int] | None = None) -> dict:
    """超时升级（压测修正）：

    - 超时未确认且无人补填的任务 → 立即通知所有在线负责人，持续提醒直到有人确认；
    - 更高级负责人未配置 → 记录"无法升级"日志，保持最高优先级告警；
    - 升级通知失败 → 重试一次，仍失败标记"升级通知失败"；更高级通知也失败 →
      保留最高优先级告警，显示"紧急天气检查任务等待人工介入"并通知系统管理员。
    """
    results: dict = {
        "escalated": [], "notified": 0, "senior_notified": 0,
        "cannot_upgrade": [], "notify_failed": [],
    }
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM weather_check_tasks WHERE status='超时未确认' "
            "AND (checked_at IS NULL OR checker='') ORDER BY id",
        ).fetchall()
        tasks = [dict(r) for r in rows]

    for t in tasks:
        task_id = t["id"]
        title = f"紧急天气检查任务：{t['alert_type']}{t['level']}预警"
        content = (
            f"检查任务 #{task_id} 已超时未确认，请立即安排检查并确认。"
            f"{ALERT_TEXTS.get(t['alert_type'], '')}"
        )

        # 去重窗口：同任务 30 分钟内已升级通知过就跳过（避免每轮监测刷屏）
        last = _last_escalation_log(task_id)
        if last:
            try:
                last_at = datetime.strptime(last["created_at"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                last_at = None
            if last_at and (_now() - last_at).total_seconds() < ESCALATE_DEDUPE_MIN * 60:
                results["escalated"].append({"task_id": task_id, "reminded": True})
                continue

        # 第 1 层：通知所有在线负责人
        sent = _notify_managers(title, content, related_id=task_id,
                                online_user_ids=online_user_ids)
        if sent == 0:
            # 升级通知失败：重试一次
            sent = _notify_managers(title, content, related_id=task_id,
                                    online_user_ids=online_user_ids)
            if sent == 0:
                log_activity("系统", "升级通知失败", "weather_check_task", task_id,
                             target_title=title, module=MODULE, detail="重试一次后仍失败，标记升级通知失败")
                results["notify_failed"].append(task_id)
            else:
                results["notified"] += sent
        else:
            results["notified"] += sent

        # 第 2 层：更高级负责人兜底
        if senior_user_ids:
            senior_sent = _notify_managers(title, content, related_id=task_id,
                                           online_user_ids=senior_user_ids)
            results["senior_notified"] += senior_sent
            if senior_sent == 0:
                log_activity("系统", "升级通知失败", "weather_check_task", task_id,
                             target_title=title, module=MODULE,
                             detail="更高级负责人通知失败：紧急天气检查任务等待人工介入")
                results["notify_failed"].append(task_id)
                _notify_system_admin(title, content, task_id)
        else:
            log_activity("系统", "超时升级通知", "weather_check_task", task_id,
                         target_title=title, module=MODULE,
                         detail="无法升级：未配置更高级负责人，持续提醒在线负责人，保持最高优先级告警")
            results["cannot_upgrade"].append(task_id)
            continue

        senior_txt = f"，并升级至更高级负责人{results['senior_notified']}位" if results["senior_notified"] else ""
        log_activity("系统", "超时升级通知", "weather_check_task", task_id,
                     target_title=title, module=MODULE,
                     detail=f"已通知{results['notified']}位负责人{senior_txt}")
        results["escalated"].append({"task_id": task_id, "reminded": False})
    return results


def _notify_system_admin(title: str, content: str, related_id: int | None = None) -> None:
    """升级通知连续失败时通知系统管理员（id=1 兜底，尽力而为）。"""
    try:
        from data.db_notifications import create_notification
        from data.db_user import get_user_by_id
        admin = get_user_by_id(1)
        if admin:
            create_notification(admin["id"], "weather_escalation",
                                f"🚨 {title}", content, related_id)
    except Exception:
        _log.warning("通知系统管理员失败", exc_info=True)


# ============================================================
# 四、老年端提醒辅助
# ============================================================

def should_send_daily_elderly_reminder(alert_id: int) -> bool:
    """极端天气持续期间每天上午 8 点提醒一次（当天未提醒才返回 True）。"""
    today = _fmt(_now())[:10]
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM activity_log WHERE module=? AND action='老年端极端天气提醒' "
            "AND target_type='weather_alert' AND target_id=? AND substr(created_at,1,10)=? LIMIT 1",
            (MODULE, alert_id, today),
        ).fetchone()
    return row is None


def log_elderly_reminder(alert_id: int, alert_type: str, level: str) -> None:
    """记录一次老年端极端天气提醒（红色预警由 UI 播报两次，数据层记录一次留痕）。"""
    log_activity("系统", "老年端极端天气提醒", "weather_alert", alert_id,
                 target_title=f"{alert_type}{level}预警",
                 module=MODULE, detail=ALERT_TEXTS.get(alert_type, ""))


def get_elderly_reminder_plan() -> list[dict]:
    """生成老年端今日提醒计划：每个 active 预警一条（红色标注重复播报两次）。"""
    plan = []
    for a in get_active_alerts():
        plan.append({
            "alert_id": a["id"],
            "alert_type": a["alert_type"],
            "level": a["level"],
            "text": ALERT_TEXTS.get(a["alert_type"], ""),
            "broadcast_times": 2 if a["level"] == "红色" else 1,
            "should_send": should_send_daily_elderly_reminder(a["id"]),
        })
    return plan


def get_reminder_banner_data() -> list[dict]:
    """居民端/负责人端顶部滚动提醒数据（按等级排序，可多预警并存）。"""
    return get_active_alerts()
