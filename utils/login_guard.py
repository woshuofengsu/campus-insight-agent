# utils/login_guard.py
"""登录失败计数防护（防爆破，内存版；接口与 Redis 实现可对调）。

WS0.3：按 `username|ip` 计数，失败 ≥ 阈值后锁定窗口（默认 5 次 / 锁 5 分钟）。
线程安全（threading.Lock + 滑动窗口），单进程即可满足需求；
WS11 换 Redis 时仅替换本模块实现（check/record_fail/reset 接口不变）。
"""
import threading
import time
from collections import defaultdict, deque

_LOCK = threading.Lock()
_FAILS: dict[str, deque] = defaultdict(deque)

# 阈值与锁定时长（秒）
_MAX_FAILS = 5
_LOCK_SECONDS = 300


def _key(username: str, ip: str) -> str:
    return f"{username}|{ip}"


def check(username: str, ip: str) -> bool:
    """是否被锁定。返回 True 表示已锁，应直接拒绝登录。"""
    now = time.time()
    with _LOCK:
        dq = _FAILS.get(_key(username, ip))
        if not dq:
            return False
        # 清理过期记录（滑动窗口）
        while dq and now - dq[0] > _LOCK_SECONDS:
            dq.popleft()
        return len(dq) >= _MAX_FAILS


def record_fail(username: str, ip: str):
    """记录一次失败。返回当前累计失败次数。"""
    now = time.time()
    with _LOCK:
        dq = _FAILS[_key(username, ip)]
        while dq and now - dq[0] > _LOCK_SECONDS:
            dq.popleft()
        dq.append(now)
        return len(dq)


def reset(username: str, ip: str):
    """登录成功后清零。"""
    with _LOCK:
        _FAILS.pop(_key(username, ip), None)


def remaining(username: str, ip: str) -> int:
    """剩余可用尝试次数（供前端提示；0 表示已锁定）。"""
    if check(username, ip):
        return 0
    now = time.time()
    with _LOCK:
        dq = _FAILS.get(_key(username, ip))
        if not dq:
            return _MAX_FAILS
        while dq and now - dq[0] > _LOCK_SECONDS:
            dq.popleft()
        return max(0, _MAX_FAILS - len(dq))
