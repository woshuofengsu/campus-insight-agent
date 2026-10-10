# -*- coding: utf-8 -*-
"""试点加固批的回归网（2026-10-06）——**一次性审查抓到的真缺陷，各自一条测试守住**。

这一批不是"新功能"，全是**缺陷修复**（试点冻结期内只修缺陷）。每条测试的 docstring 写清
"原来错在哪、会怎样害到真人"，避免以后有人"优化"回去。

覆盖：
1. 重复上报检测**只能在同一个社区内比对**（原来会把别社区工单当成重复 → 给别社区居民发通知）；
2. 安全隐患记录**按社区过滤**（该表没有 tenant_id 列，按上报人社区过滤；取不到社区给空集）；
3. 关闭工单**幂等**（原来重复关闭会重复给居民发"工单已关闭"）；
4. 报修草稿删除**只认创建者**（原来网格员身份会把归属校验短路掉）；
5. SOS 通知里**有回电号码且是掩码**（原来读的是恒为空的明文列，号码永远是空的）；
6. 家属代触发 SOS 的身份校验**fail-closed**（原来查库异常直接放行）。

隔离说明：与 `tests/test_tenant_idor_sweep.py` 相同——临时库 + teardown 恢复 `db_core._DB_PATH`。
"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"        # 租户 A
B = "朝阳试点社区"    # 租户 B
UID_A = 97201
UID_B = 97202
GRID_A = 97211
GRID_B = 97212
UID_E = 97221         # A 社区的老人


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="pilot_hardening_")
    path = os.path.join(tmp, "hardening.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, community in (
                (UID_A, "resident", "A居民", A), (UID_B, "resident", "B居民", B),
                (GRID_A, "grid", "A网格", A), (GRID_B, "grid", "B网格", B),
                (UID_E, "elderly", "A老人", A)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, community))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


def _req(uid, role, community):
    """最小可用 Request 替身（按 id 路由只用到 state.user）。"""
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"{community}{role}", "community": community,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _denied(res) -> bool:
    if isinstance(res, dict):
        return not res.get("success")
    return not json.loads(bytes(res.body).decode("utf-8")).get("success")


def _notif_count(user_id: int) -> int:
    with db_core.get_db() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id=?",
                            (user_id,)).fetchone()["n"]


# ---------------- 1. 重复上报检测：只在同一社区内比对 ----------------

def test_duplicate_detection_only_within_same_community():
    """原来没有任何租户条件：地址前 5 字（"3号楼"）各社区高度重合 →
    A 社区的新报修会被判成与 B 社区某单重复，给**别社区居民**发通知、
    并把**别社区工单号**回显给本社区居民（还说"已合并处理"）。

    判据：两个社区**都有一条地址前 5 字与描述完全相同**的工单，
    各自查询时必须只命中**自己社区**那条（而不是"谁先建谁被命中"）。
    """
    from data.db_repair import submit_issue, find_duplicate_issue
    # 地址前 5 字刻意相同（这正是误命中的来源），只有社区名不同
    a_id, err_a = submit_issue(title="同楼栋漏水", category="公共设施", issue_type="室内",
                               location="3号楼2单元-海淀", description="厨房水管一直在漏水",
                               urgency="一般", reporter_name="A居民",
                               reporter_phone="13800000021", reporter_id=UID_A)
    assert a_id > 0, err_a
    b_id, err_b = submit_issue(title="同楼栋漏水", category="公共设施", issue_type="室内",
                               location="3号楼2单元-朝阳", description="厨房水管一直在漏水",
                               urgency="一般", reporter_name="B居民",
                               reporter_phone="13800000023", reporter_id=UID_B)
    assert b_id > 0, err_b

    dup_a = find_duplicate_issue("3号楼2单元-海淀", "厨房水管一直在漏水", tenant=A)
    assert dup_a and dup_a["id"] == a_id, "本社区的重复应当命中的是**自己社区**那条"
    dup_b = find_duplicate_issue("3号楼2单元-朝阳", "厨房水管一直在漏水", tenant=B)
    assert dup_b and dup_b["id"] == b_id, "B 社区必须命中 B 自己那条"
    assert dup_b["id"] != a_id and dup_a["id"] != b_id, \
        "跨社区绝不能被当成重复（原来这里会把别社区工单返回给自己）"
    # 取不到合法社区 → 不判定（fail-closed，不允许"没社区就查全库"）
    assert find_duplicate_issue("3号楼2单元-海淀", "厨房水管一直在漏水", tenant="") is None
    with pytest.raises(ValueError):
        find_duplicate_issue("3号楼2单元-海淀", "厨房水管一直在漏水")  # 不给范围必须报错

    # ⚠️ 必须覆盖 **exclude_id 分支**：修这条时我自己的实现把"租户参数"与"exclude_id"的顺序写反了，
    #    而当时这条测试没走 exclude_id，是既有用例 `test_agent.py::test_duplicate_issue_merge` 报红才发现的。
    #    真实链路走的就是 exclude_id（建单后排除自己再找重复），所以这里必须钉住。
    a_id2, err_a2 = submit_issue(title="同楼栋漏水", category="公共设施", issue_type="室内",
                                 location="3号楼2单元-海淀", description="厨房水管一直在漏水",
                                 urgency="一般", reporter_name="A居民",
                                 reporter_phone="13800000024", reporter_id=UID_A)
    assert a_id2 > 0, err_a2
    dup_ex = find_duplicate_issue("3号楼2单元-海淀", "厨房水管一直在漏水",
                                 exclude_id=a_id2, tenant=A)
    assert dup_ex and dup_ex["id"] == a_id, \
        "带 exclude_id 时必须排除自己、命中**同社区更早那条**（参数顺序写反会一条都查不到）"
    assert find_duplicate_issue("3号楼2单元-朝阳", "厨房水管一直在漏水",
                                exclude_id=b_id, tenant=B) is None, "排除自己后 B 社区没有别的同类单"


# ---------------- 2. 安全隐患记录：按社区过滤 ----------------

def test_safety_reminders_are_tenant_scoped():
    """`safety_reminders` 没有 tenant_id 列 → 按**上报人社区**过滤。
    原来直接返回全表：任何社区的网格员都能读到别社区"疑似燃气泄漏"+地址+上报人 uid。"""
    from data.db_repair import get_safety_reminders
    with db_core.get_db() as conn:
        conn.execute("INSERT INTO safety_reminders (user_id, description, location) VALUES (?,?,?)",
                     (UID_A, "疑似燃气泄漏，已闻到味道", "海淀小区3号楼2单元"))
        conn.commit()
    mine = get_safety_reminders(tenant=A)
    assert any(r["user_id"] == UID_A for r in mine), "本社区的安全隐患必须看得到"
    assert get_safety_reminders(tenant=B) == [], "别社区不许读到（原实现返回全表）"
    assert get_safety_reminders(tenant="") == [], "取不到社区 → 空集（fail-closed）"


# ---------------- 3. 关闭工单幂等：不重复通知居民 ----------------

def test_close_issue_is_idempotent_and_does_not_renotify():
    """原来 `close_issue` 不看状态就改 + 发通知：批量关闭或界面重复点击时，
    居民每被点一次就再收到一条"工单已关闭"（同一件事刷屏）。"""
    from data.db_repair import submit_issue, close_issue, get_issue
    iid, _ = submit_issue(title="路灯不亮", category="公共设施", issue_type="室外",
                          location="海淀小区广场", description="广场东侧路灯不亮两天了",
                          urgency="一般", reporter_name="A居民",
                          reporter_phone="13800000022", reporter_id=UID_A)
    before = _notif_count(UID_A)
    ok1, _m1 = close_issue(iid, "统一处理", actor="A网格")
    assert ok1, "首次关闭应当成功"
    after_first = _notif_count(UID_A)
    assert after_first == before + 1, "首次关闭应通知居民一次"
    ok2, msg2 = close_issue(iid, "统一处理", actor="A网格")
    assert not ok2 and "已关闭" in msg2, f"重复关闭应被拒绝并说明原因，实际：{ok2} {msg2}"
    assert _notif_count(UID_A) == after_first, "重复关闭**不许**再发一条通知"
    assert get_issue(iid)["status"] == "已关闭"


# ---------------- 4. 草稿删除：只认创建者 ----------------

def test_draft_delete_requires_ownership_even_for_grid():
    """原来写的是 `role != "grid" and d.user_id != uid` —— 网格员身份把整个条件短路掉，
    于是**任何网格员都能按自增 id 删掉别人的草稿**（草稿含地址/描述/加密手机号，
    还能用 1004 与成功区分 id 是否存在）。"""
    from data.db_repair import create_draft, get_draft
    from api_routes import issues as issues_mod
    create_draft(UID_A, title="草稿：楼道灯坏", category="", issue_type="室内",
                 location="海淀小区3号楼", description="楼道灯坏了两天", urgency="一般",
                 reporter_name="", reporter_phone="")
    with db_core.get_db() as conn:
        did = conn.execute("SELECT id FROM issue_drafts WHERE user_id=? ORDER BY id DESC",
                           (UID_A,)).fetchone()["id"]
    assert get_draft(did), "前提：草稿已建"
    # 本社区网格员也不行（草稿只属于创建者，代办走服务台）
    assert _denied(issues_mod.issue_draft_delete(did, _req(GRID_A, "grid", A)))
    # 别社区网格员更不行
    assert _denied(issues_mod.issue_draft_delete(did, _req(GRID_B, "grid", B)))
    # 别人（居民）也不行；本人可以
    assert _denied(issues_mod.issue_draft_delete(did, _req(UID_B, "resident", B)))
    assert get_draft(did), "被拒绝时不许真的删掉"
    assert not _denied(issues_mod.issue_draft_delete(did, _req(UID_A, "resident", A)))
    assert get_draft(did) is None, "本人删除应当生效"


# ---------------- 5. SOS 通知：有号码，而且是掩码 ----------------

def test_sos_notification_carries_masked_phone(monkeypatch):
    """原来读 `get_user_by_id(uid)["phone"]` —— 那是**按约定恒为空**的明文列，
    于是最高优先级的 SOS 通知里"电话："永远是空的，网格员拿不到回电号码。"""
    from data import db_elderly_care as ec
    from data.db_repair import _enc_phone

    with db_core.get_db() as conn:
        conn.execute("UPDATE user_profile SET phone_enc=? WHERE id=?",
                     (_enc_phone("13800007221"), UID_E))
        conn.commit()

    monkeypatch.setattr(ec, "get_approved_contacts",
                        lambda uid: [{"name": "A家属", "phone": "13800009999"}])
    captured = {}

    def _fake_notify(title, content, call_id, tenant=""):
        captured["title"] = title
        captured["content"] = content
        captured["tenant"] = tenant

    monkeypatch.setattr(ec, "_notify_grids", _fake_notify)
    cid, err = ec.trigger_sos(UID_E, actor="A老人")
    assert cid > 0, err
    assert "电话：138****7221" in captured["content"], \
        f"SOS 通知必须带**掩码**回电号码，实际内容：{captured['content']}"
    assert "13800007221" not in captured["content"], "通知里不许出现完整手机号"


# ---------------- 6. 家属代触发 SOS：校验失败必须拒绝 ----------------

def test_family_check_fails_closed_when_binding_lookup_breaks(monkeypatch):
    """原来是 `except Exception: pass`：查库异常时**直接放行**，且日志里没有痕迹。
    授权判断必须 fail-closed（组件坏了要拒绝，不许放行）。"""
    from api_routes import elderly as elderly_mod
    import data.db_user as db_user

    def _boom(uid):
        raise RuntimeError("模拟绑定关系查询失败")

    monkeypatch.setattr(db_user, "get_bound_elderly", _boom)
    res = elderly_mod.web_emergency_trigger(_req(UID_E, "elderly", A))
    assert _denied(res), "绑定关系查不出来时必须拒绝，而不是照常触发 SOS"
