# -*- coding: utf-8 -*-
"""全站图标门禁：界面图形一律用 `components/EIcon.vue` 的单色线性图标，**不许再用 emoji**。

为什么把它做成门禁（而不是"这次改完就算了"）：
  · emoji 在每家手机上是**不同厂商字形**（大小、配色、甚至有没有都不一样），同一块天气面板
    在 iPhone / 安卓 / 微信里长得不一样；而三端首页都有天气/状态图标 —— 这是"看起来像 demo、
    换个手机就露馅"的典型；
  · `ui_audit` 能测对比度，但**测不出"字形不确定"**；`mobile_audit` 也测不出；
  · 2026-09-29 全站替换过一轮（539 处、45 个文件），这类清理不做门禁就等于"下一版又长回来"。

四道检查：
  1. `web/src/**/*.{vue,js,ts}` 里不许出现 emoji（唯一豁免见 `ALLOW`，理由写在代码里）；
  2. 页面里 `<EIcon name="…" />` 写死的名字必须是 `config/icons.js` 里真实存在的图标
     （写错名字不会报错、只会静默显示成"更多"图标——这种"静默降级"必须有静态闸门）；
  3. 配置里的 `icon: '…'`（导航/入口/状态卡）同样要能在图标表里找到；
  4. 自检：扫描器对坏样例必须报出来（否则门禁本身失效也不知道）。

2026-09-29 晚：本文件**取代**了 `tests/test_elderly_icons.py`（那一版只覆盖老年端布局层 + 正文棘轮）。
现在全站 0 emoji，棘轮不再需要——但"不许再长回来"的检查保留，而且更严。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "src")
ICONS = os.path.join(WEB, "config", "icons.js")

# 真 emoji（不含排版箭头 → ↩ ⬇；它们在文本里是标点不是图标）。
# ⚠️ 2026-09-29 补：只看码位区间会**漏掉一类**——U+23F1(⏱)/U+21A9(↩)/U+25B6(▶)/U+23F8(⏸)
# 这些基字符在"符号/几何"区，**只有后面跟 U+FE0F（变体选择符）时才是彩色 emoji**。
# 第一遍就漏了 `⏱️/↩️/▶️` 共 18 处（页面上真看得见），所以判据加一条：**出现 U+FE0F 就算 emoji**。
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u20E3]"
                   "|[\u2190-\u21FF\u23E9-\u23FA\u25A0-\u25FF\u2B00-\u2BFF]\uFE0F"
                   # 第二遍又补：这些码位**默认就是彩色 emoji 呈现**，根本不需要 VS16
                   # （⏰ U+23F0 / ⌛ U+231B / ▶ U+25B6 / ▪ U+25AA …）。
                   # 判据只按"有没有 VS16"会漏掉它们——实测就是在网格端"剩余时间"里漏了 ⏰⏳。
                   "|[\u231A-\u231B\u23E9-\u23FA\u25AA-\u25AB\u25B6\u25C0\u25FB-\u25FE]"
                   "|\uFE0F")
# 唯一豁免：这份文件里的 emoji 是**用来匹配后端数据里可能出现的 emoji**的
# （天气接口历史上会给 `emoji` 字段；没有 condition 文本时靠它兜底选图标），
# 不是界面图标 —— 豁免必须写明理由，且只豁免这一个文件。
ALLOW = {"utils/weatherIcon.js": "正则里匹配后端数据 emoji（不是界面图标）"}


def _icon_names() -> set[str]:
    src = io.open(ICONS, encoding="utf-8").read()
    body = src.split("export const ICON_PATHS = {", 1)[1].split("\n}", 1)[0]
    return set(re.findall(r"^\s{2}'?([A-Za-z][\w-]*)'?:", body, re.M))


def _sources() -> list[tuple[str, str]]:
    out = []
    for dirpath, _dirs, files in os.walk(WEB):
        for fn in sorted(files):
            if not fn.endswith((".vue", ".js", ".ts")):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, WEB).replace("\\", "/")
            out.append((rel, io.open(p, encoding="utf-8").read()))
    return out


# ---------------------------------------------------------------- 1. 不许有 emoji

def test_no_emoji_in_sources():
    bad = []
    for rel, text in _sources():
        if rel in ALLOW:
            continue
        for i, line in enumerate(text.split("\n"), 1):
            if EMOJI.search(line):
                bad.append(f"{rel}:{i} → {line.strip()[:80]}")
    assert not bad, (
        "界面里又出现 emoji 了（请改用 <EIcon name=\"…\" /> 的单色线性图标，"
        "图标不够就在 web/src/config/icons.js 里加一个）：\n  " + "\n  ".join(bad))


def test_allowlist_is_tiny_and_documented():
    """豁免只能有一个文件、且必须写明理由（防止有人图省事把文件塞进豁免）。"""
    assert set(ALLOW) == {"utils/weatherIcon.js"}, f"豁免名单变了：{sorted(ALLOW)}"
    for rel, why in ALLOW.items():
        assert len(why) >= 8, f"{rel} 的豁免理由太短（等于没写）"
        assert os.path.isfile(os.path.join(WEB, rel)), f"豁免的文件不存在：{rel}"


# ---------------------------------------------------------------- 2/3. 图标名必须真实存在

def test_literal_icon_names_exist():
    names = _icon_names()
    assert len(names) >= 40, f"图标表太小（{len(names)} 个），解析是不是坏了？"
    missing = []
    for rel, text in _sources():
        if rel == "config/icons.js":
            continue
        for m in re.finditer(r'<EIcon\s+name="([\w-]+)"', text):
            if m.group(1) not in names:
                line = text[: m.start()].count("\n") + 1
                missing.append(f"{rel}:{line} → {m.group(1)}")
    assert not missing, (
        "页面里用了图标表里**不存在**的图标名（会静默显示成「更多」图标）：\n  " + "\n  ".join(missing))


def test_config_icon_names_exist():
    """导航/入口/状态卡的 `icon: '…'` 也要真实存在（它们是动态渲染的，静态查不到就漏了）。"""
    names = _icon_names()
    missing = []
    for rel, text in _sources():
        if rel == "config/icons.js":
            continue
        for m in re.finditer(r"icon:\s*'([A-Za-z][\w-]*)'", text):
            if m.group(1) not in names:
                line = text[: m.start()].count("\n") + 1
                missing.append(f"{rel}:{line} → {m.group(1)}")
    assert not missing, "配置里的图标名不存在：\n  " + "\n  ".join(missing)


def test_icon_component_is_monochrome_and_sized():
    src = io.open(os.path.join(WEB, "components", "EIcon.vue"), encoding="utf-8").read()
    assert 'stroke="currentColor"' in src, "图标不是 currentColor（写死色在暗色下不跟着变）"
    assert ":stroke-width" in src or "stroke-width=" in src, "图标没有线宽（细线在大屏上会虚）"
    assert "aria-hidden" in src, "图标没有 aria-hidden（读屏会把图形念出来，标签文字才是内容）"


# ---------------------------------------------------------------- 4. 扫描器自检

def test_scanner_self_check():
    assert EMOJI.search("🔧 工单管理"), "自检失效：认不出 emoji"
    assert EMOJI.search("标⚠️注"), "自检失效：认不出带变体选择符的符号"
    # 第一遍漏掉的那一类必须被抓到（基字符在符号区，靠 U+FE0F 才是彩色 emoji）
    assert EMOJI.search("⏱️ 还剩多久"), "自检失效：认不出 ⏱️（U+23F1+VS16）"
    assert EMOJI.search("↩️ 撤回"), "自检失效：认不出 ↩️（U+21A9+VS16）"
    assert EMOJI.search("▶️ 接着填"), "自检失效：认不出 ▶️（U+25B6+VS16）"
    assert not EMOJI.search("首页 → 报修 · 一步到人"), "自检失效：把排版箭头当成 emoji"
    assert not EMOJI.search("● 未读　○ 待办　▲ 收起　▼ 展开"), "自检失效：把无 VS16 的排版符号当成 emoji"
    assert not EMOJI.search('<EIcon name="wrench" :size="18" />'), "自检失效：把图标组件当成 emoji"
    names = _icon_names()
    assert "wrench" in names and "bell" in names, "自检失效：图标表解析不出已知图标"
    assert "not-a-real-icon" not in names, "自检失效：图标表里混进了不存在的名字"
    # 现在真的没有 emoji 了（否则第 1 条用例应已失败）
    leftovers = [(rel, EMOJI.findall(t)) for rel, t in _sources() if rel not in ALLOW and EMOJI.search(t)]
    assert not leftovers, f"仓库里仍有 emoji：{leftovers}"


# ---------------------------------------------------------------- 5. 脚本的控制台输出
#
# 2026-09-29 新增（实测踩到，第三次最坑）：
# `scripts/*.py` 里 `print` emoji，在 **Windows 中文控制台（cp936/GBK）** 上会抛
# `UnicodeEncodeError`。前两次只是难看；第三次出现在 `restore_drill.py`：
# **六项校验全部通过之后**，打印"通过"那一刻崩掉 → 退出码 1 →
# **一次成功的恢复演练被报成失败**。这比乱码严重得多：它会让 CI 和别人误判结论。
#
# ⚠️ 判据不是"脚本不许有 emoji"——查过之后发现**仓库早就有正确做法**：
# 会打 emoji 的脚本都调了 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
# （`check_claims` / `audit_phone_encryption` / `demo_flow_check` … 十来处）。
# 所以规则是：**要么不打，要么显式设编码**。改成"一律禁止"会让那十来个
# 本来正常的脚本被迫返工，而且丢掉一个已经验证可行的模式。

_ENC_FIX = re.compile(r"reconfigure\s*\([^)]*encoding|TextIOWrapper\([^)]*encoding"
                      r"|PYTHONIOENCODING|setdefaultencoding")


def _script_sources() -> list[tuple[str, str]]:
    out = []
    for d in ("scripts", "."):
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for fn in sorted(os.listdir(base)):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(base, fn)
            if not os.path.isfile(p):
                continue
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            out.append((rel, io.open(p, encoding="utf-8").read()))
    return out


def test_scripts_printing_emoji_set_stdout_encoding():
    """脚本**打印** emoji 时，必须显式设 stdout 编码；否则管道/中文控制台下会崩。"""
    bad = []
    for rel, text in _script_sources():
        if _ENC_FIX.search(text):
            continue                     # 已按仓库既有模式设了编码 → 放行
        for i, line in enumerate(text.splitlines(), 1):
            if not EMOJI.search(line):
                continue
            s = line.strip()
            if s.startswith("#"):
                continue                 # 纯注释不打印
            if ("print(" in line or "_log." in line or "logging." in line
                    or "sys.stderr" in line or "sys.stdout" in line):
                bad.append(f"{rel}:{i} → {s[:88]}")
    assert not bad, (
        "以下脚本会往控制台打 emoji，但**没有**设置 stdout 编码"
        "（Windows 中文控制台下 UnicodeEncodeError，实测会把「演练通过」报成失败）：\n  "
        + "\n  ".join(bad)
        + "\n（两种修法任选：改成纯文本标记如 [通过]/[失败]，或在脚本开头加 "
          "`sys.stdout.reconfigure(encoding=\"utf-8\", errors=\"replace\")`）")
