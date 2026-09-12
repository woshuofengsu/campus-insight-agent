# utils/text.py
"""纯文本处理工具，不依赖任何第三方库。

UI 层（ui/）和 agent 层（agent/）都在用。单独拆出来是为了避免循环 import，
也躲开 Streamlit 对 ui/components.py 的 exec() 上下文问题。
"""
import re


def split_thinking(content: str) -> tuple[str, str]:
    """把 AI 回复拆成（正文, 思考过程）两部分。

    处理 DeepSeek 风格的 <think>...</think> 和 <thinking>...</thinking> 标签。
    聊天页（home.py）和 agent 引擎（engine.py）都在用。
    """
    thinking_parts: list[str] = []
    cleaned = content

    _t1, _t2 = "<think>", "</think>"
    for match in reversed(list(re.finditer(re.escape(_t1) + r'(.*?)' + re.escape(_t2), cleaned, re.DOTALL))):
        thinking_parts.append(match.group(0))
        cleaned = cleaned[:match.start()] + cleaned[match.end():]

    _t3, _t4 = "<thinking", "</thinking>"
    for match in reversed(list(re.finditer(
        re.escape(_t3) + r'[^>]*>' + r'(.*?)' + re.escape(_t4),
        cleaned, re.DOTALL | re.IGNORECASE,
    ))):
        thinking_parts.append(match.group(1).strip())
        cleaned = cleaned[:match.start()] + cleaned[match.end():]

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    thinking = "\n\n---\n\n".join(reversed(thinking_parts)) if thinking_parts else ""
    return cleaned, thinking


# ---- 敏感词检测（通知/内容发布前拦截，spec 05/04：涉政治、暴力、诈骗、隐私等）----

_SENSITIVE_WORDS = [
    # 涉政/违法（演示用最小集，可扩展）
    "共产党", "习近平", "习主席", "法轮功", "台独", "藏独", "疆独", "港独",
    "颠覆国家", "恐怖", "爆炸物", "枪支弹药",
    # 诈骗/隐私
    "转账给我", "打钱到", "汇款账号", "银行卡号", "身份证号", "密码发我",
    # 辱骂/色情
    "傻逼", "妈的", "操你", "妓女", "嫖娼", "赌博",
]


def check_sensitive(text: str) -> tuple[bool, str]:
    """敏感词检测：返回 (是否含敏感词, 命中的敏感词)。"""
    text = text or ""
    for w in _SENSITIVE_WORDS:
        if w and w in text:
            return True, w
    return False, ""


# ---- 检索同义词扩展（U1 混合检索：零依赖，把居民口语映射为政策书面语）----
# 放在 utils/ 供 data 层与 agent 层共用，避免 data↔agent 循环导入。
QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "医保": ("医疗保险", "基本医疗保险", "医疗费用", "报销"),
    "社保": ("社会保险", "养老保险", "参保"),
    "报销": ("医保", "医疗费用", "结算"),
    "加装电梯": ("增设电梯", "老楼装电梯", "老旧小区电梯", "电梯加装"),
    "电梯": ("加装电梯", "增设电梯", "电梯维修"),
    "补贴": ("补助", "津贴", "资助", "扶持"),
    "养老金": ("退休金", "养老待遇", "基本养老金"),
    "退休": ("养老金", "退休金", "养老待遇"),
    "老年": ("老人", "老年人", "老龄", "为老服务"),
    "高龄": ("高龄津贴", "高龄补贴", "老年人"),
    "低保": ("最低生活保障", "困难群众", "社会救助"),
    "救助": ("临时救助", "社会救助", "困难帮扶"),
    "公租房": ("公共租赁住房", "保障性租赁住房", "保障房"),
    "物业": ("物业管理", "物业费", "物业服务"),
    "垃圾": ("生活垃圾分类", "垃圾分类", "垃圾桶", "清运"),
    "停车": ("停车位", "车位", "机动车停放"),
    "暖气": ("供暖", "采暖", "供热", "供暖季"),
    "漏水": ("渗水", "滴水", "水管", "管道"),
    "报修": ("维修", "修缮", "养护"),
    "残疾": ("残疾人", "残疾人补贴", "助残"),
    "生育": ("生育津贴", "产假", "生育登记"),
    "公积金": ("住房公积金", "提取", "贷款"),
    "接诉即办": ("12345", "诉求", "热线"),
    "消防": ("消防安全", "电动车充电", "火灾隐患"),
    "养老": ("养老服务", "养老驿站", "居家养老"),
    "搬迁": ("腾退", "征收", "安置"),
    "绿化": ("绿地", "树木", "修剪"),
    "老旧小区": ("综合整治", "老旧小区改造", "改造"),
}


def expand_query(query: str) -> str:
    """把查询里的口语词扩展为同义的政策书面语（用于提升检索召回）。

    只做「加词」不做「换词」，不改变原查询语义；无命中则原样返回。
    """
    q = query or ""
    extra: list[str] = []
    for key, syns in QUERY_SYNONYMS.items():
        if key in q:
            extra.extend(s for s in syns if s not in q)
    if not extra:
        return q
    seen, uniq = set(), []
    for w in extra:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return q + " " + " ".join(uniq)


# ---- 文本级手机号脱敏（留痕/日志合规：自由文本落库前必须掩码）----

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def mask_phones(text: str) -> str:
    """把自由文本中的 11 位手机号替换为 138****8000。

    PIPL 口径：留痕/日志不得含完整手机号。用于「用户随口输入可能带手机号」的场景
    （如知识库查询日志 `kb_query_log.question`、Agent 留痕等自由文本字段）。
    只掩码、不改动其它内容；非手机号的数字串（如工单号）不受影响。
    """
    if not text:
        return ""
    return _PHONE_RE.sub(lambda m: f"{m.group()[:3]}****{m.group()[-4:]}", str(text))
