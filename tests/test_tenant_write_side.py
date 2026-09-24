# -*- coding: utf-8 -*-
"""多租户**写入侧**覆盖闸（B6）——"只加列不写入"这类事故的防锈门禁。

**为什么单独有这道闸**：v41 的教训是"给表加了 tenant_id 列、也回填了，但业务代码从不写入"，
于是新数据租户为空、隔离静默退化成"空租户"。B5 虽然补了写入侧，但 B6 审计时仍然扫出
**5 处漏盖章**，且后果不是"看不见别人的"，而是**自己人也看不见**：

  - `agent_handoffs`（转人工处理包）→ 列表已按 tenant 过滤 → **所有网格员都看不到待办**；
  - `policy_questions`（居民转人工提问）→ 网格端"待回复提问"空列表；
  - `care_event_log`（关怀事件）→ 关怀量化指标恒为 0；
  - `weather_check_tasks`（极端天气巡查任务）→ 网格端任务列表为空；
  - `community_issues`（政务上报这条入口）→ 工单在网格端列表里消失。

所以本文件用 AST 静态扫 `data/` 下**所有** `INSERT INTO <租户表>`，要求同一函数内出现
`stamp_tenant(...)`/`stamp_tenant_value(...)`（或在 INSERT 里显式写 `tenant_id`），
否则必须登记在豁免表里并写明理由。新加插入点漏盖章会在**测试期**红，而不是在演示当天。
"""
import ast
import functools
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from utils.tenant import TENANT_TABLES  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INSERT_RE = re.compile(r"INSERT\s+INTO\s+(\w+)", re.IGNORECASE)

# 豁免：这些插入点的租户由**别处**保证 → 必须写明理由
_EXEMPT = {
    ("seed.py", "_seed_issues"): "种子裸 INSERT；seed.py 结尾重跑 init_db 让 v48 统一回填（见该文件说明）",
    ("seed.py", "_seed_care_events"): "同上：种子数据由 seed.py 结尾的 init_db 调用统一回填租户",
    ("seed.py", "_seed_proposals"): "同上：种子数据由 seed.py 结尾的 init_db 调用统一回填租户",
    ("seed.py", "_seed_notices"): "同上：种子数据由 seed.py 结尾的 init_db 调用统一回填租户",
}


def _source_files():
    out = []
    for d in ("data", "agent", "utils"):
        p = os.path.join(_ROOT, d)
        if not os.path.isdir(p):
            continue
        for fn in sorted(os.listdir(p)):
            if fn.endswith(".py"):
                out.append((d, fn, os.path.join(p, fn)))
    return out


def _string_literals(node):
    """收集函数体内所有字符串字面量（含 f-string 的固定片段）。"""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
        elif isinstance(sub, ast.JoinedStr):
            for part in sub.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    out.append(part.value)
    return out


@functools.lru_cache(maxsize=1)
def _insert_sites():
    """[(目录, 文件, 函数名, 表名, 源码片段)] —— data/agent/utils 下所有租户表插入点。

    带缓存：本模块有 17 个参数化用例，不缓存的话每个都要重解析全部源码（实测 55 秒）。
    """
    sites = []
    for _d, fn, path in _source_files():
        try:
            src = open(path, encoding="utf-8").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(src, node) or ""
            lits = _string_literals(node)
            for lit in lits:
                for table in _INSERT_RE.findall(lit):
                    if table not in TENANT_TABLES:
                        continue
                    sites.append((_d, fn, node.name, table, body))
    return sites


def test_every_tenant_insert_is_stamped():
    """凡插入租户表，必须盖章（或已登记豁免并写明理由）。"""
    missing = []
    for _d, fn, fname, table, body in _insert_sites():
        if "stamp_tenant(" in body or "stamp_tenant_value(" in body:
            continue
        if f"tenant_id" in body and _INSERT_RE.search(body or ""):
            # INSERT 列清单里显式写了 tenant_id 的，也算已覆盖
            ins = body[body.find("INSERT INTO"):body.find("INSERT INTO") + 400]
            if "tenant_id" in ins:
                continue
        if (fn, fname) in _EXEMPT and _EXEMPT[(fn, fname)]:
            continue
        missing.append(f"{fn}::{fname}  插入 {table}")
    assert not missing, (
        "以下插入点没有给租户表盖章，也没有豁免理由：\n  " + "\n  ".join(sorted(set(missing)))
        + "\n（多租户：写入侧必须调 stamp_tenant/stamp_tenant_value，否则新行租户为空，"
          "读取侧 fail-closed 会让它**谁都看不见**——包括本该看到的人）")


def test_insert_sites_are_actually_found():
    """闸门自身的栅栏：扫不到插入点说明扫描逻辑坏了（防"永远绿的假闸门"）。"""
    sites = _insert_sites()
    assert len(sites) >= 12, f"只扫到 {len(sites)} 个租户表插入点，扫描逻辑疑似失效"
    tables = {t for _d, _fn, _f, t, _b in sites}
    assert {"community_issues", "proposals", "notices", "health_consults"} <= tables, \
        f"核心表的插入点没扫到，疑似失效：{sorted(tables)}"


def test_stamp_helper_has_no_side_channel_default():
    """盖章函数**不许**偷偷写默认社区：租户解析不出来就该是空（fail-closed）。"""
    from utils.tenant import stamp_tenant, stamp_tenant_value
    assert stamp_tenant is not None and stamp_tenant_value is not None
    import inspect
    for f in (stamp_tenant, stamp_tenant_value):
        sig = inspect.signature(f)
        for name, p in sig.parameters.items():
            if name in ("tenant", "owner_id", "table", "row_id"):
                assert p.default is inspect.Parameter.empty, \
                    f"{f.__name__} 的 {name} 不该有默认值（会掩盖漏传）"


@pytest.mark.parametrize("table", sorted(TENANT_TABLES))
def test_tenant_table_has_stamp_helper_usage_or_documented(table):
    """每张租户表都应该有写入侧盖章点（或在豁免里），避免"表在名单里但没人写租户"。"""
    stamped = {t for _d, _fn, _f, t, body in _insert_sites()
               if "stamp_tenant(" in body or "stamp_tenant_value(" in body}
    exempt_tables = {t for _d, _fn, _f, t, _b in _insert_sites()
                     if any((fn, fname) in _EXEMPT for fn, fname in [(_d, _fn)])}
    assert table in stamped or table in exempt_tables or table not in {
        t for _d, _fn, _f, t, _b in _insert_sites()
    }, f"{table} 有插入点却没有任何盖章路径"
