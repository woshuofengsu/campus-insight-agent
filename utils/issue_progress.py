# -*- coding: utf-8 -*-
"""老人能看懂的工单进度（v3 复核 §6-I9）。

**为什么单独有这个模块**：老年人看不懂"已审核待派单""处理中""待居民反馈"这类**系统口径**，
而且更需要知道三件事：**现在到哪一步了 / 下一步谁来做 / 大概还要多久**。
原来的老人端只是把状态字段换个说法显示（"👷 等待派单"），既没说下一步谁做，也没说时间预期，
更没有"已经超时了"的如实提示 —— 老人只能反复打电话问。

本模块是**纯函数**（无 IO、可单测、同输入同输出）：
输入工单行 + 当前时间，输出老人看得懂的一段话 + 五步进度 + 是否超时。

诚实口径（重要，不许讨好式安慰）：
  · 时间预期来自**社区自己的时限规定**（紧急 1 小时 / 中等 4 小时 / 一般 24 小时 / 普通 48 小时），
    说的是"按规定应当…"，而不是"我们保证…"；
  · **超时就明说超时**并说明"已提醒负责人"，绝不假装还在正常时限内；
  · 每一步都写明"下一步谁做"，让老人知道该等谁、不用乱找人。
"""
from datetime import datetime, timedelta

# 与 `data/db_repair._URGENCY_DEADLINE_HOURS` 保持一致（从审核通过开始计时）
SLA_HOURS = {"紧急": 1, "中等": 4, "一般": 24, "普通": 48}

# 五个阶段（老人视角，不出现系统状态名）
STEPS = ["提交", "审核", "派人", "维修", "确认完成"]

# 每个系统状态 → (第几步索引, 现在这句话, 下一步这句话, 下一步谁做)
_STATE_MAP = {
    "待审核": (1, "社区负责人正在审核您报的问题", "审核通过后会安排维修人员", "社区负责人"),
    "退回补充信息": (1, "负责人觉得还需要补充一点信息", "补充后可以重新提交", "您（也可以让家人或网格员帮忙）"),
    "已审核待派单": (2, "已经审核通过，正在安排维修人员", "会有人联系您约上门时间", "社区负责人"),
    "已派单": (3, "维修人员已经安排好了", "维修人员会上门查看", "维修人员"),
    "处理中": (3, "维修人员正在处理", "修好后请您确认一下", "维修人员"),
    "待居民反馈": (4, "已经修完了，等您确认", "您点「满意，结单」就完成了", "您"),
    "处理结束": (5, "已经处理完成", "如果还有问题，可以再报一次", "无（已完成）"),
    "已关闭": (5, "工单已经关闭", "如果问题还在，请重新报修", "无（已关闭）"),
    "已撤回": (0, "这条报修已经撤回", "如果需要，可以重新报修", "您"),
    "待协商": (2, "这件事需要先和您商量（可能涉及费用）", "商量好之后继续安排", "社区负责人"),
    "已转出": (2, "这件事已经转给别的部门处理", "由接收部门跟进", "接收部门"),
    "超时未回复": (2, "这条工单有点久了，已经提醒负责人", "负责人会尽快处理", "社区负责人"),
}


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:19].replace("T", " "))
    except (ValueError, TypeError):
        return None


def elderly_progress(issue: dict, now: datetime | None = None) -> dict:
    """把工单行翻译成老人看得懂的进度块。

    返回 `{now_line, next_line, who, eta_line, overdue, steps, step_index, status_label}`。
    """
    now = now or datetime.now()
    it = issue or {}
    status = str(it.get("status") or "")
    step_index, now_line, next_line, who = _STATE_MAP.get(
        status, (2, f"当前状态：{status or '未知'}", "负责人会跟进处理", "社区负责人"))

    # 时限：从审核通过（没有就按报修时间）起算；只有"还没结束"的工单才谈时限
    urgency = str(it.get("urgency") or "一般")
    hours = SLA_HOURS.get(urgency, 24)
    started = _parse_dt(it.get("approved_at")) or _parse_dt(it.get("reported_at"))
    closed = status in ("处理结束", "已关闭", "已撤回")
    overdue = False
    eta_line = ""
    if closed:
        done_at = _parse_dt(it.get("resolved_at")) or _parse_dt(it.get("updated_at"))
        eta_line = f"已完成（{done_at.strftime('%m月%d日 %H:%M')}）" if done_at else "已完成"
    elif who.startswith("您"):
        # 轮到老人自己确认/补充时**不算超时**（时限是约束社区的，不是催老人的），
        # 只需如实说"已经等您 X 天" —— 不能拿维修时限去吓老人。
        waiting = _parse_dt(it.get("resolved_at")) or _parse_dt(it.get("updated_at")) or started
        days = max(0, (now - waiting).days) if waiting else 0
        eta_line = ("维修已完成，等您确认" if days <= 0 else
                    f"维修已完成，已经等您确认 {days} 天（点「满意，结单」就完成了）")
    elif started:
        deadline = started + timedelta(hours=hours)
        if now > deadline:
            overdue = True
            late_h = (now - deadline).total_seconds() / 3600.0
            eta_line = (f"已经超过社区规定的 {hours} 小时时限（超了 {late_h:.0f} 小时），"
                        f"系统已提醒负责人，您也可以打电话问一下")
        else:
            left = (deadline - now).total_seconds() / 3600.0
            eta_line = (f"社区规定「{urgency}」工单 {hours} 小时内处理，"
                        f"还剩大约 {left:.0f} 小时" if left >= 1 else
                        f"社区规定「{urgency}」工单 {hours} 小时内处理，快到时间了")
    else:
        eta_line = f"社区规定「{urgency}」工单 {hours} 小时内处理"

    return {
        "status_label": now_line,
        "now_line": now_line,
        "next_line": next_line,
        "who": who,
        "eta_line": eta_line,
        "overdue": overdue,
        "steps": STEPS,
        "step_index": max(0, min(step_index, len(STEPS))),
    }
