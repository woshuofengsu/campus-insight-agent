# data/_vitals_logic.py
"""老年健康记录的**纯逻辑**：分级与文案（血压 / 血糖）。

为什么单独一个文件（AGENTS.md D12）：分级规则要能被单测直接打，
而阈值与文案是本项目**最容易越界**的地方——老年健康建议一旦写成"你是高血压"就变成诊断。

三条硬约定：
1. **只给提醒级分级**（normal / attention / alert），不给任何医学结论；
2. 文案固定为"建议联系社区医生或家属复核，必要时就医"这一档，
   **禁止**出现 确诊 / 您是 / 患了 / 得了 / 诊断为 等句式（测试里用正则拦，口径对齐 `agent/verifier.py`）；
3. 阈值是**提醒阈值**，不是诊断标准——写死在这里并带注释，改阈值必须同时改测试。
"""
from __future__ import annotations

import re

# 数值解析：**不用异常做流程控制**——校验失败是正常路径，不是异常；
# 项目门禁 `tests/test_silent_exceptions.py` 也会把"写路径里 except 后返回默认值"记成 HIGH。
_NUM_RE = re.compile(r"^\d{1,3}(\.\d{1,2})?$")


def to_number(value) -> float | None:
    """把输入转成数字；不是数字/为空返回 None（调用方按「没填」处理，绝不猜）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not _NUM_RE.match(text):
        return None
    return float(text)

# 血压提醒阈值（mmHg）。注意：这是"提醒"口径，不是诊断标准。
BP_SYS_ALERT = 180      # 收缩压 ≥180 → alert（明显偏高，建议尽快联系医生）
BP_DIA_ALERT = 110      # 舒张压 ≥110 → alert
BP_SYS_HIGH = 140       # 收缩压 ≥140 → attention
BP_DIA_HIGH = 90        # 舒张压 ≥90 → attention
BP_SYS_LOW = 90         # 收缩压 <90 → attention（偏低）
BP_DIA_LOW = 60         # 舒张压 <60 → attention

# 血糖提醒阈值（mmol/L）
GLU_FASTING_HIGH = 7.0      # 空腹 ≥7.0 → attention
GLU_POST_HIGH = 11.1        # 餐后 ≥11.1 → attention
GLU_LOW = 3.9               # <3.9 → alert（低血糖更急）

LEVELS = ("normal", "attention", "alert")

_HINT = {
    "normal": "数值在常见范围内，继续保持记录就好。",
    "attention": "数值偏高或偏低，建议联系社区医生或家属复核，必要时就医。",
    "alert": "数值明显偏离常见范围，建议尽快联系社区医生或家属，必要时立即就医。",
}


def hint_of(level: str) -> str:
    """分级 → 固定文案（唯一出口，避免各页自己写文案写出诊断口径）。"""
    return _HINT.get(level, _HINT["normal"])


def classify_bp(sys_: int | float | None, dia: int | float | None) -> tuple[str, str]:
    """血压分级：返回 `(level, hint)`。缺值/非数字按 normal 处理（不猜）。"""
    s = to_number(sys_)
    d = to_number(dia)
    if s is None and d is None:
        return "normal", hint_of("normal")

    if (s is not None and s >= BP_SYS_ALERT) or (d is not None and d >= BP_DIA_ALERT):
        level = "alert"
    elif ((s is not None and s >= BP_SYS_HIGH) or (d is not None and d >= BP_DIA_HIGH)
          or (s is not None and s < BP_SYS_LOW) or (d is not None and d < BP_DIA_LOW)):
        level = "attention"
    else:
        level = "normal"
    return level, hint_of(level)


def classify_glucose(value: float | None, when: str = "") -> tuple[str, str]:
    """血糖分级：`when` 取 fasting（空腹）/ postprandial（餐后）/ 其它视为随机。"""
    v = to_number(value)
    if v is None:
        return "normal", hint_of("normal")

    if v < GLU_LOW:
        level = "alert"
    elif when == "fasting" and v >= GLU_FASTING_HIGH:
        level = "attention"
    elif when == "postprandial" and v >= GLU_POST_HIGH:
        level = "attention"
    else:
        level = "normal"
    return level, hint_of(level)


def classify(kind: str, sys_=None, dia=None, glucose=None, when: str = "") -> tuple[str, str]:
    """统一入口：按 kind 分派。未知 kind 返回 normal（宁可不说，也不乱说）。"""
    if kind == "bp":
        return classify_bp(sys_, dia)
    if kind == "glucose":
        return classify_glucose(glucose, when)
    return "normal", hint_of("normal")


def trend_label(values: list[float]) -> str:
    """给网格员/家属看的一句话趋势（纯描述，不做预测）。"""
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 2:
        return "记录不足，暂时看不出趋势"
    if vals[-1] > vals[0] * 1.1:
        return "近几次比之前偏高"
    if vals[-1] < vals[0] * 0.9:
        return "近几次比之前偏低"
    return "近几次比较平稳"
