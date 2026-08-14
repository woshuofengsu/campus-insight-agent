# agent/verifier.py
"""事实校验反思 v2 — 回复中的工单号/提案号回查 DB，修正幻觉编号。

与 enforce_tool_call 互补：enforce 管「该调的工具调没调」，这里管「答出来的数字对不对」。
只做「追加更正提示」，绝不删改正文——不确定时保持原样，避免误伤正常回复。
"""
import logging
import re

_log = logging.getLogger(__name__)

_ID_RE = re.compile(r"#(\d{1,6})")


def verify_facts(response: str) -> str:
    """校验回复中引用的 #编号 是否真实存在，不存在的追加更正提示。

    判定为「工单/提案引用」的编号才校验：查不到即视为幻觉，提示以页面为准。
    无法访问 DB 时静默跳过（尽力而为，不阻塞主流程）。
    """
    if not response:
        return response

    ids = [int(m) for m in _ID_RE.findall(response)]
    if not ids:
        return response

    try:
        from data.db_governance import get_issues, get_proposals
        issues = get_issues(limit=1000)
        proposals = get_proposals(limit=1000)
        valid = {i["id"] for i in issues} | {p["id"] for p in proposals}
    except Exception:
        _log.warning("verify_facts: DB 查询失败，跳过", exc_info=True)
        return response

    bad = sorted({n for n in ids if n not in valid})
    if bad:
        _log.info("verify_facts: 检测到幻觉 id：%s", bad)
        refs = "、".join(f"#{n}" for n in bad)
        note = (
            f"\n\n⚠️ *核对提示：以上回复中引用的编号 {refs} 未在系统工单/提案中查到，"
            f"可能为笔误。请以「接诉即办」「我的」页面中的真实编号为准。*"
        )
        return response + note
    return response
