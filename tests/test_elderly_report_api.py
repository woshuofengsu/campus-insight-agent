# -*- coding: utf-8 -*-
"""老人报修契约的**接口层**测试（v3 卡1：缺位置不建单 + 字段来源可解释 + 不写假手机号）。

规则层单测在 `tests/test_elderly_report_contract.py`（纯函数）；这里测的是路由是否**真的**守住了契约：
  · `POST /elderly/report/draft`：缺位置/责任范围 → `need_more=true` + 一句能听懂的追问；
  · `POST /elderly/report/submit`：缺必填**不建单**（2002）；资料无手机号**不写假号**；
  · 建单成功后库里 location **绝不再是"社区"**；返回体四段值分开（原话/建议/确认/来源）。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
ELDER_A = 98821
ELDER_NO_PHONE = 98822
REAL_PHONE = "13800009999"


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="elder_report_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "er.db"))
    with db_core.get_db() as conn:
        for uid, name, phone_enc in ((ELDER_A, "A老人", ""), (ELDER_NO_PHONE, "B老人", "")):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile "
                "(id, username, role, name, is_active, community, building, unit) "
                "VALUES (?, ?, 'elderly', ?, 1, ?, '11号楼', '3单元301')",
                (uid, f"u{uid}", name, A))
        # A 老人有手机号（加密列），B 老人没有 —— 用来验证"没手机号就不建单"
        from data.db_repair import _enc_phone
        conn.execute("UPDATE user_profile SET phone_enc=? WHERE id=?", (_enc_phone(REAL_PHONE), ELDER_A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _req(uid, role="elderly"):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": "A老人", "community": A,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _err(res) -> str:
    if isinstance(res, dict):
        return res.get("error") or ""
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8")).get("error") or ""


def _denied(res) -> bool:
    if isinstance(res, dict):
        return not res.get("success")
    import json as _json
    return not _json.loads(bytes(res.body).decode("utf-8")).get("success")


def _issues():
    from data.db_core import get_db
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, title, location, issue_type, urgency, reporter_name, reporter_phone_enc "
            "FROM community_issues ORDER BY id DESC").fetchall()]


# ---------------------------------------------------------------- 草稿：缺什么就说缺什么

def test_draft_asks_when_location_missing(fresh_db):
    from api_routes.elderly import ReportDraftIn, web_elderly_report_draft
    res = web_elderly_report_draft(ReportDraftIn(text="楼道灯坏了"), _req(ELDER_A))
    assert not _denied(res), _err(res)
    d = res["data"]
    assert d["need_more"] is True and d["can_submit"] is False
    assert "location" in d["missing"]
    # 追问要具体到老人答得上：可以是"哪栋楼"，也可以是"是不是您家这栋（…）"（后者更好答）
    assert "哪栋楼" in d["ask"] or "哪个楼" in d["ask"]
    assert d["fields"]["location"] == "", "草稿里不得出现回落出来的社区名"
    assert _issues() == [], "草稿阶段绝不能建单"


def test_draft_full_text_is_ready(fresh_db):
    from api_routes.elderly import ReportDraftIn, web_elderly_report_draft
    res = web_elderly_report_draft(ReportDraftIn(text="五号楼二层楼道灯坏了"), _req(ELDER_A))
    d = res["data"]
    assert d["can_submit"] is True and d["missing"] == []
    assert d["fields"]["location"] == "5号楼2层楼道"
    assert d["fields"]["issue_type"] == "室外"
    # 字段来源必须可解释：位置来自原话、紧急度是缺省值
    assert d["sources"]["location"] == "text" and d["sources"]["urgency"] == "default"


def test_draft_indoor_uses_profile_address(fresh_db):
    from api_routes.elderly import ReportDraftIn, web_elderly_report_draft
    res = web_elderly_report_draft(ReportDraftIn(text="我家厨房水管漏水了"), _req(ELDER_A))
    d = res["data"]
    assert d["can_submit"] is True
    assert d["fields"]["location"] == "11号楼3单元301厨房"
    assert d["sources"]["location"] == "profile", "楼栋来自资料，来源要标清楚"


def test_draft_reports_missing_phone(fresh_db):
    from api_routes.elderly import ReportDraftIn, web_elderly_report_draft
    res = web_elderly_report_draft(ReportDraftIn(text="五号楼二层楼道灯坏了"), _req(ELDER_NO_PHONE))
    d = res["data"]
    assert d["reporter_phone_ready"] is False
    assert "手机号" in d.get("phone_hint", "")


# ---------------------------------------------------------------- 提交：闸门 + 不写假号

def test_submit_blocks_missing_location(fresh_db):
    """**核心回归（B1）**：缺位置提交 → 2002 + 追问，且**库里没有新工单**。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    res = web_elderly_report_submit(ReportSubmitIn(text="楼道灯坏了"), _req(ELDER_A))
    assert _denied(res)
    assert "哪栋楼" in _err(res) or "哪个楼" in _err(res)
    assert _issues() == [], "缺位置的报修绝不能建单（否则就是 location='社区' 那种废单）"


def test_submit_creates_issue_with_real_location(fresh_db):
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    res = web_elderly_report_submit(
        ReportSubmitIn(text="五号楼二层楼道灯坏了", location="5号楼2层楼道",
                       scope="室外", urgency="中等"), _req(ELDER_A))
    assert not _denied(res), _err(res)
    d = res["data"]
    assert d["issue_id"] > 0
    assert d["original_text"] == "五号楼二层楼道灯坏了"
    assert d["confirmed"]["location"] == "5号楼2层楼道"
    assert d["confirmed"]["urgency"] == "中等"
    assert d["sources"]["location"] == "user"
    rows = _issues()
    assert rows[0]["location"] == "5号楼2层楼道"
    assert rows[0]["location"] not in ("社区", A), "位置不得退化成社区名"
    assert rows[0]["issue_type"] == "室外"


def test_submit_payload_feeds_the_confirmation_card(fresh_db):
    """**确认卡片**（收敛方案第 2 阶段）要有料：社区 + 提交时间 + 每种字段的来源。

    为什么单列：卡片上写"位置：（您确认的）"这类字样，如果接口不给 `community`/`submitted_at`，
    页面就只能编一个或空着 —— 那就是"看着可信、其实含糊"。所以把"卡片需要什么"钉在接口上：
      · `community` 必须来自**服务端身份**（不采集定位）；
      · `submitted_at` 必须是**工单真实落库时间**（不是前端时钟）；
      · `sources` 里四个字段都要有来源，且**责任范围（契约里叫 issue_type）要能被卡片读到**。
    """
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    from data.db_core import get_db
    res = web_elderly_report_submit(
        ReportSubmitIn(text="五号楼二层楼道灯坏了", location="5号楼2层楼道",
                       scope="室外", urgency="中等"), _req(ELDER_A))
    assert not _denied(res), _err(res)
    d = res["data"]
    assert d["community"] == A, f"社区必须来自服务端身份：{d.get('community')}"
    assert d["submitted_at"], "确认卡片要显示提交时间，接口必须给真实落库时间"
    with get_db() as conn:
        row = conn.execute("SELECT reported_at FROM community_issues WHERE id=?",
                           (d["issue_id"],)).fetchone()
    assert d["submitted_at"] == row["reported_at"], "提交时间必须等于库里的 reported_at（不是前端时钟）"
    # 卡片读"责任范围"用的是 scope，而契约给的是 issue_type → 两边都要能拿到
    assert d["sources"].get("issue_type") or d["sources"].get("scope"), \
        f"责任范围的来源缺失（卡片会显示『暂缺』）：{d['sources']}"
    # v52：来源要真的落库（不只是返回体里有）
    with get_db() as conn:
        raw = conn.execute("SELECT field_sources FROM community_issues WHERE id=?",
                           (d["issue_id"],)).fetchone()["field_sources"]
    assert raw and "scope" in raw, f"字段来源没有按 scope 口径落库：{raw}"



def test_submit_user_confirmed_value_beats_auto_suggestion(fresh_db):
    """`不是三号楼，是五号楼`：入库值 = 老人确认的值（自动建议里的三号楼不得进库）。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    res = web_elderly_report_submit(
        ReportSubmitIn(text="不是三号楼，是五号楼，楼道灯坏了", location="5号楼楼道",
                       scope="室外"), _req(ELDER_A))
    assert not _denied(res), _err(res)
    assert _issues()[0]["location"] == "5号楼楼道"


def test_submit_without_phone_is_refused_not_faked(fresh_db):
    """资料里没有手机号 → 明确拒绝，**绝不写 13800000000 这种占位假号**。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    res = web_elderly_report_submit(
        ReportSubmitIn(text="五号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外"),
        _req(ELDER_NO_PHONE))
    assert _denied(res) and "手机号" in _err(res)
    assert _issues() == []


def test_submitted_issue_phone_is_the_real_one(fresh_db):
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    from data.db_repair import _dec_phone
    web_elderly_report_submit(
        ReportSubmitIn(text="五号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外"),
        _req(ELDER_A))
    row = _issues()[0]
    assert _dec_phone(row["reporter_phone_enc"], "") == REAL_PHONE


# ---------------------------------------------------------------- 兼容入口

def test_legacy_voice_report_is_strict_too(fresh_db):
    """旧入口（`/voice-report`）也守同一套契约：缺位置不建单，齐全才建单。"""
    from api_routes.elderly import VoiceReport, web_elderly_voice_report
    bad = web_elderly_voice_report(VoiceReport(text="楼道灯坏了"), _req(ELDER_A))
    assert _denied(bad) and _issues() == []
    good = web_elderly_voice_report(VoiceReport(text="五号楼二层楼道灯坏了"), _req(ELDER_A))
    assert not _denied(good), _err(good)
    assert _issues()[0]["location"] == "5号楼2层楼道"
