# tests/conftest.py
"""测试全局夹具：在集最早为测试环境注入 JWT/加密密钥。

api_routes/deps._load_secret 现已 secure-by-default（N2）：未配 WEB_JWT_SECRET 且未显式
DEMO_MODE=true 时拒绝启动。测试不设生产密钥，故在这里默认注入测试密钥（不影响任何断言）。
"""
import os

os.environ.setdefault("WEB_JWT_SECRET", "test-only-jwt-secret-not-for-prod")
os.environ.setdefault("CRYPTO_KEY", "test-only-crypto-key-not-for-prod")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_runtime_guards():
    """每个测试前清空运行时"每用户限流"桶，避免跨测试累计导致偶发 429（N5 限流对测试隔离）。"""
    import api_routes.agent as _agent_mod
    _agent_mod._chat_rate.clear()
    yield
    _agent_mod._chat_rate.clear()
