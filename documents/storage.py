"""Upload validation, private storage and short-lived signed download links."""
import hashlib
import zipfile
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.urls import reverse

ALLOWED = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _sniff(head, ext, fileobj):
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image/heic"
    if head.startswith(b"PK\x03\x04"):
        try:
            fileobj.seek(0)
            with zipfile.ZipFile(fileobj) as zf:
                names = set(zf.namelist())
            if "word/document.xml" in names:
                return ALLOWED[".docx"]
            if "xl/workbook.xml" in names:
                return ALLOWED[".xlsx"]
        except zipfile.BadZipFile:
            return None
        return None
    if ext in {".txt", ".csv"}:
        try:
            head.decode("utf-8")
            return ALLOWED[ext]
        except UnicodeDecodeError:
            return None
    return None


def validate_upload(uploaded):
    """Check extension, size and actual file signature. Returns (content_type, sha256)."""
    ext = Path(uploaded.name).suffix.lower()
    if ext not in ALLOWED:
        raise ValidationError(f"File type {ext or '(none)'} is not accepted. Allowed: {', '.join(sorted(ALLOWED))}.")
    if uploaded.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError(f"File is larger than the {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    if uploaded.size == 0:
        raise ValidationError("File is empty.")
    uploaded.seek(0)
    head = uploaded.read(64)
    content_type = _sniff(head, ext, uploaded)
    if content_type is None or content_type != ALLOWED[ext]:
        raise ValidationError("The file's contents do not match its extension. Upload rejected.")
    uploaded.seek(0)
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    return content_type, digest.hexdigest()


_SALT = "dealdesk.document-download"


def signed_url(version, user, inline=False):
    token = signing.TimestampSigner(salt=_SALT).sign_object({"v": version.pk, "u": user.pk, "i": int(inline)})
    return reverse("document_file", args=[token])


def read_token(token):
    return signing.TimestampSigner(salt=_SALT).unsign_object(token, max_age=settings.DOWNLOAD_LINK_MAX_AGE_SECONDS)
