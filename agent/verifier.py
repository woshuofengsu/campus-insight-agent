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


# ============================================================
# 统一校验器（LLM 幻觉防线 v2.0，挂多 Agent 执行链）
# 所有 Agent 输出在触达用户前必须过 Verifier：
#   PASS 直接输出 / WARN 降级安全回答 / BLOCK 重试一次仍 BLOCK 转人工
# 离线规则引擎输出天然来自数据库（无幻觉），Verifier 是 LLM 链路的强制防线，
# 同时对所有输出统一挂链（执行链「校验」节点），保证"无绕过路径"。
# ============================================================

import re as _re

from utils.text import check_sensitive

_PHONE_RE = _re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDCARD_RE = _re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_GBK_GARBLE_RE = _re.compile(r"[锟斤拷]|[�]|烫烫烫|屯屯屯")

# 健康禁忌：诊断词 / 药物推荐词 / 紧急症状词
_HEALTH_DIAGNOSIS_WORDS = ("可能得了", "应该是得了", "确诊", "你这是", "你患了", "诊断为")
_HEALTH_DRUG_WORDS = ("布洛芬", "阿莫西林", "头孢", "感冒灵", "连花清瘟", "建议服用")
_EMERGENCY_SYMPTOMS = ("胸痛", "呼吸困难", "意识不清", "大出血", "抽搐", "窒息")

# 网格禁忌：代替审批 / 代替回复 / 发布紧急通知
_GRID_FORBIDDEN = ("已为您审核", "已代替您审批", "审核通过，已发布", "已发布紧急通知", "已代替回复")


def _r(rule, verdict, reason):
    return {"rule": rule, "verdict": verdict, "reason": reason}


class Verifier:
    """统一校验器：按业务类型选择规则集（政策/健康/网格/通用）。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}  # 规则开关：{"CitationRequiredRule": False}

    def _enabled(self, rule: str) -> bool:
        return self.config.get(rule, True)

    # ---- 通用规则 ----

    def _general_checks(self, text: str) -> list:
        out = []
        if not text or not text.strip():
            out.append(_r("EmptyOutputRule", "block", "输出为空"))
        if self._enabled("SensitiveWordRule"):
            hit, word = check_sensitive(text)
            if hit:
                out.append(_r("SensitiveWordRule", "block", f"命中敏感词「{word}」"))
        if self._enabled("PhoneMaskRule") and _PHONE_RE.search(text):
            out.append(_r("PhoneMaskRule", "block", "输出包含完整手机号"))
        if self._enabled("IdCardMaskRule") and _IDCARD_RE.search(text):
            out.append(_r("IdCardMaskRule", "block", "输出包含完整身份证号"))
        if self._enabled("InjectionOutputRule"):
            from agent.prompt_guard import detect_output_injection
            feat = detect_output_injection(text)
            if feat:
                out.append(_r("InjectionOutputRule", "block", f"输出含注入特征「{feat}」"))
        if self._enabled("LengthRule") and len(text) > 2000:
            out.append(_r("LengthRule", "warn", "输出超过 2000 字"))
        if self._enabled("GarbledTextRule") and _GBK_GARBLE_RE.search(text):
            out.append(_r("GarbledTextRule", "block", "输出含乱码"))
        return out

    # ---- 业务规则 ----

    def _policy_checks(self, text: str) -> list:
        out = []
        if self._enabled("CitationRequiredRule") and "参考：" not in text and "依据" not in text and "文号" not in text:
            out.append(_r("CitationRequiredRule", "block", "政策回答缺少引用（无引用不回答）"))
        return out

    def _health_checks(self, text: str) -> list:
        out = []
        if self._enabled("NoDiagnosisRule") and any(w in text for w in _HEALTH_DIAGNOSIS_WORDS):
            out.append(_r("NoDiagnosisRule", "block", "健康输出疑似诊断"))
        if self._enabled("NoMedicationAdviceRule") and any(w in text for w in _HEALTH_DRUG_WORDS):
            out.append(_r("NoMedicationAdviceRule", "block", "健康输出推荐药物"))
        if self._enabled("EmergencySymptomTransferRule") and any(w in text for w in _EMERGENCY_SYMPTOMS) \
                and "120" not in text and "就医" not in text:
            out.append(_r("EmergencySymptomTransferRule", "block", "紧急症状未提示就医"))
        return out

    def _grid_checks(self, text: str) -> list:
        out = []
        if self._enabled("NoApprovalRule") and any(w in text for w in _GRID_FORBIDDEN):
            out.append(_r("NoApprovalRule", "block", "网格助手输出代替审批/回复"))
        if self._enabled("ExportMaskingRule") and _PHONE_RE.search(text):
            out.append(_r("ExportMaskingRule", "block", "导出/回答含完整手机号"))
        return out

    # ---- 主入口 ----

    def verify(self, content: dict, biz_type: str = "general") -> dict:
        """校验一轮 Agent 输出。返回 {verdict, violations, warnings, biz_type, timestamp}。"""
        text = (content.get("reply") or "") if isinstance(content, dict) else (content or "")
        biz_type = biz_type or "general"
        checks: list = self._general_checks(text)

        if biz_type in ("policy_expert", "policy"):
            checks += self._policy_checks(text)
        elif biz_type in ("health_advisor", "health"):
            checks += self._health_checks(text)
        elif biz_type in ("grid_assistant", "grid"):
            checks += self._grid_checks(text)
        # repair / notification / weather：走通用规则（数据层已保证字段合法性与引用）

        violations = [c for c in checks if c["verdict"] == "block"]
        warnings = [c for c in checks if c["verdict"] == "warn"]
        verdict = "block" if violations else ("warn" if warnings else "pass")
        return {
            "verdict": verdict,
            "violations": violations,
            "warnings": warnings,
            "biz_type": biz_type,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        }

