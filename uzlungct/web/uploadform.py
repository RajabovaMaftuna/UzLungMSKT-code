"""Ko'p fayllik yuklash (DICOM seriya papkasi) uchun forma o'qish.

Starlette standarti: bir so'rovda ko'pi bilan 1000 fayl va 1000 maydon (max_files/max_fields). Haqiqiy KT seriyalari
(DICOMDIR bilan eksport qilingan papkalar) 1000 dan ko'p fayldan iborat bo'ladi — shu sababli FastAPI'ning
`files: list[UploadFile] = File(...)` parametri bunday papkada 400 qaytarardi. Bu yerda chegara aniq belgilanadi."""
from __future__ import annotations

MAX_UPLOAD_FILES = 20_000


class UploadFormError(ValueError):
    """Forma noto'g'ri yoki chegaradan katta (kod: bad_upload | missing_field)."""


async def read_upload_form(request, max_files: int = MAX_UPLOAD_FILES):
    """Qaytaradi: (files, ckpt, patient_id). files — filename va read() ga ega obyektlar ro'yxati."""
    try:
        form = await request.form(max_files=max_files, max_fields=max_files + 50)
    except Exception as e:                                     # MultiPartException / HTTPException(400) / noto'g'ri content-type
        raise UploadFormError("bad_upload") from e
    files = [v for v in form.getlist("files") if hasattr(v, "filename") and hasattr(v, "read")]
    ckpt = form.get("ckpt")
    pid = form.get("patient_id") or ""
    if not files or not isinstance(ckpt, str) or not isinstance(pid, str):
        raise UploadFormError("missing_field")
    return files, ckpt, pid
