# -*- coding: utf-8 -*-
"""通知投递与业务提交拆开（卡9）：发不出去的通知**进队列补发**，且补发必须保留真实业务编号。

**要守住的三件事**：
  ① 通知写失败**不影响业务事实**（调用方拿到的是"业务已成功"，不是异常）；
  ② 失败的通知进队列，补发成功后仍指向**同一张工单/提案**（`related_id` 不丢）；
  ③ 一直发不出去要**留下证据**（试满次数标记"放弃" + 异常留痕），不能静默消失。
"""
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
UID = 99801
GRID = 99811


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="outbox_"), "o.db"))
    with db_core.get_db() as conn:
        for uid, role in ((UID, "resident"), (GRID, "grid")):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, f"n{uid}", A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _outbox():
    with db_core.get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM notification_outbox ORDER BY id").fetchall()]


def _notifications(uid):
    with db_core.get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY id", (uid,)).fetchall()]


def test_normal_notification_does_not_touch_outbox(fresh_db):
    """正常路径不该产生队列记录（队列只装"发失败的"）。"""
    from data.db_notifications import create_notification
    nid = create_notification(UID, "issue", "工单已受理", "请等待处理", related_id=42)
    assert nid > 0 and len(_notifications(UID)) == 1
    assert _outbox() == []


def test_failed_notification_goes_to_outbox(fresh_db):
    """写入失败 → 进队列（并且**不抛异常**：业务不受影响）。"""
    from data.db_notifications import create_notification
    real = db_core.get_db

    def boom(*a, **k):
        raise RuntimeError("数据库忙")

    with mock.patch("data.db_notifications.get_db", side_effect=boom):
        nid = create_notification(UID, "issue", "工单已受理", "请等待处理", related_id=42)
    assert nid == 0, "失败要如实返回 0，不能假装成功"
    rows = _outbox()
    assert len(rows) == 1
    assert rows[0]["status"] == "待发送" and rows[0]["related_id"] == 42
    assert "数据库忙" in rows[0]["last_error"]
    assert rows[0]["tenant_id"] == A, "入队时也要带上社区（便于按社区观测）"
    del real


def test_flush_redelivers_with_real_business_id(fresh_db):
    """补发成功后：通知里带的还是**同一张工单编号**，队列标为已发送。"""
    from data.db_notifications import create_notification
    from data.db_outbox import flush, pending_count

    with mock.patch("data.db_notifications.get_db",
                    side_effect=RuntimeError("数据库忙")):
        create_notification(UID, "issue", "工单已受理", "请等待处理", related_id=777)
    assert pending_count() == 1

    res = flush()
    assert res["sent"] == 1, res
    rows = _notifications(UID)
    assert len(rows) == 1 and rows[0]["related_id"] == 777, "补发必须保留真实业务编号"
    assert _outbox()[0]["status"] == "已发送"
    assert pending_count() == 0


def test_flush_retries_and_backs_off(fresh_db):
    """补发再失败 → 退避重试（attempts+1，下次时间推后），不丢也不假装成功。"""
    from data.db_notifications import create_notification
    from data.db_outbox import flush

    with mock.patch("data.db_notifications.get_db", side_effect=RuntimeError("数据库忙")):
        create_notification(UID, "issue", "标题", "内容", related_id=1)
    # 补发时也让它失败（`_deliver` 是补发唯一的副作用点，在它上面打桩）
    with mock.patch("data.db_outbox._deliver", side_effect=RuntimeError("还是忙")):
        res = flush()
    assert res["failed"] == 1 and res["sent"] == 0
    row = _outbox()[0]
    assert row["attempts"] == 1 and row["status"] == "待发送" and row["next_try_at"]
    assert "还是忙" in row["last_error"]


def test_gives_up_after_max_attempts_with_evidence(fresh_db):
    """试满次数 → 标「放弃」+ 写异常留痕（漏发必须看得见，不能消失）。"""
    from data.db_notifications import create_notification
    from data.db_outbox import MAX_ATTEMPTS, flush, stats

    with mock.patch("data.db_notifications.get_db", side_effect=RuntimeError("数据库忙")):
        create_notification(UID, "issue", "标题", "内容", related_id=5)
    # 反复补发失败：把退避时间清掉，让每次 flush 都能取到
    for _ in range(MAX_ATTEMPTS):
        with db_core.get_db() as conn:
            conn.execute("UPDATE notification_outbox SET next_try_at=datetime('now','-1 minutes')")
            conn.commit()
        with mock.patch("data.db_outbox._deliver", side_effect=RuntimeError("一直忙")):
            flush()
    row = _outbox()[0]
    assert row["status"] == "放弃" and row["attempts"] >= MAX_ATTEMPTS
    st = stats()
    assert st["gave_up"] == 1 and st["pending"] == 0 and st["last_error"]
    with db_core.get_db() as conn:
        exc = conn.execute("SELECT COUNT(*) c FROM exception_log WHERE module='通知投递'").fetchone()["c"]
    assert exc >= 1, "放弃补发必须留下异常记录"


def test_scheduler_includes_outbox_flush():
    """调度器要真的调用补发（写好了没人调 = 没做，本项目的经典坑）。"""
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "scripts", "scheduler.py"), encoding="utf-8").read()
    assert "outbox_sent" in src and "db_outbox" in src, "调度器没接补发"
