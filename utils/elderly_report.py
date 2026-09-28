# -*- coding: utf-8 -*-
"""老人报修的字段抽取与必填契约（v3 任务卡 1：**老人报修必填信息与责任范围**）。

**为什么单独有这个模块**：老人端原来把"位置提取失败"悄悄退化成 `profile.community` 或字面量
"社区"，然后照样建单 —— 结果库里真的躺着 `location='社区'` 的**无法派单工单**
（2026-09-28 在演示库里实测到 5 条，例：#355「3号楼2单元楼道灯坏了」location=社区、
#352「我家阳台水龙头漏水了」location=社区）。这类工单的危害不是"显示不好看"，
而是**老人以为报了、其实没人能去修**。所以位置必须**要么问清楚、要么不建单**。

本模块是**纯函数、无 IO**：
  - 便于单测（`tests/test_elderly_report_contract.py`）；
  - 也满足"同一输入重复运行得到一致的任务对象"（v2 卡10 的要求）。

契约（缺一不可才允许建单）：
  1. **问题描述**：老人原话，≥5 字；
  2. **位置**：室内 → 房间（厨房/卫生间/阳台…）；公共区域 → 楼栋/单元/楼层 + 部位
     （楼道/电梯/外墙/绿地…）。**"社区/小区"这类粗粒度词不算位置**（派不了单）；
  3. **责任范围**：`室内`（户内，费用自理）/ `室外`（公共区域，社区负责）/
     `不确定`（必须问 —— 责任与费用不同，猜错就是误导老人）；
  4. **紧急程度**：默认「一般」，可由老人改；危险词（燃气/冒烟/着火/电梯困人/漏水到楼下）自动升级。

**字段来源必须可解释**（v3 复核 §6-I7）：每个字段标注
`user`（老人确认/补充）/ `text`（原话里抽出来的）/ `profile`（服务端资料里的地址）/
`suggestion`（系统建议）/ `default`（缺省值）。未确认的"纠正"不得变成业务事实。
"""
import re

# ---------------------------------------------------------------- 词表

# 楼栋/单元/楼层（阿拉伯与中文数字都认）
_NUM = r"[一二三四五六七八九十百\d]{1,3}"
_BUILDING_RE = re.compile(rf"({_NUM})\s*(号楼|栋|楼)(?!道|梯|层)")
_UNIT_RE = re.compile(rf"({_NUM})\s*(单元|门)")
_FLOOR_RE = re.compile(rf"({_NUM})\s*(层|楼)(?=[^\d]|$)")

# 公共部位（社区/物业负责）——**楼栋级**：必须能指到具体楼栋/单元/楼层才算可派单
_PUBLIC_WORDS = (
    "楼道", "走廊", "楼梯", "电梯", "电梯间", "外墙", "屋顶", "楼顶", "天台", "地下室",
    "车库", "车棚", "自行车棚", "充电桩", "门禁", "单元门", "院内",
    "下水道", "消防通道", "停车位",
)

# **社区级**地标：本身就能定位（"广场的灯不亮"不需要再说楼栋）
_COMMUNITY_LEVEL = (
    "广场", "绿地", "花园", "大门口", "小区门口", "垃圾站", "垃圾桶", "快递柜",
    "公告栏", "健身器材", "滑梯", "坡道", "化粪池", "水泵房", "配电房", "路灯",
)

# 户内房间（室内，费用自理）
_ROOM_WORDS = (
    "厨房", "卫生间", "厕所", "洗手间", "卧室", "客厅", "阳台", "浴室", "水房",
    "屋里", "家里", "我家", "室内", "房顶", "天花板", "窗户", "水管", "水龙头", "马桶",
    "插座", "开关", "暖气", "燃气灶", "热水器", "空调",
)

# 危险/紧急信号（自动升级紧急程度，但仍由老人确认）
_URGENT_WORDS = (
    "燃气", "煤气", "冒烟", "着火", "火警", "漏电", "触电", "电梯困人", "被困",
    "老人摔倒", "有人受伤", "漏水到楼下", "水漫", "停水停电好几天", "坍塌", "冒火花",
)

# 太粗、不能作为可派单位置的词
_TOO_COARSE = ("社区", "小区", "我们院", "附近", "外面", "家里")

# 泛化的"房间"词：能证明是室内，但不足以定位（"我家水管坏了"要说清是哪个房间）
_GENERIC_ROOM = ("我家", "家里", "屋里", "室内")

_ASK_LOCATION = "请问是哪个楼、哪一层？（比如：5号楼二层楼道，或者「我家厨房」）"
_ASK_SCOPE = "这个是您家里的事，还是楼道、电梯这样的公共地方？"
_ASK_BOTH = "这个是您家里的事，还是楼道、电梯这样的公共地方？顺便告诉我哪栋楼、哪一层。"

# 中文数字 → 阿拉伯数字（楼栋/单元/楼层统一成 "5号楼2单元3层" 这种口径，
# 与知识图谱的楼栋实体归一（`data/db_kg` 把「四号楼」归一成「4号楼」）保持一致）
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(s: str) -> str:
    """把「五」「十二」「二十三」这类中文数字转成阿拉伯数字；转不了就原样返回。"""
    s = (s or "").strip()
    if not s or s.isdigit():
        return s
    if "十" not in s:
        return "".join(str(_CN_DIGITS[c]) for c in s if c in _CN_DIGITS) or s
    head, _, tail = s.partition("十")
    tens = _CN_DIGITS.get(head, 1) if head else 1
    ones = _CN_DIGITS.get(tail, 0) if tail else 0
    return str(tens * 10 + ones)


def _normalize_frag(frag: str) -> str:
    """片段里的中文数字归一：`五号楼`→`5号楼`、`二层`→`2层`、`三单元`→`3单元`。"""
    m = re.fullmatch(rf"({_NUM})(号楼|栋|楼|单元|门|层)", frag)
    if m:
        return f"{_cn_to_int(m.group(1))}{m.group(2)}"
    return frag


def _parse_fragments(text: str) -> dict:
    """把原话拆成位置部件（**有序**，中文数字归一）。

    返回 `{"structural": [...], "room": "", "public": "", "landmark": "", "all": [...]}`：
      - `structural`：楼栋/单元/楼层（按原话顺序）；
      - `room`/`public`/`landmark`：房间词 / 楼栋级公共部位 / 社区级地标（各取第一个）；
      - `all`：以上全部（按原话顺序，供"这算是位置吗"的判定用）。
    """
    out: list[tuple[int, str]] = []

    def _add(m):
        if m:
            out.append((m.start(), m.group(0).replace(" ", "")))

    for m in _BUILDING_RE.finditer(text):
        _add(m)
    for m in _UNIT_RE.finditer(text):
        _add(m)
    for m in _FLOOR_RE.finditer(text):
        _add(m)
    structural_map: dict[int, str] = {}
    for pos, frag in out:
        structural_map[pos] = _normalize_frag(frag)
    structural = [structural_map[p] for p in sorted(structural_map)]

    def _first(words, *, skip: tuple = (), strict: bool = False) -> str:
        """取原话里**最先出现**的词。

        `skip` 里的泛化词（我家/家里）只作兜底；`strict=True` 时**没有具体词就返回空串**
        （用于"这算不算具体房间"的判断——泛化的"家里"不能冒充具体房间，否则会把
        「电梯坏了，家里老人下不来楼」这种公共问题判成室内，实测踩到过）。
        """
        hits = [(text.find(w), w) for w in words if text.find(w) >= 0]
        if not hits:
            return ""
        specific = [(i, w) for i, w in hits if w not in skip]
        if specific:
            return min(specific)[1]
        return "" if strict else min(hits)[1]

    # 房间要取**具体**的房间（"我家阳台漏水"→阳台，"我家"只是泛指）
    room = _first(_ROOM_WORDS, skip=_GENERIC_ROOM, strict=True)
    # 泛化的"在家"提法（我家/家里）只说明"可能跟家里有关"，**不足以**把责任范围判成室内、
    # 更不该让它跟公共部位打架（例：「3号楼2单元电梯又坏了…家里老人下不来楼」——
    # 报的是电梯，不是家里）。所以只把**具体房间**算作室内信号。
    room_weak = _first(_GENERIC_ROOM)
    public = _first(_PUBLIC_WORDS)
    landmark = _first(_COMMUNITY_LEVEL)
    allf = list(structural)
    for w in (room or room_weak, public, landmark):
        if w and w not in allf:
            allf.append(w)
    return {"structural": structural, "room": room, "room_weak": room_weak,
            "public": public, "landmark": landmark, "all": allf}


def extract_report_fields(text: str, profile: dict | None = None,
                          confirmed_location: str = "",
                          confirmed_scope: str = "",
                          confirmed_urgency: str = "") -> dict:
    """从老人原话（＋服务端资料＋老人**已确认**的补充值）算出报修字段。

    返回：
      {
        "fields":   {title, description, location, issue_type, urgency},
        "sources":  {location/issue_type/urgency/title 各自来源},
        "missing":  ["location" | "scope"],          # 缺一不可才允许建单
        "ask":      "追问话术（老人能懂的一句话）",
        "suggestion": {location, issue_type, urgency},  # 系统建议（未确认，仅供展示）
        "note":     "为什么这样判定（给页面/答复用）",
      }
    """
    profile = profile or {}
    raw = (text or "").strip()
    p = _parse_fragments(raw)
    structural, room = p["structural"], p["room"]
    room_weak, public, landmark = p["room_weak"], p["public"], p["landmark"]
    has_building = any(re.fullmatch(rf"{_NUM}(号楼|栋|楼)", f) for f in structural)
    has_specific = any(re.fullmatch(rf"{_NUM}(号楼|栋|楼|单元|门|层)", f) for f in structural)

    # ---- 责任范围（室内/室外/不确定）----
    if confirmed_scope in ("室内", "室外"):
        issue_type, scope_src = confirmed_scope, "user"
    elif (public or landmark) and not room:
        # 只提到公共部位（"我家"这类泛指不算室内信号）→ 室外
        issue_type, scope_src = "室外", "text"
    elif room and not (public or landmark):
        issue_type, scope_src = "室内", "text"
    elif room and (public or landmark):
        # **具体房间**与公共部位同时出现（"厨房漏水，楼道也湿了"）→ 责任范围不猜，交给老人
        issue_type, scope_src = "", "suggestion"
    elif room_weak:
        # 只有"我家/家里"这种泛指 → 是室内，但哪个房间还不知道（位置会因此缺）
        issue_type, scope_src = "室内", "suggestion"
    else:
        issue_type, scope_src = "", "suggestion"

    # ---- 位置 ----
    # 什么样的位置才"可派单"：
    #   · 室内：房间即可（老人住哪社区有资料），楼栋/单元优先用原话里的；
    #   · 公共：必须能指到具体楼栋/单元/楼层，**或者**本身就是社区级地标（广场/绿地/大门…）。
    #     ——这一点是 B1 的关键：只说"楼道灯坏了"，网格员不知道去哪个楼，等于没报。
    if issue_type == "室内":
        locatable = bool(room)
    elif issue_type == "室外":
        locatable = bool(landmark) or (bool(public) and has_specific)
    else:
        locatable = False   # 责任范围都没定，位置也不急着猜（先问清楚）
    place = room or public or landmark
    suggestion_location = "".join(structural) + place if locatable else ""
    b = str(profile.get("building") or "").strip()
    u = str(profile.get("unit") or "").strip()
    # 老人没说楼栋、但**登记资料里有住址**时的候选位置（是资料，不是猜）
    profile_candidate = f"{b}{u}{place}".strip() if (b or u) else ""
    if confirmed_location.strip():
        location, loc_src = confirmed_location.strip(), "user"
    else:
        location, loc_src = suggestion_location, "text"
        if not has_building and profile_candidate:
            if issue_type == "室内":
                # 室内：登记住址**就是**他家 → 可以直接用（不存在"其实是别人家"的问题）
                location, loc_src = profile_candidate, "profile"
            elif issue_type == "室外" and public and not landmark and not location:
                # 室外：老人说的可能是**别人家那栋楼**的楼道 → **必须确认**，
                # 只把登记住址作为**候选**呈现（页面会问"是不是您家这栋？"）。
                # 这就是 B1 的验收点：不许把"楼道灯坏了"直接建单。
                suggestion_location = profile_candidate
                location, loc_src = "", "none"
    # 太粗的位置不算位置（"社区""小区"派不了单）；空位置也要如实标来源
    if location in _TOO_COARSE:
        location, loc_src = "", "none"
    if not location:
        loc_src = "none"

    # ---- 紧急程度 ----
    if confirmed_urgency in ("一般", "中等", "紧急"):
        urgency, urg_src = confirmed_urgency, "user"
    elif any(w in raw for w in _URGENT_WORDS):
        urgency, urg_src = "紧急", "suggestion"
    else:
        urgency, urg_src = "一般", "default"

    missing: list[str] = []
    if not location:
        missing.append("location")
    if issue_type not in ("室内", "室外"):
        missing.append("scope")
    # 追问顺序：先说清楚"是家里还是公共地方"（决定谁负责、要不要收费），再问具体位置。
    # 两个都缺时一次问完 —— 老人一次性说"5号楼二层楼道"就能同时答上两个问题。
    if "scope" in missing and "location" in missing:
        ask = _ASK_BOTH
    elif "scope" in missing:
        ask = _ASK_SCOPE
    elif "location" in missing:
        # 有登记住址候选时，把问题问成"是不是您家这栋"——老人点一下就行，不用打字
        if suggestion_location:
            ask = f"您说的是哪栋楼的{place or '地方'}？如果是您家这栋（{suggestion_location}），确认一下就行。"
        else:
            ask = _ASK_LOCATION
    else:
        ask = ""

    return {
        "fields": {
            "title": raw[:80],
            "description": raw,
            "location": location,
            "issue_type": issue_type,
            "urgency": urgency,
        },
        "sources": {
            "title": "text", "description": "text",
            "location": loc_src, "issue_type": scope_src, "urgency": urg_src,
        },
        "suggestion": {
            "location": suggestion_location or (structural and "".join(structural) + place) or "",
            "issue_type": issue_type or ("室外" if (public or landmark) else ("室内" if room else "")),
            "urgency": "紧急" if any(w in raw for w in _URGENT_WORDS) else "一般",
        },
        "missing": missing,
        "ask": ask,
        "note": (
            "位置与责任范围都齐了，可以确认上报。" if not missing
            else "还差必填信息，**不能建单**（缺位置的工单没人能去修，等于没报）。"
        ),
    }


def build_report_confirm_payload(text: str, profile: dict | None,
                                 confirmed_location: str = "",
                                 confirmed_scope: str = "",
                                 confirmed_urgency: str = "") -> tuple[bool, dict, str]:
    """提交前的**统一闸门**：返回 `(可提交, 字段, 提示语)`。

    缺必填 → `(False, {...}, 追问话术)`，调用方**必须**把提示语原样告诉老人，且不得建单。
    """
    r = extract_report_fields(text, profile, confirmed_location, confirmed_scope, confirmed_urgency)
    if r["missing"]:
        return False, r, r["ask"]
    if len((r["fields"]["description"] or "").strip()) < 5:
        return False, r, "问题描述太短了，请再多说两个字（比如：厨房水管漏水了）"
    return True, r, ""
