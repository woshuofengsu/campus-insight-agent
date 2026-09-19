# -*- coding: utf-8 -*-
"""项目完整性门禁（终局核验沉淀）。

## 为什么要有这个文件
终局核验时做了四类"跨文件、平时没人测"的检查，结果都是干净的——但**它们每一项在本项目历史上都真的出过问题**，
所以不能让它们只停留在一次性人工审查里：

| 检查 | 历史上真实踩过的坑 |
|---|---|
| 受控文本文件都是合法 UTF-8 | 曾用 PowerShell `Add-Content` 把 `docs/mobile-deploy.md` 写成 GBK，文件损坏且当时误判为"没问题" |
| Markdown 相对链接可解析 | 删掉 `扫码体验.html`／`演示旁白.md` 后，多份文档仍指向它们；两份旁白稿口径还互相矛盾 |
| 前端调用的 API 路径后端真的存在 | 前端路径与后端路由表分离，删/改路由不会有任何编译期信号——只会在页面上变成 404 |
| 不误提交 .env / 数据库 / 临时文件 | `.env` 里有真实 LLM 与加密密钥 |

> 这些都是"跑测试、跑审计都全绿，却会在评委/用户面前直接暴露"的类别，最适合做成门禁。

注意：**历史文档**（`docs/review/**`、`docs/competition/日报-*`、`CHANGELOG`、`docs/competition/创意说明书.md` 等）
允许保留当时的引用与措辞，因此链接检查只针对"当前状态文档 + 提交件所在目录"，历史目录不参与。
"""
import io
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BINARY_EXT = (".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".pdf",
              ".zip", ".webm", ".mp4", ".db", ".xlsx", ".docx",
              # Office 格式同样是 ZIP 二进制容器：2026-09-15 把路演 PPT 入库时，本门禁
              # 曾把 .pptx 误判为"非 UTF-8 文本文件"——二进制必须显式排除。
              ".pptx", ".ppt", ".doc", ".xls", ".7z", ".rar", ".gz")

# 允许保留历史引用的目录（历史快照，不参与链接检查）
HISTORY_PREFIXES = ("docs/review/", "docs/superpowers/", "docs/TECHNICAL.md",
                    "docs/competition/日报-", "docs/competition/迁移日志-",
                    "CHANGELOG.md", "HANDOFF.md", "docs/competition/创意说明书.md")


def _tracked() -> list[str]:
    """受版本控制的文件（core.quotepath=false 以正确处理中文文件名）。"""
    out = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "-z"],
                         capture_output=True, cwd=ROOT).stdout.decode("utf-8")
    return [f for f in out.split("\x00") if f.strip()]


def test_tracked_text_files_are_valid_utf8():
    """所有受控文本文件必须是合法 UTF-8（防止 GBK 混入导致文件损坏）。"""
    bad = []
    checked = 0
    for rel in _tracked():
        if os.path.splitext(rel)[1].lower() in BINARY_EXT:
            continue
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        try:
            with io.open(p, encoding="utf-8") as fh:
                fh.read()
            checked += 1
        except UnicodeDecodeError as e:
            bad.append(f"{rel}（首个非法字节位置 {e.start}）")
    assert checked > 300, f"受控文本文件只有 {checked} 个，检查逻辑可能失效"
    assert not bad, "以下文件不是合法 UTF-8（大概率被 GBK 工具写坏）：\n  " + "\n  ".join(bad)


def test_markdown_relative_links_resolve():
    """当前状态文档里的相对链接必须指向真实存在的文件（历史快照目录除外）。"""
    dangling = []
    scanned = 0
    for rel in _tracked():
        if not rel.endswith(".md") or rel.startswith(HISTORY_PREFIXES):
            continue
        scanned += 1
        txt = io.open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"\[([^\]]{0,80})\]\(([^)#\s]+?)\)", txt):
            target = m.group(2)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            full = os.path.normpath(os.path.join(ROOT, os.path.dirname(rel), target))
            if not os.path.exists(full):
                dangling.append(f"{rel} → {target}")
    assert scanned > 20, f"只扫描到 {scanned} 份 Markdown，检查逻辑可能失效"
    assert not dangling, "以下文档链接指向不存在的文件：\n  " + "\n  ".join(dangling)


def test_frontend_api_paths_exist_in_backend():
    """前端 `web/src/api/index.js` 调用的每个路径，后端必须真的有（否则页面上是 404）。"""
    sys.path.insert(0, ROOT)
    import config
    tmp = os.path.join(tempfile.mkdtemp(prefix="contract_"), "c.db")
    config.DB_PATH = tmp                      # 必须在 import api_web 之前指到临时库
    import api_web

    schema = api_web.app.openapi()
    backend = {re.sub(r"\{[^}]+\}", "*", p) for p in schema.get("paths", {})}
    assert len(backend) > 60, f"后端 OpenAPI 只解析出 {len(backend)} 条路径，检查逻辑可能失效"

    src = io.open(os.path.join(ROOT, "web", "src", "api", "index.js"), encoding="utf-8").read()
    calls = re.findall(r"api\.(?:get|post|put|delete|patch)\(\s*[`'\"]([^`'\"]+)", src)
    assert len(calls) > 50, f"前端只解析出 {len(calls)} 个调用，检查逻辑可能失效"

    prefix = "/api/web"                        # 与 api/index.js 的 baseURL 一致
    missing = []
    for c in calls:
        norm = re.sub(r"\$\{[^}]+\}", "*", c.split("?")[0])
        norm = re.sub(r"\{[^}]+\}", "*", norm).rstrip("/")
        full = prefix + norm
        if full not in backend and not any(b.startswith(full) for b in backend):
            missing.append(c)
    assert not missing, f"前端调用了后端不存在的路径：{missing}"


def test_secrets_and_artifacts_not_committed():
    """`.env` / 数据库 / 覆盖率 / 临时文件不得进入版本控制。"""
    tracked = _tracked()
    banned = [f for f in tracked
              if os.path.basename(f) == ".env"
              or f.endswith((".db", ".db.bak", ".coverage"))
              or re.search(r"(tmp_.*\.py$|\.tmp$|\.orig$|~$)", f)]
    assert not banned, f"以下文件不应被提交：{banned}"
    # .env.example 必须在（否则别人无法配置），且不得含真实密钥形态
    example = os.path.join(ROOT, ".env.example")
    if os.path.exists(example):
        txt = io.open(example, encoding="utf-8", errors="replace").read()
        leaked = re.findall(r"(sk-[A-Za-z0-9]{20,})", txt)
        assert not leaked, f".env.example 里出现真实密钥形态：{leaked[:1]}"
