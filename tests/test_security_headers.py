# -*- coding: utf-8 -*-
"""P1-2：安全响应头套件测试。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="hdr_")
config.DB_PATH = os.path.join(_tmp, "hdr.db")

from fastapi.testclient import TestClient  # noqa: E402
import api_web  # noqa: E402


def test_security_headers():
    with TestClient(api_web.app) as c:
        r = c.get("/login")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
        assert r.headers.get("Referrer-Policy") == "same-origin"
        assert "geolocation=()" in r.headers.get("Permissions-Policy", "")
