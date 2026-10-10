# -*- coding: utf-8 -*-
"""试点冻结校验 —— 把"**暂时不要再增加新 Agent、新页面和新业务模块**"变成可执行的门禁。

## 为什么要有它

用户给的顺序里，第一步就是"冻结目标"：老年端 6 个入口 / 三个主要动作 / 报修·问答·进度流程 /
网格接单处置流程 / 当前 UI 版本 / 当前接口与数据库结构 —— 全部冻住，**不再加功能**。

但"不再加功能"如果只写在文档里，它的执行就依赖记性。本项目已经反复吃过这个亏
（dev-log 六十四：门禁盲区；六十八：文档与代码矛盾；六十九：删变量删出白字白底）。
所以这里把冻结项写成**可复算的数字**，任何一项变大就是红：

| 冻结项 | 判据 | 现在 |
|---|---|---|
| 接口面 | HTTP 路由数 | 158 |
| 老年端入口 | 老年端路由数 | 8 |
| 居民端/网格端页面 | 各端路由数 | 14 / 9 |
| 多智能体规模 | `AGENT_CLASSES` 角色数 | 9 |
| 数据面 | 业务表数 / schema 版本 / 迁移条数 | 54 / 54 / 53 |
| 路由模块数 | `api_routes/*.py` 里定义 APIRouter 的模块 | 15 |
| 老年端一级导航 | `ElderlyLayout.vue` 的 `navs` 条数 | **6** |
| 老年端主要动作 | 首页 `quick` 条数 | **3** |
| 紧急求助入口 | `data-longpress` 元素数 | **2** |

数字变大 → 说明加了东西（要显式 `--update --force` 并写明理由）；
数字**变小** → 说明删了东西，同样报红（冻结的意义是"两边都不许动"）。

用法：
    python scripts/pilot_freeze_check.py            # 校验（=0 才算"冻结成立"）
    python scripts/pilot_freeze_check.py --detail   # 附各项的来源
    python scripts/pilot_freeze_check.py --update --force   # 改冻结值（要写明理由）
"""
import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

#: 冻结值（2026-10-06，`pilot-ui-v1` 打标签时的实测值）。**两边都不许动**。
#: ⚠️ 三端页面数是**实测修正后**的值：材料里长期写着「居民 14 / 网格 9 / 老年 8」，
#: 而代码里实际是 **14 / 10 / 10**（网格端后来加了消息中心与健康、老年端加了健康与用药，
#: 文档没跟着改）。冻结必须以**代码为准**——顺手把这几个数字加进了 `check_claims` 的结构核对，
#: 以后不许再漂。文档侧的数字已在同一批修掉。
FROZEN = {
    "routes": 158,
    "routes_elderly": 10,
    "routes_resident": 14,
    "routes_grid": 10,
    "agents": 9,
    "tables": 54,
    "schema": 54,
    "migrations": 53,
    "route_modules": 15,
    "elderly_nav": 6,
    "elderly_quick_actions": 3,
    "elderly_sos_entries": 2,
}

_LABEL = {
    "routes": "HTTP 路由数（接口面）",
    "routes_elderly": "老年端路由数",
    "routes_resident": "居民端路由数",
    "routes_grid": "网格端路由数",
    "agents": "Agent 角色数",
    "tables": "业务表数",
    "schema": "schema 版本",
    "migrations": "版本化迁移条数",
    "route_modules": "路由模块数",
    "elderly_nav": "老年端一级导航入口",
    "elderly_quick_actions": "老年端首页主要动作",
    "elderly_sos_entries": "紧急求助入口（长按键）",
}


def _routes_by_portal() -> dict:
    """各端页面数（**复用 check_claims 的同一份判据**，避免两处各算一遍）。"""
    from scripts.check_claims import _portal_page_counts
    return _portal_page_counts()


def _count_list_len(src_rel: str, name: str) -> int:
    """数源码里一个数组字面量的元素个数（`const navs = [` … `]`）。

    只数顶层条目：`{ ... },` 的个数（这些数组里每个元素都是一行对象），
    够用且不依赖 JS 解析器。
    """
    src = io.open(os.path.join(ROOT, src_rel), encoding="utf-8").read()
    m = re.search(rf"{name}\s*=\s*\[(.*?)\n\]", src, re.S)
    if not m:
        return -1
    return len(re.findall(r"\{[^{}]*\}", m.group(1)))


def _longpress_entries() -> int:
    """老年端紧急求助入口：布局顶栏 1 个 + 首页大按钮 1 个（`data-longpress`）。"""
    n = 0
    for rel in ("web/src/layouts/ElderlyLayout.vue", "web/src/views/elderly/Home.vue"):
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
        n += src.count("data-longpress")
    return n


def _route_modules() -> int:
    d = os.path.join(ROOT, "api_routes")
    n = 0
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        if "APIRouter(" in io.open(os.path.join(d, fn), encoding="utf-8").read():
            n += 1
    return n


def measure() -> dict:
    """实测当前值（复用 `check_claims` 的计数口径，避免两处各算一遍）。"""
    from scripts.check_claims import (_migration_count, _route_count, _role_count,
                                      _schema_version, _table_count)
    portals = _routes_by_portal()
    return {
        "routes": _route_count(),
        "routes_elderly": portals["elderly"],
        "routes_resident": portals["resident"],
        "routes_grid": portals["grid"],
        "agents": _role_count(),
        "tables": _table_count(),
        "schema": _schema_version(),
        "migrations": _migration_count(),
        "route_modules": _route_modules(),
        "elderly_nav": _count_list_len("web/src/layouts/ElderlyLayout.vue", "const navs"),
        "elderly_quick_actions": _count_list_len("web/src/views/elderly/Home.vue", "const quick"),
        "elderly_sos_entries": _longpress_entries(),
    }


def compare(now: dict, frozen: dict | None = None) -> list[str]:
    """返回不一致项（变大变小都算）。"""
    frozen = FROZEN if frozen is None else frozen
    bad = []
    for k, want in frozen.items():
        got = now.get(k, -1)
        if got != want:
            direction = "变大（新增了东西）" if got > want else "变小（删了东西）"
            bad.append(f"{_LABEL.get(k, k)}：冻结 {want} → 现在 {got}（{direction}）")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    now = measure()
    print("=" * 74)
    print("试点冻结校验（`pilot-ui-v1`：范围与结构冻结，不再加功能）")
    print("=" * 74)
    for k in FROZEN:
        flag = "OK  " if now.get(k) == FROZEN[k] else "DIFF"
        print(f"  [{flag}] {_LABEL.get(k, k):<24} {now.get(k):>5}（冻结 {FROZEN[k]}）")
    bad = compare(now)
    if a.detail:
        print("-" * 74)
        print("来源：路由数/角色数/表数/schema/迁移 取自 scripts/check_claims.py 的口径；"
              "各端页面数取自 web/src/router/index.js；")
        print("      导航与主要动作取自 ElderlyLayout.vue / elderly/Home.vue 的数组；"
              "紧急求助入口数 data-longpress。")
    if a.update:
        worse = [b for b in bad if "变大" in b]
        if worse and not a.force:
            print("-" * 74)
            print("拒绝更新：以下项**变大了**（这不是冻结，是加东西）：")
            for b in worse:
                print("   " + b)
            print("确实要改冻结面（并在提交信息里写明理由）再加 --force。")
            return 1
        path = os.path.abspath(__file__)
        src = io.open(path, encoding="utf-8").read()
        block = "FROZEN = {\n" + "".join(f'    "{k}": {now[k]},\n' for k in FROZEN) + "}"
        src = re.sub(r"FROZEN = \{.*?\n\}", block, src, count=1, flags=re.S)
        io.open(path, "w", encoding="utf-8", newline="").write(src)
        print("-" * 74)
        print("冻结值已更新：" + " · ".join(f"{k}={now[k]}" for k in FROZEN))
        return 0
    if bad:
        print("-" * 74)
        print("冻结被破坏：")
        for b in bad:
            print("   " + b)
        print("处置：① 回退这些改动（试点期不加功能）；② 确属必要 → `--update --force` "
              "并在提交信息 / docs/eval/pilot-冻结清单.md 的变更登记里写明理由。")
        return 1
    print("-" * 74)
    print("结论：冻结成立（路由 / 页面 / 角色 / 表结构 / 老年端入口与动作 全都没变）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
