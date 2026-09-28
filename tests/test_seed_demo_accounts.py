# -*- coding: utf-8 -*-
"""演示账号可登录（含第二社区）—— **别让演示账号在台上才发现登不上**。

**为什么单独立这条门禁**：`seed_all` 以前对"已存在的用户"只补手机号，
不补密码；第二社区网格员 `demo_grid_cy` 被隔离探测脚本建出来时 `password_hash` 是空的，
于是「多租户隔离」这条演示（另一个社区的网格员也看不到本社区工单）**根本演不出来**——
文档还写着"跑 seed_all 即可修复"，其实修不回来（首批八条浏览器旅程第 7 条实测踩到）。

守住三件事：
  ① seed 定义里的每个**带密码**账号，密码哈希都写进了库；
  ② 空密码哈希能被 seed **补回**（幂等、可重复跑）；
  ③ 已有密码的账号**不被覆盖**（用户自己改过密码就尊重用户的，别拿 seed 冲掉）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

# seed 里必须能登录的账号（用户名 → 口令）；免密账号（居民/老人演示）不在此列
NEED_PASSWORD = {
    "demo_grid": "demo123",
    "demo_grid2": "demo123",
    "demo_resident_cy": "demo123",
    "demo_grid_cy": "demo123",
}


@pytest.fixture()
def seeded_db():
    from data import db_core
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="seed_acct_")
    path = os.path.join(tmp, "seed.db")
    db_core._DB_PATH = ""
    db_core.init_db(path)
    from data.seed import seed_all
    seed_all(path)
    from utils.tenant import clear_cache
    clear_cache()
    yield path
    db_core._DB_PATH = orig
    clear_cache()


def _rows():
    from data.db_core import get_db
    with get_db() as conn:
        return {r["username"]: dict(r) for r in conn.execute(
            "SELECT id, username, role, community, COALESCE(password_hash,'') AS ph FROM user_profile")}


def test_every_seeded_account_with_password_can_login(seeded_db):
    """seed 里带口令的账号都要能真登录（不是"库里有这行"就算数）。"""
    from data.db_user import authenticate
    rows = _rows()
    for uname, pw in NEED_PASSWORD.items():
        assert uname in rows, f"seed 缺少演示账号 {uname}（多租户隔离演示要用）"
        assert rows[uname]["ph"], f"{uname} 没有密码哈希 —— 网格员账号登录不上"
        assert authenticate(uname, pw), f"{uname} 用文档口令登录失败"
        assert not authenticate(uname, "definitely-wrong-pw-123"), f"{uname} 错密码也放行了"


def test_seed_repairs_missing_password(seeded_db):
    """密码哈希为空 → 再跑一次 seed 必须补回来（这正是 demo_grid_cy 的真实故障）。"""
    from data.db_core import get_db
    from data.seed import seed_all
    from data.db_user import authenticate
    with get_db() as conn:
        conn.execute("UPDATE user_profile SET password_hash='' WHERE username='demo_grid_cy'")
        conn.commit()
    assert not authenticate("demo_grid_cy", "demo123"), "前置条件没成立：空密码本该登不上"
    seed_all(seeded_db)
    assert _rows()["demo_grid_cy"]["ph"], "seed 没能补回缺失的密码哈希"
    assert authenticate("demo_grid_cy", "demo123"), "补回后仍登录不上"


def test_seed_does_not_overwrite_user_changed_password(seeded_db):
    """用户自己改过密码的账号不被 seed 冲掉（补的是"缺"，不是"改"）。"""
    from data.db_core import get_db
    from data.seed import seed_all
    from data.db_user import authenticate
    mine = "MyOwnPassw0rd!"
    with get_db() as conn:
        from data.db_core import _hash_password
        conn.execute("UPDATE user_profile SET password_hash=? WHERE username='demo_grid'",
                     (_hash_password(mine),))
        conn.commit()
    seed_all(seeded_db)
    assert authenticate("demo_grid", mine), "seed 覆盖了用户自己改过的密码"
    assert not authenticate("demo_grid", "demo123"), "seed 把密码重置回默认口令了"
