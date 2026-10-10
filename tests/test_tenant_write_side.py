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


@functools.lru_cache(maxsize=1)
def _uncovered_inserts():
    """[(目录, 文件, 函数名, 表名, 源码片段, [(行号, 表名)…])] —— 第 6 项是**没被盖章覆盖**的 INSERT。

    逐条判据（2026-10-06 加固）：
      - INSERT 的那段字符串里**显式写了 tenant_id** → 自带覆盖；
      - 否则要求同一函数内存在 `stamp_tenant(...)` / `stamp_tenant_value(...)`，
        且它的**行号不早于**该 INSERT（盖章必须发生在这条插入之后）。
    """
    out = []
    for _d, fn, path in _source_files():
        try:
            src = open(path, encoding="utf-8").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        for fname, inserts, uncovered, body in _scan_functions(tree, src):
            if not inserts:
                continue
            for _ln, t, _lit in inserts:
                out.append((_d, fn, fname, t, body, uncovered))
    return out


def _scan_functions(tree, src):
    """从 AST 抽出每个函数的三样东西：INSERT 列表 / 未覆盖清单 / 源码片段。

    抽成独立函数是为了能用**合成源码**单测这套判据本身（见 `test_scanner_flags_second_insert`）。
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        inserts, stamps = [], []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                for table in _INSERT_RE.findall(sub.value):
                    if table in TENANT_TABLES:
                        inserts.append((sub.lineno, table, sub.value))
            elif isinstance(sub, ast.Call):
                fname_ = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
                if fname_ in ("stamp_tenant", "stamp_tenant_value"):
                    stamps.append(sub.lineno)
        uncovered = [(ln, t) for ln, t, lit in inserts
                     if "tenant_id" not in lit and not any(s >= ln for s in stamps)]
        out.append((node.name, inserts, uncovered, ast.get_source_segment(src, node) or ""))
    return out


def test_every_tenant_insert_is_stamped():
    """凡插入租户表，**每一条 INSERT 都必须盖章**（或已登记豁免并写明理由）。

    ⚠️ 2026-10-06 加固：原来是**函数级**判断（函数体里出现过 `stamp_tenant(` 就算过），
    于是"一个函数里两条 INSERT、只给其中一条盖章"永远绿灯 ——
    `db_policy.ask_question` 就是这样：RAG 分支盖了、**主路径没盖**，
    导致"被自动回答"的提问租户为空 → 居民点"没帮到我"转人工后网格端**谁都不看见**。
    现在改成**按 INSERT 出现的位置**逐条判（同函数内、该 INSERT 之后必须有盖章调用），
    只有"INSERT 里显式写了 tenant_id"才算自带覆盖。
    """
    missing = []
    for _d, fn, fname, table, body, uncovered in _uncovered_inserts():
        if not uncovered:
            continue
        if (fn, fname) in _EXEMPT and _EXEMPT[(fn, fname)]:
            continue
        missing.append(f"{fn}::{fname}  第 {uncovered[0][0]} 行插入 {table}")
    assert not missing, (
        "以下 INSERT 之后没有给租户表盖章，也没有豁免理由：\n  " + "\n  ".join(sorted(set(missing)))
        + "\n（多租户：写入侧必须调 stamp_tenant/stamp_tenant_value，否则新行租户为空，"
          "读取侧 fail-closed 会让它**谁都看不见**——包括本该看到的人）")


def test_per_insert_check_is_not_vacuous():
    """闸门自身的栅栏：逐条判必须真的能扫到"位置"信息（防止又退化成永远绿）。"""
    sites = _uncovered_inserts()
    assert sites, "没扫到任何租户表插入点，加固后的扫描逻辑疑似失效"
    assert any(lits for *_rest, lits in sites), "没扫到 INSERT 的行号信息"


_SYNTHETIC = '''
def two_inserts_one_stamp(user_id):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO policy_questions (user_id) VALUES (?)", (user_id,))
        qid = cur.lastrowid
        stamp_tenant(conn, "policy_questions", qid, user_id)
        cur2 = conn.execute("INSERT INTO policy_questions (user_id) VALUES (?)", (user_id,))
        qid2 = cur2.lastrowid
        conn.commit()
    return qid, qid2
'''


def test_scanner_flags_second_insert():
    """**这条是闸门自己的回归网**：一个函数里两条 INSERT、只给第一条盖章 → 必须报出第二条。

    加固前的那版（函数级字符串匹配）在这里会**放过**——`db_policy.ask_question` 线上就是这么漏的。
    """
    with_tenant = _SYNTHETIC.replace(
        "INSERT INTO policy_questions (user_id)",
        "INSERT INTO policy_questions (user_id, tenant_id)")
    funcs = _scan_functions(ast.parse(_SYNTHETIC), _SYNTHETIC)
    assert len(funcs) == 1
    _name, inserts, uncovered, _body = funcs[0]
    assert len(inserts) == 2, f"应该扫到 2 条 INSERT，实际 {len(inserts)}"
    assert len(uncovered) == 1, f"应该报出 1 条未盖章，实际 {uncovered}"
    assert uncovered[0][1] == "policy_questions"
    # 两条都盖章 → 干净；显式写 tenant_id → 也算覆盖
    assert not _scan_functions(ast.parse(_SYNTHETIC.replace("qid2 = cur2.lastrowid",
                                                           "stamp_tenant(conn, 'policy_questions', "
                                                           "cur2.lastrowid, user_id)\n        qid2 = cur2.lastrowid")),
                               _SYNTHETIC)[0][2]
    assert not _scan_functions(ast.parse(with_tenant), with_tenant)[0][2]


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
