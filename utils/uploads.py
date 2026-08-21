# utils/uploads.py
"""上传文件本地存储 — 存到 uploads/ 目录，返回相对路径。

说明：本地/演示环境有效；Streamlit Cloud 文件系统临时（重启/重新部署会重置），
如需上云持久化，后续接入 S3/OSS 替换本模块即可（对外接口不变）。
"""
import os
import uuid

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPLOAD_DIR = os.path.join(_BASE, "uploads")


def _folder_path(folder: str) -> str:
    p = os.path.join(_UPLOAD_DIR, folder)
    os.makedirs(p, exist_ok=True)
    return p


def save_uploaded_files(files, folder: str = "issues", max_count: int = 3) -> list[str]:
    """保存一批上传文件。返回相对路径列表（如 uploads/issues/xxx.jpg）。

    files: st.file_uploader 返回的对象列表（含 None）。
    folder: 子目录（issues / proposals / notices / consults / meds）。
    """
    saved: list[str] = []
    folder_dir = _folder_path(folder)
    for f in files[:max_count]:
        if f is None:
            continue
        ext = os.path.splitext(f.name or "")[1].lower() or ".jpg"
        fname = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(folder_dir, fname)
        with open(path, "wb") as out:
            out.write(f.getbuffer())
        saved.append(f"uploads/{folder}/{fname}")
    return saved


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
