# utils/timeutil.py — UTC 时间工具（统一替代已弃用的 datetime.utcnow）
"""`datetime.utcnow()` 自 Python 3.12 起被弃用（计划移除）。替代写法有两个坑：

1. `datetime.now(timezone.utc)` 是 **aware** 的，而库里（SQLite CURRENT_TIMESTAMP）存的是 naive 字符串，
   拿 aware 和 naive 直接比较/相减会抛 `TypeError: can't subtract offset-naive and offset-aware`；
2. 若改成 `datetime.now()` 则变成本地时间，与既有 UTC 口径不一致，会静默产生 8 小时偏差。

所以统一走这里：`utcnow()` 返回 **naive UTC**，语义与旧的 `datetime.utcnow()` 完全一致，
只去掉弃用告警（本项目 13 处调用点全部替换，见第七轮复审 P3-F）。
"""
from datetime import datetime, timezone

__all__ = ["utcnow", "utcnow_str"]


def utcnow() -> datetime:
    """当前 UTC 时间（naive，秒级精度与 SQLite 一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """当前 UTC 时间字符串（默认与 SQLite CURRENT_TIMESTAMP 同格式）。"""
    return utcnow().strftime(fmt)
