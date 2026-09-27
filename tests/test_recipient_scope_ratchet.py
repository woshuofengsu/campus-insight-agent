# -*- coding: utf-8 -*-
"""收件人越界的防锈闸（v2 升级方案任务卡 4）。

背景：项目里曾有 19 处不带社区过滤的网格员收件人写法，把社区内发生的事
（含居民诉求、老人姓名与健康读数）投递给别的社区的网格员。
根因不是忘了加 WHERE，而是收件人选择没有统一入口 —— 所以一边迁移、一边防止新代码再长出这种写法。

规则：
  1. 写成 community=... 或走 data.db_user.managers_of(tenant) 即合规；
  2. 出现不带 community 的写法，必须已登记在 BASELINE，否则报错；
  3. 基线只减不增：迁移一处删一处，防止改回去。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 待迁移清单（文件名 -> 处数）。迁移一处删一处，不许新增。
BASELINE = {
    "db_elderly_care.py": 1,    # SOS 升级通知（_notify_grids）——用药审核超时已迁移
    "db_elderly.py": 1,         # SOS 指派（notify_sos_targeted）——久未活跃已迁移
    "db_repair.py": 3,          # 工单流转通知（受理/派单/解决）
    "db_policy.py": 5,          # 知识到期、提问转人工等
    "db_health_content.py": 2,  # 咨询超时/回复提醒


    "db_dispatch.py": 3,        # 派单候选（按楼栋匹配，仍需按社区收口）
}

_SCAN_DIRS = ("agent", "data", "api_routes", "scripts")

def _unscoped_sites() -> dict:
    """扫出未带 community 过滤的 `list_users(role="grid")` **真实调用**。

    用 AST 而不是正则：正则会把文档字符串里提到的字样也算成一处（第一版就误报了自己），
    而闸门误报会让人习惯性忽略它 —— 那就等于没有闸门。
    """
    import ast
    found: dict = {}
    for d in _SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                try:
                    txt = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
                    tree = ast.parse(txt)
                except (OSError, SyntaxError):
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    fn_node = node.func
                    if not (isinstance(fn_node, ast.Name) and fn_node.id == "list_users"):
                        continue
                    role_kw = next((k for k in node.keywords if k.arg == "role"), None)
                    if role_kw is None:
                        continue
                    if not (isinstance(role_kw.value, ast.Constant) and role_kw.value.value == "grid"):
                        continue
                    if any(k.arg == "community" for k in node.keywords):
                        continue          # 已按社区过滤 → 合规
                    found[fn] = found.get(fn, 0) + 1
    return found


def test_no_new_unscoped_grid_recipients():
    """新增把全部网格员当收件人的代码 -> 直接红。"""
    found = _unscoped_sites()
    grew = {f: (n, BASELINE.get(f, 0)) for f, n in found.items() if n > BASELINE.get(f, 0)}
    detail = "\n  ".join("%s: %d 处（基线 %d）" % (f, n, b) for f, (n, b) in grew.items())
    assert not grew, (
        "以下文件出现了新的未按社区过滤的网格员收件人写法：\n  " + detail +
        "\n（社区内事件通知负责人请用 data.db_user.managers_of(tenant)，或显式传 community=）")


def test_baseline_only_shrinks():
    """基线只减不增：迁移完成后要把条目从 BASELINE 删掉。"""
    found = _unscoped_sites()
    stale = [f for f, n in BASELINE.items() if n > 0 and found.get(f, 0) == 0]
    assert not stale, (
        "这些文件已不再有未按社区过滤的收件人写法，请从 BASELINE 删除对应条目：\n  "
        + "\n  ".join(stale))


def test_managers_of_is_the_structured_entry():
    """结构化收件人入口必须存在且 fail-closed（空租户 -> 空表）。"""
    from data.db_user import managers_of
    assert managers_of("") == [] and managers_of("海淀区") == [], \
        "managers_of 必须 fail-closed：社区为空或非法时返回空表，不得回落成全部网格员"


def test_scanner_actually_works():
    """扫描器自检：坏代码必须能被抓到（防止闸门失效变成永远绿）。"""
    import ast
    bad_src = 'for u in list_users(role="grid"):\n    pass'
    ok_src = 'x = list_users(role="grid", community=t)'
    doc_src = '"""提到 list_users(role="grid") 的文档不算。"""'

    def _hits(src):
        tree = ast.parse(src)
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "list_users":
                role_kw = next((k for k in node.keywords if k.arg == "role"), None)
                if role_kw and getattr(role_kw.value, "value", None) == "grid" \
                        and not any(k.arg == "community" for k in node.keywords):
                    n += 1
        return n

    assert _hits(bad_src) == 1, "扫描逻辑失效：坏代码没抓到"
    assert _hits(ok_src) == 0, "带 community 的写法不该被误报"
    assert _hits(doc_src) == 0, "**文档字符串里提到的字样不算调用**（第一版正是这么误报的）"


@pytest.mark.parametrize("fname", sorted(BASELINE))
def test_baseline_files_still_exist(fname):
    """基线里的文件必须还在（改名或删除后要同步基线，避免基线变成僵尸）。"""
    hit = [os.path.join(r, fname) for d in _SCAN_DIRS
           for r, _dd, ff in os.walk(os.path.join(ROOT, d)) if fname in ff]
    assert hit, f"基线里的 {fname} 已不存在，请更新 BASELINE"
