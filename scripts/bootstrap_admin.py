# -*- coding: utf-8 -*-
"""首个社区负责人账号的**显式引导**（生产空库初始化之后的第一步）。

## 为什么必须有这个脚本

生产红线是"空库初始化"——`DEMO_MODE=false` 启动一套空库时，服务只建表结构、
**不灌任何演示账号**（见 `api_web._ensure_db()` 与 `scripts/empty_db_drill.py`）。
但这样一来"怎么登进去"就成了新问题：空库里一个账号都没有。

这个脚本就是那一步：**在空库里显式创建第一个负责人账号**。

## 三条硬约束（都是踩过的坑）

1. **必须给强密码**：`data.db_user.authenticate()` 的历史行为是——
   `role='resident'` 且 `password_hash` 为空时**任意密码（含空密码）都能登进去**。
   演示数据库无所谓，生产库里这就是个洞。所以本脚本对**所有角色**都强制 ≥12 位密码。
2. **不许用 `demo` 开头的用户名**：那是演示账号的命名前缀，
   生产库里出现 `demo*` 账号等于"红线被破了"，这里直接拒绝（不是警告）。
3. **社区名必填**：租户键 = 社区名。账号没有社区 → 它的数据谁都看不见
   （读取侧 fail-closed），而且第一单就会盖成空租户。所以社区名在这里是**必填参数**。

## 用法

```bash
# 首次部署（生产姿态）：
python scripts/bootstrap_admin.py --username zhuren01 --name 王主任 \\
    --community 幸福里社区 --generate-password

# 或者自带强密码（≥12 位）：
python scripts/bootstrap_admin.py --username zhuren01 --name 王主任 \\
    --community 幸福里社区 --password '<强密码>'
```
"""
import argparse
import os
import secrets
import sqlite3
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

MIN_PW = 12


def _gen_password(n: int = 20) -> str:
    """生成一次性强密码（去掉容易看错的 0/O/1/l/I）。"""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main() -> int:
    ap = argparse.ArgumentParser(description="在空库里创建第一个社区负责人账号")
    ap.add_argument("--username", required=True)
    ap.add_argument("--name", required=True, help="真实姓名（界面上显示）")
    ap.add_argument("--community", required=True, help="社区名 = 租户键，必须与材料/部署配置一致")
    ap.add_argument("--role", default="grid", choices=["grid", "resident", "elderly"])
    ap.add_argument("--password", default="")
    ap.add_argument("--generate-password", action="store_true")
    ap.add_argument("--building", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--db", default="", help="默认用 config.DB_PATH（可用 COMMUNITY_DB_PATH 指定）")
    ap.add_argument("--force", action="store_true",
                    help="演示姿态（DEMO_MODE=true）下也允许执行（默认拒绝，避免误在生产之外重复建号）")
    a = ap.parse_args()

    import config
    db_path = a.db or config.DB_PATH

    if not os.path.exists(db_path):
        print(f"[失败] 数据库不存在：{db_path}")
        print("       先启动一次服务（会自动建表并跑迁移），或用 COMMUNITY_DB_PATH 指到目标库。")
        return 2

    # ---- 约束 2：演示账号前缀不许出现在生产库里 ----
    if a.username.strip().lower().startswith("demo"):
        print("[失败] 用户名以 `demo` 开头——那是演示账号的命名前缀，生产库里不许出现。")
        print("       请换一个真实账号名（例：zhuren01 / wangzhuren）。")
        return 2

    # ---- 约束 3：社区名必填（租户键）----
    community = a.community.strip()
    if not community:
        print("[失败] 社区名不能为空：它是租户键，缺了会导致这个账号的数据谁都看不见。")
        return 2

    # ---- 约束 1：强密码必填 ----
    pw = a.password
    generated = False
    if a.generate_password and not pw:
        pw = _gen_password()
        generated = True
    if not pw:
        print("[失败] 必须给密码：用 --password '<强密码>' 或 --generate-password。")
        print(f"       （≥{MIN_PW} 位；居民角色的空密码会被 authenticate 放行，生产库不能这样）")
        return 2
    if len(pw) < MIN_PW:
        print(f"[失败] 密码只有 {len(pw)} 位，要求 ≥{MIN_PW} 位。")
        return 2

    if config.DEMO_MODE and not a.force:
        print("[失败] 当前是**演示姿态**（DEMO_MODE=true），本脚本面向生产空库。")
        print("       确认要在演示库里建号就加 --force。")
        return 2

    # ---- 库必须已初始化 ----
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        has = conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name='user_profile'").fetchone()
        if not has:
            print("[失败] 库里没有 user_profile 表——先启动一次服务完成建表与迁移。")
            return 2
        dup = conn.execute("SELECT id, role FROM user_profile WHERE username=?",
                           (a.username.strip(),)).fetchone()
        if dup:
            print(f"[失败] 用户名已存在（id={dup['id']}，role={dup['role']}）——本脚本不覆盖已有账号。")
            print("       要改密码请用服务里的「修改密码」，或删掉该账号后重建。")
            return 2
    finally:
        conn.close()

    from data.db_core import init_db
    from data.db_user import create_user

    init_db(db_path)                      # 幂等：保证连接层指向这个库
    uid = create_user(username=a.username.strip(), password=pw, role=a.role,
                      community=community, building=a.building, unit=a.unit,
                      name=a.name.strip())

    print("=" * 70)
    print("首个账号已创建（请立刻在服务里改密码，或记录进密码管理器）")
    print(f"  账号　：{a.username.strip()}")
    print(f"  姓名　：{a.name.strip()}")
    print(f"  角色　：{a.role}" + ("（社区负责人，可进服务台/工单/治理页）" if a.role == "grid" else ""))
    print(f"  社区　：{community}")
    print(f"  用户 id：{uid}")
    print(f"  数据库：{db_path}")
    if generated:
        print(f"  一次性密码：{pw}   ← 只显示这一次，请现在记下")
    print("-" * 70)
    print("下一步：登录 → 新建本社区其他负责人 → 再建居民/老人账号（别用 demo 前缀）。")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
