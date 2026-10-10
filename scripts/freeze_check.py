# -*- coding: utf-8 -*-
"""观察期界面冻结校验 —— 把用户定的硬规矩"**观察期间不改界面**"变成可执行的检查。

## 为什么需要它

试点方案的规矩是：打完 `pilot-v1` 标签后开始真实老人观察，**观察期间不改界面**。
理由不是洁癖：观察的是"老人能不能自己把事办完"，如果中途界面变了，
前面几位老人的数据与后面几位就**不是同一个东西**了，试点结论当场作废。

但"不改界面"这句话只写在文档里时，它的执行依赖**人的记性**——而这正是本项目反复吃亏的地方
（六十四节：门禁盲区；六十八节：文档与代码矛盾）。所以这里用 git 把它钉住：
**把老年端界面相关的文件，与冻结标签那一刻逐字对比**，有改动就红。

## 判据（"老年端界面"指什么）

老人看得见的东西：老年端页面 · 老年端布局（顶部导航/紧急求助键）· 语音与 SOS 的组合式函数
（它们决定降级提示的文案与行为）· 图标表与图标组件（图形变了老人也看得见）·
全局样式表（对比度/字号/配色都在这儿）。

⚠️ 这是一条**需要人工判断边界**的判据，我不假装它是纯客观的：
比如"全局样式表"改一行给网格端用的类名也会被算进来。宁可**多管一点**——
冻结期想改网格端样式，看完提示后在 `ALLOW` 里登记一行理由即可（登记动作本身就是那次改动的记录）。

## 用法

```bash
python scripts/freeze_check.py                  # 冻结校验（默认对 pilot-v1）
python scripts/freeze_check.py --status         # 只看现状：冻结点、被改的文件、判定范围
python scripts/freeze_check.py --ref <tag>      # 换一个冻结点（观察结束后重新冻结时用）
```

**观察结束、下一版要动界面时**：打一个新的冻结标签，然后把默认 `--ref` 换成它
（或者把 `FREEZE_REF` 改掉）。**不要**用 `ALLOW` 长期豁免整个目录——那是把门禁关掉。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

#: 默认冻结点（打完标签开始观察的那一版）。
#: ⚠️ 2026-10-06：从 `pilot-v1` 换成 **`pilot-ui-v1`**——界面重设计（任务书）必然改了老年端界面，
#: 旧冻结点下这条检查会（正确地）报红。按脚本自己给的处置路径走第 ② 条：
#: **观察尚未开始，先打新标签重新冻结**，而不是把改动登记成"例外"（那等于把门禁关掉）。
#: 现在 `pilot-ui-v1` 就是"真实老人观察必须用的那一版"。
FREEZE_REF = "pilot-ui-v1"

#: 老人的"界面面"：这些路径下任何改动都算改了界面
SURFACE = [
    "web/src/views/elderly/",
    "web/src/layouts/ElderlyLayout.vue",
    "web/src/composables/useSpeech.js",
    "web/src/composables/useSos.js",
    "web/src/components/EIcon.vue",
    "web/src/components/AgentChat.vue",
    "web/src/config/icons.js",
    "web/src/utils/weatherIcon.js",
    "web/src/style.css",
    "web/index.html",
]

#: 冻结期内**确有必要**的例外：必须逐条写理由（登记本身就是那次改动的记录）。
#: 现在是空的——冻结期内不该有例外；真要改就重新冻结（换 `--ref`）。
ALLOW: dict[str, str] = {}


def _git(*args: str) -> tuple[int, str]:
    """跑一条 git 命令，**只要 stdout**。

    ⚠️ 不要把 stderr 合进来：`pilot-v1` 这个标签与同名分支会让 git 往 stderr 打
    `warning: refname 'pilot-v1' is ambiguous.`，第一版把它当成"被改动的文件名"，
    于是校验结果变成"界面改了 1 个文件：warning: refname ..."（**一条假红**）。
    """
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "").strip()


def _resolve_ref(ref: str) -> str:
    """把 `pilot-v1` 解析成明确的 `refs/tags/pilot-v1`。

    本项目分支与标签**同名**（`pilot-v1` 既是分支也是冻结标签），git 对裸名字是有歧义的：
    必须显式走 `refs/tags/…`，否则同一个名字今天指标签、明天可能指分支。
    """
    for cand in (f"refs/tags/{ref}", f"refs/heads/{ref}", ref):
        rc, _ = _git("rev-parse", "--verify", f"{cand}^{{commit}}")
        if rc == 0:
            return cand
    return ""


def _ref_exists(ref: str) -> bool:
    return bool(_resolve_ref(ref))


def _changed(ref: str) -> list[str]:
    """冻结点 → 工作区的改动文件（含未提交的；**只看界面面**）。"""
    full = _resolve_ref(ref) or ref
    rc, out = _git("diff", "--name-only", full, "--", *SURFACE)
    files = [ln.strip() for ln in out.splitlines() if ln.strip()] if rc == 0 else []
    # 未跟踪的新文件（`git diff` 看不到）也要算：新增一个老年端页面同样是改界面
    rc2, out2 = _git("ls-files", "--others", "--exclude-standard", "--", *SURFACE)
    if rc2 == 0:
        files += [ln.strip() for ln in out2.splitlines() if ln.strip()]
    return sorted(set(files))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=FREEZE_REF, help=f"冻结点（默认 {FREEZE_REF}）")
    ap.add_argument("--status", action="store_true", help="只打印现状，不做判定")
    a = ap.parse_args()

    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("[无法校验] 这不是一个 git 工作区 —— 冻结校验依赖 git 历史。")
        return 2
    if not _ref_exists(a.ref):
        print(f"[无法校验] 冻结点 `{a.ref}` 不存在（标签没打？浅克隆？）。")
        print("           打了标签再跑：git tag -a <名字> -m '<冻结说明>'")
        return 2

    rc, head = _git("rev-parse", "--short", "HEAD")
    rc2, refsha = _git("rev-parse", "--short", f"{_resolve_ref(a.ref)}^{{commit}}")
    changed = _changed(a.ref)
    blocked = [f for f in changed if f not in ALLOW]

    print("=" * 74)
    print(f"观察期界面冻结校验 · 冻结点 {a.ref}（{refsha}） → 工作区 HEAD（{head}）")
    print(f"判定范围（{len(SURFACE)} 条）：" + " · ".join(SURFACE))
    print("=" * 74)
    if a.status:
        print(f"被改动的界面文件：{len(changed)} 个")
        for f in changed:
            print(f"  {'[已登记例外]' if f in ALLOW else '[改动]'} {f}"
                  + (f"  —— {ALLOW[f]}" if f in ALLOW else ""))
        print("-" * 74)
        print("提示：观察结束后重新冻结 → `python scripts/freeze_check.py --ref <新标签>`")
        return 0

    if not blocked:
        print(f"[OK] 冻结点以来**老年端界面零改动**"
              f"{'（有 %d 个已登记例外）' % len(ALLOW) if ALLOW else ''}")
        print("结论：界面冻结成立，观察数据仍属同一版本。")
        return 0

    print(f"[FAIL] 冻结点 `{a.ref}` 以来，老年端界面有 {len(blocked)} 个文件被改动：")
    for f in blocked:
        print(f"  - {f}")
    print("-" * 74)
    print("为什么这条要红：观察期间改界面 → 前后面向的不是同一个界面，**试点数据不可比**。")
    print("三种正确处理方式：")
    print("  ① 回退这些改动（观察结束前不动界面）；")
    print("  ② 观察已结束 → 打新标签并重新冻结：`python scripts/freeze_check.py --ref <新标签>`；")
    print("  ③ 确有必要（如修一个会让老人用不下去的缺陷）→ 在 scripts/freeze_check.py 的 "
          "ALLOW 里登记该文件**并写明理由**，同时在 docs/eval/pilot-v1-基线.md 的变更登记里补一行。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
