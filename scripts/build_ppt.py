# scripts/build_ppt.py — 生成 9·22 路演 PPT（真 .pptx，可在 PowerPoint 里直接改）
# -*- coding: utf-8 -*-
"""为什么用脚本做 PPT：路演讲稿、数字、截图会反复改；手工改 PPT 三遍以后必然出现
"这页还是旧数字"的问题。脚本生成 = 数字只在一处改，重跑一次全部同步。

用法：
    python scripts/build_ppt.py                     # 用默认数字（638 / 48）
    python scripts/build_ppt.py --tests 638 --golden 48
    python scripts/build_ppt.py --out D:\\答辩素材\\路演.pptx

前置：先跑 `python scripts/shoot_ppt_assets.py` 抓截图（缺失的图会自动跳过，不影响生成）。

结构（18 页）：
  正文 14 页 封面 / 痛点 / 方案总览 / 架构与数据流 / 多智能体与双层防线 /
             居民端·报修 / 居民端·问与议 / 网格员端·工作台 / 网格员端·处理与关怀 /
             老人端·看得见按得动 / 老人端·不会打字也能办事 / 功能一览 / 数字墙 / 位置与诉求
  备用 2 页  规则为主·LLM 为辅 / 防编造与数据安全
  附录 2 页  如需看实物 / 最常被问的四个问题

设计约束（用户要求）：标题 ≥40pt、正文尽量 ≥20pt、不出现代码、字少图多、
**页面上不写"给作者自己看"的说明**（如"未做美化""本地可复现"），也不写舞台提示。

排版教训（已内建）：
  · 封面标题只占左侧、与右侧截图不重叠（曾被截图盖住右半段，看起来像截断）
  · 竖屏手机截图必须 letterbox（按宽度缩放会变很高，压住下方说明）
  · 被 PowerPoint 占用的文件：先写 .tmp 再替换，失败则改存"（新版）"并提示
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.enum.text import PP_ALIGN                              # noqa: E402
from pptx.util import Inches, Pt                                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "docs", "competition", "ppt-assets")

NAVY = RGBColor(0x12, 0x2A, 0x51)
BLUE = RGBColor(0x2D, 0x5B, 0xFF)
ORANGE = RGBColor(0xFF, 0x8C, 0x42)
INK = RGBColor(0x1B, 0x22, 0x33)
GREY = RGBColor(0x6B, 0x74, 0x85)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xF2, 0xF5, 0xFB)
PALE = RGBColor(0xE8, 0xEE, 0xF9)
FONT = "微软雅黑"
MAIN_PAGES = 14          # 正文档数（页码显示 n/14）

ROLES = ["接待员", "报修调度", "提案协商", "政策专员", "健康顾问",
         "天气守护", "通知管理", "网格助手", "合规审计"]


def _set_font(run, size, bold=False, color=INK, font=FONT):
    """同时设置 latin 与 east-asian 字体，避免中文回落到宋体。"""
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    for tag in ("latin", "ea", "cs"):
        el = rPr.find(ns + tag)
        if el is None:
            from lxml import etree
            el = etree.SubElement(rPr, ns + tag)
        el.set("typeface", font)


def bg(slide, color):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def box(slide, x, y, w, h, color):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                                 Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def text(slide, x, y, w, h, lines, size=28, bold=False, color=INK, align=PP_ALIGN.LEFT,
         spacing=1.25):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        _set_font(r, size, bold, color)
    return tb


def pic(slide, name, x, y, w=None, h=None):
    p = os.path.join(ASSETS, name)
    if not os.path.exists(p):
        return None
    kw = {}
    if w:
        kw["width"] = Inches(w)
    if h:
        kw["height"] = Inches(h)
    return slide.shapes.add_picture(p, Inches(x), Inches(y), **kw)


def pic_fit(slide, name, x, y, box_w, box_h):
    """把图片等比装进给定外框（letterbox）——竖屏手机截图必须用这个，否则会压住下方文字。"""
    p = os.path.join(ASSETS, name)
    if not os.path.exists(p):
        return None
    from PIL import Image
    iw, ih = Image.open(p).size
    ar = iw / ih
    w = min(box_w, box_h * ar)
    h = w / ar
    return pic(slide, name, x + (box_w - w) / 2, y + (box_h - h) / 2, w=w)


def title(slide, t):
    box(slide, 0.6, 0.55, 0.14, 0.62, ORANGE)
    text(slide, 0.95, 0.5, 11.8, 0.9, [t], size=40, bold=True, color=NAVY)


def page_no(slide, n, total=MAIN_PAGES, name=True, label=""):
    """统一页脚：细分隔线 + 左侧项目名 + 右侧页码（附录页给文字标签，避免两套分母）。"""
    from pptx.enum.shapes import MSO_SHAPE
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(7.12),
                                  Inches(11.9), Pt(0.75))
    line.fill.solid()
    line.fill.fore_color.rgb = RGBColor(0xDD, 0xE3, 0xEE)
    line.line.fill.background()
    line.shadow.inherit = False
    if name:
        text(slide, 0.6, 7.16, 8.0, 0.3, ["社区先知 CommunityInsight"], size=12, color=GREY)
    right = label if label else (f"{n} / {total}" if n else "")
    if right:
        text(slide, 11.0, 7.16, 1.5, 0.3, [right], size=12, color=GREY, align=PP_ALIGN.RIGHT)


def build(tests, golden):
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ================= 正文 1：封面 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, NAVY)
    text(s, 1.1, 1.55, 6.6, 0.95, ["社区先知"], size=52, bold=True, color=WHITE)
    text(s, 1.1, 2.6, 6.6, 0.75, ["CommunityInsight"], size=36, bold=True, color=WHITE)
    text(s, 1.1, 3.6, 6.6, 0.7, ["社区接诉即办 · 多智能体平台"], size=26, color=ORANGE)
    text(s, 1.1, 4.4, 6.6, 0.7, ["北京工商大学 · 单人开发"], size=22, color=WHITE)
    text(s, 1.1, 5.15, 6.6, 0.6, ["9·22 中关村软件园 OPC 沙龙"], size=16,
         color=RGBColor(0x9F, 0xB4, 0xD8))
    text(s, 1.1, 6.0, 11.4, 0.5, ["痛点 → 方案 → 机制 → 界面 → 数字 → 诉求"],
         size=18, color=ORANGE)
    pic(s, "01-登录页.png", 8.0, 1.5, w=4.6)

    # ================= 正文 2：痛点 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "四个老问题")
    for i, t in enumerate(["网格员：一半时间在重复派单",
                           "老人：不会用手机，报修太难",
                           "政策：网上答案没出处，不敢信",
                           "天气 / 健康 / 通知：分属不同部门，出事没人主动联动"]):
        box(s, 0.95, 1.75 + i * 1.15, 7.4, 0.95, LIGHT)
        text(s, 1.2, 1.88 + i * 1.15, 6.9, 0.8, [t], size=22)
    pic(s, "13-网格员端-工单管理.png", 8.7, 2.0, w=3.9)
    page_no(s, 2)

    # ================= 正文 3：方案总览 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "9 个角色，像一个小组")
    for i, r in enumerate(ROLES):
        col, row = i % 3, i // 3
        box(s, 0.95 + col * 2.55, 1.8 + row * 1.02, 2.3, 0.86,
            BLUE if r == "合规审计" else LIGHT)
        text(s, 1.0 + col * 2.55, 1.98 + row * 1.02, 2.2, 0.55, [r], size=18,
             bold=(r == "合规审计"), color=WHITE if r == "合规审计" else INK,
             align=PP_ALIGN.CENTER)
    text(s, 8.3, 1.9, 4.4, 2.8,
         ["三端各 14 / 9 / 8 页：", "居民端：一句话报修、提问",
          "网格员端：工单、提案、导数据", "老人端：大字、语音、长按求助"], size=19, spacing=1.4)
    pic(s, "02-居民首页与社区小助手.png", 0.95, 4.8, w=3.2)
    pic(s, "06-网格员工作台.png", 4.5, 4.8, w=3.2)
    pic_fit(s, "07-老年端大字首页.png", 9.2, 4.8, 1.6, 1.95)
    text(s, 0.95, 6.78, 3.2, 0.3, ["居民端"], size=15, color=GREY, align=PP_ALIGN.CENTER)
    text(s, 4.5, 6.78, 3.2, 0.3, ["网格员端"], size=15, color=GREY, align=PP_ALIGN.CENTER)
    text(s, 8.3, 6.78, 3.3, 0.3, ["老年端"], size=15, color=GREY, align=PP_ALIGN.CENTER)
    page_no(s, 3)

    # ================= 正文 4：它是怎么搭起来的 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "它是怎么搭起来的")
    for label, x in (("居民端", 0.95), ("网格员端", 3.1), ("老年端", 5.25)):
        box(s, x, 1.9, 2.0, 0.95, LIGHT)
        text(s, x, 2.13, 2.0, 0.5, [label], size=20, color=INK, align=PP_ALIGN.CENTER)
    text(s, 7.6, 1.95, 4.9, 1.0,
         ["三端共用一个后端", "（Vue3 + Naive UI，已构建为静态文件）"], size=17, color=GREY)
    box(s, 0.95, 3.15, 11.4, 1.0, BLUE)
    text(s, 1.2, 3.38, 11.0, 0.6,
         ["主服务 FastAPI：接口 · 鉴权 · 安全响应头 · 实时通知"],
         size=20, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    text(s, 0.95, 4.4, 11.4, 0.5, ["9 个智能体角色（黑板协作）"], size=18, color=NAVY, bold=True)
    for i, r in enumerate(ROLES):
        x = 0.95 + i * 1.29
        box(s, x, 4.9, 1.2, 0.62, LIGHT if r != "合规审计" else ORANGE)
        text(s, x, 5.02, 1.2, 0.45, [r], size=13,
             color=WHITE if r == "合规审计" else INK, align=PP_ALIGN.CENTER)
    box(s, 0.95, 5.85, 11.4, 1.0, PALE)
    text(s, 1.2, 6.02, 11.0, 0.7,
         ["本地数据库 SQLite：约 50 张表 · 手机号 AES-256-GCM 加密 · 全流程留痕"],
         size=19, color=INK, align=PP_ALIGN.CENTER)
    page_no(s, 4)

    # ================= 正文 5：多智能体与双层防线（重点） =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "它们真的在传消息")
    text(s, 0.95, 1.75, 6.4, 2.6,
         ["黑板：带锁 · 带版本 · 带历史",
          "5 种消息：请求 / 响应 / 通知 /",
          "错误 / 转交",
          "校验 + 仲裁，合规审计一票否决"], size=22, spacing=1.45)
    box(s, 0.95, 4.35, 6.4, 1.9, LIGHT)
    text(s, 1.2, 4.55, 6.0, 1.6,
         ["规则为主，大模型为辅：", "意图/追问/政策生成 → 大模型",
          "状态机/派单/权限/加密 → 规则"], size=20, spacing=1.35)
    pic(s, "04-多智能体执行链.png", 7.7, 1.7, w=4.9)
    text(s, 7.7, 6.12, 5.2, 0.5, ["↑ 一次提问后，角色之间的执行链"], size=16, color=GREY)
    page_no(s, 5)

    # ================= 正文 6：居民端（一）报修 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "居民端：报修，一句话提交")
    text(s, 0.95, 2.0, 5.3, 2.6,
         ["不用选分类、不用挑部门", "一句话说清哪儿坏了",
          "进度看得见：上报 → 派单 → 办结"], size=24, spacing=1.5)
    text(s, 0.95, 4.9, 5.3, 1.2, ["安全隐患自动升级为紧急通知"], size=20, color=ORANGE, bold=True)
    pic(s, "10-提交报修表单.png", 6.6, 1.7, w=3.3)
    text(s, 6.6, 3.82, 3.3, 0.4, ["① 一句话提交"], size=17, bold=True, color=NAVY)
    pic(s, "09-报修列表与状态.png", 6.6, 4.35, w=3.3)
    text(s, 6.6, 6.47, 3.3, 0.4, ["② 进度一目了然"], size=17, bold=True, color=NAVY)
    page_no(s, 6)

    # ================= 正文 7：居民端（二）问与议 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "居民端：问政策、议事情")
    gallery = [
        ("03-政策问答带依据与属地.png", "政策问答：依据 + 适用地区", 0.95),
        ("11-居民端-邻里议事.png", "邻里议事：提案与附议", 4.85),
        ("12-居民端-通知.png", "通知：普通 / 紧急 / 定时", 8.75),
    ]
    for name, cap, gx in gallery:
        pic(s, name, gx, 1.8, w=3.6)
        text(s, gx, 4.22, 3.6, 0.7, [cap], size=16, color=GREY)
    text(s, 0.95, 5.3, 11.4, 1.4,
         ["查不到依据就转人工，不硬答。", "通知发出去有已读回执。"], size=22, spacing=1.4)
    page_no(s, 7)

    # ================= 正文 8：网格员端（一）工作台 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "网格员端：一个工作台")
    pic(s, "06-网格员工作台.png", 0.95, 1.75, w=7.1)
    text(s, 0.95, 6.3, 7.1, 0.4, ["待办、概览、导出在一页看完"], size=16, color=GREY)
    text(s, 8.45, 1.95, 4.4, 4.2,
         ["待办：要派的、要回访的", "红黑榜：哪个小区问题多",
          "导出：按条件导周报", "AI 助手：大白话问数据"], size=20, spacing=1.7)
    page_no(s, 8)

    # ================= 正文 9：网格员端（二）处理与关怀 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "网格员端：留痕，和盯住老人")
    pic(s, "05-工单详情与处理留痕.png", 0.95, 1.8, w=5.4)
    pic(s, "14-网格员端-老年关怀.png", 6.95, 1.8, w=5.4)
    text(s, 0.95, 5.35, 5.4, 0.7, ["工单详情：谁在什么时候处理"], size=16, color=GREY)
    text(s, 6.95, 5.35, 5.4, 0.7, ["老年关怀：用药与联系人要审核"], size=16, color=GREY)
    text(s, 0.95, 6.15, 11.4, 0.9, ["退回必须写审核意见；求助要确认响应、再结束。"],
         size=19, color=ORANGE, bold=True)
    page_no(s, 9)

    # ================= 正文 10：老人端（一）看得见按得动 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "老人端：看得见，按得动")
    text(s, 0.95, 1.95, 6.9, 3.4,
         ["不是把居民端放大，是重做的", "字大、按钮大、不用登录就能进",
          "首页六件事：天气 通知 报修", "联系社区 联系人 用药提醒"], size=24, spacing=1.5)
    text(s, 0.95, 5.15, 6.9, 1.2, ["天气和帮助都能用语音念出来"], size=20, color=ORANGE, bold=True)
    pic_fit(s, "07-老年端大字首页.png", 8.9, 1.75, 2.4, 4.9)
    text(s, 8.3, 6.75, 3.6, 0.4, ["大字首页（手机实拍）"], size=16, color=GREY, align=PP_ALIGN.CENTER)
    page_no(s, 10)

    # ================= 正文 11：老人端（二）不会打字也能办事 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "老人端：不会打字，也能办事")
    elder = [
        ("15-老年端-社区小助手.png", "点现成的话就能问"),
        ("16-老年端-用药提醒.png", "我吃了 / 10 分钟后再说"),
        ("08-老年端长按求助确认框.png", "长按 3 秒，10 秒自动取消"),
    ]
    ex = 1.5
    for name, cap in elder:
        pic_fit(s, name, ex, 1.7, 2.3, 4.4)
        text(s, ex - 0.45, 6.2, 3.2, 0.6, [cap], size=15, color=GREY, align=PP_ALIGN.CENTER)
        ex += 3.55
    text(s, 0.95, 6.85, 11.4, 0.4, ["三条路都不用打字；紧急求助防了两道"],
         size=18, color=ORANGE, bold=True)
    page_no(s, 11)

    # ================= 正文 12：现在能用的功能（分端全景） =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "现在能用的功能（分端）")
    cols = [
        ("居民端 · 14 页", [
            "首页：天气卡 + 社区小助手",
            "报修：拍照提交 + 草稿恢复",
            "工单详情：时间线 + 撤回/重开",
            "邻里议事：提案 + 投票 + 匿名议论",
            "通知：紧急置顶 + 已读回执",
            "政策问答：依据 + 属地 + 提问历史",
            "健康防护：咨询 + 紧急转人工",
            "天气：实时 + 3 天预报 + 预警",
            "消息中心 / 我的 / 隐私政策",
        ]),
        ("网格员端 · 9 页", [
            "工作台：待办 + 红黑榜下钻",
            "工单管理：审核/派单/协商/转出",
            "　+ 批量操作 + 时限 + 导出",
            "提案管理：决定执行 + 转执行 + 延票",
            "通知管理：紧急/定时 + 已读统计",
            "政策问答管理：知识库维护 + 阈值",
            "天气管理：检查任务 + 异常日志",
            "健康管理：咨询处理 + 内容审核",
            "老年关怀：用药/联系人审核 + SOS",
        ]),
        ("老人端 · 8 页", [
            "首页：大字 + 六宫格 + 长按求助",
            "小助手：按住说话 → 转写确认 → 播报",
            "语音报修：识别 → 确认 → 提交",
            "用药提醒：审核后播报 + 我吃了",
            "听通知：大字 + 语音（紧急播两次）",
            "紧急联系人：审核后可拨打 + 留痕",
            "我的报修：进度 + 满意度反馈",
            "政策问答：语音提问 + 转人工确认",
        ]),
    ]
    cx = 0.7
    for head, items in cols:
        box(s, cx, 1.62, 3.9, 0.52, NAVY)
        text(s, cx, 1.71, 3.9, 0.4, [head], size=19, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        text(s, cx + 0.1, 2.28, 3.75, 0.4 * len(items),
             items, size=14.5, color=INK, spacing=1.02)
        cx += 4.15
    box(s, 0.7, 6.55, 11.95, 0.62, LIGHT)
    text(s, 0.9, 6.66, 11.6, 0.45,
         ["跨端：转人工「处理包」（AI 已整理上下文）· 双层防线（校验 + 仲裁）· "
          "规则为主、四个开关默认关 · 治理大屏 · 稳定性演示页"],
         size=15, color=INK)
    page_no(s, 12)

    # ================= 正文 13：数字墙 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, NAVY)
    title(s, "几个能复算的数字")
    items = [(f"{tests}", "项测试 · 全绿"), ("550", "并发 · 零失败"),
             (f"{golden}", "条金标 · 第一位命中 100%"), ("0", "ruff 问题")]
    for i, (num, lab) in enumerate(items):
        x = 0.95 + (i % 2) * 6.0
        y = 2.1 + (i // 2) * 2.1
        text(s, x, y, 5.4, 1.2, [num], size=72, bold=True, color=WHITE)
        text(s, x, y + 1.15, 5.4, 0.6, [lab], size=22, color=ORANGE)
    text(s, 0.95, 6.3, 11, 0.7, ["数据库 schema v46 · 约 50 张表　｜　本机自测，非第三方测评"],
         size=20, color=WHITE)
    page_no(s, 13)

    # ================= 正文 14：位置与诉求 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "它现在的位置，和我想请教的三件事")
    box(s, 0.95, 1.85, 11.4, 1.0, LIGHT)
    text(s, 1.3, 2.0, 10.8, 0.7,
         ["工程原型：还没在真实街道试点，没有运营数据，商业模式在探索"], size=24)
    qs = [("① 多智能体的「自动」边界怎么划？", "想请教技术专家"),
          ("② 第一个试点社区怎么找、怎么谈？", "想请教企业负责人"),
          ("③ 没有历史数据，冷启动怎么破？", "想请教投资人视角")]
    for i, (q, who) in enumerate(qs):
        text(s, 1.2, 3.35 + i * 0.95, 8.4, 0.7, [q], size=26)
        text(s, 9.8, 3.45 + i * 0.95, 2.6, 0.6, [who], size=15, color=GREY)
    text(s, 1.2, 6.5, 11, 0.6, ["张奶奶那条路，现在是一句话。"], size=20, color=ORANGE, bold=True)
    page_no(s, 14)

    # ================= 备用 1 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "备用：为什么规则为主、大模型为辅")
    text(s, 0.95, 2.0, 11.4, 3.0,
         ["接了 DeepSeek，但四个 LLM 开关默认关",
          "意图识别 / 追问补全 / 政策生成 → 大模型",
          "状态机 / 派单 / 权限 / 加密 → 永远走规则",
          "每次调用 3–5 秒超时，自动回落规则"], size=26, spacing=1.5)
    text(s, 0.95, 6.3, 11.4, 0.6, ["省成本，也保稳定。"], size=20, color=GREY)

    # ================= 备用 2 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "备用：防编造与数据安全")
    text(s, 0.95, 2.0, 11.4, 3.4,
         ["政策回答强制挂知识库出处，回答完回查数据库",
          "敏感词 + 权限再审计一道；查不到就转人工",
          "手机号 AES-256-GCM 加密存储，展示导出脱敏",
          "SQL 参数化；合规审计员有一票否决"], size=26, spacing=1.5)

    # ================= 附录 1：如需看实物 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "附录 · 如需看实物")
    text(s, 0.95, 1.9, 11.4, 2.6,
         ["1) 双击项目文件夹里的「启动演示」",
          "2) 等它提示「服务已就绪」（首次约 10–20 秒，会自动建好数据库）",
          "3) 浏览器会自动打开登录页"], size=26, spacing=1.5)
    box(s, 0.95, 4.4, 11.4, 1.9, LIGHT)
    text(s, 1.25, 4.6, 10.8, 1.6,
         ["演示账号：居民点「居民」免密 · 老年点「老年」免密 · 网格员 demo_grid / demo123",
          "环境：Windows + Python 3.10 以上；首次启动会自动装依赖",
          "没有网络也能用：大模型与天气会自动回到规则与本地数据"],
         size=19, spacing=1.35)
    page_no(s, None, label="附录")

    # ================= 附录 2：最常被问的四个问题 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "附录 · 最常被问的四个问题")
    qa = [
        ("这算真多智能体吗？",
         "角色之间靠黑板消息真来往，联动是运行时决定的；内核是规则驱动，不是全自主大模型智能体。"),
        ("数据是真的吗？",
         "全部是程序生成的演示数据，不含真实居民信息；手机号加密存储、展示脱敏。"),
        ("有人真的用过吗？",
         "没有。还没做真实街道试点，也没有运营数据，这是下一步。"),
        ("商业模式想清楚了吗？",
         "没有。可能是政府购买服务，但付费方和定价完全没有验证过。"),
    ]
    for i, (q, a) in enumerate(qa):
        y = 1.85 + i * 1.32
        box(s, 0.95, y, 11.4, 1.12, LIGHT if i % 2 == 0 else WHITE)
        text(s, 1.2, y + 0.1, 11.0, 0.45, [q], size=20, bold=True, color=NAVY)
        text(s, 1.2, y + 0.56, 11.0, 0.55, [a], size=16, color=INK)
    page_no(s, None, label="附录")

    # ================= 讲者备注（顺序与页面一一对应） =================
    notes = [
        "开场（25 秒，不念 PPT）：上周，我家楼下张奶奶摔了一跤。她想找人帮忙，手机却只会打给外地的儿子。等社区知道这件事，天已经黑了。——这一晚没有人做错什么，是这条路太长了。我想把它缩短成一句话，这就是社区先知。",
        "各位专家好，我是北京工商大学大二学生。这个项目我一个人做。它服务三种人：居民、网格员、老人。今天七分钟，我讲三件事：怎么做、能干什么、我卡在哪。",
        "四个痛点：网格员一半时间在重复派单；老人不会用手机、报修太难；网上政策没出处不敢信；天气/健康/通知分属不同部门，出事没人主动联动。主动说明：还没在真实街道试点，这是下一步。",
        "把社区里的事拆开，交给 9 个角色。社区里其实是三种人，所以三个端我分开做。居民端 14 页：居民要的是一句话把事说清，报修、提问都在这儿。网格员端 9 页：网格员要的是待办清楚、有据可查，工单、提案、导出都在这儿。老人端 8 页：老人要的是看得见、按得动，所以大字、语音、长按求助。三拨人要的东西不一样，硬做成一个 App，谁都不好用。",
        "它是怎么搭起来的：三端共用一个 FastAPI 后端，中间是 9 个角色在黑板协作，最下面是本地数据库（约 50 张表、手机号加密、全流程留痕）。数据库我选了本地 SQLite，不用单独搭服务器，也就没有运维。整条链路不依赖外部服务，一台普通电脑就能跑。",
        "重点页（85 秒）：9 个角色不写死流程，靠黑板 + 5 种消息真来往；每轮过校验员与仲裁器，合规审计一票否决。大模型只做意图/追问/政策生成，状态机、派单、权限、加密永远走规则；四个开关默认关。防编造三招：强制出处、回查数据库、敏感词与权限审计。实话：这是按规则分工协作，不是完全自主的大模型智能体。",
        "居民端（一）报修：提交不用选分类、不用挑部门，一句话说清哪儿坏了；提交后在列表里看进度（上报 → 派单 → 处理 → 办结），每一步带时间。识别到安全隐患（比如燃气味）会自动升级成紧急通知。",
        "居民端（二）问与议：政策问答的答案下面挂依据——哪份政策、适用哪个地区；查不到依据就转人工，不硬答。邻里议事可以提提案、邻居附议、社区回应。通知分普通/紧急/定时，发出去有已读回执。",
        "网格员端（一）工作台：一页看完待办（要派的、要回访的）、数据概览（红黑榜看哪个小区问题多）、导出（按条件导周报）、以及 AI 助手（用大白话问数据）。",
        "网格员端（二）处理与关怀：工单管理能搜索、能导出、能批量派单、能批量关闭；审核退回必须写意见，派单必须填维修人员与电话。点开一条工单，处理过程全程留痕。老年关怀里，用药提醒和紧急联系人都要审核通过才生效；老人求助来了，要确认响应、再结束。",
        "老人端（一）看得见按得动：不是把居民端放大，是重做的。字大、按钮大、不用登录。首页就六件事：天气、通知、报修、联系社区、联系人、用药提醒。天气和帮助都能用语音念出来。",
        "老人端（二）不会打字也能办事：三条路——① 点现成的话（家里灯不亮了 / 医保怎么报销）；② 直接说话，语音报修；③ 吃药提醒，就两个按钮「我吃了」「10 分钟后再说」，而且用药提醒要社区审核通过才开始播报。紧急求助长按 3 秒出确认框，10 秒不点自动取消——我怕老人放兜里误触，所以防了两道。",
        "功能按端列一遍（一列一段，手指往下扫）：居民端 14 页——报修拍照提交、能存草稿；工单详情有时间线，能撤回、能重开；邻里议事能提案、投票、公示期匿名议论；政策问答给依据和适用地区；还有健康防护、三天天气、通知、消息中心、我的、隐私政策。网格员端 9 页——工作台有待办和红黑榜下钻；工单管理能审核、派单、协商、转出，能批量操作和导出；提案管理能决定执行、转执行、延票；还有知识库维护、天气检查任务、健康内容审核、老年关怀的用药审核与 SOS 响应。老人端 8 页——语音小助手、语音报修、用药提醒、听通知、紧急联系人、报修进度、语音政策问答。最后一行跨端：转人工处理包、双层防线、规则为主，另有治理大屏与稳定性演示页。",
        "几个能复算的数字：638 项测试全绿、550 并发零失败、48 条金标第一位命中 100%、ruff 0；数据库 v46、约 50 张表。都是本机自测，不是第三方测评。",
        "它现在的位置：工程原型，没在真实街道试点，没有运营数据，商业模式在探索。今天不是来要投资，是来请教三个问题：多智能体的自动边界怎么划、第一个试点社区怎么谈、没有历史数据怎么冷启动。张奶奶那条路，现在是一句话。",
        "备用页：被追问「为什么不全用大模型」时翻到这页。",
        "备用页：被追问「会不会编造、数据安全吗」时翻到这页。",
        "附录：若对方想知道怎么在电脑上看实物，翻到这页。",
        "附录：四个最常被问的问题与诚实回答，独立阅读时直接看这页。",
    ]
    for i, note in enumerate(notes):
        if i < len(prs.slides):
            prs.slides[i].notes_slide.notes_text_frame.text = note

    return prs


def _save_safely(prs, out: str) -> tuple[str, str]:
    """安全落盘：先写临时文件，再尝试替换目标。

    踩过的坑（2026-09-15）：目标 pptx 正被 PowerPoint 打开时写入会 PermissionError，
    而脚本已经跑完一半——更糟的是**校验脚本随后校验的是旧文件**，会给出"通过"的假结论。
    所以这里先写 .tmp，再 os.replace；被占用时保留新版文件并明确告知怎么处理。
    """
    tmp = out + ".tmp"
    prs.save(tmp)
    try:
        os.replace(tmp, out)
        return out, ""
    except PermissionError:
        alt = out.replace(".pptx", "（新版）.pptx")
        try:
            os.replace(tmp, alt)
        except OSError:
            alt = tmp
        return alt, ("⚠️ 目标文件正被 PowerPoint 打开，已改存为："
                     f"{os.path.basename(alt)}\n"
                     "   处理：关掉 PowerPoint 里那份 PPT 后重跑本脚本；"
                     "或直接用这个新版文件（旧文件仍是上一版）。")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 9·22 路演 PPT")
    ap.add_argument("--tests", type=int, default=638, help="测试数（默认 638）")
    ap.add_argument("--golden", type=int, default=48, help="金标条数（默认 48）")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "competition",
                                                  "9月22日路演-社区先知.pptx"))
    args = ap.parse_args()
    prs = build(args.tests, args.golden)
    p, warn = _save_safely(prs, args.out)
    size = os.path.getsize(p) // 1024
    deck = Presentation(p)
    n_slides = len(deck.slides)
    n_notes = sum(1 for sl in deck.slides
                  if sl.has_notes_slide and sl.notes_slide.notes_text_frame.text.strip())
    n_pics = sum(1 for sl in deck.slides for sh in sl.shapes if sh.shape_type == 13)
    print(f"✅ 已生成：{p}（{size} KB）")
    print(f"   共 {n_slides} 页 = 正文 {MAIN_PAGES} 页 + 备用 2 页 + 附录 2 页；"
          f"{n_notes} 页带讲者备注；内嵌截图 {n_pics} 张")
    print(f"   截图素材目录：{ASSETS}")
    print(f"   数字口径：测试 {args.tests} / 金标 {args.golden}（改数字重跑本脚本即可）")
    if warn:
        print("   " + warn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
