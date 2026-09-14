# utils/region.py
"""地区（属地）识别：纯函数、零 IO、可单测。

设计原则（见 docs/spec/地区识别落地方案.md v2）：
- **属地来自"用户所属社区"**（账号里已有的 community），不做 GPS/IP 自动定位；
- 不做完整国标行政区划表：只做"演示社区 + 常见别名 + 复合串拆分"足够的归一化；
- **解析不了不惩罚**：看不懂的自由文本按"全国"处理（安全默认），
  但**看得懂的外地行政区**（以 省/市/区/县/街道 等结尾）会判为 other → 软降权、仍可见；
- 级别与权重常量由本模块统一提供，`data/db_policy`（线上加性分）与 `agent/rag`（RRF 重排分）**共用同一份**，
  避免两套检索口径不一致。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)

NATIONAL = "全国"

# 级别（由具体到宽泛）
LEVEL_STREET = "local_street"
LEVEL_DISTRICT = "local_district"
LEVEL_CITY = "local_city"
LEVEL_PROVINCE = "local_province"
LEVEL_NATIONAL = "national"
LEVEL_OTHER = "other"

# 线上加性分（与业务阈值解耦：阈值永远只看 base 分，见 db_policy.ask_question）
REGION_BOOST: dict[str, float] = {
    LEVEL_STREET: 1.5, LEVEL_DISTRICT: 1.5, LEVEL_CITY: 1.0,
    LEVEL_PROVINCE: 0.5, LEVEL_NATIONAL: 0.0, LEVEL_OTHER: -0.5,
}
# RRF 重排分（RRF 以排名为本，加权限要小，只掰平近同分）
RRF_REGION: dict[str, float] = {
    LEVEL_STREET: 0.30, LEVEL_DISTRICT: 0.30, LEVEL_CITY: 0.20,
    LEVEL_PROVINCE: 0.10, LEVEL_NATIONAL: 0.0, LEVEL_OTHER: -0.10,
}

# 「全国/通用」等同义词
_NATIONAL_WORDS = ("全国", "通用", "不限", "全地区", "所有地区", "各地")

# 常见别名 → 规范 token（够用即可；命中不了的交给下面的"行政区后缀"判断）
_PROVINCE_ALIASES = {
    "北京": "北京市", "京": "北京市", "上海": "上海市", "天津": "天津市", "重庆": "重庆市",
    "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省", "黑龙江": "黑龙江省",
    "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省", "福建": "福建省", "江西": "江西省",
    "山东": "山东省", "河南": "河南省", "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省",
    "四川": "四川省", "陕西": "陕西省",
}
_DISTRICT_ALIASES = {
    "海淀": "海淀区", "朝阳": "朝阳区", "东城": "东城区", "西城": "西城区",
    "丰台": "丰台区", "石景山": "石景山区", "昌平": "昌平区", "大兴": "大兴区",
    "通州": "通州区", "顺义": "顺义区",
}
# 看得懂的行政区后缀（用于判断"这是外地地名"而不是"乱码/说明文字"）
_ADMIN_SUFFIX = re.compile(r"(省|市|区|县|旗|盟|自治州|自治区|街道|镇|乡|村)$")
# 直辖市：市即省级
_MUNICIPALITIES = ("北京市", "上海市", "天津市", "重庆市")


@dataclass(frozen=True)
class Region:
    """用户属地。字段全部可空；`chain()` 会自动跳过空值。"""

    community: str = ""
    province: str = ""
    city: str = ""
    city_id: str = ""      # 和风天气 adcode
    district: str = ""
    street: str = ""
    source: str = field(default="config", compare=False)  # config / fallback，便于排查

    def chain(self) -> list[str]:
        """属地链：由具体到宽泛（社区 → 街道 → 区 → 市 → 省），去空去重。"""
        out: list[str] = []
        for v in (self.community, self.street, self.district, self.city, self.province):
            v = (v or "").strip()
            if v and v not in out:
                out.append(v)
        return out

    def label(self) -> str:
        """展示用属地标签，如「北京市海淀区·海淀小区」。"""
        head = "".join(p for p in ((self.province or self.city), self.district) if p)
        if self.street and self.street not in head:
            head = head or self.street
        if self.community:
            return f"{head}·{self.community}" if head else self.community
        return head or self.city or ""

    def cache_key(self) -> str:
        """天气缓存键：优先 adcode（稳定、与展示名解耦），否则城市名。"""
        return (self.city_id or self.city or "").strip()

    def is_empty(self) -> bool:
        return not (self.community or self.city or self.city_id or self.district or self.street)


def _fallback_region(community: str = "") -> Region:
    """回落：全局城市配置（保证单社区/未知社区行为与现状一致）。"""
    from config import COMMUNITY_CITY, COMMUNITY_CITY_ID, COMMUNITY_DISTRICT

    # 直辖市：市即省级；展示用全称（"北京市"而非"北京"），否则标签会显示成"北京海淀区"
    _municipality = f"{COMMUNITY_CITY}市"
    province = _municipality if _municipality in _MUNICIPALITIES else ""
    return Region(community=community, province=province, city=COMMUNITY_CITY,
                  city_id=COMMUNITY_CITY_ID, district=COMMUNITY_DISTRICT, source="fallback")


_warned: set[str] = set()


def resolve_region(community: str | None) -> Region:
    """由社区名解析属地：命中映射用之，否则回落全局默认并**告警**（不允许静默无效）。

    为什么必须告警：映射键与库里真实值不一致时（例如库里是「海淀小区」而映射写「示例社区」），
    功能会**悄悄退化成"和没做一样"** —— 这类"静默无效"是本项目重点防的问题。
    """
    key = (community or "").strip()
    try:
        from config import REGION_BY_COMMUNITY
    except Exception as e:  # config 未提供（单测/老版本）→ 用回落
        _log.warning("读取 config.REGION_BY_COMMUNITY 失败，改用回落策略：%s", e)
        REGION_BY_COMMUNITY = {}
    table = REGION_BY_COMMUNITY if isinstance(REGION_BY_COMMUNITY, dict) else {}
    if key and key in table:
        conf = dict(table[key] or {})
        return Region(community=key, source="config", **{
            k: v for k, v in conf.items() if k in
            ("province", "city", "city_id", "district", "street")
        })
    if key and key not in _warned:
        _warned.add(key)
        _log.warning("社区「%s」未配置属地映射，回落到全局默认城市（如需属地化请在 "
                     "config.REGION_BY_COMMUNITY 配置该社区）", key)
    return _fallback_region(key)


def normalize_area(text: str) -> set[str]:
    """把 `applicable_area` 文本归一到 token 集合。

    规则：
    - 空 / 全国 / 通用 / 不限 → {NATIONAL}
    - 复合串拆分：`北京市海淀区` → {北京市, 海淀区}（库里真实数据就长这样）
    - 别名归一：`北京`→北京市、`海淀`→海淀区
    - 看得懂的外地行政区（以 省/市/区/县… 结尾）→ 保留原词（调用方据此判 other：软降权、仍可见）
    - 看不懂的自由文本 → {NATIONAL}（安全默认：解析不了不惩罚、不误排）
    """
    raw = (text or "").strip()
    if not raw:
        return {NATIONAL}
    if any(w in raw for w in _NATIONAL_WORDS):
        return {NATIONAL}

    # ① 先认「配置里登记过的真实社区名」（如「海淀小区」）——
    #    否则会被下面的「海淀」别名吞成区级，丢掉社区级精度。
    try:
        from config import REGION_BY_COMMUNITY as _tbl
        if isinstance(_tbl, dict) and raw in _tbl:
            return {raw}
    except Exception as e:  # noqa: BLE001
        _log.debug("读取社区映射失败（继续按别名归一）：%s", e)

    tokens: set[str] = set()
    for alias, canon in _DISTRICT_ALIASES.items():
        if alias in raw:
            tokens.add(canon)
    for alias, canon in _PROVINCE_ALIASES.items():
        if alias in raw:
            tokens.add(canon)
    if tokens:
        return tokens

    # 没有命中别名：看是不是"看得懂的行政区名"
    if _ADMIN_SUFFIX.search(raw):
        return {raw}
    return {NATIONAL}


def _level_of(token: str, region: Region) -> str | None:
    """判断某个 token 相对用户属地属于哪一级（命中不了返回 None）。"""
    if token == NATIONAL:
        return LEVEL_NATIONAL
    if region.street and token == region.street:
        return LEVEL_STREET
    if region.district and token == region.district:
        return LEVEL_DISTRICT
    if region.community and token == region.community:
        return LEVEL_STREET          # 社区级视同最具体一级
    if region.city and token == region.city:
        return LEVEL_CITY
    if region.city and token == f"{region.city}市":
        return LEVEL_CITY
    if region.province and token == region.province:
        return LEVEL_PROVINCE
    return None


_LEVEL_ORDER = (LEVEL_STREET, LEVEL_DISTRICT, LEVEL_CITY, LEVEL_PROVINCE)
# 区/县级后缀：用于判断"这条政策写的是别的区"（更具体的地名一旦对不上，就应按外地处理）
_DISTRICT_LIKE = re.compile(r"(区|县|旗)$")
# 但「XX小区 / XX社区 / XX园区 / XX地区」不是行政区划 —— 小区名恰好以"区"结尾，
# 若不做这个排除，「海淀小区」会被误判成"别区的行政区"而被打成外地（复查时踩到）。
_NOT_DISTRICT_SUFFIX = ("小区", "社区", "园区", "学区", "景区", "地区")


def _is_district_token(t: str) -> bool:
    if t.endswith(_NOT_DISTRICT_SUFFIX):
        return False
    return bool(_DISTRICT_LIKE.search(t))


def policy_region_boost(applicable_area: str, region: Region | None) -> tuple[float, str]:
    """返回 (加分, 级别)。`region=None` 或"全国" → (0.0, national)，调用方排序完全不变。

    取**最具体**的命中级别（同时命中"北京市"和"海淀区" → 按区级算）。

    ⚠ 关键规则（复查时补的 BUG 修复）：**更具体的地名一旦对不上，就按外地降权**。
    例：政策写「北京市海淀区」，对**海淀**用户是区级命中（+1.5）；
    但对**朝阳**用户只因为"北京市"匹配就给市级 +1.0 是错的 —— 这条政策根本不适用于朝阳。
    现在：只要条目里出现"别的区/县"，一律判 other（软降权、仍可见，不做过滤）。
    """
    if region is None or region.is_empty():
        return 0.0, LEVEL_NATIONAL
    raw = (applicable_area or "").strip()
    # 「本社区/本小区」= 用户自己那一级（最具体）
    if raw in ("本社区", "本小区", "本站", "本街道"):
        return REGION_BOOST[LEVEL_STREET], LEVEL_STREET
    tokens = normalize_area(raw)
    if NATIONAL in tokens:
        return 0.0, LEVEL_NATIONAL
    # ① 别的区/县 → 外地（避免"沾了同城就算本地"）
    if region.district:
        for t in tokens:
            if _is_district_token(t) and t != region.district:
                return REGION_BOOST[LEVEL_OTHER], LEVEL_OTHER
    matched = [lv for lv in (_level_of(t, region) for t in tokens) if lv in _LEVEL_ORDER]
    if matched:
        level = min(matched, key=_LEVEL_ORDER.index)
        return REGION_BOOST.get(level, 0.0), level
    return REGION_BOOST[LEVEL_OTHER], LEVEL_OTHER


def rrf_region_bonus(level: str) -> float:
    """RRF 重排用的属地加分（与 REGION_BOOST 同一套级别定义）。"""
    return RRF_REGION.get(level, 0.0)
