# -*- coding: utf-8 -*-
"""老人端「我的报修」接口：带进度、只给自己的单、不泄露敏感字段（§6-I9）。"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
ELDER = 99601
OTHER = 99602
PHONE = "13800009601"


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="orders_"), "o.db"))
    with db_core.get_db() as conn:
        for uid, com in ((ELDER, A), (OTHER, B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, 'elderly', ?, 1, ?)", (uid, f"u{uid}", f"n{uid}", com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _req(uid, com=A):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": "elderly", "name": "老人", "community": com,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _seed_issue(uid, title, status, tenant):
    from data.db_repair import submit_issue
    iid, _ = submit_issue(title=title, category="设施维修", issue_type="室外",
                          location="5号楼2层楼道", description=title, urgency="一般",
                          reporter_name="老人", reporter_phone=PHONE, reporter_id=uid)
    from data.db_core import get_db
    with get_db() as conn:
        conn.execute("UPDATE community_issues SET status=?, tenant_id=?, "
                     "approved_at='2026-09-28 10:00:00' WHERE id=?", (status, tenant, iid))
        conn.commit()
    return iid


def _ok(res):
    if isinstance(res, dict):
        return res
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8"))


def test_orders_carry_readable_progress(fresh_db):
    from api_routes.elderly import web_elderly_orders
    _seed_issue(ELDER, "5号楼2层楼道灯坏了", "已派单", A)
    res = _ok(web_elderly_orders(_req(ELDER)))
    assert res["success"], res
    rows = res["data"]
    assert len(rows) == 1
    p = rows[0]["progress"]
    assert p["now_line"] and p["next_line"] and p["who"] and p["eta_line"]
    assert p["steps"] and isinstance(p["step_index"], int)


def test_orders_only_mine(fresh_db):
    """只能看到自己报的单（别人的不出现）。"""
    from api_routes.elderly import web_elderly_orders
    _seed_issue(ELDER, "我家的楼道灯坏了", "待审核", A)
    _seed_issue(OTHER, "别人家的楼道灯坏了", "待审核", B)
    rows = _ok(web_elderly_orders(_req(ELDER)))["data"]
    titles = [r["title"] for r in rows]
    assert "我家的楼道灯坏了" in titles, f"本人的单必须能看到：{titles}"
    assert "别人家的楼道灯坏了" not in titles


def test_orders_hide_phone_fields(fresh_db):
    """老人端列表不回传手机号（含密文列）——页面上用不到，就别带出来。"""
    from api_routes.elderly import web_elderly_orders
    _seed_issue(ELDER, "5号楼2层楼道灯坏了", "处理中", A)
    row = _ok(web_elderly_orders(_req(ELDER)))["data"][0]
    for k in ("reporter_phone", "reporter_phone_enc", "agent_phone", "agent_phone_enc"):
        assert k not in row, f"不该回传 {k}"
