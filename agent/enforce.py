# agent/enforce.py
"""兜底：LLM 编造回复时，强制真调 report_issue。

LLM 嘴上说干了事（比如"已生成工单 #42"）但没真调工具时，
这个模块用关键词分类强制补一次真实的 report_issue 调用，
保证数据库和回复一致。
"""
import logging

_log = logging.getLogger(__name__)


# 幻觉工单检测：看 LLM 回复有没有声称"已生成/已上报"工单
_CLAIMED_REPORT_MARKERS = (
    "已上报", "已生成工单", "已创建工单", "已为你生成", "已帮你上报",
    "上报成功", "工单编号",
)


def _claimed_report(response: str) -> bool:
    """检测 LLM 回复是否声称创建了工单（幻觉工单号）。"""
    return any(m in response for m in _CLAIMED_REPORT_MARKERS)


def enforce_tool_call(response: str, user_input: str,
                      intermediate_steps: list | None = None) -> str:
    """LLM 编造回复或工具调用失败时，强制补一次真实的 report_issue。

    覆盖两种翻车：LLM 压根没调工具（编了回复），或者调了但失败了
    （比如位置校验没过）。检查全过就原样返回，否则返回
    带真实 report_issue 结果的替换回复。
    """
    if not intermediate_steps:
        intermediate_steps = []

    # 检查 report_issue 有没有被调用且成功
    report_called = False
    report_succeeded = False
    for step in intermediate_steps:
        if len(step) >= 2:
            tool = step[0]  # (AgentAction, observation) 元组
            tool_name = getattr(tool, 'tool', '')
            if tool_name == "report_issue":
                report_called = True
                observation = step[1]  # 工具返回值
                # 看工具返回的是不是错误
                if not any(observation.startswith(p) for p in ("⚠️", "❌")):
                    report_succeeded = True
                break

    if report_succeeded:
        return response  # 工具调过且成功了，啥也不用干

    # 修复"假工单"：只在两种情况下兜底
    # 1. report_issue 被调用但失败（report_called=True）→ 重试
    # 2. LLM 声称已上报但没调工具（幻觉工单号）→ 补真实上报
    # 之前光凭 detect_persona 觉得"像上报"就兜底，会把 LLM 的正常追问
    # （"哪栋楼？"）和咨询（"充电桩怎么收费？"）误判成幻觉，强造假工单。
    if not report_called and not _claimed_report(response):
        return response

    # 强制走真工具
    if report_called:
        _log.warning(
            "安全网：report_issue 被调了但失败了，重试。 "
            "user_input=%r", user_input[:80]
        )
    else:
        _log.warning(
            "安全网：维修意图下 report_issue 没被调用。 "
            "强制走真工具。user_input=%r, response_preview=%r",
            user_input[:80], response[:80]
        )

    try:
        from tools.action_report_issue import report_issue, _keyword_classify, _keyword_urgency
        from agent.helpers import extract_location
        try:
            from data.db_user import get_current_user
            _u = get_current_user() or {}
            reporter_name = _u.get("name") or ""
            reporter_phone = _u.get("phone") or ""
        except Exception:
            reporter_name, reporter_phone = "", ""

        # 把标题里的预取上下文剥掉
        clean_input = user_input.split("\n\n[📊")[0].strip()
        title = clean_input[:80]
        location = extract_location(clean_input)

        # 用快速关键词方法预判分类和紧急程度
        # （不调 LLM 接口——秒出，兜底够用了）
        cat = _keyword_classify(title, clean_input)
        urg = _keyword_urgency(title, clean_input)

        # 位置还是空的，就从完整输入里再试一次
        if not location:
            location = extract_location(user_input)

        result = report_issue.invoke({
            "title": title,
            "category": cat,
            "location": location,
            "description": clean_input,
            "urgency": urg,       # 快路径：跳过 _llm_classify
            "reporter_name": reporter_name,
            "reporter_phone": reporter_phone,
        })

        # 结果还是报错，说明被 validate_location 拦了。
        # 用完整输入当位置再重试一次。
        if result.startswith("⚠️") or result.startswith("❌"):
            _log.warning(
                "安全网重试也被校验拦了。 "
                "退回用完整输入当位置。error=%r", str(result)[:80]
            )
            result = report_issue.invoke({
                "title": title,
                "category": cat,
                "location": location or clean_input[:60],
                "description": clean_input,
                "urgency": urg,
                "reporter_name": reporter_name,
                "reporter_phone": reporter_phone,
            })

        _log.info("安全网：report_issue 返回结果=%r", str(result)[:120])
        return str(result)
    except Exception as e:
        _log.error("安全网 report_issue 也失败了：%s", e)
        # 千万别把 LLM 编的假工单回复原样返回。
        # 老老实实告诉用户失败了。
        return (
            "很抱歉，自动上报没有成功 😥\n\n"
            "你可以试试页面顶部的「⚡ 快速报修」——它不走 AI，直接写入数据库，"
            "不会出现这种问题。\n\n"
            f"（错误信息：{str(e)[:100]}）"
        )
