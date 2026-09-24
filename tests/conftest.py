# tests/conftest.py
"""测试全局夹具：在集最早为测试环境注入 JWT/加密密钥。

api_routes/deps._load_secret 现已 secure-by-default（N2）：未配 WEB_JWT_SECRET 且未显式
DEMO_MODE=true 时拒绝启动。测试不设生产密钥，故在这里默认注入测试密钥（不影响任何断言）。
"""
import os

os.environ.setdefault("WEB_JWT_SECRET", "test-only-jwt-secret-not-for-prod")
os.environ.setdefault("CRYPTO_KEY", "test-only-crypto-key-not-for-prod")

# 测试姿态钉死（AGENTS.md 硬规则：「测试必须姿态无关」）：
# 本机 `.env` 四个 LLM 开关是**全开**的；不钉住的话，没显式设置姿态的用例会**真打 DeepSeek**——
# 既慢（实测全量由 ~3:30 变成 ~8:00）、又花钱，还会因网络抖动造成假失败。
# 需要 LLM 的用例必须自己 `monkeypatch.setenv("LLM_XXX", "1")`（写法见 tests/test_agent.py）。
for _k in ("LLM_ORCHESTRATION", "LLM_NEGOTIATION", "POLICY_LLM_RAG", "RECEPTION_LLM_FALLBACK"):
    os.environ.setdefault(_k, "0")

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
    """每个测试前复位运行时全局状态，避免跨测试累计导致偶发失败。

    ① 每用户限流桶（N5）：不清会跨测试累计 → 偶发 429；
    ② **LLM 熔断器**（2026-09-24 补）：`agent.llm_client._FAIL` 是模块级状态，
       前面的用例把真实网络打失败后熔断打开（连续 3 次失败即锁定窗口），
       后面的用例即使 mock 好了也会被"快速失败"短路 → 表现为"单跑过、全量挂"。
       实测：`tests/test_agent.py::test_llm_polish_pass_uses_llm` 就是这么红的。
    """
    import api_routes.agent as _agent_mod
    from agent.llm_client import reset_circuit
    _agent_mod._chat_rate.clear()
    reset_circuit()
    yield
    _agent_mod._chat_rate.clear()
    reset_circuit()


@pytest.fixture(autouse=True, scope="module")
def _isolate_db_path():
    """模块级兜底：测试文件动了全局 DB 状态后，模块结束时把整套状态复位。

    为什么需要（2026-09-14 实测踩到，且**三连跑必现、单跑/两两全过**）：
    `data/db_core._DB_PATH` 是模块级全局，个别测试文件会 `init_db(自己的临时库)` 再在
    teardown 删库；而 `api_web._ensure_db()` 用 `config.DB_PATH` 做"每个库只初始化一次"的
    守卫（`_db_path_seeded`）—— 它看到路径没变就**直接早返回**，于是下一个测试文件拿到的
    是一个指向"已删除文件"或空字符串的全局状态：
      · 指向已删除路径 → sqlite 就地新建空库 → `no such table: user_profile`；
      · 被写回空串 → `RuntimeError: Database not initialized`。

    复位三件事：① `_DB_PATH`/`config.DB_PATH` 回滚到进入本模块前的值（**空值不写回**，
    否则会把"未初始化"状态传染给下一个文件）；② 清掉 `api_web._db_path_seeded`，
    让下一次进入 TestClient 时**重新建表 + 幂等灌种子**（种子本身幂等）。
    """
    import config
    from data import db_core

    saved_cfg = getattr(config, "DB_PATH", None)
    saved_core = getattr(db_core, "_DB_PATH", None)
    yield
    try:
        if saved_cfg:
            config.DB_PATH = saved_cfg
        # 空值不写回：宁可让它回落到 config.DB_PATH，也不要把"未初始化"状态传给下一个文件
        db_core._DB_PATH = saved_core or saved_cfg or db_core._DB_PATH
        try:
            import api_web
            api_web._db_path_seeded = None      # 强制下次进 App 时重新 ensure_db
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001  兜底失败不影响测试结果
        pass


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
