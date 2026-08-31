# -*- coding: utf-8 -*-
"""WS5：真仲裁——仲裁结果进入用户可见文案（不再丢弃）+ Verifier 精准化（降误杀）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.blackboard import Blackboard
from agent.roles.business_agents import HealthAdvisorAgent
from agent.verifier import Verifier


def _health_confirmed(risk="none", symptom="头晕"):
    return {"type": "task_response",
            "payload": {"event": "health_weather_risk_confirmed",
                        "risk_level": risk, "symptom": symptom}}


def test_arbitration_changes_reply_high_risk_symptom():
    """低风险天气评估 + 高危症状 → 仲裁 professional_first → reply 含「仲裁」并更加保守。"""
    bb = Blackboard()
    ag = HealthAdvisorAgent(bb)
    r = ag.process_negotiation(_health_confirmed(risk="none", symptom="头晕"))
    assert r is not None
    assert "仲裁" in r["reply"]
    assert r["need_human"] is False
    assert bb.read("last_arbitration")["decision"] == "professional"


def test_arbitration_safety_escalates_to_human():
    """安全类症状（胸痛）→ arbitration decision=human → reply 提示转人工。"""
    bb = Blackboard()
    ag = HealthAdvisorAgent(bb)
    r = ag.process_negotiation(_health_confirmed(risk="none", symptom="胸痛"))
    assert r is not None
    assert r["need_human"] is True
    assert "转人工" in r["reply"]


def test_arbitration_not_triggered_for_plain_symptom():
    """低风险 + 非高危症状（如倦怠）→ 不触发仲裁（返回无 reply，仅留痕）。"""
    bb = Blackboard()
    ag = HealthAdvisorAgent(bb)
    r = ag.process_negotiation(_health_confirmed(risk="none", symptom="倦怠乏力"))
    assert r is None or "reply" not in r
    assert bb.read("last_arbitration") is None


# ---------- Verifier 精准化（降误杀 + 保留处方拦截） ----------

def test_verifier_does_not_block_mention_of_allergy():
    v = Verifier()
    # 陈述句「我对布洛芬过敏」不应被误杀
    assert v.verify({"reply": "我对布洛芬过敏，以前吃过一次。"}, "health_advisor")["verdict"] == "pass"


def test_verifier_blocks_prescriptive_sentence():
    v = Verifier()
    assert v.verify({"reply": "你可以吃布洛芬缓释缓解。"}, "health_advisor")["verdict"] == "block"
    assert v.verify({"reply": "建议每日服药一次。"}, "health_advisor")["verdict"] == "block"
    assert v.verify({"reply": "建议减半剂量。"}, "health_advisor")["verdict"] == "block"


def test_verifier_still_blocks_diagnosis_and_keeps_benign():
    v = Verifier()
    assert v.verify({"reply": "你可能得了感冒。"}, "health_advisor")["verdict"] == "block"
    # 良性建议不误杀
    assert v.verify({"reply": "建议多喝水多休息，如症状持续请及时就医。"}, "health_advisor")["verdict"] == "pass"


def test_verifier_policy_cited_titles_double_check():
    v = Verifier()
    # 回复引用了检索集合内的标题 → pass
    assert v.verify({"reply": "参考：《医保报销办法》说明报销 70%"}, "policy_expert",
                    cited_titles={"医保报销办法", "重阳政策"})["verdict"] == "pass"
    # 引用了集合外标题（伪造） → block
    assert v.verify({"reply": "参考：《不存在政策》说报销 70%"}, "policy_expert",
                    cited_titles={"医保报销办法"})["verdict"] == "block"
