# agent/roles/business_agents.py
"""5 个业务角色 Agent（薄壳）：报修调度员 / 提案协商员 / 政策专员 / 健康顾问 / 通知管理员。
process() 复用现有数据层与规则引擎（web_agent_service / data/*），不复制业务逻辑。
会话状态（追问/草稿）存黑板：user:{uid}:state / user:{uid}:{draft_key}。
"""
import logging

from agent import web_agent as A
from agent.roles.base import BaseAgent

_log = logging.getLogger(__name__)


def _llm_polish_health_suggestion(tags: str, base: str) -> str:
    """可选 LLM 润色健康协商建议（P1-3）。

    仅在 LLM_NEGOTIATION=1 且配置了 key 时走真实 DeepSeek（WS2：统一走 agent.llm_client）；
    产出强制过 Verifier（健康规则集），BLOCK/WARN 一律回退规则文案（幻觉兜底）。
    任何异常/无 key/熔断一律回退规则文案。
    """
    import os

    if os.getenv("LLM_NEGOTIATION", "0") != "1":
        return base
    from config import DEEPSEEK_API_KEY
    if not DEEPSEEK_API_KEY:
        return base
    from agent.llm_client import chat
    r = chat(
        [{"role": "system", "content":
          "你是社区健康顾问。根据天气预警标签，用一句不超过50字的口语化中文给出老年人"
          "防护建议。不做诊断、不推荐药物、紧急情况提示就医。"},
         {"role": "user", "content": f"天气预警：{tags}。基础建议：{base}"}],
        module="健康润色", purpose=f"{tags}/{base[:40]}",
        temperature=0.3, max_tokens=120, timeout=8,
    )
    if not r["ok"]:
        return base
    text = r["text"].strip()
    # 幻觉防线：健康规则集校验，不过则回退规则文案
    from agent.verifier import Verifier
    v = Verifier().verify({"reply": text}, biz_type="health")
    if v["verdict"] == "pass":
        return text
    return base


def _extract_repair_fields(text: str, uid) -> dict:
    """从这句话（＋服务端登记资料）抽取位置与责任范围（卡10：字段来源可解释）。

    与**老人端共用**同一套契约 `utils/elderly_report`（一套规则、两种入口，别各写一份）：
      · 拿到位置 → 不再问"哪个楼/哪一层"；
      · 责任范围明确（室内/室外）→ 不再问"家里还是公共区域"；
      · 拿不准就不给结论（`extract_report_fields` 会把它放进 `missing`），由状态机继续追问。
    异常一律退化成"什么都没抽到"（宁可多问一句，也不猜）。
    """
    import logging
    _log = logging.getLogger(__name__)
    # 资料查询与文本抽取**分开兜底**：查不到资料只是少了"补齐楼栋"的能力，
    # 绝不能因此把用户**已经说出来的位置**一起丢掉（旧写法一个 try 包住两件事，
    # 数据库一抖就退化成"什么都没抽到"，用户被白问一遍）。
    prof: dict = {}
    if uid:
        try:
            from data.db_user import get_user_by_id
            row = get_user_by_id(uid) or {}
            prof = {"building": row.get("building") or "", "unit": row.get("unit") or "",
                    "community": row.get("community") or ""}
        except Exception as e:  # noqa: BLE001
            _log.warning("读取登记资料失败（仅影响用资料补齐位置）：%s", e)
    try:
        from utils.elderly_report import extract_report_fields
        r = extract_report_fields(text, prof)
        return {"location": r["fields"]["location"], "type": r["fields"]["issue_type"],
                "sources": r["sources"], "missing": r["missing"]}
    except Exception as e:  # noqa: BLE001 — 抽取失败不阻断对话，但要留痕
        _log.warning("报修字段抽取失败（按什么都没抽到处理）：%s", e)
        return {"location": "", "type": "", "sources": {}, "missing": ["location", "scope"]}


def _state_key(uid):
    return f"user:{uid}:state"


def _draft_key(uid, name):
    return f"user:{uid}:{name}"


# ---- 卡8 / v3 卡4：判断这一句是"回答刚才的追问"还是"新的一件事" ----
# 为什么必须有它：老人在**上一件事还没确认完**时又说了一件新事（很常见：先说家里漏水，
# 又想起楼道灯坏），状态机原来会把新句子当成"对上一个问题的回答"，
# 于是**把新位置合并进旧草稿** → 确认卡里出现"上一件事的描述 + 这一件事的位置"的混合体。
# 判据刻意保守（宁可多问一句，也不猜）：
#   · 短句且不含问题描述特征 → 当成回答（"家里"、"公共区域"、"紧急"）；
#   · 长句或含问题特征（坏/漏/堵/不亮/停…）→ 当成**新报修**，另起草稿并说清旧草稿的去向。
_PROBLEM_WORDS = ("坏", "漏", "堵", "不亮", "不亮", "停", "坏掉", "破", "冒", "响", "塌",
                  "脱落", "松动", "积水", "堵住", "异响", "不转", "不制冷", "不热", "没水", "没电",
                  # 2026-09-30 补：这些是**问题形态**（"窗户也关不上""门打不开""灯不响"），
                  # 老人常用来描述**第二件事**；不补的话会被当成"对上一个问题的回答"（实测踩到：
                  # 「窗户也关不上」被当成位置补充填进了上一件的草稿）。
                  "关不上", "打不开", "不响", "不下水", "不通", "没反应", "滴水", "闪")


def _is_new_repair_utterance(text: str, step: str) -> bool:
    """这一句是不是"又一件新事"（而不是在回答追问）。`step` 决定"期望的回答"长什么样。"""
    t = (text or "").strip()
    if not t:
        return False
    if any(k in t for k in _PROBLEM_WORDS):
        return True
    # 期待作答时，短句视为回答（"家里" / "公共区域" / "紧急" / "不着急"）
    if step == "ask_type" and len(t) <= 8:
        return False
    if step == "ask_urgency" and len(t) <= 12:
        return False
    # 确认阶段：只有明确的确认/取消词才算在流程里，其余长句按新事处理
    if step == "confirm" and len(t) <= 6:
        return False
    return len(t) > 12


# 报修地点归一类：区分「室内(家里)」vs「室外(公共区域)」。
# 判据覆盖常见表述；无明确地点词时按上下文默认（默认室内，更贴合老人报修"家里"场景）。
# 注意：室外词优先，避免"我家楼下"这类含"家"又含室外词的场景判错。
_INDOOR_WORDS = ("内", "家", "屋", "卧室", "客厅", "厨房", "卫生间", "厕所", "浴室", "阳台")
_OUTDOOR_WORDS = ("公共", "楼道", "走廊", "楼梯", "楼下", "广场", "过道", "门口", "外面", "室外", "花园", "车库", "电梯")


# 明确"取消"的用词：**只有这些词**才会取消报修草稿（其余一律不取消，见确认分支）
_CANCEL_WORDS = ("算了", "取消", "不要了", "先不弄了", "不报了", "撤了", "不修了", "别报了")


def _apply_repair_supplement(text: str, draft: dict, uid) -> list[str]:
    """确认卡阶段收到的"补充信息" → 回填草稿；返回被更新的字段说明（没识别出则为空）。

    为什么需要（2026-09-30 实测）：老人在确认卡上往往不是回"确认"，而是补充/修正——
    「是5号楼二层楼道」「我住在五号楼」「其实是我家里」「挺急的」。
    旧行为把这些当"非确认词"→ 清空草稿并回"已取消"（等于把报修弄丢，比"没听懂"更有害）；
    现在能用就用上：责任范围/紧急程度按短句判，位置走**与老人端同一套抽取契约**。
    """
    filled: list[str] = []
    t = (text or "").strip()
    if t in ("家里", "室内", "我家", "屋里"):
        draft["type"] = "室内"
        filled.append("责任范围=您家里")
    elif t in ("公共", "公共区域", "室外", "楼道", "外面"):
        draft["type"] = "室外"
        filled.append("责任范围=公共地方")
    if any(k in t for k in ("不着急", "不急", "一般", "有空再说")):
        draft["urgency"] = "一般"
        filled.append("紧急程度=一般")
    elif any(k in t for k in ("紧急", "很急", "马上", "尽快", "快点")):
        draft["urgency"] = "紧急"
        filled.append("紧急程度=紧急")
    try:
        from utils.elderly_report import extract_report_fields
        prof = {}
        try:
            from data.db_user import get_user_by_id
            row = get_user_by_id(uid) or {}
            prof = {"building": row.get("building") or "", "unit": row.get("unit") or ""}
        except Exception as e:  # noqa: BLE001 — 读不到资料只是少了"补齐楼栋"，不影响回填
            _log.warning("确认阶段读取登记资料失败（仅影响用资料补齐位置）：%s", e)
        r = extract_report_fields(t, prof)
        loc = (r["fields"].get("location") or "").strip()
        if not loc:
            # 老人只说了楼栋/楼层（"我住在五号楼""是二层"）时，extract_report_fields 因为
            # 责任范围未定而给不出可派单位置；但**这句是老人明确说的**，应当优先于登记资料
            # （实测：说"我住在五号楼"却用了资料里的"3号楼2单元501"，等于没听老人说话）。
            frag = _structural_fragment(t)
            if frag:
                loc = frag
        # extract_report_fields 只会给出"能派单"的位置（太笼统的判为空）→ 这里可以直接用
        if loc and loc != (draft.get("location") or ""):
            draft["location"] = loc
            draft.setdefault("sources", {})["location"] = "user"
            if r["fields"].get("issue_type"):
                draft["type"] = r["fields"]["issue_type"]
            filled.append(f"位置=「{loc}」")
    except Exception as e:  # noqa: BLE001 — 解析失败就不回填（走"重新问一遍"分支）
        _log.warning("确认阶段解析补充信息失败：%s", e)
    return filled



def _structural_fragment(text: str) -> str:
    """从一句话里取出"楼栋/单元/楼层"片段（老人补充位置时最常说的那部分）。

    只认**明确的结构片段**（5号楼 / 3单元 / 二层），不做推断；取不到就返回空串。
    """
    try:
        from utils.elderly_report import _BUILDING_RE, _FLOOR_RE, _UNIT_RE
    except Exception:  # noqa: BLE001 — 拿不到正则就退化成"不补位置"
        return ""
    t = text or ""
    parts: list[str] = []
    for rx, suffix in ((_BUILDING_RE, "号楼"), (_UNIT_RE, "单元"), (_FLOOR_RE, "层")):
        m = rx.search(t)
        if m:
            num = m.group(1)
            from utils.elderly_report import _cn_to_int
            try:
                num = _cn_to_int(num)
            except Exception:  # noqa: BLE001
                pass
            frag = f"{num}{suffix}"
            if frag not in parts:
                parts.append(frag)
    return "".join(parts)

def _classify_repair_location(text: str) -> str:
    """根据用户描述判断报修地点是室内还是室外。"""
    t = text or ""
    # 室外词优先命中（如"我家楼下广场"含"家"也含"广场"，应判室外）
    if any(w in t for w in _OUTDOOR_WORDS):
        return "室外"
    if any(w in t for w in _INDOOR_WORDS):
        return "室内"
    return "室内"  # 默认室内（老人常直接说"家里漏水"）


def _classify_repair_urgency(text: str, state_urgent: bool | None) -> str:
    """判断紧急程度。显式写紧急/急（排除"不着急/别急"否定）→ 紧急；否则按上下文标记兜底。"""
    t = text or ""
    # 否定词优先：不着急/别急/不用急 → 一般
    if any(k in t for k in ("不着急", "别急", "不用急", "不急", "缓缓", "有空再说", "不紧")):
        return "一般"
    if any(k in t for k in ("紧急", "急", "很急", "马上", "立刻", "尽快", "快点")):
        return "紧急"
    return "紧急" if state_urgent else "一般"


# 安全隐患词 → 隐患类型（P2 扩展2：报修中发现生命财产风险，协商通知管理员升级）。
# 与 web_agent 意图词一致；只用复合/明确风险词，避免"燃气缴费/触电急救"等误路由。
_HAZARD_MAP = [
    (("燃气泄漏", "煤气泄漏", "燃气味", "煤气味", "漏气"), "燃气泄漏"),
    (("漏电", "冒火花"), "漏电隐患"),
    (("起火", "着火", "冒烟", "烧焦味", "焦味", "浓烟"), "火灾风险"),
]


def _detect_hazard(text: str) -> str:
    """识别报修描述中的安全隐患类型，无则返回空串。"""
    t = text or ""
    for words, label in _HAZARD_MAP:
        if any(w in t for w in words):
            return label
    return ""


# 健康词表（从 HealthAdvisorAgent.process 内联提取，供协商共用；行为不变）
_DISCOMFORT_WORDS = ("不舒服", "难受", "头晕", "头疼", "胸闷", "心慌", "没力气",
                     "胸痛", "呼吸困难", "意识不清", "大出血", "抽搐")
_URGENT_SYMPTOM_WORDS = ("胸痛", "呼吸困难", "意识不清", "大出血", "抽搐")
# 对健康有影响的预警类型（扩展1：健康顾问反向查询天气守护员时过滤用）
_WEATHER_HEALTH_TYPES = ("高温", "寒潮", "暴雨", "台风", "大雾", "雷电", "重污染")


# ---------------------------------------------------------------------------
# 报修调度员
# ---------------------------------------------------------------------------

class RepairDispatchAgent(BaseAgent):
    key = "repair_dispatch"
    name = "报修调度员"
    icon = "🔧"
    role_desc = "报修全流程：草稿、创建、分派、跟踪、反馈"
    audience = "居民/老人"
    human_stop = "生成工单前必须用户确认"
    tools_whitelist = ["db_repair.submit_issue", "db_repair.get_issues", "撤回引导"]

    def process(self, ctx: dict) -> dict:
        from agent.web_agent_service import _exec_report
        text = ctx.get("user_input") or ""
        uid = ctx.get("uid"); name = ctx.get("name") or "居民"
        st = self._read(_state_key(uid)) or {}
        draft = self._read(_draft_key(uid, "work_order_draft"))
        # 会话恢复（落库后黑板可能无 draft）：有 step 但无 draft 时补空草稿
        if draft is None and st.get("step"):
            draft = {}

        # 追问/确认阶段
        step = st.get("step")
        # 卡8 / v3 卡4：**上一件事还没走完，老人又说了新的一件事** →
        # 绝不把它当成"对上一个问题的回答"合并进旧草稿（那会生成"旧描述 + 新位置"的混合工单）。
        # 处理：旧草稿如实丢弃（留痕），按新的一句话重新起草，并明确告诉老人。
        superseded = ""
        if step and draft and _is_new_repair_utterance(text, step):
            superseded = str(draft.get("desc") or "")[:40]
            _log.info("报修草稿被新报修顶替（旧：%s）→ 按新描述重新起草", superseded)
            self.bb.unlock(_draft_key(uid, "work_order_draft"))
            self._write(_draft_key(uid, "work_order_draft"), None, lock=False)
            try:
                from data.db_draft import delete_draft
                delete_draft(uid, "work_order_draft")   # 库里也别留，免得下一轮回填
            except Exception as e:  # noqa: BLE001
                _log.warning("清理被顶替的草稿失败：%s", e)
            draft = None
            st.clear()
            step = None
        # 老人可能在任何一步才补充位置/责任范围（实测：「我住在五号楼」是在问"急不急"时说的，
        # 只认确认阶段的话就漏了，最后用登记资料的门牌建单——等于没听老人说话）。
        # 所以只要草稿还在、这句话不是确认/取消词，就先尝试把补充吸收进草稿（拿不准就不动）。
        if draft is not None and step and text not in _CANCEL_WORDS:
            _apply_repair_supplement(text, draft, uid)

        if step == "ask_type":
            draft["type"] = _classify_repair_location(text)
            st["step"] = "ask_urgency" if draft.get("urgency") is None else "confirm"
        elif step == "ask_urgency":
            draft["urgency"] = _classify_repair_urgency(text, st.get("urgent"))
            st["step"] = "confirm"
        elif step == "confirm":
            if text in ("确认", "确认提交", "提交", "对", "是", "对，提交", "好的", "好"):
                draft["urgency"] = draft.get("urgency") or "一般"  # 确认前兜底
                r_text, status, iid = _exec_report(uid, name, draft)
                self.bb.unlock(_draft_key(uid, "work_order_draft"))
                self._write(_draft_key(uid, "work_order_draft"), None, lock=False)
                st.clear()
                self._write(_state_key(uid), st)
                return self._reply(r_text, status, "报修", related_id=iid,
                                   chain_note="用户确认，工单已创建")
            # ⚠️ 2026-09-30 修（用户实测反馈引出，三处真问题之一）：这里原来是
            # "不是确认词 → 清空草稿 + 回『已取消，没有生成工单』"。
            # 于是老人拿到确认卡后说「窗户也关不上」「我住在五号楼」，草稿被**静默丢掉**，
            # 还被告知"已取消"——他根本没说要取消，等于把一次报修弄丢了（比"没听懂"更有害）。
            # 现在分三种情况处理，唯一会取消的是**明确取消词**：
            if text in _CANCEL_WORDS:
                st.clear()
                self._write(_state_key(uid), st)
                self.bb.unlock(_draft_key(uid, "work_order_draft"))
                self._write(_draft_key(uid, "work_order_draft"), None, lock=False)
                try:
                    from data.db_draft import delete_draft
                    delete_draft(uid, "work_order_draft")
                except Exception as e:  # noqa: BLE001
                    _log.warning("取消报修时清理草稿失败：%s", e)
                return self._reply("已取消，没有生成工单。", "已取消", "报修", chain_note="用户取消")
            # ② 是补充信息（位置/责任范围/紧急程度）→ 回填后重新确认（不丢草稿）
            filled = _apply_repair_supplement(text, draft, uid)
            if filled:
                self._write(_draft_key(uid, "work_order_draft"), draft, lock=False)
                self._write(_state_key(uid), st)
                return self._reply(
                    f"好的，已按您说的更新：{'、'.join(filled)}。\n"
                    f"请您确认报修信息：\n· 问题：{draft.get('desc', '')[:60]}\n"
                    f"· 位置：{draft.get('location') or draft.get('type') or '（待补充）'}\n"
                    f"· 分类：{draft.get('type')}\n· 紧急程度：{draft.get('urgency') or '一般'}",
                    "需确认", "报修",
                    actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
                    chain_note="确认阶段收到补充信息：已回填并重新确认")
            # ③ 既不是确认、也不是可用补充、也没说取消 → **重新问一遍，草稿保留**
            self._write(_draft_key(uid, "work_order_draft"), draft, lock=False)
            self._write(_state_key(uid), st)
            return self._reply(
                "这条报修我**还没有提交**（您刚说的我先记下了）。\n"
                "· 要提交：说「确认提交」，或点下面的按钮\n"
                "· 要改位置/责任范围：直接说，比如「是5号楼二层楼道」\n"
                "· 不要了：说「取消」",
                "需确认", "报修",
                actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
                chain_note="确认阶段未收到确认词：重新询问（草稿保留）")

        # 新报修
        if draft is None:
            # P2 扩展2：安全隐患 → 紧急直确认 + 安全引导 + 协商通知管理员（跳过"家里/公共区域"追问）
            hazard = _detect_hazard(text)
            if hazard:
                draft = {"desc": text, "type": _classify_repair_location(text), "urgency": "紧急"}
                st["step"] = "confirm"
                st["intent"] = "repair"
                self._write(_draft_key(uid, "work_order_draft"), draft, lock=False)
                self._write(_state_key(uid), st)
                self._post("notification_manager", "notify", {
                    "event": "safety_hazard", "hazard": hazard,
                    "location": draft["type"], "desc": text[:60],
                })
                return self._reply(
                    f"🚨 这属于{hazard}，请先确保安全：远离现场、不要开关电器、"
                    f"{'开窗通风、' if hazard == '燃气泄漏' else ''}到安全位置，必要时拨打 119。\n\n"
                    f"已按「紧急」为您准备好工单，确认后立即通知负责人处理：\n"
                    f"· 问题：{text[:50]}\n· 位置：{draft['type']}\n· 紧急程度：紧急",
                    "需确认", "报修",
                    actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
                    chain_note=f"安全隐患（{hazard}）：紧急直确认 + 主动协商通知管理员")
            draft = {"desc": text, "type": "室内", "urgency": "紧急" if st.get("urgent") else None}
            # 卡10（字段来源与追问策略）：**只追问必要信息** —— 先用同一套抽取契约看一眼
            # 这句话里已经有什么（位置/责任范围），说清了就不再问那一句；
            # 同时把"每个字段从哪来"记进草稿，确认卡片上标出来（未确认的不算业务事实）。
            ex = _extract_repair_fields(text, uid)
            if ex.get("location"):
                draft["location"] = ex["location"]
            if ex.get("type"):
                draft["type"] = ex["type"]
            draft["sources"] = ex.get("sources") or {}
            if ctx.get("role") == "elderly":
                draft["urgency"] = draft["urgency"] or "一般"
                st["step"] = "confirm"
            elif ex.get("type") and ex.get("location"):
                # 位置与责任范围都清楚了 → 跳过"家里还是公共区域"，只问紧急程度
                st["step"] = "ask_urgency" if draft["urgency"] is None else "confirm"
            else:
                st["step"] = "ask_type"
        else:
            st["step"] = st.get("step") or "ask_type"
        st["intent"] = "repair"

        self._write(_draft_key(uid, "work_order_draft"), draft, lock=False)
        self._write(_state_key(uid), st)

        if st["step"] == "ask_type":
            return self._reply("是您家里还是公共区域？", "追问", "报修",
                               actions=[{"type": "buttons", "options": ["家里", "公共区域"]}],
                               chain_note="追问分类")
        if st["step"] == "ask_urgency":
            return self._reply("是紧急情况吗？", "追问", "报修",
                               actions=[{"type": "buttons", "options": ["紧急", "一般"]}],
                               chain_note="追问紧急程度")
        urgent_txt = "紧急" if draft.get("urgency") == "紧急" else "一般"
        prefix = ""
        if superseded:
            # 诚实告知：上一次那条没提交的报修**已被这条替换**（不是"顺手改一改"，是两件事）
            prefix = (f"（说明：刚才那条「{superseded}」还没确认，我按您现在说的这件事重新开了工单草稿，"
                      f"刚才那条没有提交。）\n")
        # 字段来源可解释（卡10）：位置来自"您说的"还是"您的登记资料"，让用户一眼能核
        src_label = {"text": "来自您说的话", "profile": "来自您的登记资料",
                     "user": "您确认的"}.get((draft.get("sources") or {}).get("location", ""), "")
        loc_line = f"\n· 位置：{draft['location']}" + (f"（{src_label}）" if src_label else "") \
            if draft.get("location") else ""
        return self._reply(
            f"{prefix}请您确认报修信息：\n· 问题：{draft.get('desc', '')[:60]}{loc_line}\n"
            f"· 分类：{draft.get('type')}\n· 紧急程度：{urgent_txt}",
            "需确认", "报修",
            actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
            chain_note="生成草稿，等待用户确认")


# ---------------------------------------------------------------------------
# 提案协商员
# ---------------------------------------------------------------------------

class ProposalCollabAgent(BaseAgent):
    key = "proposal_collab"
    name = "提案协商员"
    icon = "💡"
    role_desc = "提案提交、公示、投票、执行、反馈"
    audience = "居民"
    human_stop = "执行决定必须负责人批准"
    tools_whitelist = ["db_proposal.submit_proposal", "db_proposal.get_proposals"]

    def process(self, ctx: dict) -> dict:
        from agent.web_agent_service import _exec_proposal
        text = ctx.get("user_input") or ""
        uid = ctx.get("uid"); name = ctx.get("name") or "居民"
        st = self._read(_state_key(uid)) or {}
        draft = self._read(_draft_key(uid, "proposal_draft"))
        if draft is None and st.get("step"):
            draft = {}

        step = st.get("step")
        if step == "ask_public":
            draft["is_public"] = 1 if ("公开" in text or "公" in text) else 0
            st["step"] = "confirm"
        elif step == "confirm":
            if text in ("确认", "确认提交", "提交", "对", "是"):
                r_text, status, pid = _exec_proposal(uid, name, draft)
                self.bb.unlock(_draft_key(uid, "proposal_draft"))
                self._write(_draft_key(uid, "proposal_draft"), None, lock=False)
                st.clear()
                self._write(_state_key(uid), st)
                return self._reply(r_text, status, "提案", related_id=pid,
                                   chain_note="用户确认，提案已提交")
            # ⚠️ 同类问题（2026-09-30）：非确认词不等于取消 —— 只有明确取消词才取消，
            # 其余重新问一遍，草稿保留（老人在确认卡上常说的是补充，不是"取消"）。
            if text in _CANCEL_WORDS:
                st.clear()
                self._write(_state_key(uid), st)
                self._write(_draft_key(uid, "proposal_draft"), None, lock=False)
                return self._reply("已取消，没有生成提案。", "已取消", "提案", chain_note="用户取消")
            self._write(_draft_key(uid, "proposal_draft"), draft, lock=False)
            self._write(_state_key(uid), st)
            return self._reply(
                "这条提案我**还没有提交**。\n· 要提交：说「确认提交」\n· 不要了：说「取消」",
                "需确认", "提案",
                actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
                chain_note="确认阶段未收到确认词：重新询问（草稿保留）")

        if draft is None:
            draft = {"desc": text}
            st["step"] = "ask_public"
        else:
            st["step"] = st.get("step") or "ask_public"
        st["intent"] = "proposal"

        self._write(_draft_key(uid, "proposal_draft"), draft, lock=False)
        self._write(_state_key(uid), st)
        if st.get("step") == "confirm":
            pub = "公开" if draft.get("is_public") else "私有"
            return self._reply(
                f"请您确认提案信息：\n· 内容：{draft.get('desc', '')[:60]}\n· 公开方式：{pub}",
                "需确认", "提案",
                actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
                chain_note="生成提案草稿，等待用户确认")
        return self._reply("您想公开还是私有？（公开会进入公示投票）", "追问", "提案",
                           actions=[{"type": "buttons", "options": ["公开", "私有"]}],
                           chain_note="追问公开/私有")


# ---------------------------------------------------------------------------
# 政策专员（无引用不回答）
# ---------------------------------------------------------------------------

class PolicyExpertAgent(BaseAgent):
    key = "policy_expert"
    name = "政策专员"
    icon = "📖"
    role_desc = "政策问答，强制引用知识库，无引用不回答"
    audience = "居民/老人"
    human_stop = "无引用不回答，转人工"
    tools_whitelist = ["db_policy.ask_question", "db_policy.get_knowledge_list"]

    def process(self, ctx: dict) -> dict:
        from data.db_policy import ask_question
        text = ctx.get("user_input") or ""
        uid = ctx.get("uid")
        r = ask_question(uid, text, source="Agent")
        if r.get("matched"):
            # 强制引用：附带知识条目标题（spec：无引用不回答）
            title = (r.get("knowledge") or {}).get("title", "")
            answer = r.get("auto_answer", "")
            ref = f"\n\n📎 参考：《{title}》" if title else ""
            return self._reply(f"✅ 已为您找到答案：\n{answer}{ref}", "成功", "政策问答",
                               related_id=r.get("question_id"),
                               actions=[{"type": "buttons", "options": ["有帮助", "无帮助"]}],
                               chain_note="命中知识库，附带引用")
        return self._reply(f"暂未找到答案。{r.get('manual_text', '')}", "needs_human", "政策问答",
                           related_id=r.get("question_id"),
                           actions=[{"type": "confirm_transfer", "label": "转人工咨询",
                                     "related_id": r.get("question_id")}],
                           chain_note="未命中知识库：转人工（无引用不回答）")


# ---------------------------------------------------------------------------
# 健康顾问（不诊断，仅给建议）
# ---------------------------------------------------------------------------

class HealthAdvisorAgent(BaseAgent):
    key = "health_advisor"
    name = "健康顾问"
    icon = "🏥"
    role_desc = "健康咨询、就医指引、疾病预防提醒（不诊断，仅给建议）"
    audience = "居民"
    human_stop = "不诊断，仅给建议；紧急症状提示就医"
    tools_whitelist = ["db_health_content.get_published_contents", "紧急求助引导"]

    def process(self, ctx: dict) -> dict:
        text = ctx.get("user_input") or ""
        # 身体不适 → 提示联系社区/家属 + 紧急求助（不诊断）
        # 紧急症状（胸痛/呼吸困难等）独立触发，确保即使不在普通不适词表也转人工（P1-D3-01 评测暴露）
        if any(k in text for k in _DISCOMFORT_WORDS):
            # 疑似紧急症状 → 主动协商：handoff 接待员转人工
            urgent_symptom = any(k in text for k in _URGENT_SYMPTOM_WORDS)
            if urgent_symptom:
                self._post("receptionist", "handoff", {
                    "event": "urgent_symptom", "reason": "疑似紧急症状，需人工确认",
                    "suggestion": "建议立即就医或拨打 120",
                })
                return self._reply(
                    "您描述的疑似紧急症状需要专业人士确认。社区顾问不做诊断，请及时就医，必要时拨打 120。已为您转人工跟进。",
                    "needs_human", "健康顾问",
                    actions=[{"type": "buttons", "options": ["拨打 120", "联系社区", "紧急求助"]},
                             {"type": "navigate", "to": "/resident/health", "label": "去健康防护"}],
                    chain_note="疑似紧急症状：转人工（停机点）")
            # P2 扩展1：非紧急不适 + 生效天气预警 → 主动查询天气守护员（健康→天气反向协商）
            try:
                from data.db_weather import get_active_alerts
                alerts = [a for a in get_active_alerts()
                          if a.get("alert_type") in _WEATHER_HEALTH_TYPES]
            except Exception:
                alerts = []
            if alerts:
                tags = "、".join(f"{a.get('alert_type')}{a.get('level')}" for a in alerts[:2])
                symptom = next((k for k in _DISCOMFORT_WORDS if k in text), "")
                self._post("weather_guardian", "task_request", {
                    "event": "health_weather_risk_query",
                    "symptom": symptom, "tags": tags, "question": text[:60],
                })
            return self._reply(
                "您感觉不舒服吗？请不要着急。社区顾问不做诊断，如果症状持续或加重，请及时就医。"
                "需要的话，可以帮您联系社区或家属，也可以长按红色紧急求助按钮。",
                "成功", "健康顾问",
                actions=[{"type": "navigate", "to": "/elderly/home", "label": "紧急求助（长按3秒）"},
                         {"type": "buttons", "options": ["联系社区", "查天气"]}],
                chain_note="身体不适：不做诊断，提示就医与求助")
        # 健康知识/疾病预防 → 返回已发布内容
        try:
            from data.db_health_content import get_published_contents
            rows = get_published_contents(limit=3)
            if rows:
                lines = [f"· {r.get('title', '')}" for r in rows]
                return self._reply("为您推荐最近的健康内容：\n" + "\n".join(lines), "成功", "健康顾问",
                                   actions=[{"type": "navigate", "to": "/resident/health", "label": "去健康防护"}],
                                   chain_note="推荐已发布健康内容")
        except Exception:
            pass
        return self._reply("健康咨询请到「健康防护」提交，负责人会在 24 小时内回复。", "成功", "健康顾问",
                           actions=[{"type": "navigate", "to": "/resident/health", "label": "去健康防护"}],
                           chain_note="引导到健康咨询表单")

    def process_negotiation(self, msg: dict) -> dict | None:
        """健康顾问处理协商（真协商 P2-A2-02）：天气守护员极端天气 → 健康风险评估。"""
        payload = msg.get("payload") or {}
        if payload.get("event") == "extreme_weather":
            tags = payload.get("tags", "")
            # 极端天气对老人有风险 → 建议升级通知（触发天气→通知管理员链路）
            escalate = any(k in tags for k in ("高温", "寒潮", "台风", "暴雨"))
            base = "提醒老人注意防暑/保暖，减少外出，备好常用药" if escalate else (payload.get("suggestion") or "")
            # P1-3：可选 LLM 润色建议文案（产出过 Verifier 健康规则集，BLOCK 回退规则文案）。
            # 注意：escalate 用原始确定性条件判定（tags 高危词），不依赖 LLM 措辞，保证守护员升级逻辑稳定。
            suggestion = _llm_polish_health_suggestion(tags, base)
            if escalate:
                return {
                    "accepted": True,
                    "reply": f"已根据天气预警准备健康提醒：{suggestion}",
                    "suggestion": suggestion,
                    "event": "extreme_weather",
                    "tags": tags,
                    "escalate": True,
                }
            return {"accepted": True, "reply": f"已根据天气预警准备健康提醒：{suggestion}",
                    "suggestion": suggestion, "event": "extreme_weather",
                    "tags": tags, "escalate": False}
        # P2 扩展1：天气守护员的风险评估回执（健康顾问发起反向查询的响应）
        if msg.get("type") == "task_response" and payload.get("event") == "health_weather_risk_confirmed":
            # WS5：真实分歧 → 仲裁 → 改写最终文案（不只留痕，进入用户可见回复）
            # 天气守护员评估"可正常活动/无直接风险"，但健康侧看到高危症状说明 → 应更保守。
            # 触发条件：天气评估低风险 + 高危症状（头晕/胸闷/心慌），或安全类症状（胸痛/呼吸困难）。
            symptom = payload.get("symptom") or ""
            low_risk = payload.get("risk_level") in ("none", "")
            high_risk_symptom = symptom in ("头晕", "胸闷", "心慌")
            safety_symptom = any(w in symptom for w in ("胸痛", "呼吸困难", "抽搐", "大出血"))
            if (low_risk and high_risk_symptom) or safety_symptom:
                try:
                    from agent.arbiter import Arbiter
                    arb = Arbiter().arbitrate({
                        "professional_domain": True,          # 专业判断以健康顾问为准
                        "safety_risk": bool(safety_symptom),  # 涉人身安全 → safety_first(human)
                        "agent": self.key,
                        "conflict_summary": (
                            "天气评估可正常活动/无直接风险，但健康侧判断症状需保守处理"
                            if not safety_symptom else
                            "天气评估无直接风险，但症状疑为紧急，需转人工确认"),
                    })
                    self._write("last_arbitration", arb)
                    decision = arb.get("decision")
                    # 仲裁结果进入用户可见协作提示（不再丢弃）
                    if decision == "human":
                        collab = ("【仲裁·转人工】该症状可能与天气无关且建议进一步确认，"
                                  "已升级人工/家属跟进，请及时就医。")
                        need_human = True
                    else:  # professional
                        collab = ("【仲裁·专业优先】尽管天气评估可正常活动，结合您的症状，"
                                  "健康侧建议以保守稳妥为主：减少外出、注意休息、早睡早起，"
                                  "症状持续请及时就医。")
                        need_human = False
                    return {"accepted": True,
                            "reply": collab, "need_human": need_human,
                            "arbitration": decision}
                except Exception:
                    pass
            return {"accepted": True}  # 无 reply：不重复合并文本，仅留执行链节点
        return None


# ---------------------------------------------------------------------------
# 通知管理员（紧急通知需负责人人工审核，Agent 不直接发布紧急通知）
# ---------------------------------------------------------------------------

class NotificationManagerAgent(BaseAgent):
    key = "notification_manager"
    name = "通知管理员"
    icon = "📢"
    role_desc = "通知创建、定时、发布；紧急通知需负责人审核"
    audience = "负责人"
    human_stop = "紧急通知二次确认；Agent 不直接发布紧急通知"
    tools_whitelist = ["db_notice.get_notices_with_stats", "通知发布引导"]

    def process(self, ctx: dict) -> dict:
        text = ctx.get("user_input") or ""
        # 紧急相关：Agent 不能直接发布，引导负责人手动
        if any(k in text for k in ("紧急", "预警", "停水", "停电")):
            return self._reply(
                "紧急通知需要负责人手动发布（含二次确认与置顶）。已为您打开通知管理页。",
                "成功", "通知管理员",
                actions=[{"type": "navigate", "to": "/grid/notices", "label": "去通知管理"}],
                chain_note="停机点：紧急通知必须负责人手动发布")
        # 普通通知：引导到发布页
        return self._reply("通知发布请到「通知管理」创建（支持定时与附件）。", "成功", "通知管理员",
                           actions=[{"type": "navigate", "to": "/grid/notices", "label": "去通知管理"}],
                           chain_note="引导到通知管理")

    def process_negotiation(self, msg: dict) -> dict | None:
        """通知管理员处理协商（真协商 P2-A2-02）：天气升级的预警通知草稿。

        停机点：紧急通知必须负责人手动发布——Agent 只生成草稿引导，不自动发布。
        """
        payload = msg.get("payload") or {}
        if payload.get("event") == "extreme_weather":
            # Codex 评审 I3 修复（2026-09-25）：这里**没有真的建通知草稿对象**（不写库、不返回草稿 id），
            # 说"已生成草稿"属于把建议说成事实。文案改为"建议生成…（待负责人在通知管理页创建并发布）"，
            # 与系统真实状态一致；等真正实现持久化草稿后再改回"已生成"。
            return {
                "accepted": True,
                "reply": "建议生成天气预警通知（含老人防护提示）：需负责人在通知管理页创建并确认后发布",
                "draft_ready": True,
            }
        # P2 扩展2：报修调度员上报安全隐患 → 建议生成紧急预警通知（仍由负责人创建后发布）
        if payload.get("event") == "safety_hazard":
            hazard = payload.get("hazard", "安全隐患")
            return {
                "accepted": True,
                "reply": f"【通知管理员】建议生成「{hazard}」紧急预警通知"
                         f"（提醒相关楼栋居民避险）：需负责人在通知管理页创建并确认后发布",
                "draft_ready": True, "hazard": hazard,
            }
        return None
