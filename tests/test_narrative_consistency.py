# -*- coding: utf-8 -*-
"""对外叙事一致性门禁（2026-09-29，收敛方案第 1 阶段）。

**为什么要门禁**：本项目的教训是"机制做了、说法各写一份"，最后六份材料各讲一套，
答辩时口径对不上就是硬伤（历史上真出现过：登录页自转率与后端口径不一致）。
所以把"第一句话"也变成可执行判据：

  1. **同一句定位**：六份对外材料都要出现定稿的定位句（允许 markdown 加粗差异）；
  2. **同一句开场**：演示脚本与答辩手册都要有那句 30 秒开场；
  3. **不许把"未做的事"写成"已做"**：真实用户/老人验证、试点、真机这些**没做**的事，
     材料里不许出现"已证明/已验证/已实测"式表述（只允许"待验证/未验证/没有"）。

门禁自检：给一段假文本，判据必须报出来（防止"扫描器自己失效"）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 定稿的定位句（去掉 markdown 加粗与空白后比对，允许排版差异）
POSITION_CORE = ("社区先知把老年居民的一句话诉求，经过智能研判、证据校验与网格员协同，"
                 "转化为可处理、可追踪、可反馈的社区服务闭环")
#: 定稿的 30 秒开场（同上处理）
OPENING_CORE = ("我解决的不是「能不能调用大模型」，而是老年人提出的一句话诉求，"
                "能不能被准确理解、交给正确的人处理，并最终得到看得懂的反馈")
#: 必须出现定位句的对外材料
MATERIALS = [
    "README.md",
    "PRODUCT.md",
    "docs/competition/创意说明书-提交版.md",
    "docs/competition/技术实现报告.md",
    "docs/competition/演示脚本.md",
    "docs/competition/答辩问答手册.md",
]
#: 必须出现开场句的材料
OPENING_DOCS = ["docs/competition/演示脚本.md", "docs/competition/答辩问答手册.md"]
#: 禁止出现的"把没做的事说成已做"的表述
FORBIDDEN = ["已证明老人可以独立使用", "真实用户已验证", "真实老人已验证", "已完成真实用户验证",
             "社区试点已完成", "真机验证已完成"]


def _flat(text: str) -> str:
    """去掉 markdown 标记与所有空白，便于比对同一句话的不同排版。"""
    out = text
    for ch in ("*", "`", " ", "\n", "\r", "\t", "「", "」", "“", "”", '"', "'"):
        out = out.replace(ch, "")
    return out


def _read(rel: str) -> str:
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_all_materials_share_the_same_positioning():
    flat_pos = _flat(POSITION_CORE)
    missing = [m for m in MATERIALS if flat_pos not in _flat(_read(m))]
    assert not missing, (
        "这些材料没有使用定稿的定位句（对外六份必须是同一句话）：" + "、".join(missing))


def test_demo_and_qa_share_the_same_opening():
    flat_open = _flat(OPENING_CORE)
    missing = [m for m in OPENING_DOCS if flat_open not in _flat(_read(m))]
    assert not missing, "演示脚本/答辩手册缺少定稿的 30 秒开场：" + "、".join(missing)


def test_materials_do_not_claim_unfinished_validation():
    bad = []
    for m in MATERIALS + ["docs/competition/最终版交付说明.md"]:
        txt = _read(m)
        for i, ln in enumerate(txt.splitlines(), 1):
            for f in FORBIDDEN:
                if f in ln:
                    bad.append(f"{m}:{i} 出现「{f}」→ {ln.strip()[:70]}")
    assert not bad, ("材料里把没做过的事写成了已做（真实用户/老人验证尚未完成）：\n  " + "\n  ".join(bad))


def test_materials_still_say_it_is_unverified():
    """反向也要守：材料必须**如实说明**没有真实用户验证（不能反过来漏写）。"""
    txt = _read("docs/competition/最终版交付说明.md") + _read("docs/competition/创意说明书-提交版.md")
    assert ("无真实社区试点" in txt) or ("尚无真实社区试点" in txt), \
        "提交材料应明确写出「无真实社区试点/真实用户」这条边界"


def test_gate_self_check_catches_a_bad_material():
    """**门禁自检**：假材料（用了别的定位句 / 宣称已验证）必须被判红。"""
    fake = "本平台让居民知社区事、报社区修。真实用户已验证，老人可以独立使用。"
    assert _flat(POSITION_CORE) not in _flat(fake), "自检失效：假材料竟然命中了定位句"
    assert any(f in fake for f in FORBIDDEN), "自检失效：假材料里的『已验证』没被认出来"
