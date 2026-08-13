# -*- coding: utf-8 -*-
"""生成「一键安装包」zip。

用法: python scripts/make_installer.py
输出: dist/CommunityInsight_社区先知_一键安装包.zip

排除规则：.git / 虚拟环境 / 数据库 / 真实密钥 / 文档 / 测试 / Docker 等，
文本文件统一转 CRLF，二进制（图片）原样复制。
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "dist")
ZIP_NAME = "CommunityInsight_社区先知_一键安装包.zip"

# 目录级排除（相对 ROOT 的目录名）
EXCLUDE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", "venv", ".venv",
    "dist", "build", ".github", ".devcontainer", "docs", "tests", "scripts",
}
# 文件级排除（相对 ROOT 的文件名）
EXCLUDE_FILES = {
    ".env", "ngrok_backup.bat", "Dockerfile", "docker-compose.yml",
    "deploy.sh", ".dockerignore", "PRODUCT.md",
}
# 扩展名级排除
EXCLUDE_EXTS = {".db", ".pyc", ".pyo", ".log"}
# 二进制扩展名（不转 CRLF，原样写入）
BINARY_EXTS = {".webp", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".zip"}


def to_crlf(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    return text.encode("utf-8")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, ZIP_NAME)
    if os.path.exists(out_path):
        os.remove(out_path)

    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # 剪枝：跳过被排除的目录
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn in EXCLUDE_FILES:
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext in EXCLUDE_EXTS:
                    continue
                full = os.path.join(dirpath, fn)
                arcname = os.path.relpath(full, ROOT).replace("\\", "/")
                if ext in BINARY_EXTS:
                    zf.write(full, arcname)
                else:
                    with open(full, "rb") as f:
                        data = f.read()
                    zf.writestr(arcname, to_crlf(data))
                count += 1

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print("Done:", out_path)
    print("files:", count, " size: %.2f MB" % size_mb)


if __name__ == "__main__":
    main()
