# -*- coding: utf-8 -*-
"""试点冻结门禁：**"不再加功能"必须是机器守着的**，不能靠记性。

用户给的推进顺序第一步就是"冻结目标"：老年端 6 个入口 / 三个主要动作 / 报修·问答·进度流程 /
网格接单处置流程 / 当前 UI 版本 / 当前接口与数据库结构，全部冻住，**暂时不再增加新 Agent、新页面、
新业务模块**。

为什么做成用例而不是写进文档：这个项目已经反复证明"只写在文档里的约束会被忘掉"
（dev-log 六十四 门禁盲区 / 六十八 文档与代码矛盾 / 六十九 删变量删出白字白底）。
冻结一旦失守，代价是**试点数据不可比**：老人在 A 界面完成、B 界面完不成，等于没测。

三道检查：
  1. `scripts/pilot_freeze_check.py` 跑绿（路由/页面/角色/表结构/老年端入口与动作 全都没变）；
  2. 冻结值**不许被悄悄放宽**（`--update` 拒绝"变大"，要 `--force` 并写明理由）；
  3. 冻结清单文档存在、写清"怎么验 / 怎么解冻 / 什么还没做"（别让后来人以为冻结=万事俱备）。
"""
import io
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "pilot_freeze_check.py")
DOC = os.path.join(ROOT, "docs", "eval", "pilot-冻结清单.md")


def _load():
    spec = importlib.util.spec_from_file_location("pilot_freeze_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, ROOT)
    spec.loader.exec_module(mod)
    return mod


def _run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def test_freeze_holds():
    """**核心判据**：冻结面一项都没变（多了/少了都算失守）。"""
    p = _run()
    out = p.stdout or ""
    assert p.returncode == 0, (
        "试点冻结被破坏了（试点期不加功能、也不删功能）：\n" + out + "\n"
        "处置：① 回退改动；② 确属必要 → `python scripts/pilot_freeze_check.py --update --force` "
        "并在 docs/eval/pilot-冻结清单.md 的变更登记里写明理由")
    assert "冻结成立" in out, out


def test_freeze_has_no_loose_ends():
    """冻结清单里每一项都必须真的测得到（不能有 -1 / 空值这类"测不出来还报绿"的项）。"""
    mod = _load()
    now = mod.measure()
    for key in mod.FROZEN:
        assert key in now, f"冻结项 {key} 没有被真正测量（判据失效）"
        assert isinstance(now[key], int) and now[key] > 0, f"冻结项 {key} 测出异常值：{now[key]}"
    # 老年端入口与主要动作是用户**明确点名**要冻的，单独再钉一次
    assert mod.FROZEN["elderly_nav"] == 6, "老年端 6 个入口是用户明确要求冻结的"
    assert mod.FROZEN["elderly_quick_actions"] == 3, "老年端三个主要动作是用户明确要求冻结的"
    assert mod.FROZEN["elderly_sos_entries"] == 2, "紧急求助必须仍有独立入口（顶栏 + 首页）"


def test_update_refuses_to_loosen():
    """`--update` 在"变大"时必须拒绝（否则冻结就成了一句空话）。"""
    mod = _load()
    bigger = dict(mod.FROZEN)
    bigger["routes"] = mod.FROZEN["routes"] + 5      # 假装加了 5 个接口
    bad = mod.compare({**mod.measure(), **bigger}, mod.FROZEN)
    assert any("变大" in b for b in bad), f"加了接口竟然没被判成破坏冻结：{bad}"
    smaller = dict(mod.FROZEN)
    smaller["routes"] = mod.FROZEN["routes"] - 5     # 假装删了 5 个接口
    bad2 = mod.compare({**mod.measure(), **smaller}, mod.FROZEN)
    assert any("变小" in b for b in bad2), f"删了接口竟然没被判成破坏冻结：{bad2}"


def test_freeze_doc_is_honest():
    """冻结清单必须写清三件事：怎么验、怎么解冻、**什么还没做**。"""
    assert os.path.isfile(DOC), f"缺少冻结清单：{DOC}"
    txt = io.open(DOC, encoding="utf-8").read()
    for needle in ("pilot_freeze_check.py", "解冻", "未开展"):
        assert needle in txt, f"冻结清单里没有写清「{needle}」"
    # 不许把"自动化跑绿"说成"真人验证过"
    for lie in ("老人已验证", "已由老人验证", "真实用户验证通过"):
        assert lie not in txt, f"冻结清单出现了把自动化说成真人验证的表述：{lie}"
