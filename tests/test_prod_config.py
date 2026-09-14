# -*- coding: utf-8 -*-
"""WS0.2：生产（DEMO_MODE=false）配置——交互式 API 文档关闭、CORS 白名单化；
第十轮复审追加：**加密密钥 fail-closed**（生产姿态下 CRYPTO_KEY 缺失/占位 → 拒绝启动）。

在子进程以全新解释器加载 api_web（此时 DEMO_MODE=false 生效），
避免与测试主进程已 import 的（DEMO_MODE=true）默认 App 冲突。
"""
import os
import subprocess
import sys
import tempfile

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCRIPT = r"""
import os, tempfile
import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="prod_"), "prod.db")
import api_web
app = api_web.app
# 1) 文档/OpenAPI 关闭
assert app.docs_url is None, app.docs_url
assert app.openapi_url is None, app.openapi_url
assert app.redoc_url is None, app.redoc_url
# 2) CORS 白名单化
cors = [m for m in app.user_middleware if getattr(m, 'cls', None) is not None
        and 'CORS' in getattr(m.cls, '__name__', '')]
assert cors, "未找到 CORS 中间件"
opts = cors[0].kwargs
assert opts.get('allow_origins') == ['http://allowed.example'], opts.get('allow_origins')
assert opts.get('allow_credentials') is False
print("PROD_CONFIG_OK")
"""


def test_prod_config_disables_docs_and_whitelists_cors():
    env = dict(os.environ)
    env["DEMO_MODE"] = "false"
    env["WEB_JWT_SECRET"] = "test-prod-secret-0123456789"
    env["CORS_ORIGINS"] = "http://allowed.example"
    p = subprocess.run([sys.executable, "-c", _SCRIPT],
                       cwd=_PROJ, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert "PROD_CONFIG_OK" in (p.stdout or ""), f"stdout={p.stdout} stderr={p.stderr}\nreturn={p.returncode}"


# ---------------------------------------------------------------------------
# 加密密钥 fail-closed（本次修复）：生产姿态下绝不允许用缺失/公开占位密钥加密手机号
# ---------------------------------------------------------------------------

_KEY_SCRIPT = r"""
import os, tempfile
import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="key_"), "k.db")
from utils.crypto import Crypto
c = Crypto()
token = c.encrypt("13800000000")
assert token.startswith("g1$"), token[:8]
assert c.decrypt(token) == "13800000000"
print("CRYPTO_OK")
"""


def _run_key_script(env_overrides: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("CRYPTO_KEY", "DEMO_MODE", "WEB_JWT_SECRET"):
        env.pop(k, None)
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", _KEY_SCRIPT],
                          cwd=_PROJ, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _out(p: subprocess.CompletedProcess) -> str:
    """合并 stdout/stderr（显式 UTF-8 解码，避免中文报错被 GBK 解码失败导致属性为 None）。"""
    return (p.stdout or "") + (p.stderr or "")


def test_prod_posture_refuses_default_crypto_key():
    """DEMO_MODE=false 且 CRYPTO_KEY 缺失 → 必须拒绝（此前只打 warning 然后照常加密）。"""
    p = _run_key_script({"DEMO_MODE": "false", "WEB_JWT_SECRET": "s" * 32})
    assert p.returncode != 0, f"生产姿态下缺 CRYPTO_KEY 竟然成功加密了：{_out(p)}"
    assert "CRYPTO_KEY" in _out(p), _out(p)[-400:]
    assert "CRYPTO_OK" not in (p.stdout or "")


def test_prod_posture_refuses_repo_placeholder_crypto_key():
    """模板里公开的占位密钥（.env.demo 的 demo-please-set-a-crypto-key）在生产姿态等同没配。"""
    p = _run_key_script({"DEMO_MODE": "false", "WEB_JWT_SECRET": "s" * 32,
                         "CRYPTO_KEY": "demo-please-set-a-crypto-key"})
    assert p.returncode != 0, f"占位密钥竟然被采用了：{_out(p)}"
    assert "CRYPTO_OK" not in (p.stdout or "")


def test_prod_posture_accepts_strong_crypto_key():
    """生产姿态 + 自定义强密钥 → 正常加解密（防止把 fail-closed 写成一律拒绝）。"""
    p = _run_key_script({"DEMO_MODE": "false", "WEB_JWT_SECRET": "s" * 32,
                         "CRYPTO_KEY": "Zx9" + "k" * 45})
    assert "CRYPTO_OK" in (p.stdout or ""), _out(p)


def test_demo_posture_still_works_without_key():
    """演示姿态（DEMO_MODE=true）不破坏本机/演示可用性：缺密钥仍能加解密（但会告警）。"""
    p = _run_key_script({"DEMO_MODE": "true", "WEB_JWT_SECRET": "s" * 32})
    assert "CRYPTO_OK" in (p.stdout or ""), _out(p)
