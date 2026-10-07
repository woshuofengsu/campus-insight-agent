# -*- coding: utf-8 -*-
"""观察期界面冻结门禁：`scripts/freeze_check.py` 的常驻检查。

用户定的硬规矩是"**真实老人观察期间不改界面**"（`docs/eval/pilot-v1-基线.md`）。
规矩只写在文档里就等于靠记性执行 —— 本项目已经在这上面吃过两次亏
（六十四节门禁盲区、六十八节文档与代码矛盾），所以这里把它钉成用例：

- 冻结点标签**存在**时：必须零改动（改了 → 这里的用例红，且 `freeze_check` 会说清三种正确做法）；
- 冻结点标签**不存在**时（浅克隆/换了环境）：`skip` **并写明原因** —— 不假装校验过了；
- 判定范围（SURFACE）不许被清空或改窄：它是"老年端界面"的定义，改它就是改判据。
"""
import importlib.util
import io
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "freeze_check.py")


def _load():
    spec = importlib.util.spec_from_file_location("freeze_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def test_surface_is_defined_and_covers_the_elderly_ui():
    """判定范围必须真的覆盖老年端界面（清空/改窄 SURFACE 等于把门禁关掉）。"""
    mod = _load()
    surface = list(mod.SURFACE)
    assert len(surface) >= 6, f"判定范围太窄（{surface}）——是不是被改小了？"
    joined = " ".join(surface)
    for must in ("views/elderly", "ElderlyLayout.vue", "useSpeech.js", "useSos.js",
                 "style.css"):
        assert must in joined, f"判定范围缺少「{must}」——那部分界面就没被冻结"
    for rel in surface:
        # 每条范围要么是存在的目录，要么是存在的文件（写错路径 = 静默不生效）
        assert os.path.exists(os.path.join(ROOT, rel.rstrip("/"))), f"范围里的路径不存在：{rel}"


def test_allowlist_entries_have_reasons():
    """冻结期内的例外必须逐条写理由（登记本身就是那次改动的记录）。"""
    mod = _load()
    for path, why in mod.ALLOW.items():
        assert len(why) >= 10, f"{path} 的例外理由太短（等于没写）"
        assert path in mod.SURFACE, f"{path} 不在判定范围里，登记例外没有意义"


def test_status_mode_reports_the_freeze_point():
    p = _run("--status")
    out = p.stdout or ""
    assert p.returncode == 0, f"--status 失败：{out}\n{p.stderr}"
    assert "观察期界面冻结校验" in out and "判定范围" in out, out[:300]


def test_elderly_ui_is_unchanged_since_the_freeze_tag():
    """**核心判据**：冻结点以来老年端界面零改动。

    标签不在（浅克隆、没打标签）→ skip 并写明原因：宁可不判，也不假装判过了。
    """
    mod = _load()
    p = _run("--status")
    if not mod._ref_exists(mod.FREEZE_REF):
        pytest.skip(f"冻结点标签 `{mod.FREEZE_REF}` 在当前工作区不存在（浅克隆/未打标签），"
                    "无法校验界面冻结 —— 这不是通过，是没验")
    p = _run()
    out = p.stdout or ""
    assert p.returncode == 0, (
        f"冻结点 `{mod.FREEZE_REF}` 以来老年端界面被改动了：\n{out}\n"
        "（观察期间不改界面：要么回退，要么打新标签重新冻结，"
        "要么在 scripts/freeze_check.py 的 ALLOW 里登记理由）")


def test_check_fails_loudly_when_ref_is_missing():
    """冻结点不存在时必须**明确报出"无法校验"**（退出码 2），不许静默通过。"""
    p = _run("--ref", "no-such-freeze-ref-xyz")
    assert p.returncode == 2, f"不存在的冻结点竟然返回 {p.returncode}：{p.stdout}"
    assert "无法校验" in (p.stdout or ""), p.stdout


def test_script_is_wired_into_the_docs():
    """门禁必须写在会被读到的地方（不然没人知道要跑它）。"""
    for rel, needle in (("docs/eval/pilot-v1-基线.md", "freeze_check"),
                        ("docs/deploy/生产部署手册.md", "freeze_check")):
        path = os.path.join(ROOT, rel)
        assert os.path.isfile(path), f"缺少文档：{rel}"
        txt = io.open(path, encoding="utf-8").read()
        assert needle in txt, f"{rel} 里没有提到 {needle}（没人会去跑一个没人知道的门禁）"
