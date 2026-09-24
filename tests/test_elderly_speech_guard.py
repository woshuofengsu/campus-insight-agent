# -*- coding: utf-8 -*-
"""老年端语音降级守卫（B4 无障碍硬化）。

为什么要有这个测试：老年端语音在 iOS Safari / 微信内置浏览器里大概率不可用，
"不支持时的降级路径"最容易只写在文档里、代码里悄悄退回去（例如又有人在 onMounted 里自动播报）。
这里把三条硬规则钉住：

1. **用了语音的页面必须有降级提示条**（`data-speech-fallback`），且走统一文案 `reasonText`；
2. **承载信息的播报不许自动触发**（首页问候/紧急通知必须用户点一下）——iOS 要求用户手势，
   自动播会静默不响，老人以为"坏了"；
3. **能力探测用真值判断**，不能用 `'speechSynthesis' in window`（属性存在但为 undefined 时误判，
   实测踩到：审计注入脚本把 API 置空后仍被判为"支持"）。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELDERLY = os.path.join(ROOT, "web", "src", "views", "elderly")
COMPOSABLE = os.path.join(ROOT, "web", "src", "composables", "useSpeech.js")

# 用语音的页面：必须有降级提示条
SPEECH_PAGES = ("Home.vue", "Agent.vue", "Report.vue", "QA.vue", "Notices.vue", "Health.vue")


def _read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def test_speech_pages_have_fallback_banner():
    for name in SPEECH_PAGES:
        src = _read(os.path.join(ELDERLY, name))
        assert "data-speech-fallback" in src, f"{name} 缺少降级提示条（data-speech-fallback）"
        assert "speechCapability" in src, f"{name} 没做能力探测，语音不可用时无法提前说明"


def test_pages_that_recognize_explain_reason():
    """调用 recognize() 的页面：必须用统一文案说明原因，不能一律"没听清"。"""
    for name in ("Agent.vue", "Report.vue", "QA.vue"):
        src = _read(os.path.join(ELDERLY, name))
        assert "recognize(" in src
        assert "reasonText" in src, f"{name} 应使用 composables 里的统一降级文案 reasonText"
        assert "asrBlocked" in src, f"{name} 应记录语音不可用状态并在界面上说明"
        # 不允许再出现"把所有失败都当成没听清"的写法
        assert "没听清，请再说一次或直接打字" not in src, f"{name} 又把失败原因一律当成没听清"


def test_info_bearing_speech_is_not_auto_played():
    """承载信息的自动播报必须改成用户手势触发（iOS 静默失败的根因）。"""
    home = _read(os.path.join(ELDERLY, "Home.vue"))
    m = re.search(r"onMounted\(async \(\) => \{(.*?)\n\}\)", home, re.S)
    assert m, "Home.vue 的 onMounted 结构变了，请同步本测试"
    body = m.group(1)
    assert "speak(" not in body, "首页 onMounted 里不许再自动播报（iOS 需用户手势）"
    assert "playWelcome" in home and "playUrgent" in home, "首页应提供「点一下听」的入口"

    notices = _read(os.path.join(ELDERLY, "Notices.vue"))
    m2 = re.search(r"onMounted\(async \(\) => \{(.*?)\n\}\)", notices, re.S)
    assert m2, "Notices.vue 的 onMounted 结构变了，请同步本测试"
    assert "speak(" not in m2.group(1), "通知页不许挂载即播报"
    assert "readUrgent" in notices, "通知页应提供点一下听紧急通知的入口"


def test_speak_result_is_consumed_where_it_matters():
    """承载信息的页面必须处理 speak() 的返回值（false = 这台机器念不出来）。"""
    notices = _read(os.path.join(ELDERLY, "Notices.vue"))
    assert re.search(r"await speak\(", notices), "Notices.vue 应 await speak() 并处理返回值"
    assert "ttsOk" in notices
    health = _read(os.path.join(ELDERLY, "Health.vue"))
    assert "ttsOk" in health and "data-speech-fallback" in health


def test_capability_probe_uses_truthiness():
    """能力探测必须用真值判断：`in window` 在「属性存在但值为 undefined」时会误判成支持。"""
    js = _read(COMPOSABLE)
    # 只看代码行：注释里会引用反例说明原因，不该被本测试当成违规
    code = "\n".join(ln.split("//")[0] for ln in js.splitlines())
    assert "!!window.speechSynthesis" in code, "hasTTS 必须用真值判断"
    assert "'speechSynthesis' in window" not in code, "不许用 in window 判断 TTS 能力"
    assert "export function speechCapability" in code
    assert "export function reasonText" in code
