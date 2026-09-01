# api_routes/upload.py
"""上传路由模块（从 api_web.py 拆出，P2-04 / P1-F2-01）。"""
from fastapi import APIRouter, Request

from api_routes.deps import _fail, _ok

router = APIRouter(tags=["upload"])


class _FakeUploadFile:
    """把 multipart 上传对象适配成 utils/uploads 需要的接口（name/size/getbuffer）。

    getbuffer() 返回 bytes（与 Streamlit UploadedFile.getbuffer() 的 memoryview 等价），
    utils/uploads.save_uploaded_files 用 out.write(f.getbuffer()) 落盘。
    """

    def __init__(self, name, size, data):
        self.name = name
        self.size = size
        self._data = data

    def getbuffer(self):
        return self._data


@router.post("/api/web/upload")
async def upload_files(request: Request, folder: str = "web"):
    """上传附件（图片/PDF，≤5MB）。multipart/form-data，字段名 files。"""
    from utils.uploads import save_uploaded_files, MAX_FILE_SIZE
    try:
        form = await request.form()
        files = form.getlist("files")
        objs = []
        for f in files:
            # N1：分块读取，累计超 5MB 立即停止，避免先全读进内存再判大小
            data = b""
            while True:
                chunk = await f.read(64 * 1024)
                if not chunk:
                    break
                data += chunk
                if len(data) > MAX_FILE_SIZE:
                    break
            objs.append(_FakeUploadFile(f.filename or "x.jpg", len(data), data))
        if not objs:
            return _fail(1001, "未选择文件")
        saved, errs = save_uploaded_files(objs, folder=folder, max_count=5)
        if errs:
            return _fail(2001, "；".join(errs))
        return _ok({"paths": saved}, "上传成功")
    except ValueError as e:  # N1：非法目录等 参数错误 → 400
        return _fail(1003, str(e))
    except Exception as e:  # noqa: BLE001
        return _fail(1001, "上传失败，请重试")
