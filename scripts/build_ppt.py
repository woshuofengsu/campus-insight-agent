# scripts/build_ppt.py — 生成 9·22 路演 PPT（真 .pptx，可在 PowerPoint 里直接改）
# -*- coding: utf-8 -*-
"""为什么用脚本做 PPT：路演讲稿、数字、截图会反复改；手工改 PPT 三遍以后必然出现
"这页还是旧数字"的问题。脚本生成 = 数字只在一处改，重跑一次全部同步。

用法：
    python scripts/build_ppt.py                     # 用默认数字（638 / 48）
    python scripts/build_ppt.py --tests 638 --golden 48
    python scripts/build_ppt.py --out D:\\答辩素材\\路演.pptx

前置：先跑 `python scripts/shoot_ppt_assets.py` 抓截图（缺失的图会自动跳过，不影响生成）。
设计约束（按用户要求）：标题 ≥40pt、正文 ≥24pt、不出现代码、每页正文 ≤3 行、字少图多。
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
FONT = "微软雅黑"


def _set_font(run, size, bold=False, color=INK, font=FONT):
    """同时设置 latin 与 east-asian 字体，避免中文回落到宋体。"""
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rPr.find(f"{{http://schemas.openxmlformats.org/drawingml/2006/main}}{tag.split(':')[1]}")
        if el is None:
            from lxml import etree
            el = etree.SubElement(rPr, f"{{http://schemas.openxmlformats.org/drawingml/2006/main}}{tag.split(':')[1]}")
        el.set("typeface", font)


def bg(slide, color):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                 Inches(13.333), Inches(7.5))
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


def page_no(slide, n, total):
    text(slide, 12.1, 6.95, 1.0, 0.4, [f"{n} / {total}"], size=12, color=GREY,
         align=PP_ALIGN.RIGHT)


def title(slide, t):
    box(slide, 0.6, 0.55, 0.14, 0.62, ORANGE)
    text(slide, 0.95, 0.5, 11.8, 0.9, [t], size=40, bold=True, color=NAVY)


def build(tests, golden, gi, out):
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    total = 8

    # ---------- 1 封面 ----------
    # ⚠️ 排版教训（2026-09-15 实测）：标题文本框原来宽 11 英寸、一直伸到 12.1 英寸，
    #    而右侧登录页截图从 8.3 英寸开始并且**后画**（在标题之上）→ 把 "…yInsight" 挡住了，
    #    看起来像"标题被切断"。所以封面**标题只占左侧 6.6 英寸、分两行写**，右侧留给图，两者不重叠。
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, NAVY)
    text(s, 1.1, 1.9, 6.6, 0.95, ["社区先知"], size=52, bold=True, color=WHITE)
    text(s, 1.1, 2.95, 6.6, 0.75, ["CommunityInsight"], size=36, bold=True, color=WHITE)
    text(s, 1.1, 3.95, 6.6, 0.7, ["社区接诉即办 · 多智能体平台"], size=26, color=ORANGE)
    text(s, 1.1, 4.8, 6.6, 0.7, ["北京工商大学 · 单人开发"], size=22, color=WHITE)
    pic(s, "01-登录页.png", 8.0, 1.6, w=4.6)

    # ---------- 2 痛点 ----------
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "四个老问题")
    for i, t in enumerate(["网格员：一半时间在重复派单",
                           "老人：不会用手机，报修太难",
                           "政策：网上答案没出处，不敢信"]):
        box(s, 0.95, 1.9 + i * 1.35, 7.4, 1.05, LIGHT)
        text(s, 1.25, 2.05 + i * 1.35, 6.9, 0.8, [t], size=28)
    text(s, 0.95, 6.0, 11, 0.6,
         ["（第四点口述：天气、健康、通知分属不同部门，出事没人主动联动）"], size=16, color=GREY)
    pic(s, "06-网格员工作台.png", 8.7, 2.0, w=3.9)
    page_no(s, 2, total)

    # ---------- 3 方案总览 ----------
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "9 个角色，像一个小组")
    roles = ["接待员", "报修调度", "提案协商", "政策专员", "健康顾问",
             "天气守护", "通知管理", "网格助手", "合规审计"]
    for i, r in enumerate(roles):
        col, row = i % 3, i // 3
        box(s, 0.95 + col * 2.55, 1.95 + row * 1.25, 2.3, 1.0,
            BLUE if r == "合规审计" else LIGHT)
        text(s, 1.0 + col * 2.55, 2.2 + row * 1.25, 2.2, 0.6, [r], size=22,
             bold=(r == "合规审计"), color=WHITE if r == "合规审计" else INK,
             align=PP_ALIGN.CENTER)
    text(s, 0.95, 6.0, 11, 0.7, ["三端：居民 14 页 / 网格员 9 页 / 老人 8 页"], size=24, color=NAVY)
    page_no(s, 3, total)

    # ---------- 4 多智能体与双层防线（重点） ----------
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "它们真的在传消息")
    # 「5 种消息」那行原来太长被折成「转 / 交」，改为拆两行写（COM 量到 textH 167.7 说明发生了折行）
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
    text(s, 7.7, 6.15, 5.0, 0.5, ["↑ 现场展开的「多智能体执行链」"], size=14, color=GREY)
    page_no(s, 4, total)

    # ---------- 5 适老化 ----------
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "老人端是重做的，不是放大的")
    text(s, 0.95, 1.8, 5.6, 3.2,
         ["大字大按钮，免登录就能进",
          "语音报修；用药提醒点一下「我已吃」",
          "长按 3 秒才求助，还要再确认一次"], size=26, spacing=1.5)
    text(s, 0.95, 5.2, 5.6, 1.2, ["我怕老人放兜里，误触。"], size=22, color=ORANGE, bold=True)
    pic(s, "07-老年端大字首页.png", 7.1, 1.7, h=4.6)
    pic(s, "08-老年端长按求助确认框.png", 9.9, 1.7, h=4.6)
    page_no(s, 5, total)

    # ---------- 6 现场演示 ----------
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "现在看它真的能跑")
    steps = ["① 居民报修", "② 政策问答（看依据）", "③ 天气联动（看执行链）",
             "④ 老人端长按求助", "⑤ 网格员工作台"]
    for i, t in enumerate(steps):
        box(s, 0.95, 1.95 + i * 1.0, 11.4, 0.82, LIGHT if i % 2 == 0 else WHITE)
        text(s, 1.3, 2.08 + i * 1.0, 10.6, 0.6, [t], size=26)
    page_no(s, 6, total)

    # ---------- 7 数字墙 ----------
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
    page_no(s, 7, total)

    # ---------- 8 下一步与诉求 ----------
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
    page_no(s, 8, total)

    # ---------- 备用页 ----------
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "备用：为什么规则为主、大模型为辅")
    text(s, 0.95, 2.0, 11.4, 3.0,
         ["接了 DeepSeek，但四个 LLM 开关默认关",
          "意图识别 / 追问补全 / 政策生成 → 大模型",
          "状态机 / 派单 / 权限 / 加密 → 永远走规则",
          "每次调用 3–5 秒超时，自动回落规则"], size=26, spacing=1.5)
    text(s, 0.95, 6.4, 11.4, 0.6, ["省成本，也保稳定——学生项目也养得起。"], size=20, color=GREY)

    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "备用：防编造与数据安全")
    text(s, 0.95, 2.0, 11.4, 3.4,
         ["政策回答强制挂知识库出处，回答完回查数据库",
          "敏感词 + 权限再审计一道；查不到就转人工",
          "手机号 AES-256-GCM 加密存储，展示导出脱敏",
          "SQL 参数化；合规审计员有一票否决"], size=26, spacing=1.5)

    prs.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 9·22 路演 PPT")
    ap.add_argument("--tests", type=int, default=638, help="测试数（默认 638）")
    ap.add_argument("--golden", type=int, default=48, help="金标条数（默认 48）")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "competition",
                                                  "9月22日路演-社区先知.pptx"))
    args = ap.parse_args()
    p = build(args.tests, args.golden, args.tests, args.out)
    size = os.path.getsize(p) // 1024
    print(f"✅ 已生成：{p}（{size} KB，8 页 + 2 页备用）")
    n_pic = sum(1 for _ in os.listdir(ASSETS)) if os.path.isdir(ASSETS) else 0
    print(f"   截图素材：{ASSETS}（{n_pic} 个文件）")
    print("   数字口径：测试 %d / 金标 %d（改数字重跑本脚本即可）" % (args.tests, args.golden))
    return 0


if __name__ == "__main__":
    sys.exit(main())
