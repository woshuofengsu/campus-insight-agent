# -*- coding: utf-8 -*-
"""老年端「语音文案 ↔ 代码行为」一致性门禁（v3 复核 §6-B3）。

**为什么要这个闸门**：老年端是给不会看文档的人用的，文案就是产品的全部承诺。
历史上出现过两类"页面替设备撒谎"：

  ① **文案写"按住说话"，代码绑的却是 `@click`** —— 老人按住不放，页面以为他按完了，
     或者压根没启动；`web/src/views/elderly/Agent.vue` 用的是
     `@mousedown/@mouseup/@touchstart/@touchend`（真的"按住"），而报修页曾写"按住说话"+`@click`。
  ② **挂载即自动播报**（`onMounted(() => speak(...))`）—— iOS Safari 的 TTS 必须由用户手势触发，
     自动播**静默不响**，老人看不到任何提示，页面却像"已经念过了"。必须改成"点一下听"，
     并且播不出来时如实显示降级文案（不能假装老人听到了）。

本闸门用源码扫描把这两条钉住：新增页面若再犯，直接红。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELDERLY_DIR = os.path.join(ROOT, "web", "src", "views", "elderly")

# 允许"挂载即播报"的**白名单**（必须逐条写理由；空着就是不允许）
MOUNT_SPEAK_WHITELIST: dict[str, str] = {}

_HOLD_COPY = ("按住说话", "按住说", "按住不放")
_HOLD_EVENTS = ("pointerdown", "pointerup", "mousedown", "mouseup", "touchstart", "touchend")


def _vue_files() -> list[str]:
    return [f for f in sorted(os.listdir(ELDERLY_DIR)) if f.endswith(".vue")]


def _read(fn: str) -> str:
    with open(os.path.join(ELDERLY_DIR, fn), encoding="utf-8") as fh:
        return fh.read()


def _callback_block(src: str, open_brace_index: int, limit: int = 4000) -> str:
    """从 `{` 开始做**大括号配对**取出回调体（固定长度切片会把后面的普通函数也算进来，误报）。"""
    depth = 0
    for i in range(open_brace_index, min(len(src), open_brace_index + limit)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[open_brace_index:i + 1]
    return src[open_brace_index:open_brace_index + limit]


def _mount_blocks(src: str) -> list[str]:
    out = []
    for m in re.finditer(r"onMounted\(\s*(async\s*)?\([^)]*\)\s*=>\s*\{", src):
        out.append(_callback_block(src, m.end() - 1))
    return out


def test_mount_time_speak_is_not_silently_claimed():
    """不许在 `onMounted` 里直接 `speak(...)`（iOS 会静默不响 → 等于假装播过了）。"""
    bad = []
    for fn in _vue_files():
        src = _read(fn)
        if fn in MOUNT_SPEAK_WHITELIST:
            continue
        for block in _mount_blocks(src):
            if re.search(r"\bspeak\(|\bsay\(", block):
                bad.append(f"{fn}: onMounted 里调用了 speak()/say()")
                break
    assert not bad, (
        "老年端不许挂载即播报（iOS Safari 的 TTS 必须由用户手势触发，自动播静默不响，"
        "而页面看起来像已经念过了）。请改成「🔊 听一遍」按钮，并把 speak() 的返回值用于降级提示：\n  "
        + "\n  ".join(bad))


def _buttons(src: str) -> list[tuple[str, str]]:
    """返回 [(按钮开标签, 按钮内容)]。只关心"按钮上写的话"，因为那是老人读到的东西。"""
    return [(m.group(1), m.group(2)) for m in
            re.finditer(r"<n-button([^>]*)>(.*?)</n-button>", src, re.S)]


def test_hold_to_talk_copy_requires_hold_events():
    """按钮文案写"按住说话"，这个按钮就必须真的绑按住/松开事件（不能只绑 @click）。

    只查**按钮上写的话**：页面正文里描述别的页面（如「更多服务」里介绍小助手"按住说话"）
    不算违规 —— 闸门要抓的是"按钮承诺了按住、实际只认点击"。
    """
    bad = []
    for fn in _vue_files():
        src = _read(fn)
        for attrs, inner in _buttons(src):
            if not any(w in inner for w in _HOLD_COPY):
                continue
            if not any(e in attrs for e in _HOLD_EVENTS):
                label = re.sub(r"\s+", " ", inner).strip()[:24]
                bad.append(f"{fn}: 按钮「{label}」写了按住说话，但事件只有 {attrs.strip()[:60]}")
    assert not bad, (
        "「按住说话」的按钮必须与真实交互一致（要么真做 pointerdown/up 或 touchstart/end，"
        "要么把文案改成「点一下开始说话」）：\n  " + "\n  ".join(bad))


def test_speech_failure_is_visible_not_silent():
    """用了 TTS 的老年端页面必须有**播报失败**的可见降级（不能吞掉 speak 的返回值）。"""
    bad = []
    for fn in _vue_files():
        src = _read(fn)
        if "useSpeech" not in src or "speak(" not in src:
            continue
        # 判据：要么把返回值接住并在 UI 上体现（ttsOk / 统一 say() 入口）
        handled = bool(re.search(r"ok\s*=\s*await\s+speak", src)) or bool(
            re.search(r"async function say\(", src)) or "ttsOk" in src
        if not handled:
            bad.append(f"{fn}: 调用了 speak() 但没处理失败（老人会以为「没念」是自己没听见）")
    assert not bad, (
        "播报失败必须可见（这是「不许假装成功」的一部分）：\n  " + "\n  ".join(bad))


def test_scanner_actually_finds_violations():
    """扫描器自检：坏代码必须被抓到（防止闸门退化成永远绿）。"""
    bad_src = "onMounted(async () => {\n  speak('欢迎')\n})"
    good_src = ("onMounted(async () => {\n  welcome.value = '欢迎'\n})\n"
                "function hear(){ speak(welcome.value) }")
    bad_blocks = _mount_blocks(bad_src)
    assert bad_blocks, "onMounted 匹配失效"
    assert re.search(r"\bspeak\(", bad_blocks[0]), "自动播报没抓到"
    good_blocks = _mount_blocks(good_src)
    assert good_blocks and not re.search(r"\bspeak\(", good_blocks[0]), \
        "合法写法被误报（固定长度切片会把后面的普通函数算进来）"
    # 按钮文案判定也要自检：按住说话 + 只有 @click → 必须抓到
    fake_bad = '<n-button @click="f">🎤 按住说话</n-button>'
    fake_ok = '<n-button @pointerdown="f" @pointerup="g">🎤 按住说话</n-button>'
    hits_bad = [a for a, t in _buttons(fake_bad)
                if any(w in t for w in _HOLD_COPY) and not any(e in a for e in _HOLD_EVENTS)]
    hits_ok = [a for a, t in _buttons(fake_ok)
               if any(w in t for w in _HOLD_COPY) and not any(e in a for e in _HOLD_EVENTS)]
    assert len(hits_bad) == 1 and not hits_ok, "按住说话的按钮判定失效"
