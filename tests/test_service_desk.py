# -*- coding: utf-8 -*-
"""服务台模式门禁（阶段 2）：`/service-desk` 的授权、代录与共享设备清理。

**这一组用例守的是"谁在替谁办理"这件事的底线**，每条都对应一个真实会出事的场景：

  ① 角色：服务台是**工作人员**的工具，居民/老人调不到（否则等于开放代录入口）；
  ② **被代录的人必须在操作人所在社区**——不然是"帮隔壁社区建单"；
  ③ **代录必须有授权依据**（`consent_status`）：没记录就不给提交（fail-closed）；
  ④ **走查用户（无账号）的工单必须按操作人社区盖章**——
     `submit_issue` 按 `reporter_id` 盖章，`reporter_id=0` 会盖成空租户，
     于是这张单在网格端（读取侧 fail-closed）**谁都看不见**（B6 老坑的翻版）；
  ⑤ **结束本次办理**要真清掉服务端草稿；清不掉要**报错**，不许假装清干净；
  ⑥ 已建成的工单**不因清理而消失**（业务事实不能删）。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
GRID_A = 99401
GRID_B = 99402
ELDER_A = 99410
RESIDENT_A = 99411
ELDER_B = 99412


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="desk_"), "g.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((GRID_A, "grid", "王老师", A),
                                     (GRID_B, "grid", "B网格", B),
                                     (ELDER_A, "elderly", "张大爷", A),
                                     (RESIDENT_A, "resident", "A居民", A),
                                     (ELDER_B, "elderly", "B老人", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _req(uid, role="grid", com=A):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"n{uid}", "community": com,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _code(r) -> int:
    if isinstance(r, dict):
        return int(r.get("code", -1))
    try:
        import json
        return int(json.loads(r.body.decode("utf-8")).get("code", -1))
    except Exception:  # noqa: BLE001
        return -1


def _data(r) -> dict:
    if isinstance(r, dict):
        return r.get("data") or {}
    try:
        import json
        return json.loads(r.body.decode("utf-8")).get("data") or {}
    except Exception:  # noqa: BLE001
        return {}


def _msg(r) -> str:
    if isinstance(r, dict):
        return str(r.get("message") or "")
    try:
        import json
        return str(json.loads(r.body.decode("utf-8")).get("message") or "")
    except Exception:  # noqa: BLE001
        return ""


def _submit(request, **kw):
    from api_routes.service_desk import DeskSubmit, service_desk_submit
    body = dict(channel="service_desk_tablet", consent_status="口头同意",
                station_id="STATION-01", reporter_id=ELDER_A,
                reporter_name="张大爷", reporter_phone="13800001111",
                title="楼道灯坏了", description="楼道灯不亮，晚上上下楼看不见",
                location="3号楼2单元", scope="室外", urgency="一般")
    body.update(kw)
    return service_desk_submit(DeskSubmit(**body), request)


def _issue(iid: int) -> dict:
    with db_core.get_db() as conn:
        return dict(conn.execute("SELECT * FROM community_issues WHERE id=?", (iid,)).fetchone())


# ---------------------------------------------------------------- ① 角色

def test_only_staff_can_open_service_desk(fresh_db):
    from api_routes.service_desk import (DeskVoice, service_desk_context, service_desk_extract,
                                         service_desk_search, service_desk_submit)
    for role in ("resident", "elderly"):
        assert _code(service_desk_context(_req(RESIDENT_A, role))) != 0, role
        assert _code(service_desk_search(_req(RESIDENT_A, role))) != 0, role
        assert _code(service_desk_extract(DeskVoice(text="楼道灯坏了"), _req(RESIDENT_A, role))) != 0
        assert _code(_submit(_req(RESIDENT_A, role))) != 0, f"{role} 竟然能代录"
    assert _code(service_desk_context(_req(GRID_A))) == 0


# ---------------------------------------------------------------- ② 社区边界

def test_context_community_comes_from_identity(fresh_db):
    """社区只从服务端身份来（前端传什么都不影响）。"""
    from api_routes.service_desk import service_desk_context
    d = _data(service_desk_context(_req(GRID_A)))
    assert d["community"] == A, d
    assert d["operator"]["uid"] == GRID_A
    # 可选办理方式与服务台口径一致
    vals = {c["value"] for c in d["channels"]}
    assert vals == {"service_desk_tablet", "family_assisted", "grid_recorded", "phone_manual"}
    # 本社区人员列表里不该出现别的社区的人
    ids = {p["id"] for p in d["people"]}
    assert ELDER_A in ids and ELDER_B not in ids, d["people"]


def test_cannot_record_for_another_community(fresh_db):
    """**帮隔壁社区建单**必须被拒（这不是"格式问题"，是越权写入）。"""
    r = _submit(_req(GRID_A), reporter_id=ELDER_B, reporter_name="B老人")
    assert _code(r) != 0, "竟然给别的社区的人代录成功了"
    assert "社区" in _msg(r), _msg(r)
    with db_core.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM community_issues").fetchone()["c"]
    assert n == 0, "被拒的代录不能留下半截数据"


def test_channel_and_consent_are_validated(fresh_db):
    assert _code(_submit(_req(GRID_A), channel="elderly_self")) != 0, "自助渠道不该走服务台入口"
    r = _submit(_req(GRID_A), consent_status="")
    assert _code(r) != 0 and "授权" in _msg(r), (r, _msg(r))
    assert _code(_submit(_req(GRID_A), consent_status="随便写的")) != 0


# ---------------------------------------------------------------- ③④ 代录落库与双身份

def test_assisted_submit_records_operator_and_reporter_separately(fresh_db):
    r = _submit(_req(GRID_A))
    assert _code(r) == 0, r
    d = _data(r)
    assert d["issue_code"], "服务台提交必须返回对外事项编号"
    row = _issue(d["issue_id"])
    assert row["reporter_id"] == ELDER_A, "reporter 必须是被代录的人"
    assert row["operator_user_id"] == GRID_A, "operator 必须是实际操作的工作人员"
    assert row["reporter_id"] != row["operator_user_id"]
    assert row["submission_channel"] == "service_desk_tablet"
    assert row["station_id"] == "STATION-01"
    assert row["consent_status"] == "口头同意"


def test_walk_in_issue_is_stamped_with_operator_community(fresh_db):
    """**走查用户（无账号）**：工单必须按操作人社区盖章，否则网格端谁都看不见。"""
    r = _submit(_req(GRID_A), reporter_id=0, reporter_name="路过的大爷",
                reporter_phone="13900002222")
    assert _code(r) == 0, r
    d = _data(r)
    assert d["walk_in"] is True
    row = _issue(d["issue_id"])
    assert row["tenant_id"] == A, f"走查工单租户是「{row['tenant_id']}」——网格端会看不见"
    # 且真的能在本社区列表里被读到（读取侧 fail-closed 反证）
    from data.db_repair import get_issues
    titles = [i.get("title") for i in get_issues(tenant=A)]
    assert "楼道灯坏了" in titles, "按社区读不到刚建的走查工单"


def test_walk_in_requires_name_and_phone(fresh_db):
    """走查用户必须有姓名与手机号（否则网格员联系不上，等于建废单）。"""
    assert _code(_submit(_req(GRID_A), reporter_id=0, reporter_name="", reporter_phone="")) != 0
    assert _code(_submit(_req(GRID_A), reporter_id=0, reporter_name="大爷",
                         reporter_phone="")) != 0


def test_service_desk_submit_is_idempotent(fresh_db):
    tok = "desktok-" + "a" * 12
    r1 = _submit(_req(GRID_A), client_token=tok)
    r2 = _submit(_req(GRID_A), client_token=tok)
    assert _code(r1) == 0 and _code(r2) == 0
    assert _data(r1)["issue_id"] == _data(r2)["issue_id"], "同编号提交建了两张单"
    assert _data(r2).get("duplicate") is True


# ---------------------------------------------------------------- 提取（复用老人端契约）

def test_extract_reuses_elderly_contract(fresh_db):
    from api_routes.service_desk import DeskVoice, service_desk_extract
    d = _data(service_desk_extract(DeskVoice(text="3号楼2单元楼道灯不亮"), _req(GRID_A)))
    assert d["fields"], d
    assert d["sources"], "抽取必须带字段来源（老人端同一套契约）"


# ---------------------------------------------------------------- 查询

def test_search_by_name_and_code(fresh_db):
    from api_routes.service_desk import service_desk_search
    d0 = _data(_submit(_req(GRID_A)))
    by_name = _data(service_desk_search(_req(GRID_A), name="张大爷"))
    assert by_name["count"] == 1, by_name
    by_code = _data(service_desk_search(_req(GRID_A), code=d0["issue_code"]))
    assert by_code["count"] == 1 and by_code["items"][0]["issue_id"] == d0["issue_id"]
    # 手机号只收后四位
    assert _data(service_desk_search(_req(GRID_A), phone_tail="13800001111"))["count"] == 0
    assert _data(service_desk_search(_req(GRID_A), phone_tail="1111"))["count"] == 1
    # 跨社区查不到
    assert _data(service_desk_search(_req(GRID_B, com=B), name="张大爷"))["count"] == 0


# ---------------------------------------------------------------- ⑤⑥ 结束本次办理

def test_reset_clears_drafts_but_keeps_issues(fresh_db):
    from api_routes.service_desk import DeskReset, service_desk_reset
    d0 = _data(_submit(_req(GRID_A)))
    # 造一条草稿（服务台/老人端都可能留下）
    from data.db_repair import create_draft
    did = create_draft(ELDER_A, "半截的事", "公共设施", "室外", "3号楼", "写到一半", "一般")
    assert did > 0
    out = _data(service_desk_reset(DeskReset(station_id="STATION-01", reporter_id=ELDER_A),
                                   _req(GRID_A)))
    assert out["drafts"] >= 1, out
    with db_core.get_db() as conn:
        n_draft = conn.execute("SELECT COUNT(*) c FROM issue_drafts WHERE user_id=?",
                               (ELDER_A,)).fetchone()["c"]
        n_issue = conn.execute("SELECT COUNT(*) c FROM community_issues").fetchone()["c"]
    assert n_draft == 0, "草稿没清干净"
    assert n_issue == 1, "已提交的工单不该被清理删掉（那是业务记录）"
    assert "工单" in out["kept"], out


def test_reset_reports_failure_instead_of_pretending(fresh_db, monkeypatch):
    """清不掉必须**报错**（否则下一位老人的信息还留在机器上，却显示"已清理"）。"""
    from api_routes.service_desk import DeskReset, service_desk_reset
    import data.db_core as core
    real = core.get_db

    def _boom(*a, **kw):
        raise RuntimeError("模拟清理失败")

    monkeypatch.setattr(core, "get_db", _boom)
    r = service_desk_reset(DeskReset(reporter_id=ELDER_A), _req(GRID_A))
    monkeypatch.setattr(core, "get_db", real)
    assert _code(r) != 0 and "清理" in _msg(r), (r, _msg(r))
