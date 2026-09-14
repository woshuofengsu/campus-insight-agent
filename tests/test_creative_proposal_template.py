# -*- coding: utf-8 -*-
"""《创意说明书-提交版》模板符合性门禁。

## 为什么要有这个测试
这份文件是**交给组委会的正式提交件**，它必须与官方模板逐节对齐——而"对齐"最容易在改写时被破坏：
本项目第四十九轮重写时，就曾把模板里的三处内容改薄或改没（五.2 的四项勾选自评、七的附件材料 5 条、
三.3/三.4 的模板要点），并把「项目概述」写到超字数。这类问题在答辩/初筛阶段是**硬伤**，
但在代码层面毫无信号（跑测试、跑审计都全绿）。

所以我们把模板要求写成断言：
1. **28 个模板标题**（层级 + 原文）必须齐全，不得改名或删除；
2. 「二、项目概述（≤300 字）」**必须真的 ≤300 字**（同时按"中文字数"和"去空白总字符"两种口径卡）；
3. 「五、2 已完成验证」四项自评勾选必须在（未测试/内部测试/小范围试用/场景试点）；
4. 「七、附件材料」模板要求的 1–5 条必须在（第 5 条后可以再补仓库材料索引）；
5. 参赛方向**只勾选"基层治理"**，负责人/成员关键字段非空且格式合法。

注意：本测试**不硬编码身份证号/手机号等个人信息**（避免把 PII 复制到第二处文件），
只校验"字段在且格式像"。
"""
import io
import os
import re

DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "competition", "创意说明书-提交版.md")

# 官方模板的全部标题（层级, 原文）——不得改名、不得删除
TEMPLATE_HEADINGS = [
    (1, "智能体创意说明书"),
    (2, "一、项目基本信息"),
    (3, "1. 项目名称"),
    (3, "2. 团队成员信息表"),
    (3, "3. 参赛方向（勾选）"),
    (3, "4. 项目负责人信息"),
    (2, "二、项目概述（≤300 字）"),
    (2, "三、智能体架构与技术实现（核心）"),
    (3, "1. 整体架构逻辑"),
    (3, "2. 智能体工作流设计"),
    (3, "3. 人机协同边界设计"),
    (3, "4. 架构创新点"),
    (2, "四、产业 / 场景应用说明"),
    (3, "1. 精准应用场景（垂直细分）"),
    (3, "2. 目标问题与现有方案痛点"),
    (3, "3. 智能体提效 / 降本 / 提质 / 风控价值"),
    (3, "4. 适配区域 / 社区落地路径"),
    (2, "五、可运行性与落地可行性"),
    (3, "1. 原型状态"),
    (3, "2. 已完成验证"),
    (3, "3. 核心技术栈与依赖工具"),
    (3, "4. 落地所需条件"),
    (3, "5. 风险点与应对方案"),
    (2, "六、合规与知识产权"),
    (3, "1. 数据来源与合规说明"),
    (3, "2. 第三方资源授权情况"),
    (3, "3. 知识产权规划"),
    (2, "七、附件材料"),
]

# 三.3 / 三.4 里模板明确要求的小标题（原文）
REQUIRED_SUBPOINTS = [
    "智能体自动执行环节",
    "人类监督 / 审核 / 决策环节",
    "安全与合规校验机制",
    "可复用、可迁移、可规模化",
    "AI 原生与智能体规范符合性",
]

OVERVIEW_LIMIT = 300


def _doc() -> str:
    assert os.path.exists(DOC), f"提交件不存在：{DOC}"
    return io.open(DOC, encoding="utf-8").read()


def _section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    assert i >= 0, f"找不到章节：{start}"
    j = text.find(end, i + 1)
    return text[i:j] if j > i else text[i:]


def test_template_headings_intact():
    """28 个模板标题必须齐全（改名/删除都会失败）。"""
    text = _doc()
    have = {(len(m.group(1)), m.group(2).strip())
            for m in re.finditer(r"(?m)^(#{1,4})\s*(.+)$", text)}
    missing = [h for h in TEMPLATE_HEADINGS if h not in have]
    assert not missing, f"提交件缺少/改动了模板标题：{missing}"


def test_required_subpoints_present():
    """三.3、三.4 的模板要点必须在（本轮曾把它们改薄）。"""
    text = _doc()
    missing = [k for k in REQUIRED_SUBPOINTS if k not in text]
    assert not missing, f"缺少模板要求的要点：{missing}"


def test_overview_within_300_words():
    """「项目概述（≤300 字）」必须真的 ≤300：中文口径 + 去空白总字符口径都卡。"""
    sec = _section(_doc(), "## 二、项目概述", "## 三、")
    body = re.sub(r"[#>*\-\s]", "", sec.split("\n", 1)[1])
    cn = len(re.findall(r"[\u4e00-\u9fa5]", body))
    assert cn <= OVERVIEW_LIMIT, f"项目概述中文字数 {cn} 超限（≤{OVERVIEW_LIMIT}）"
    assert len(body) <= OVERVIEW_LIMIT, (
        f"项目概述去空白总字符 {len(body)} 超限（≤{OVERVIEW_LIMIT}）——"
        "按严格口径（含标点与数字）也必须达标")
    assert cn >= 120, f"项目概述只有 {cn} 字，信息量过低（疑似被误删）"


def test_verification_checkboxes_present():
    """五.2「已完成验证」必须保留四项自评勾选（未测试/内部测试/小范围试用/场景试点）。"""
    blk = _section(_doc(), "### 2. 已完成验证", "### 3.")
    boxes = re.findall(r"(?m)^-\s\[[ x]\]\s*(.+)$", blk)
    assert len(boxes) >= 4, f"勾选项只剩 {len(boxes)} 条：{boxes}"
    joined = "".join(boxes)
    for key in ("未测试", "内部测试", "小范围试用", "场景试点"):
        assert key in joined, f"缺少模板要求的自评项：{key}"
    assert "[x]" in blk and "[ ]" in blk, "四项自评必须至少有一条勾选、一条不勾选（当前状态要如实反映）"


def test_attachment_items_present():
    """七、附件材料：模板要求的 1–5 条必须在（索引表可作为补充追加）。"""
    sec = _section(_doc(), "## 七、附件材料", "\n## ")
    items = re.findall(r"(?m)^(\d)\.\s", sec)
    assert items[:5] == ["1", "2", "3", "4", "5"], f"附件材料编号条目异常：{items[:6]}"
    for key in ("架构图", "原型界面截图", "测试数据", "知识产权", "支撑材料"):
        assert key in sec, f"附件材料缺少模板条目关键词：{key}"


def test_direction_checked_only_governance():
    """参赛方向必须只勾选「基层治理」。"""
    blk = _section(_doc(), "### 3. 参赛方向", "### 4.")
    checked = re.findall(r"(?m)^-\s\[x\]\s*(.+)$", blk)
    assert len(checked) == 1, f"应只勾选一项，实际勾选 {len(checked)} 项：{checked}"
    assert "基层治理" in checked[0], f"勾选项应为基层治理，实际：{checked[0]}"


def test_identity_fields_present_without_leaking_values():
    """负责人/成员关键字段非空且格式合法（**不复制 PII 到测试里**）。"""
    text = _doc()
    assert re.search(r"\|[^|\n]*\|\s*\d{17}[\dXx]\s*\|", text), "成员信息表缺 18 位身份证号"
    assert re.search(r"联系电话：\s*1\d{10}", text), "缺 11 位手机号"
    assert re.search(r"电子邮箱：\s*[\w.\-]+@[\w.\-]+", text), "缺邮箱"
    assert re.search(r"\|[^|\n]*本科[^|\n]*\|", text), "成员信息表缺学历"
    assert "单人参赛" in text, "应写明单人参赛（与团队信息表一致）"
