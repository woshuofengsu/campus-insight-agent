# utils/uploads.py
"""上传文件本地存储 — 存到 uploads/ 目录，返回相对路径。

说明：本地/演示环境有效；Streamlit Cloud 文件系统临时（重启/重新部署会重置），
如需上云持久化，后续接入 S3/OSS 替换本模块即可（对外接口不变）。
"""
import os
import uuid

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPLOAD_DIR = os.path.join(_BASE, "uploads")

# spec：单张附件 ≤5MB（报修/提案/通知/健康/用药统一口径）
MAX_FILE_SIZE = 5 * 1024 * 1024

# N1：文件夹白名单 + 扩展名白名单（防路径穿越 / 防上传非图片PDF）
_ALLOWED_FOLDER = {"issues", "proposals", "notices", "consults", "meds", "web"}
_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".pdf"}


def _folder_path(folder: str) -> tuple[str, str]:
    """校验并返回 (规范化目录绝对路径, 安全目录名)；非法即抛 ValueError（fail-closed）。

    - 白名单内：直接使用。
    - 白名单外：若带路径特征（绝对路径 / `..` / 分隔符）视为穿越 → 抛错（400）；
      否则为"干净但未识别的目录名"，保守降级到 issues（不落任意目录）。
    - realpath 消解 `../` 与符号链接后，必须仍在 uploads 根内（双保险）。
    """
    safe = folder
    if folder not in _ALLOWED_FOLDER:
        if os.path.isabs(folder) or ".." in folder or "/" in folder or "\\" in folder:
            raise ValueError("不合法的上传目录")
        safe = "issues"
    root = os.path.realpath(_UPLOAD_DIR)
    p = os.path.realpath(os.path.join(root, safe))
    if p != root and not p.startswith(root + os.sep):
        raise ValueError("不合法的上传目录")
    os.makedirs(p, exist_ok=True)
    return p, safe


def _is_allowed_ext(ext: str) -> bool:
    return ext in _ALLOWED_EXT


def save_uploaded_files(files, folder: str = "issues", max_count: int = 3) -> list[str]:
    """保存一批上传文件。返回相对路径列表（如 uploads/issues/xxx.jpg）。

    files: st.file_uploader 返回的对象列表（含 None）。
    folder: 子目录（issues / proposals / notices / consults / meds）。
    单文件超过 5MB 跳过并记入返回值中的错误列表——用 (saved, errors) 双返回。
    """
    saved: list[str] = []
    errors: list[str] = []
    folder_dir, safe_folder = _folder_path(folder)   # 用原始值校验，穿越即抛 400
    for f in files[:max_count]:
        if f is None:
            continue
        size = 0
        try:
            size = f.size or 0
        except Exception:
            pass
        if size > MAX_FILE_SIZE:
            errors.append(f"{f.name or '文件'} 超过 5MB，已跳过")
            continue
        ext = os.path.splitext(f.name or "")[1].lower() or ".jpg"
        if not _is_allowed_ext(ext):
            errors.append(f"{f.name or '文件'} 类型不允许（仅支持图片/PDF）")
            continue
        fname = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(folder_dir, fname)
        with open(path, "wb") as out:
            out.write(f.getbuffer())
        saved.append(f"uploads/{safe_folder}/{fname}")
    return saved, errors


def delete_upload(rel_path: str | None) -> None:
    """删除一个上传文件（相对路径）。"""
    if not rel_path:
        return
    full = os.path.normpath(os.path.join(_BASE, rel_path))
    if full.startswith(os.path.normpath(_UPLOAD_DIR)) and os.path.exists(full):
        try:
            os.remove(full)
        except Exception:
            pass


def resolve_path(rel_path: str | None) -> str | None:
    """把相对路径转成绝对路径（用于 st.image 展示），校验在 uploads 目录内。"""
    if not rel_path:
        return None
    full = os.path.normpath(os.path.join(_BASE, rel_path))
    if full.startswith(os.path.normpath(_UPLOAD_DIR)) and os.path.exists(full):
        return full
    return None
