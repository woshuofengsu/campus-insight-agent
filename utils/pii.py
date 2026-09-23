# utils/pii.py
"""自由文本 PII 脱敏 —— 居民手写在正文里的手机号/身份证不允许原样落库。

为什么需要它（已知边界第 6 条）：`reporter_phone` 这类**结构化字段**早就做了 AES 加密 +
列级脱敏，但居民完全可能在工单描述里自己写"我电话 13800138000"、在提案或健康咨询里
写身份证号。这类**自由文本**过去是原样入库的，等于绕过了一整套脱敏设计。

口径（与项目既有约定一致）：
- 手机号：与 `data/db_repair._mask_phone` 同格式，`138****8000`；
- 身份证：保留前 6 位地区码与后 4 位，中间打星，`110113********4512`；
- **只在自由文本里做**，结构化字段（`reporter_phone` 等）仍走加密列，绝不用本模块替代；
- 命中了要**打 warning**（本项目禁止静默行为），但**日志里只记数量，绝不记原文**。

不做的事：不做「姓名/地址」这类无法可靠识别的实体抽取——误伤比漏检更难解释。
"""
import logging
import re

_log = logging.getLogger(__name__)

# 中国大陆手机号：1 开头、第二位 3-9、共 11 位；前后不能再挨着数字（避免切掉长数字串中间一段）
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 18 位身份证：17 位数字 + 校验位（数字或 X）；前后不挨数字
_ID_RE = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")
# 已被脱敏过的手机号形态（138****8000），避免二次处理把星号当数字
_ALREADY_MASKED_RE = re.compile(r"1[3-9]\d\*{2,}\d{4}")


def mask_phone(phone: str) -> str:
    """手机号脱敏，格式与 data/db_repair._mask_phone 保持一致。"""
    if not phone or len(phone) < 7:
        return phone or ""
    return f"{phone[:3]}****{phone[-4:]}"


def scrub_text(text: str) -> tuple[str, int]:
    """把自由文本里的手机号/身份证打码。

    返回 `(处理后文本, 命中数量)`。非字符串（None/数字）原样返回、命中 0。
    本函数是纯函数、无副作用；是否记日志由调用方决定（避免日志里出现原文）。
    """
    if not isinstance(text, str) or not text:
        return text, 0

    hits = 0
    # 先记下已脱敏片段，处理完再还原，避免对星号形态做二次替换
    placeholders: list[str] = []

    def _stash(match: re.Match) -> str:
        placeholders.append(match.group(0))
        return f"\x00{len(placeholders) - 1}\x00"

    protected = _ALREADY_MASKED_RE.sub(_stash, text)

    def _mask_phone_hit(match: re.Match) -> str:
        nonlocal hits
        hits += 1
        return mask_phone(match.group(0))

    def _mask_id_hit(match: re.Match) -> str:
        nonlocal hits
        hits += 1
        return f"{match.group(1)}********{match.group(2)}"

    out = _PHONE_RE.sub(_mask_phone_hit, protected)
    out = _ID_RE.sub(_mask_id_hit, out)

    for i, original in enumerate(placeholders):
        out = out.replace(f"\x00{i}\x00", original)
    return out, hits


def scrub_field(value: str, field: str, logger: logging.Logger | None = None) -> str:
    """对单个字段做脱敏，命中就打 warning（只记字段名与数量，不记原文）。"""
    cleaned, hits = scrub_text(value)
    if hits:
        (logger or _log).warning(
            "自由文本 PII 已脱敏：field=%s hits=%d（原文不入库、不入日志）", field, hits
        )
    return cleaned
