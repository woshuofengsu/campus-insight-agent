# scripts/demo_elderly_inactive.py — 演示用：把某位老人的"最后活跃"回拨，触发 P3 安全闭环
# -*- coding: utf-8 -*-
"""为什么需要它：P3 的"老人久未互动 → 通知网格员/家属"要求老人**真的**超过 24 小时没互动。
演示现场不可能等一天；而演示前跑审计脚本又会把 `last_active_at` 刷新成刚刚（审计确实算互动）。
所以给一个**明确的演示用杠杆**：把时间回拨，让链路可复现地触发。

诚实提示：这是**演示数据操作**，不是业务功能；脚本会打印改了什么、怎么改回来。
用法：
    python scripts/demo_elderly_inactive.py                 # 回拨 demo_elderly 到 30 小时前
    python scripts/demo_elderly_inactive.py --hours 30
    python scripts/demo_elderly_inactive.py --restore       # 改回"刚刚"（恢复正常态）
    python scripts/demo_elderly_inactive.py --run           # 回拨后立刻跑一次巡检，看通知真的生成
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import config  # noqa: E402
from data.db_core import get_db, init_db  # noqa: E402


def _elder(username: str = "demo_elderly"):
    with get_db() as conn:
        return conn.execute("SELECT id, name FROM user_profile WHERE username=?",
                            (username,)).fetchone()


def main() -> int:
    ap = argparse.ArgumentParser(description="演示：触发老人久未互动")
    ap.add_argument("--username", default="demo_elderly")
    ap.add_argument("--hours", type=int, default=30, help="回拨到多少小时之前")
    ap.add_argument("--restore", action="store_true", help="恢复为刚刚活跃")
    ap.add_argument("--run", action="store_true", help="回拨后立刻跑一次安全巡检")
    args = ap.parse_args()

    init_db(config.DB_PATH)
    row = _elder(args.username)
    if not row:
        print(f"❌ 找不到演示老人账号 {args.username}")
        return 1

    with get_db() as conn:
        if args.restore:
            conn.execute("UPDATE elderly_profile SET last_active_at=CURRENT_TIMESTAMP WHERE user_id=?",
                         (row["id"],))
            print(f"✅ 已把 {row['name']} 恢复为「刚刚活跃」")
        else:
            conn.execute(
                "UPDATE elderly_profile SET last_active_at=datetime('now', ?) WHERE user_id=?",
                (f"-{args.hours} hours", row["id"]))
            print(f"✅ 已把 {row['name']} 的 last_active_at 回拨到 {args.hours} 小时前（演示态）")
        conn.commit()

    if args.run:
        from data.db_elderly import get_inactive_elders, notify_inactive_elders
        print("   巡检判定：", [(e["user_id"], e.get("name")) for e in get_inactive_elders(24)])
        n = notify_inactive_elders(24)
        print("   本次新通知老人数：", n)
        if n == 0:
            print("   （0 = 24 小时去重生效：今天已经通知过一次，不会重复打扰——这正是要演示的行为）")
        with get_db() as conn:
            for r in conn.execute(
                    "SELECT n.user_id, u.name AS to_name, u.role, n.title, substr(n.content,1,50) AS c "
                    "FROM notifications n JOIN user_profile u ON u.id=n.user_id "
                    "WHERE n.type='elderly_safety' ORDER BY n.id DESC LIMIT 6"):
                print(f"   → 通知 {r['to_name']}（{r['role']}）：{r['title']} ｜ {r['c']}")
    else:
        print("   下一步：python scripts/demo_elderly_inactive.py --run   （跑巡检看通知）")
        print("   演示完恢复：python scripts/demo_elderly_inactive.py --restore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
