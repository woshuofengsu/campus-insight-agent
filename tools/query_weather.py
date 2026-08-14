# tools/query_weather.py
import logging
import random
from datetime import datetime, timedelta
from langchain.tools import tool
from config import USE_REAL_WEATHER

_log = logging.getLogger(__name__)

# 北京分季节的天气模板（模拟数据，上线换成真实 API）
_SEASONAL_WEATHER = {
    # 格式：月份: (低温范围, 高温范围, 常见天气列表)
    (12,1,2):  ((-10, -2), (0, 6),   [("晴天","☀️"),("多云","⛅"),("小雪","❄️"),("大风","🌬️")]),
    (3,4,5):   ((3, 12),   (15, 25), [("晴天","☀️"),("多云","⛅"),("小雨","🌧️"),("扬沙","💨")]),
    (6,7,8):   ((20, 25),  (30, 36), [("晴天","☀️"),("多云","⛅"),("雷阵雨","⛈️"),("暴雨","🌊")]),
    (9,10,11): ((5, 15),   (15, 25), [("晴天","☀️"),("多云","⛅"),("小雨","🌧️"),("阴天","☁️")]),
}


def _get_seasonal_config(month: int):
    for months, (t_low_range, t_high_range, conditions) in _SEASONAL_WEATHER.items():
        if month in months:
            return (t_low_range, t_high_range), conditions
    return ((-5, 25), (5, 30)), [("晴天","☀️"),("多云","⛅")]  # 兜底默认值


def _mock_weather():
    """按北京季节规律生成模拟天气数据。
    上线时换成和风/OpenWeatherMap 的 API（把 USE_REAL_WEATHER 设成 True）。
    """
    today = datetime.now()
    temps, conditions = _get_seasonal_config(today.month)
    t_low_range, t_high_range = temps

    days = []
    for offset in range(3):
        date = today + timedelta(days=offset)
        cond, emoji = random.choice(conditions)
        temp_high = random.randint(*t_high_range)
        temp_low = random.randint(*t_low_range)
        if temp_low >= temp_high:
            temp_low = temp_high - random.randint(5, 10)

        rain_map = {"晴天": 0, "多云": 10, "阴天": 30, "小雨": 60, "雷阵雨": 75, "暴雨": 90, "小雪": 40, "扬沙": 5, "大风": 5}
        advice_map = {
            "晴天": "适合出行，注意防晒", "多云": "适合出行", "阴天": "建议带伞以防万一",
            "小雨": "记得带伞", "雷阵雨": "减少外出，注意防雷", "暴雨": "尽量避免外出",
            "小雪": "路面可能结冰，注意安全", "扬沙": "戴口罩，减少户外活动", "大风": "注意防风保暖",
        }

        days.append({
            "date": date.strftime("%Y-%m-%d"),
            "weekday": ["周一","周二","周三","周四","周五","周六","周日"][date.weekday()],
            "condition": cond,
            "emoji": emoji,
            "temp_high": temp_high,
            "temp_low": temp_low,
            "rain_prob": rain_map.get(cond, 10),
            "wind": random.choice(["微风 1-2级","北风 2-3级","南风 3-4级","东北风 2-3级"]),
            "advice": advice_map.get(cond, "适合出行"),
        })
    return days


# 共用的辅助函数（聊天工具和看板都用）

_CONDITION_EMOJI = {
    "晴": "☀️", "少云": "🌤️", "晴间多云": "⛅", "多云": "⛅",
    "阴": "☁️", "小雨": "🌧️", "中雨": "🌧️", "大雨": "🌧️", "暴雨": "🌊",
    "雷阵雨": "⛈️", "小雪": "❄️", "中雪": "❄️", "大雪": "❄️",
    "扬沙": "💨", "沙尘暴": "💨", "霾": "🌫️", "雾": "🌫️", "风": "🌬️",
}


def _make_advice(condition: str, precip: float) -> str:
    """根据天气情况生成出行建议文案。"""
    if condition in ("暴雨", "雷阵雨"):
        return "减少外出，注意防雷"
    elif condition in ("大雨", "中雨", "小雨"):
        return "记得带伞"
    elif condition in ("霾", "沙尘暴", "扬沙"):
        return "戴口罩，减少户外活动"
    elif condition in ("大雪", "中雪", "小雪"):
        return "路面可能结冰，注意安全"
    elif precip > 50:
        return "降水概率高，建议带伞"
    elif condition in ("晴", "少云"):
        return "适合出行，注意防晒"
    return "适合出行"


def fetch_real_weather_days(api_key: str, city_id: str,
                             city_name: str = "") -> tuple[list[dict], str]:
    """从和风天气 API 拉 3 天天气，返回结构化的天数据字典。

    返回 (days_list, location_name)。任何失败都会抛异常，
    让调用方自己优雅地退回模拟数据。

    聊天工具和看板组件都走这个入口，API 调用逻辑只写一份。
    """
    import requests
    from config import HEFENG_API_HOST

    # 优先用账号自己的 host（控制台 V4，2025 年后），
    # 没配就用公共的开发 host
    api_host = HEFENG_API_HOST or "devapi.qweather.com"

    # 第一步：城市名换成 location ID
    location_id = city_id
    location_name = city_name or "北京"
    try:
        geo_url = f"https://{api_host}/v2/city/lookup"
        geo_resp = requests.get(
            geo_url,
            params={"location": city_name or "北京", "key": api_key},
            timeout=10,
        )
        geo_data = geo_resp.json()
        if geo_data.get("code") == "200" and geo_data.get("location"):
            loc = geo_data["location"][0]
            location_id = loc["id"]
            # 拼展示用的地名，比如"北京市海淀区"
            adm1 = loc.get("adm1", "")
            adm2 = loc.get("adm2", "")
            name = loc.get("name", "")
            parts = [p for p in (adm1, adm2, name) if p]
            if parts:
                location_name = "".join(parts)
    except Exception:  # 记个日志跳过
        _log.debug("GPS 定位失败，先用 config 里的默认位置")

    # 第二步：拉 3 天天气
    weather_url = f"https://{api_host}/v7/weather/3d"
    weather_resp = requests.get(
        weather_url,
        params={"location": location_id, "key": api_key},
        timeout=10,
    )
    weather_data = weather_resp.json()

    if weather_data.get("code") != "200":
        raise RuntimeError(f"API error code {weather_data.get('code')}")

    daily = weather_data.get("daily", [])
    if not daily:
        raise RuntimeError("天气预报数据为空")

    # 第三步：拼结构化数据（字段和 _mock_weather 保持一致）
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    # 风力等级数字转成中文说法
    wind_scale_labels = {"1": "微风", "2": "轻风", "3": "微风", "4": "和风",
                         "5": "清风", "6": "强风", "7": "疾风"}

    days = []
    for i, d in enumerate(daily[:3]):
        date_str = d["fxDate"]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            wd = weekday_map[dt.weekday()]
        except Exception:
            _log.debug("解析天气日期字符串失败", exc_info=True)
            wd = ""

        cond = d.get("textDay", "未知")
        emoji = _CONDITION_EMOJI.get(cond, "🌈")
        temp_high = d.get("tempMax", "?")
        temp_low = d.get("tempMin", "?")
        wind_dir = d.get("windDirDay", "")
        wind_scale = d.get("windScaleDay", "")
        wind_label = wind_scale_labels.get(wind_scale, f"{wind_scale}级")
        wind = f"{wind_dir} {wind_label}" if wind_dir else "未知"

        try:
            precip = float(d.get("precip", 0))
        except (ValueError, TypeError):
            precip = 0.0

        days.append({
            "date": date_str,
            "weekday": wd,
            "condition": cond,
            "emoji": emoji,
            "temp_high": temp_high,
            "temp_low": temp_low,
            "rain_prob": int(precip),
            "wind": wind,
            "advice": _make_advice(cond, precip),
        })

    return days, location_name


@tool
def get_weather() -> str:
    """查询当日及未来2天天气。

    返回温度、天气状况、降水概率、风力、出行建议。如遇恶劣天气会特别标注。
    """
    if USE_REAL_WEATHER:
        return _real_weather()

    days = _mock_weather()
    lines = ["🌤️ 天气预报："]
    lines.append(f"  🟡 {_get_data_source_note()}")
    alerts = []

    for i, d in enumerate(days):
        prefix = "📌 今天" if i == 0 else f"📅 {d['date']}" if i == 1 else f"📅 后天"
        lines.append(
            f"\n  {prefix} {d['weekday']} {d['emoji']} {d['condition']}\n"
            f"    气温：{d['temp_low']}°C ~ {d['temp_high']}°C\n"
            f"    降水概率：{d['rain_prob']}% | {d['wind']}\n"
            f"    出行建议：{d['advice']}"
        )
        if d["rain_prob"] >= 60:
            alerts.append(f"{d['date']} {d['condition']}")

    if alerts:
        lines.append(f"\n⚠️ 恶劣天气预警：{'、'.join(alerts)}，请注意出行安全！")

    return "\n".join(lines)


def _real_weather() -> str:
    """从和风天气免费开发 API 拉实时天气。

    用的是 devapi.qweather.com（免费，不用实名认证）。
    网络、key 不对等任何报错都会退回模拟数据。
    """
    from config import HEFENG_API_KEY, COMMUNITY_CITY, COMMUNITY_CITY_ID

    if not HEFENG_API_KEY:
        return (
            "⚠️ 和风天气 API Key 未配置。\n\n"
            "获取免费 Key（3步，2分钟）：\n"
            "1. 访问 https://id.qweather.com/#/register 注册\n"
            "2. 进入控制台 → 项目管理 → 创建项目（选择\"免费订阅\"）\n"
            "3. 将 Key 填入 .env 的 HEFENG_API_KEY=xxx\n\n"
            f"{_get_data_source_note(real=False)}"
        )

    try:
        days, location_name = fetch_real_weather_days(
            HEFENG_API_KEY, COMMUNITY_CITY_ID, COMMUNITY_CITY,
        )
    except Exception:  # 失败就失败吧
        _log.debug("真实天气 API 请求失败，退回 mock 数据", exc_info=True)
        return _fallback_weather("天气API请求失败，已切换为模拟数据")

    # 拼返回文案
    lines = ["🌤️ 天气预报："]
    lines.append(f"  🟢 {_get_data_source_note(real=True)}")
    alerts = []

    for i, d in enumerate(days):
        prefix = "📌 今天" if i == 0 else f"📅 明天" if i == 1 else f"📅 后天"
        lines.append(
            f"\n  {prefix} {d['weekday']} {d['emoji']} {d['condition']}\n"
            f"    气温：{d['temp_low']}°C ~ {d['temp_high']}°C\n"
            f"    降水概率：{d['rain_prob']}% | {d['wind']}\n"
            f"    出行建议：{d['advice']}"
        )

        if d["rain_prob"] >= 60 or d["condition"] in ("暴雨", "雷阵雨", "大雨", "大雪"):
            alerts.append(f"{d['date']} {d['condition']}")

    if alerts:
        lines.append(f"\n⚠️ 恶劣天气预警：{'、'.join(alerts)}，请注意出行安全！")

    return "\n".join(lines)


def _fallback_weather(reason: str = "") -> str:
    """真实接口挂了就用模拟数据兜底。"""
    days = _mock_weather()
    lines = ["🌤️ 天气预报："]
    if reason:
        lines.append(f"  🟡 {reason}")
    else:
        lines.append(f"  🟡 {_get_data_source_note(real=False)}")

    for i, d in enumerate(days):
        prefix = "📌 今天" if i == 0 else f"📅 {d['date']}" if i == 1 else f"📅 后天"
        lines.append(
            f"\n  {prefix} {d['weekday']} {d['emoji']} {d['condition']}\n"
            f"    气温：{d['temp_low']}°C ~ {d['temp_high']}°C\n"
            f"    降水概率：{d['rain_prob']}% | {d['wind']}\n"
            f"    出行建议：{d['advice']}"
        )
    return "\n".join(lines)


def get_today_weather() -> tuple[list[dict] | None, str, bool]:
    """统一天气入口 — 返回 (days, location_name, is_real)。

    先试真实 API，不行退回模拟。感知监控、脉搏页、天气工具都用它，
    逻辑集中起来免得各写一份。
    """
    from config import COMMUNITY_CITY, COMMUNITY_DISTRICT, COMMUNITY_CITY_ID
    location_name = f"{COMMUNITY_CITY}{COMMUNITY_DISTRICT}"
    is_real = False
    days = None

    if USE_REAL_WEATHER:
        from config import HEFENG_API_KEY
        if HEFENG_API_KEY:
            try:
                days, api_location = fetch_real_weather_days(
                    HEFENG_API_KEY, COMMUNITY_CITY_ID, COMMUNITY_CITY,
                )
                location_name = api_location
                is_real = True
            except Exception:  # 记个日志跳过
                _log.debug("Hefeng API 定位失败，退回 mock 数据")

    if days is None:
        try:
            days = _mock_weather()
        except Exception:
            _log.debug("mock 天气生成失败", exc_info=True)
            days = None

    return days, location_name, is_real


def _get_data_source_note(real: bool = False) -> str:
    """返回当前数据来源的说明。"""
    if real:
        return "数据来源：和风天气实时API"
    return "模拟数据（北京季节模式）— 接入和风天气API可获取实时数据"
