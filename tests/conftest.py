# tests/conftest.py
"""测试全局夹具：在集最早为测试环境注入 JWT/加密密钥。

api_routes/deps._load_secret 现已 secure-by-default（N2）：未配 WEB_JWT_SECRET 且未显式
DEMO_MODE=true 时拒绝启动。测试不设生产密钥，故在这里默认注入测试密钥（不影响任何断言）。
"""
import os

os.environ.setdefault("WEB_JWT_SECRET", "test-only-jwt-secret-not-for-prod")
os.environ.setdefault("CRYPTO_KEY", "test-only-crypto-key-not-for-prod")

import warnings  # noqa: E402

import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# 受控预热导入：把**第三方模块导入期**的弃用告警在此处消耗掉
#
# 背景（第八轮终审 N1 的目标是「pytest 输出零告警」）：
#   FastAPI 的 `testclient` 在**首次导入时**就会发 StarletteDeprecationWarning
#   （"Using `httpx` with `starlette.testclient` is deprecated"），这是上游依赖问题、与自有代码无关。
#   它发生在**收集期**而不是用例执行期，所以：
#     · 写进 pytest.ini 的 filterwarnings 对它有类别解析限制（基类不匹配，实测无效）；
#     · 写成本用例级 simplefilter 也来不及（告警在导入时就发了）。
#   这里在 conftest 里**先于任何测试模块**导入一次，用局部 catch_warnings 吃掉这条告警；
#   之后 test 模块再 import 时命中 sys.modules 缓存，不会再触发。
# ---------------------------------------------------------------------------
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        import starlette.testclient  # noqa: F401  （预热导入，仅为消耗导入期告警）
    except Exception:  # noqa: BLE001 — 未安装 fastapi/starlette 时不影响测试
        pass


@pytest.fixture(autouse=True)
def _reset_runtime_guards():
    """每个测试前清空运行时"每用户限流"桶，避免跨测试累计导致偶发 429（N5 限流对测试隔离）。"""
    import api_routes.agent as _agent_mod
    _agent_mod._chat_rate.clear()
    yield
    _agent_mod._chat_rate.clear()


def _purge_stale_test_dbs() -> list[str]:
    """删除 tests/ 下遗留的固定名临时库（含 -wal/-shm）。返回被删文件名。

    为什么需要：多数测试文件用**固定名**临时库（如 `_test_dispatch_dept.db`），
    只清理主文件、不清理 `-wal/-shm`，Windows 下还可能因为句柄占用删不掉；
    残留会让 `create_user` 抛 `Username 'xxx' already taken`，
    表现为「单独跑通过、全量跑报错」的偶发失败（实测 `test_dispatch` 就是这样挂的）。
    在会话开始前统一清一次，用一处兜住这一整类问题。
    """
    import time

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    removed: list[str] = []
    for root, _dirs, files in os.walk(tests_dir):
        for fn in files:
            if not fn.startswith("_test_"):
                continue
            p = os.path.join(root, fn)
            for attempt in range(4):
                try:
                    os.unlink(p)
                    removed.append(os.path.relpath(p, tests_dir).replace("\\", "/"))
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(0.15 * (attempt + 1))
    return removed


def pytest_sessionstart(session):  # noqa: ARG001
    """会话开始前清理上一次运行残留的测试库（幂等；失败不阻塞测试）。"""
    try:
        _purge_stale_test_dbs()
    except Exception:  # noqa: BLE001
        pass
