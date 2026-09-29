# -*- coding: utf-8 -*-
"""幂等与"结果未知"的测试（卡8 / v3 卡4，对应 v3 复核 §6-I5）。

**要守住的三件事**：
  ① 同一个幂等编号重复提交 → **只建一张工单**，第二次直接返回上一次的结果；
  ② 断网/超时时能用该编号**查出真实结果**（不是猜的，是服务端记的）；
  ③ 别人的编号不能用来探测/复用别人的结果。
另有一组**故障注入**（外部评审第十一轮指出）：占位失败（库忙/锁/异常）时必须 **fail-closed** ——
不建单、不执行动作，如实回"状态未知 + 去核对"；这一条正是"最需要幂等的时刻别把幂等关掉"。
"""
import json
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
RESIDENT_UID = 99303
GRID_UID = 99304
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


def test_concurrent_same_token_creates_one_issue(fresh_db):
    """**并发**（不只是顺序第二次）同一个编号 → 仍然只建一张单。

    为什么必须单独有一条：顺序调用通过**完全不等于**并发安全。
    原来只有"先查 recall、后写 remember"，两个并发请求会同时查不到 → 各建一张单
    （首批八条浏览器旅程第 4 条实测：老人连点两下「确认上报」→ 库里两张单、两个工单号）。
    现在靠 `begin()` 的原子占位挡住，这条用例守住它。
    """
    import threading
    from api_routes.elderly import ReportSubmitIn, web_elderly_report_submit
    body = dict(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外",
                client_token="tok-hhhh8888")
    out: list[dict] = []
    lock = threading.Lock()

    def go():
        res = _ok_payload(web_elderly_report_submit(ReportSubmitIn(**body), _req(ELDER)))
        with lock:
            out.append(res)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    issues = _issues()
    assert len(issues) == 1, f"并发同编号不得建第二张单：{issues}"
    assert len(out) == 2, out
    # 两次都必须知道"同一张单"：一个建单成功、另一个复用（duplicate）或如实说"正在提交中"
    ids = {r["data"].get("issue_id") for r in out if r.get("success")}
    assert ids == {issues[0]["id"]}, f"两次提交必须指向同一张单：{out}"


def test_status_distinguishes_in_flight(fresh_db):
    """「正在提交中」不能答成「没提交过」—— 那句话会诱导老人再点一次（就重复了）。"""
    from api_routes.elderly import web_elderly_report_status
    from data.db_idempotency import begin
    tok = "tok-iiii9999"
    st, _ = begin("elderly_report", tok, ELDER)
    assert st == "new"
    res = _ok_payload(web_elderly_report_status(_req(ELDER), token=tok))
    assert res["data"]["in_flight"] is True
    assert res["data"]["submitted"] is False
    assert "处理中" in (res.get("message") or ""), res


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


# ---------------------------------------------------------------- 故障注入：占位失败必须 fail-closed

def test_reservation_failure_blocks_the_write(fresh_db):
    """**占位失败时不许继续建单**（外部评审第十一轮指出的硬伤，2026-09-29 修）。

    原来的取舍是"宁可重复也不能阻断报修"：占位抛异常就返回 `("new", None)` 继续办。
    这个取舍是错的 —— 占位失败恰恰最容易发生在**库忙/锁冲突**这种并发场景，
    而那正是幂等要保护的时刻；此时放行等于在最需要保护的时候把保护关掉。
    本用例注入"占位语句抛异常"，断言：**一张单都不许建**、答复是"状态未知 + 去核对"，
    并且同一个编号在故障解除后仍能正常提交（只建一张）。
    """
    from api_routes.elderly import (ReportSubmitIn, web_elderly_report_status,
                                    web_elderly_report_submit)
    from data import db_idempotency as ID
    tok = "tok-jjjj1111"
    body = dict(text="5号楼二层楼道灯坏了", location="5号楼2层楼道", scope="室外",
                client_token=tok)

    real_get_db = ID.get_db
    boom = {"on": True}

    class _Boom:
        def __enter__(self):
            raise RuntimeError("database is locked（注入）")

        def __exit__(self, *a):
            return False

    def _flaky():
        if boom["on"]:
            return _Boom()
        return real_get_db()

    ID.get_db = _flaky
    try:
        res = web_elderly_report_submit(ReportSubmitIn(**body), _req(ELDER))
    finally:
        ID.get_db = real_get_db
    payload = _ok_payload(res)
    assert payload["success"] is False, f"占位失败竟然放行并建单：{payload}"
    assert "无法确认" in _err(payload), f"答复没说清「状态未知」：{payload}"
    assert _issues() == [], f"占位失败时**不许建单**，但库里出现了：{_issues()}"

    # 故障解除后，同一个编号能正常提交（且只建一张）
    ok = _ok_payload(web_elderly_report_submit(ReportSubmitIn(**body), _req(ELDER)))
    assert ok["success"], _err(ok)
    assert len(_issues()) == 1, f"恢复后应恰好建一张：{_issues()}"
    # 客户端手里还是同一个编号 → 「查一下」能查到真实结果（不诱导重复提交）
    st = _ok_payload(web_elderly_report_status(_req(ELDER), token=tok))
    assert st["data"]["submitted"] is True and st["data"]["issue_id"] == ok["data"]["issue_id"]


def test_begin_returns_unknown_when_placeholder_fails(fresh_db):
    """`begin()` 的契约：占位失败 → `("unknown", None)`（而不是 `("new", None)` 放行）。"""
    from data import db_idempotency as ID
    real_get_db = ID.get_db

    class _Boom:
        def __enter__(self):
            raise RuntimeError("disk I/O error（注入）")

        def __exit__(self, *a):
            return False

    ID.get_db = lambda: _Boom()
    try:
        st, res = ID.begin("elderly_report", "tok-kkkk2222", ELDER)
    finally:
        ID.get_db = real_get_db
    assert st == "unknown" and res is None, f"占位失败必须报 unknown（fail-closed），实际：{st}"


def test_handoff_action_blocks_on_placeholder_failure(fresh_db):
    """人工待办的补问/回复会给居民发通知：占位失败时同样**不许执行**（否则居民收两条）。"""
    from api_routes.agent import HandoffAction, agent_handoff_action
    from data import db_idempotency as ID
    from data.db_agent import create_handoff
    from utils.tenant import clear_cache
    clear_cache()
    # 先建好两个账号：处理包归属社区靠**写入侧盖章**（按 user_id 查其 community），
    # 账号不存在就会盖成空租户 → 连领取都会被租户闸门挡住（顺序不能反）
    with db_core.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, "
            "community, phone_enc) VALUES (?, ?, 'resident', ?, 1, ?, '')",
            (RESIDENT_UID, f"r{RESIDENT_UID}", "居民", A))
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, "
            "community, phone_enc) VALUES (?, ?, 'grid', ?, 1, ?, '')",
            (GRID_UID, f"g{GRID_UID}", "网格员", A))
        conn.commit()
    clear_cache()
    hid = create_handoff(session_id="sess-boom", user_id=RESIDENT_UID, role="resident",
                         reason="注入测试", intent="handoff", package={"original_input": "测试"})
    req = SimpleNamespace(
        state=SimpleNamespace(user={"uid": GRID_UID, "role": "grid", "name": "网格员", "community": A}),
        query_params={}, client=SimpleNamespace(host="127.0.0.1"))
    # 先正常领取（让状态允许"回复"）
    agent_handoff_action(hid, HandoffAction(action="claim"), req)

    real_get_db = ID.get_db

    class _Boom:
        def __enter__(self):
            raise RuntimeError("database is locked（注入）")

        def __exit__(self, *a):
            return False

    ID.get_db = lambda: _Boom()
    try:
        res = agent_handoff_action(
            hid, HandoffAction(action="reply", text="这条不该发出去", client_token="tok-llll3333"), req)
    finally:
        ID.get_db = real_get_db
    body = res if isinstance(res, dict) else json.loads(bytes(res.body).decode("utf-8"))
    assert body["success"] is False, f"占位失败竟然执行了回复：{body}"
    with db_core.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=?", (RESIDENT_UID,)).fetchone()[0]
        row = conn.execute("SELECT status, reply FROM agent_handoffs WHERE id=?", (hid,)).fetchone()
    assert n == 0, f"注入故障时不该给居民发通知（发了 {n} 条）"
    assert row["status"] == "已领取" and not (row["reply"] or ""), f"处理包不该被改动：{dict(row)}"


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
