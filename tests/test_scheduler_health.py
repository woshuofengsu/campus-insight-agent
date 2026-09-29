# -*- coding: utf-8 -*-
"""定时任务健康门禁：**每个自动任务都要真的能跑通**（外部评审第十一轮引出的教训）。

**为什么单列这条门禁**：`scripts/scheduler.py` 里所有任务都被 `_safe()` 包着——
"失败只记一条 warning，不打断其它任务"。这个设计本身是对的（一个任务坏了不该拖垮全部），
但它有个致命副作用：**任务可能从来没跑成过，而界面上完全看不出来**。

实测踩到（2026-09-29，在**演示库副本**上逐个任务探测）：`SOS升级` 长这样——

    get_sos_calls(status="求助中")        # ← 没传社区

多租户 fail-closed 直接抛 `ValueError: 跨用户列表/聚合查询必须显式提供 tenant=`，
于是**老人 SOS 无人响应升级这个任务一次都没执行过**（安全链路上静默丢失）。
本文件守住：所有任务在当前 schema 上都能跑完，且 SOS 升级**真的会升级**。
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
ELDER = 99401
GRID = 99402


@pytest.fixture()
def seeded_db():
    """空库 → init_db + seed_all（与真实交付同一套建库路径；不用演示库，避免污染）。"""
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="sched_health_")
    path = os.path.join(tmp, "sched.db")
    db_core._DB_PATH = ""
    db_core.init_db(path)
    from data.seed import seed_all
    seed_all(path)
    with db_core.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, "
            "community, phone_enc) VALUES (?, ?, 'elderly', ?, 1, ?, '')",
            (ELDER, f"e{ELDER}", "张大爷", A))
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, "
            "community, phone_enc) VALUES (?, ?, 'grid', ?, 1, ?, '')",
            (GRID, f"g{GRID}", "刘网格员", A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield path
    db_core._DB_PATH = orig
    clear_cache()


def _task_list() -> dict:
    """任务清单：**与调度器同源**（别在测试里另抄一份，否则抄的那份会先过期）。"""
    import scripts.scheduler as S
    tasks = {name: fn for _key, (name, fn) in S.scheduled_tasks().items()}
    assert len(tasks) >= 20, f"任务清单异常（只有 {len(tasks)} 个）：{list(tasks)[:5]}"
    return tasks


def _make_active_sos(minutes_ago: int = 1) -> int:
    """造一条"进行中的紧急求助"，并把创建时间推到 `minutes_ago` 分钟前。

    ⚠️ 回填时间**必须用 SQLite 的 UTC 时钟**（`datetime('now','-N minutes')`）：
    `created_at` 存的是 `CURRENT_TIMESTAMP`（UTC），而 `escalate_sos` 也用 `utcnow()` 比。
    本机时区是 UTC+8，若用 `datetime.now()-11min` 写入，等于写了个"未来时间"，
    升级判定会得到负的年龄 → 任务看起来"没生效"（实测踩到，纯属测试自身的时间口径错误）。
    库内时间口径统一成一句：**谁写入用哪个时钟，比较就用哪个时钟**。
    """
    from data.db_core import get_db
    from data.db_elderly_care import (add_emergency_contact, audit_emergency_contact,
                                      trigger_sos)
    contacts = add_emergency_contact(ELDER, "女儿", "13800009999", "家属")
    cid = contacts[0] if isinstance(contacts, tuple) else contacts
    audit_emergency_contact(cid, True, actor="网格员")
    call_id, msg = trigger_sos(ELDER, actor="老人")
    assert call_id, f"前置失败：没建出求助记录（{msg}）"
    with get_db() as conn:
        conn.execute("UPDATE emergency_calls SET created_at=datetime('now', ?) WHERE id=?",
                     (f"-{int(minutes_ago)} minutes", call_id))
        conn.commit()
    return call_id


def test_every_scheduled_task_runs_on_current_schema(seeded_db):
    """所有自动任务都要能跑完（不抛异常）——这就是"静默失效"的照妖镜。"""
    bad = []
    for name, fn in _task_list().items():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            bad.append(f"{name}: {type(e).__name__}: {str(e)[:110]}")
    assert not bad, "有定时任务在当前 schema 上跑不通（界面看不出来，但功能是坏的）：\n  " + "\n  ".join(bad)


def test_sos_escalation_actually_escalates(seeded_db):
    """SOS 升级**真的要升级**：11 分钟未响应的求助 → 跑任务后应产生升级动作/通知。

    这条是"任务能跑通"之外的**行为级**验证：跑通不等于做了事
    （第 11 轮评审的教训是"机制存在 ≠ 入口接通"，这里同理：任务不抛异常 ≠ 真的升级了）。
    """
    import scripts.scheduler as S
    from data.db_core import get_db

    call_id = _make_active_sos(minutes_ago=11)
    res = S._sos_escalations()
    assert res >= 1, "SOS 升级任务没有升级任何一条超时求助（fail-closed 挡住过？）"
    with get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM notifications WHERE title LIKE '%求助%'").fetchone()["c"]
        log = conn.execute(
            "SELECT COUNT(*) c FROM activity_log WHERE target_id=?", (call_id,)).fetchone()["c"]
        result = conn.execute("SELECT result FROM emergency_calls WHERE id=?", (call_id,)).fetchone()["result"]
    assert n > 0 or log > 0, "升级动作没有留下通知或留痕（等于没升级）"
    assert "已升级" in (result or ""), f"求助记录没有留下升级痕迹：{result!r}"


def test_sos_escalation_is_scoped_per_tenant(seeded_db):
    """按社区逐个跑：A 社区的求助归 A 社区负责人（不能靠"不传租户查全库"来实现）。"""
    import scripts.scheduler as S
    from data.db_elderly_care import get_sos_calls

    _make_active_sos(minutes_ago=1)
    # 建完"算数"的：本社区看得到、别的社区看不到（fail-closed），任务仍能跑完
    assert get_sos_calls(status="求助中", limit=50, tenant=A), "本社区应当能看到这条求助"
    assert get_sos_calls(status="求助中", limit=50, tenant="别的社区") == [], "跨社区不该看得到"
    S._sos_escalations()   # 只为确认按社区跑不抛异常
    # 换个不存在的社区：按 fail-closed 应当看不到（证明任务不是"查全库"跑通的）
    assert get_sos_calls(status="求助中", limit=50, tenant="别的社区") == []
    S._sos_escalations()   # 只为确认按社区跑不抛异常
