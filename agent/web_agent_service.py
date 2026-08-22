# -*- coding: utf-8 -*-
"""Web 版 Agent 服务：会话状态机 + 路由执行（api_web 端点调用）。

handle_chat(role, uid, name, text) → {
    reply: str,          # Agent 回复文本
    intent: str,         # 识别意图
    corrected: str,      # 纠正后文本（空=未纠正）
    routed: str,         # 路由结果描述
    status: str,         # 成功/失败/需确认/已取消
    related_id: int|None,# 关联业务编号
    actions: [dict],     # 前端动作：navigate / buttons / confirm_call / download
}
会话状态保存在本模块内存 dict（重启丢失，演示级；留痕已落库）。
"""
import logging

from agent import web_agent as A
from data import db_agent

_log = logging.getLogger(__name__)

# 会话状态：key = f"{role}:{uid}"
_SESSIONS: dict[str, dict] = {}


def _sess(role: str, uid: int | None) -> dict:
    key = f"{role}:{uid or 0}"
    if key not in _SESSIONS:
        _SESSIONS[key] = {"intent": None, "step": None, "data": {}, "pending_correct": None,
                          "draft": None, "pending_action": None}
    return _SESSIONS[key]


def _clear(role: str, uid: int | None) -> None:
    key = f"{role}:{uid or 0}"
    _SESSIONS.pop(key, None)


# ---------------------------------------------------------------------------
# 快捷回复（不进入状态机）
# ---------------------------------------------------------------------------

def _polite_reply() -> str:
    return "不客气，有需要随时找我。"


def _intro_reply() -> str:
    return "我是社区小助手，可以帮您报修、查政策、看天气、看通知，也可以帮您联系社区。"


def _help_reply(role: str) -> str:
    entries = A.quick_entries(role)
    return "我可以帮您：" + "、".join(entries) + "。直接对我说就行，或点击下方快捷按钮。"


# ---------------------------------------------------------------------------
# 路由执行（调用数据层，不复制业务逻辑）
# ---------------------------------------------------------------------------

def _exec_report(uid: int, name: str, data: dict) -> tuple[str, str, int | None]:
    """提交报修（草稿确认后）。data: title/type/urgency/location/desc/phone。"""
    from data.db_repair import submit_issue
    iid, hint = submit_issue(
        title=data.get("title") or data.get("desc", "")[:50],
        category="公共设施", issue_type=data.get("type", "室内"),
        location=data.get("location", "社区"),
        description=data.get("desc", ""),
        urgency=data.get("urgency", "一般"),
        reporter_name=name or "居民", reporter_phone=data.get("phone") or "13800000000",
        reporter_id=uid,
    )
    if iid <= 0:
        return "提交失败，请稍后重试。", "失败", None
    return f"已为您提交报修，工单号：WO{iid:08d}，负责人会尽快联系您。", "成功", iid


def _exec_proposal(uid: int, name: str, data: dict) -> tuple[str, str, int | None]:
    """提交提案（草稿确认后）。"""
    from data.db_proposal import submit_proposal
    pid, msg = submit_proposal(
        title=data.get("title", ""), description=data.get("desc", ""),
        category=data.get("category", "其他"),
        reporter_name=name or "居民", reporter_phone=data.get("phone") or "13800000000",
        is_public=data.get("is_public", 0), reporter_id=uid,
    )
    if pid <= 0:
        return f"提交失败：{msg}", "失败", None
    return f"已为您提交提案，提案编号：P{pid:08d}，进入审核流程。", "成功", pid


def _exec_policy(uid: int, text: str) -> tuple[str, str, int | None]:
    """政策问答（路由到知识库匹配）。"""
    from data.db_policy import ask_question
    r = ask_question(uid, text, source="Agent")
    if r.get("matched"):
        return f"✅ 已为您找到答案：\n{r.get('auto_answer', '')}", "成功", r.get("question_id")
    return f"暂未找到答案。{r.get('manual_text', '')}", "未匹配", r.get("question_id")


def _exec_weather(text: str) -> tuple[str, str, None]:
    """天气查询 + 生活建议。"""
    from data.db_weather import get_weather_for_display
    w = get_weather_for_display("")
    days = w.get("days") or []
    d = days[0] if days else {}
    tip = A.weather_tip(text)
    note = w.get("note") or ""
    return (f"今天天气：{d.get('condition', '')} {d.get('temp_low', '')}°~{d.get('temp_high', '')}°，"
            f"{d.get('wind', '')}，降水概率 {d.get('rain_prob', 0)}%{('。' + tip) if tip else ''}"
            f"{('。' + note) if note else ''}"), "成功", None


def _exec_notices(uid: int) -> tuple[str, str, None]:
    """通知查询：返回最近列表。"""
    from data.db_notice import get_visible_notices
    rows = get_visible_notices("resident", uid, limit=5)
    if not rows:
        return "最近没有新通知。", "成功", None
    lines = [f"· {n.get('title', '')}" for n in rows]
    return "最近通知：\n" + "\n".join(lines), "成功", None


def _exec_community_phone() -> str:
    from data.db_elderly_care import COMMUNITY_PHONE
    return str(COMMUNITY_PHONE)

# ---------------------------------------------------------------------------
# 负责人端路由
# ---------------------------------------------------------------------------

def _grid_todos() -> tuple[str, str, None]:
    """待办统计：待审工单/待回咨询/待审用药/超时。"""
    from data.db_repair import get_issues, get_overdue_issues
    from data.db_health_content import list_consults
    from data.db_elderly_care import list_medication_reminders
    pend_issues = len([i for i in get_issues(limit=1000) if i.get("status") == "待审核"])
    pend_consults = len([c for c in list_consults(limit=1000) if c.get("status") == "待回复"])
    pend_meds = len([m for m in list_medication_reminders() if m.get("status") == "待审核"])
    overdue = len(get_overdue_issues())
    return (f"今日待办：\n· 待审工单 {pend_issues} 条\n· 待回咨询 {pend_consults} 条\n"
            f"· 待审用药 {pend_meds} 条\n· 超时工单 {overdue} 条\n建议优先处理超时工单。"), "成功", None


def _grid_stats(text: str) -> tuple[str, str, None]:
    """统计查询（本周/本月/总量）。"""
    from data.db_policy import get_frequency_stats
    from data.db_repair import get_issues
    from data.db_notice import get_notices_with_stats
    issues = get_issues(limit=1000)
    total = len(issues)
    closed = len([i for i in issues if i.get("status") in ("处理结束", "已关闭")])
    stats = {}
    try:
        stats = get_frequency_stats()
    except Exception:
        pass
    notices = {}
    try:
        notices = get_notices_with_stats(limit=1000)
    except Exception:
        pass
    return (f"统计概览：\n· 工单总数 {total} 条（已结束 {closed} 条）\n"
            f"· 政策提问累计 {stats.get('total_questions', 0)} 条\n"
            f"· 通知共 {notices.get('total', 0) if isinstance(notices, dict) else len(notices)} 条\n"
            f"· 居民已读 {notices.get('resident_read', 0) if isinstance(notices, dict) else 0} 人次"), "成功", None


def _grid_search(text: str) -> tuple[str, str, None]:
    """搜索资料：按关键词搜工单/提案/知识库。"""
    from data.db_repair import get_issues
    from data.db_proposal import get_proposals
    from data.db_policy import get_knowledge_list
    kw = text
    parts = []
    try:
        issues = [i for i in get_issues(limit=1000)
                  if kw in (i.get("title") or "") or kw in (i.get("location") or "") or kw in (i.get("reporter_name") or "")]
        if issues:
            parts.append(f"工单 {len(issues)} 条：" + "；".join(f"#{i.get('id')} {i.get('title', '')[:12]}" for i in issues[:5]))
    except Exception:
        pass
    try:
        props = [p for p in get_proposals(limit=1000) if kw in (p.get("title") or "")]
        if props:
            parts.append(f"提案 {len(props)} 条：" + "；".join(f"P{p.get('id')} {p.get('title', '')[:12]}" for p in props[:5]))
    except Exception:
        pass
    try:
        kbs = [k for k in get_knowledge_list(limit=500) if kw in (k.get("title") or "") or kw in (k.get("category") or "")]
        if kbs:
            parts.append(f"知识库 {len(kbs)} 条：" + "；".join(k.get("title", "")[:12] for k in kbs[:5]))
    except Exception:
        pass
    if not parts:
        return f"未找到与「{kw}」相关的工单、提案或知识条目。", "成功", None
    return "搜索结果：\n" + "\n".join(parts), "成功", None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def handle_chat(role: str, uid: int, name: str, text: str,
                elder_uid: int | None = None) -> dict:
    """处理一条用户消息，返回回复与动作。role: resident/elderly/grid。"""
    text = (text or "").strip()[:200]
    s = _sess(role, uid)
    eff_uid = elder_uid or uid

    # 1. 礼貌 / 自我介绍 / 使用帮助（全局快捷）
    if A.detect_polite(text):
        return _reply(s, "礼貌回复", _polite_reply(), "成功", [], uid, role, text)
    if "你是谁" in text or "你叫什么" in text:
        return _reply(s, "自我介绍", _intro_reply(), "成功", [], uid, role, text)
    if A.detect_intent(text, role) == "使用帮助":
        return _reply(s, "使用帮助", _help_reply(role), "成功", [], uid, role, text)

    # 2. 纠错确认状态（pending_correct）—— 上轮纠错展示确认后
    if s.get("pending_correct"):
        pc = s.pop("pending_correct")
        if text in ("对", "确认", "是的", "确定", "对，提交"):
            text = pc["corrected"]
        else:
            text = pc["original"]

    # 3. 取消指令
    if text in ("算了", "取消", "不要了", "先不弄了"):
        _clear(role, uid)
        return _reply(s, "取消", "已取消，没有生成草稿。", "已取消", [], uid, role, text)

    # 4. 情绪安抚（前置，仍继续识别意图）
    emotion = A.detect_emotion(text) and not s.get("step")

    # 5. 紧急语义 → 默认紧急
    urgent = A.detect_emergency(text)

    # 5.5 负责人导出确认（pending_action）
    if s.get("pending_action"):
        pa = s.pop("pending_action")
        if text in ("确认", "确认导出", "确定"):
            if pa.get("action") == "export":
                return _reply(s, "导出数据", "已生成脱敏报表，点击下方按钮下载。", "成功",
                              [{"type": "download", "url": "/api/web/export/issues", "label": "下载工单报表"}],
                              uid, role, text)
        return _reply(s, "导出数据", "已取消导出。", "已取消", [], uid, role, text)

    # 6. 状态机推进（追问回答）
    step = s.get("step")
    if step:
        out = _step_answer(role, uid, name, s, step, text, urgent)
        if out:
            return out

    # 7. 新意图识别（先纠错确认）
    cc = correct_and_confirm(role, uid, text)
    if cc:
        return cc

    intent = A.detect_intent(text, role)
    if not intent:
        # 出行联想
        if A.detect_go_out(text):
            return _reply(s, "出行联想", "需要帮您查天气吗？", "成功",
                          [{"type": "buttons", "options": ["查今天天气", "不用了"]}], uid, role, text)
        if emotion:
            return _reply(s, "情绪安抚", "我理解您的着急，马上为您处理。请告诉我具体的问题，比如是漏水、灯坏还是其他。",
                          "成功", [{"type": "buttons", "options": ["报修", "提案", "政策问答", "查天气"]}], uid, role, text)
        return _reply(s, "未知意图", A.unknown_reply(role), "成功",
                      [{"type": "buttons", "options": A.quick_entries(role)}], uid, role, text)

    s["intent"] = intent
    s["step"] = None
    s["data"] = {"desc": text}

    # 老年端：身体不适 → 提示联系社区/家属 + 紧急求助按钮
    if role == "elderly" and intent == "身体不适":
        return _reply(s, intent,
                      "您感觉不舒服吗？请不要着急。如果需要，可以帮您联系社区或家属，也可以长按下方红色按钮紧急求助。",
                      "成功",
                      [{"type": "navigate", "to": "/elderly/home", "label": "紧急求助（长按3秒）"},
                       {"type": "buttons", "options": ["帮我联系家属", "查天气"]}], uid, role, text)

    # 老年端：报修默认室内/一般，直接确认草稿（文档：默认分类室内、紧急程度一般）
    if role == "elderly" and intent == "报修":
        s["data"]["type"] = "室内"
        s["data"]["urgency"] = "紧急" if urgent else "一般"
        s["step"] = "confirm_issue"
        return _reply(s, "报修",
                      f"请您确认报修信息：\n· 问题：{text[:60]}\n· 分类：室内\n· 紧急程度：{s['data']['urgency']}",
                      "需确认",
                      [{"type": "buttons", "options": ["确认提交", "取消"]}], uid, role, text, confirm="报修")

    # 报修：紧急语义直接标记，未说明时追问
    if intent == "报修":
        s["data"]["urgency"] = "紧急" if urgent else None
        return _ask_issue_step(role, uid, name, s, text)

    if intent == "提案":
        return _ask_proposal_step(role, uid, name, s, text)

    # 直接执行类
    if intent == "政策问答":
        r_text, st, qid = _exec_policy(eff_uid, text)
        actions = []
        if st == "未匹配":
            actions = [{"type": "confirm_transfer", "label": "转人工咨询", "related_id": qid}]
        else:
            actions = [{"type": "buttons", "options": ["有帮助", "无帮助"]}]
        return _reply(s, intent, r_text, st, actions, uid, role, text, related_id=qid)

    if intent == "天气查询":
        r_text, st, _ = _exec_weather(text)
        return _reply(s, intent, r_text, st, [], uid, role, text)

    if intent == "通知查询":
        r_text, st, _ = _exec_notices(uid)
        return _reply(s, intent, r_text, st, [{"type": "navigate", "to": "/resident/notices", "label": "查看全部通知"}],
                      uid, role, text)

    if intent == "联系社区":
        phone = _exec_community_phone()
        return _reply(s, intent, f"社区服务中心电话：{phone}", "成功",
                      [{"type": "confirm_call", "label": "一键拨打", "phone": phone}], uid, role, text)

    if intent == "撤回引导":
        return _reply(s, intent, "工单在「待审核」状态可以撤回。已为您打开我的报修列表。", "成功",
                      [{"type": "navigate", "to": "/resident/work-orders", "label": "去我的报修"}], uid, role, text)

    if role == "grid":
        return _grid_handle(s, uid, name, text, intent)

    return _reply(s, intent, A.unknown_reply(role), "成功",
                  [{"type": "buttons", "options": A.quick_entries(role)}], uid, role, text)


def _ask_issue_step(role, uid, name, s, text):
    d = s["data"]
    if not d.get("type"):
        s["step"] = "ask_type"
        return _reply(s, "报修", "是您家里还是公共区域？", "追问",
                      [{"type": "buttons", "options": ["家里", "公共区域"]}], uid, role, text)
    if not d.get("urgency"):
        s["step"] = "ask_urgency"
        return _reply(s, "报修", "是紧急情况吗？", "追问",
                      [{"type": "buttons", "options": ["紧急", "一般"]}], uid, role, text)
    return _issue_confirm(s, uid, name)


def _ask_proposal_step(role, uid, name, s, text):
    d = s["data"]
    if d.get("is_public") is None:
        s["step"] = "ask_public"
        return _reply(s, "提案", "您想公开还是私有？（公开会进入公示投票）", "追问",
                      [{"type": "buttons", "options": ["公开", "私有"]}], uid, role, text)
    return _proposal_confirm(s, uid, name)


def _step_answer(role, uid, name, s, step, text, urgent):
    d = s["data"]
    if step == "ask_type":
        if "家" in text or "室" in text:
            d["type"] = "室内" if "内" in text or "家" in text else "室外"
        else:
            d["type"] = "室内"  # 默认室内
        s["step"] = "ask_urgency" if not d.get("urgency") else None
        if s["step"]:
            return _reply(s, "报修", "是紧急情况吗？", "追问",
                          [{"type": "buttons", "options": ["紧急", "一般"]}], uid, role, text)
        return _issue_confirm(s, uid, name)
    if step == "ask_urgency":
        d["urgency"] = "紧急" if (urgent or "紧急" in text or "急" in text) else "一般"
        s["step"] = None
        return _issue_confirm(s, uid, name)
    if step == "ask_public":
        d["is_public"] = 1 if ("公开" in text or "公" in text) else 0
        s["step"] = None
        return _proposal_confirm(s, uid, name)
    if step == "confirm_issue":
        if text in ("确认", "确认提交", "提交", "对", "是"):
            r_text, st, iid = _exec_report(uid, name, d)
            _clear(role, uid)
            return _reply(s, "报修", r_text, st, [], uid, role, "", related_id=iid)
        _clear(role, uid)
        return _reply(s, "报修", "已取消，没有生成工单。", "已取消", [], uid, role, text)
    if step == "confirm_proposal":
        if text in ("确认", "确认提交", "提交", "对", "是"):
            r_text, st, pid = _exec_proposal(uid, name, d)
            _clear(role, uid)
            return _reply(s, "提案", r_text, st, [], uid, role, "", related_id=pid)
        _clear(role, uid)
        return _reply(s, "提案", "已取消，没有生成提案。", "已取消", [], uid, role, text)
    return None


def _issue_confirm(s, uid, name):
    d = s["data"]
    s["step"] = "confirm_issue"
    desc = d.get("desc", "")
    urgent_txt = "紧急" if d.get("urgency") == "紧急" else "一般"
    return _reply(s, "报修",
                  f"请您确认报修信息：\n· 问题：{desc[:60]}\n· 分类：{d.get('type', '室内')}\n· 紧急程度：{urgent_txt}",
                  "需确认",
                  [{"type": "buttons", "options": ["确认提交", "取消"]}], uid, "resident", "", confirm="报修")


def _proposal_confirm(s, uid, name):
    d = s["data"]
    s["step"] = "confirm_proposal"
    pub = "公开" if d.get("is_public") else "私有"
    return _reply(s, "提案",
                  f"请您确认提案信息：\n· 内容：{d.get('desc', '')[:60]}\n· 公开方式：{pub}",
                  "需确认",
                  [{"type": "buttons", "options": ["确认提交", "取消"]}], uid, "resident", "", confirm="提案")


def _grid_handle(s, uid, name, text, intent):
    if intent == "待办提醒":
        r_text, st, _ = _grid_todos()
        return _reply(s, intent, r_text, st,
                      [{"type": "navigate", "to": "/grid/work-orders", "label": "跳转处理工单"},
                       {"type": "navigate", "to": "/grid/health", "label": "处理咨询"}], uid, "grid", text)
    if intent == "导出数据":
        # B类：负责人确认
        s["pending_action"] = {"action": "export"}
        return _reply(s, intent, "确认导出数据报表？（将生成脱敏文件）", "需确认",
                      [{"type": "buttons", "options": ["确认导出", "取消"]}], uid, "grid", text)
    if intent == "统计查询":
        r_text, st, _ = _grid_stats(text)
        return _reply(s, intent, r_text, st, [], uid, "grid", text)
    if intent == "搜索资料":
        kw = text.replace("查一下", "").replace("搜索", "").replace("找一下", "").replace("帮我查", "").strip()
        r_text, st, _ = _grid_search(kw or text)
        return _reply(s, intent, r_text, st, [{"type": "navigate", "to": "/grid/work-orders", "label": "去工单页"}],
                      uid, "grid", text)
    if intent == "页面跳转":
        to = "/grid/dashboard"
        if "工单" in text or "审核" in text:
            to = "/grid/work-orders"
        elif "提案" in text:
            to = "/grid/proposals"
        elif "通知" in text:
            to = "/grid/notices"
        elif "天气" in text:
            to = "/grid/weather"
        elif "健康" in text or "咨询" in text:
            to = "/grid/health"
        elif "老年" in text:
            to = "/grid/elderly-care"
        return _reply(s, intent, f"正在为您打开页面。", "成功",
                      [{"type": "navigate", "to": to, "label": "已打开"}], uid, "grid", text)
    return _reply(s, intent, A.unknown_reply("grid"), "成功",
                  [{"type": "buttons", "options": A.quick_entries("grid")}], uid, "grid", text)


def _reply(s, intent, text, status, actions, uid, role, user_input,
           related_id=None, confirm=None) -> dict:
    """组装回复 + 落库（历史对话 + 留痕）。"""
    try:
        if user_input:
            db_agent.add_dialog(uid, role, user_input, is_bot=0, intent=intent)
        db_agent.add_dialog(uid, role, text, is_bot=1, intent=intent, related_id=related_id)
        db_agent.log_agent(uid, role, user_input or text, intent,
                           routed=f"{intent}/{status}", status=status,
                           related_id=related_id)
    except Exception as e:  # noqa: BLE001
        _log.warning("Agent 落库失败：%s", e)
    return {
        "reply": text,
        "intent": intent,
        "corrected": "",
        "routed": f"{intent}/{status}",
        "status": status,
        "related_id": related_id,
        "actions": actions,
        "confirm": confirm,
    }


def correct_and_confirm(role: str, uid: int, text: str) -> dict | None:
    """纠错检测：有变化返回待确认结构，无变化返回 None。"""
    corrected = A.correct_text(text)
    if corrected and corrected != text:
        s = _sess(role, uid)
        s["pending_correct"] = {"original": text, "corrected": corrected}
        return {"reply": f"您说的是「{corrected}」吗？", "intent": "纠正确认", "corrected": corrected,
                "status": "需确认",
                "actions": [{"type": "buttons", "options": ["对", "不是"]}]}
    return None
