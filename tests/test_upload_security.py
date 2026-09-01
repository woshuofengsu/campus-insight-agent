# -*- coding: utf-8 -*-
"""N1：上传路径穿越 + 扩展名白名单安全测试。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="upl_")
config.DB_PATH = os.path.join(_tmp, "upl.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import api_web  # noqa: E402

UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


@pytest.fixture(scope="module")
def client():
    with TestClient(api_web.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _seed_own_db():
    """强制本模块使用自己的临时库并全量种子——避免共享 config.DB_PATH 被其它测试文件覆盖导致无表。"""
    config.DB_PATH = os.path.join(_tmp, "upl.db")
    from data.db_core import init_db
    from data.seed import seed_all
    init_db(config.DB_PATH)
    seed_all(config.DB_PATH)


def _tok(client, role="resident"):
    r = client.post("/api/web/auth/demo", json={"role": role})
    return r.json()["data"]["token"]


def _auth(client):
    return {"Authorization": f"Bearer {_tok(client)}"}


def test_folder_traversal_rejected(client):
    """folder=../../x / 绝对路径 逃逸 uploads → 400。"""
    h = _auth(client)
    for bad in ("../../x", "../web/dist", r"C:\Windows\Temp", "..\\..\\web"):
        r = client.post(f"/api/web/upload?folder={bad}", files={"files": ("a.jpg", b"xx", "image/jpeg")},
                        headers=h)
        assert r.status_code == 400, f"folder={bad} -> {r.status_code}"


def test_disallowed_ext_rejected(client):
    """扩展名非白名单（.exe/.html/.svg）→ 拒绝且未落盘。"""
    h = _auth(client)
    for name in ("a.exe", "a.html", "a.svg", "a.php"):
        r = client.post("/api/web/upload?folder=issues",
                        files={"files": (name, b"xx", "application/octet-stream")}, headers=h)
        body = r.json()
        assert not (body.get("data") or {}).get("paths"), f"{name} 不应保存"


def test_oversize_rejected(client):
    """>5MB 文件被拒。"""
    h = _auth(client)
    big = b"a" * (5 * 1024 * 1024 + 1)
    r = client.post("/api/web/upload?folder=issues",
                    files={"files": ("a.jpg", big, "image/jpeg")}, headers=h)
    assert not (r.json().get("data") or {}).get("paths")


def test_valid_upload_ok(client):
    """白名单目录 + .jpg + 合理大小 → 成功且落在 uploads/ 内。"""
    h = _auth(client)
    r = client.post("/api/web/upload?folder=issues",
                    files={"files": ("ok.jpg", b"fakedata", "image/jpeg")}, headers=h)
    assert r.status_code == 200 and r.json()["success"]
    paths = r.json()["data"]["paths"]
    assert paths and all(p.startswith("uploads/issues/") for p in paths)
    full = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *paths[0].split("/"))
    # 写入必须仍在 uploads/ 内（realpath 校验双保险）
    assert os.path.realpath(full).startswith(os.path.realpath(UPLOAD_ROOT) + os.sep)
    try:
        os.remove(full)
    except OSError:
        pass
