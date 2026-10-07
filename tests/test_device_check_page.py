# -*- coding: utf-8 -*-
"""真机自查页（`web/public/device-check.html` + `device-check.js`）的结构门禁。

## 为什么要有这个测试

真机走查（Android Chrome / iOS Safari / 微信内置浏览器）**只能由人拿真手机做**，
机器替代不了。但"支持件本身有没有坏"是机器能守的：

- 这页是**主试在真机上打开的那一页**，它坏了 → 走查记录直接变空白（而且没人会发现，因为没人天天点）；
- 它必须能在真机上加载（`<script src>` 同源外部文件，**不能内联**——CSP 是 `script-src 'self'`）；
- 它必须**如实**：不能写着"能自动拨号/能接通"，也不能暗示"这页等于找真人观察过"。

所以本文件只验**结构与口径**（能否加载、探针齐不齐、报告能不能复制回去、有没有夸大），
**不验真机结果**——真机结果只能由人在 `docs/eval/真机验证记录.md` 里如实登记（现在是"未开展"）。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "web", "public")
HTML = os.path.join(PUBLIC, "device-check.html")
JS = os.path.join(PUBLIC, "device-check.js")
RECORD = os.path.join(ROOT, "docs", "eval", "真机验证记录.md")


def _html() -> str:
    return io.open(HTML, encoding="utf-8").read()


def _js() -> str:
    return io.open(JS, encoding="utf-8").read()


def test_page_files_exist():
    assert os.path.isfile(HTML), f"缺少真机自查页：{HTML}"
    assert os.path.isfile(JS), f"缺少真机自查脚本：{JS}"


def test_script_is_external_not_inline():
    """CSP `script-src 'self'`：脚本必须是同源外部文件，内联会在真机上直接被拦。"""
    src = _html()
    assert 'src="/device-check.js"' in src, "没有引用外部的 /device-check.js"
    # 找所有 <script ...> 开始标签，除了带 src 的那个，其余都不许出现
    tags = re.findall(r"<script\b[^>]*>", src, re.I)
    inline = [t for t in tags if "src=" not in t.lower()]
    assert not inline, f"出现了内联 script 标签（CSP 会拦）：{inline}"


def test_all_probe_sections_and_ids_present():
    """页面结构 + 脚本要用的元素 id 必须对得上（写错 id 只会静默不显示）。"""
    src, js = _html(), _js()
    for sec in ("语音", "播报", "拨号", "草稿", "SOS", "报告"):
        assert sec in src, f"页面缺少「{sec}」这一节"
    for eid in ("env", "speech", "tts", "tel", "report"):
        assert f'id="{eid}"' in src, f"页面缺少 id={eid} 的容器"
        assert f"getElementById('{eid}')" in js, f"脚本没有用到 id={eid}（两边对不上）"
    for btn in ("speak", "copy", "again"):
        assert f'id="{btn}"' in src, f"页面缺少按钮 id={btn}"
        assert f"getElementById('{btn}')" in js, f"脚本没有绑定按钮 {btn}"


def test_report_can_be_copied_back_to_the_record_sheet():
    """报告要能一键复制回记录表（否则主试只能手抄，真机走查会因此被偷懒跳过）。"""
    src, js = _html(), _js()
    assert re.search(r"<textarea[^>]*id=\"report\"[^>]*readonly", src), "报告框不是 readonly 的"
    assert "execCommand('copy')" in js or "execCommand(\"copy\")" in js, "没有复制实现"
    assert "真机验证记录.md" in js, "报告头没有指向 docs/eval/真机验证记录.md"
    assert "真机自查报告" in js, "报告头没有标题"


def test_probes_are_the_real_ones():
    """四项机器探针必须在：语音能力 / 播报是否需要手势 / 拨号 / 设备信息。"""
    js, src = _js(), _html()
    for needle in ("SpeechRecognition", "webkitSpeechRecognition", "speechSynthesis",
                   "SpeechSynthesisUtterance", "userAgent", "maxTouchPoints"):
        assert needle in js, f"脚本缺少探针：{needle}"
    assert 'href="tel:' in src, "没有拨号链接（真机验证拨号行为要用它）"


def test_wording_is_honest():
    """口径必须如实：能替代什么/不能替代什么、拨号只到"打开拨号盘"为止。"""
    src = _html()
    assert "不能替代" in src, "没有写清「这页替代不了什么」（会把「测过设备」说成「观察过老人」）"
    assert "只在网页里打开拨号盘" in src, "没有写清拨号只到「打开拨号盘」为止"
    assert "别真的按下去" in src, "SOS 那一节没有提醒别真按（会真的发通知）"
    js = _js()
    assert "已接通" in js, "脚本里没有提醒「网页拿不到已接通状态」"
    # ⚠️ 判据要写"**肯定式**的夸大说法"，不能把否定句一起禁掉：
    # 第一版黑名单里放了「自动拨出」，而页面原话是「**不会**自动拨出」——
    # 那正是**诚实**的那一句，却被我自己的判据判成违规（判据写错比漏判更误导人）。
    assert "不会自动拨出" in js or "不自动拨出" in js, "没有写清「不会自动拨出」"
    assert not re.search(r"(location(\.href)?\s*=|window\.open\s*\()\s*['\"]tel:", js), \
        "脚本里出现了「自己跳转 tel:」——那等于替用户拨号（我们只允许用户点链接）"
    lies = ("能自动拨出", "自动拨打", "已接通成功", "保证接通", "正在呼叫", "已拨通")
    for bad in lies:
        assert bad not in src and bad not in js, f"出现了夸大表述：{bad}"


def test_companion_record_doc_exists_and_is_honest():
    """配套记录表必须在，而且如实写着"未开展"（别把支持件当成已完成的证据）。"""
    assert os.path.isfile(RECORD), f"缺少真机验证记录：{RECORD}"
    txt = io.open(RECORD, encoding="utf-8").read()
    assert "未开展" in txt or "尚未" in txt, "真机验证记录没有写明「尚未开展」"
    assert "device-check.html" in txt, "记录表没有指向真机自查页（两件东西必须互相引用）"
