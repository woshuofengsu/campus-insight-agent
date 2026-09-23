# utils/timeutil.py — UTC 时间工具（统一替代已弃用的 datetime.utcnow）
"""`datetime.utcnow()` 自 Python 3.12 起被弃用（计划移除）。替代写法有两个坑：

1. `datetime.now(timezone.utc)` 是 **aware** 的，而库里（SQLite CURRENT_TIMESTAMP）存的是 naive 字符串，
   拿 aware 和 naive 直接比较/相减会抛 `TypeError: can't subtract offset-naive and offset-aware`；
2. 若改成 `datetime.now()` 则变成本地时间，与既有 UTC 口径不一致，会静默产生 8 小时偏差。

所以统一走这里：`utcnow()` 返回 **naive UTC**，语义与旧的 `datetime.utcnow()` 完全一致，
只去掉弃用告警（本项目 13 处调用点全部替换，见第七轮复审 P3-F）。
"""
from datetime import datetime, timedelta, timezone

__all__ = ["utcnow", "utcnow_str", "local_to_utc_naive", "utc_stamp_of_local"]


def utcnow() -> datetime:
    """当前 UTC 时间（naive，秒级精度与 SQLite 一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """当前 UTC 时间字符串（默认与 SQLite CURRENT_TIMESTAMP 同格式）。"""
    return utcnow().strftime(fmt)


def local_to_utc_naive(dt: datetime) -> datetime:
    """把**本地 naive 时间**换算成 **UTC naive 时间**（库里的时间列统一是 UTC）。

    为什么需要它：2026-09-24 实测发现 `data/db_care_proactive.run_followup` 拿本地日期
    去比库里的 UTC 日期做"今日已回访"去重，本地时间落在 0:00–8:00 时（此刻 UTC 还在前一天）
    去重必然失效。**准确地说它被静默时段掩盖了**：错配窗口(本地 0–8 点)与"21:00–8:00 不打扰"
    完全重叠，所以生产上没真发出重复回访；但传假 `now` 的测试必然失败，且静默时段一旦调整
    就会真的重复打扰居民。约定：库内时间列一律 UTC，"要不要打扰居民"按本地时间判断
    （见 `_is_quiet_hour`），两者之间必须显式换算。
    """
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    return dt - offset


def utc_stamp_of_local(local_dt: datetime) -> str:
    """本地 naive 时间 → 库内统一格式的 UTC 时间字符串。"""
    return local_to_utc_naive(local_dt).strftime("%Y-%m-%d %H:%M:%S")
