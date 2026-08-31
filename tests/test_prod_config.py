# -*- coding: utf-8 -*-
"""WS0.2：生产（DEMO_MODE=false）配置——交互式 API 文档关闭、CORS 白名单化。

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
                       cwd=_PROJ, env=env, capture_output=True, text=True)
    assert "PROD_CONFIG_OK" in p.stdout, f"stdout={p.stdout} stderr={p.stderr}\nreturn={p.returncode}"
