# -*- coding: utf-8 -*-
"""幂等与"结果未知"的测试（卡8 / v3 卡4，对应 v3 复核 §6-I5）。

**要守住的三件事**：
  ① 同一个幂等编号重复提交 → **只建一张工单**，第二次直接返回上一次的结果；
  ② 断网/超时时能用该编号**查出真实结果**（不是猜的，是服务端记的）；
  ③ 别人的编号不能用来探测/复用别人的结果。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
ELDER = 99301
OTHER = 99302
PHONE = "13800009301"


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="idem_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "idem.db"))
    with db_core.get_db() as conn:
        for uid, role in ((ELDER, "elderly"), (OTHER, "elderly")):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, "
                "community, building, unit, phone_enc) VALUES (?, ?, ?, ?, 1, ?, '5号楼', '2单元201', ?)",
                (uid, f"u{uid}", role, f"n{uid}", A, ""))
        from data.db_repair import _enc_phone
        conn.execute("UPDATE user_profile SET phone_enc=? WHERE id=?", (_enc_phone(PHONE), ELDER))
        # OTHER 也给一个号码：本用例要验的是"编号不能跨用户复用"，别被"缺手机号"挡住
        conn.execute("UPDATE user_profile SET phone_enc=? WHERE id=?",
                     (_enc_phone("13800009302"), OTHER))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _req(uid):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": "elderly", "name": "老人", "community": A,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _issues():
    from data.db_core import get_db
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, title, location FROM community_issues ORDER BY id").fetchall()]


def _err(res) -> str:
    if isinstance(res, dict):
        return res.get("error") or ""
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8")).get("error") or ""


def _ok_payload(res) -> dict:
    if isinstance(res, dict):
        return res
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8"))


# ---------------------------------------------------------------- 幂等

def test_same_token_submits_only_once(fresh_db):
    """同一个编号提交两次 → 只建一张工单，第二次返回上一次的结果（带 duplicate 标记）。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    body = dict(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外",
                client_token="tok-aaaa1111")
    first = _ok_payload(web_elderly_report_submit(ReportSubmitIn(**body), _req(ELDER)))
    assert first["success"], _err(first if isinstance(first, dict) else first)
    second = _ok_payload(web_elderly_report_submit(ReportSubmitIn(**body), _req(ELDER)))
    assert second["success"]
    assert second["data"]["issue_id"] == first["data"]["issue_id"], "同编号必须复用同一张工单"
    assert second["data"]["duplicate"] is True
    assert len(_issues()) == 1, f"重复提交不得建第二张单：{_issues()}"


def test_different_tokens_create_two_issues(fresh_db):
    """**反向断言**：不同编号就是两件不同的事 → 允许建两张单（别把幂等做成"只能报一次"）。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    for tok in ("tok-bbbb2222", "tok-cccc3333"):
        res = web_elderly_report_submit(
            ReportSubmitIn(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外",
                           client_token=tok), _req(ELDER))
        assert _ok_payload(res)["success"], _err(res)
    assert len(_issues()) == 2


def test_no_token_still_works(fresh_db):
    """不带编号的老调用方式仍然可用（兼容旧前端），只是没有幂等保护。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    res = web_elderly_report_submit(
        ReportSubmitIn(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外"),
        _req(ELDER))
    assert _ok_payload(res)["success"]


def test_other_user_cannot_reuse_token(fresh_db):
    """别人的编号不能复用（否则等于用别人的"提交凭证"探测结果）。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    first = _ok_payload(web_elderly_report_submit(
        ReportSubmitIn(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外",
                       client_token="tok-dddd4444"), _req(ELDER)))
    other = _ok_payload(web_elderly_report_submit(
        ReportSubmitIn(text="5号楼三层楼道灯坏了", location="5号楼3层楼道", scope="室外",
                       client_token="tok-dddd4444"), _req(OTHER)))
    assert other["success"], _err(other)
    assert other["data"].get("duplicate") is not True, "同编号属于别人，不该当成自己的重复提交"
    assert other["data"]["issue_id"] != first["data"]["issue_id"]


# ---------------------------------------------------------------- 结果未知 → 查真实结果

def test_status_finds_real_result(fresh_db):
    """§6-I5：断网后按编号能查出**真实结果**（已提交 → 带工单号）。"""
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_status, \
        web_elderly_report_submit
    tok = "tok-eeee5555"
    r = _ok_payload(web_elderly_report_submit(
        ReportSubmitIn(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外",
                       client_token=tok), _req(ELDER)))
    iid = r["data"]["issue_id"]
    st = _ok_payload(web_elderly_report_status(_req(ELDER), token=tok))
    assert st["data"]["submitted"] is True and st["data"]["issue_id"] == iid


def test_status_says_not_submitted_when_absent(fresh_db):
    """没提交过就**如实说没提交**（不能为了安慰老人而报成功）。"""
    from api_routes.elderly import web_elderly_report_status
    st = _ok_payload(web_elderly_report_status(_req(ELDER), token="tok-ffff6666"))
    assert st["data"]["submitted"] is False and st["data"]["issue_id"] == 0


def test_status_rejects_bad_token(fresh_db):
    """编号格式非法 → 明确报错（不要把任意字符串当查询键）。"""
    from api_routes.elderly import web_elderly_report_status
    st = _ok_payload(web_elderly_report_status(_req(ELDER), token="短"))
    assert st["success"] is False and "编号" in _err(st)


def test_existing_logs_are_honest(fresh_db):
    """重复提交的日志要能看出来「幂等命中」，而不是看起来像两次正常提交。"""
    import io
    import logging
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("api_routes.elderly").addHandler(handler)
    logging.getLogger("api_routes.elderly").setLevel(logging.INFO)
    try:
        body = dict(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外",
                    client_token="tok-gggg7777")
        web_elderly_report_submit(ReportSubmitIn(**body), _req(ELDER))
        web_elderly_report_submit(ReportSubmitIn(**body), _req(ELDER))
    finally:
        logging.getLogger("api_routes.elderly").removeHandler(handler)
    assert "幂等命中" in buf.getvalue(), f"缺少幂等留痕：{buf.getvalue()[:200]}"
