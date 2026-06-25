# media_handler.py

import base64
import os
import re
import uuid
from typing import TypedDict

import magic
from azure.storage.blob import BlobServiceClient, ContentSettings


class MediaUploadResult(TypedDict):
    media_type: str  # image | audio | video
    mime_type: str  # image/png, audio/wav, ...
    extension: str  # png, jpg, mp3, mp4 ...
    blob_path: str
    blob_url: str


def detect_mime_from_binary(binary: bytes) -> str:
    return magic.from_buffer(binary, mime=True)


def normalize_extension(mime_type: str) -> str:
    NORMALIZE_MAP = {
        "image/jpeg": "jpg",
        "audio/mpeg": "mp3",
        "audio/x-wav": "wav",
        "audio/wave": "wav",
        "video/quicktime": "mov",
    }

    if mime_type in NORMALIZE_MAP:
        return NORMALIZE_MAP[mime_type]

    ext = mime_type.split("/")[-1]
    return ext.replace("+xml", "")


def parse_data_url(data: str) -> tuple[str | None, str]:
    """
    returns: (declared_mime_type, pure_base64)
    """
    match = re.match(r"data:(.*?);base64,(.*)", data, re.DOTALL)
    if not match:
        b64 = re.sub(r"\s+", "", data)
        if len(b64) % 4 != 0:
            b64 += "=" * (4 - len(b64) % 4)
        return None, b64

    mime_type, b64 = match.groups()
    b64 = re.sub(r"\s+", "", b64)

    if len(b64) % 4 != 0:
        b64 += "=" * (4 - len(b64) % 4)

    return mime_type, b64


def upload_base64_to_blob(*, data: str) -> MediaUploadResult:
    """
    base64 (data URL or raw) → binary → Azure Blob Storage (SAS auth)
    """

    account_url = os.getenv("AZURE_STORAGE_MEDIA_BASE_URL")
    sas_token = os.getenv("AZURE_STORAGE_MEDIA_SAS_KEY")

    if not account_url or not sas_token:
        raise ValueError(
            "AZURE_STORAGE_MEDIA_ACCOUNT_URL or AZURE_STORAGE_MEDIA_SAS_TOKEN is not set"
        )

    declared_mime, b64 = parse_data_url(data)
    binary = base64.b64decode(b64)

    detected_mime = detect_mime_from_binary(binary)
    final_mime = detected_mime or declared_mime
    if not final_mime:
        raise ValueError("Unable to determine MIME type")

    media_type = final_mime.split("/")[0]
    extension = normalize_extension(final_mime)

    filename = f"{uuid.uuid4().hex}.{extension}"
    blob_path = f"{filename}"

    blob_service_client = BlobServiceClient(
        account_url=account_url,
        credential=sas_token,
    )

    blob_client = blob_service_client.get_blob_client(
        container=os.getenv("AZURE_STORAGE_MEDIA_CONTAINER"),
        blob=blob_path,
    )

    blob_client.upload_blob(
        binary,
        overwrite=True,
        content_settings=ContentSettings(content_type=final_mime),
    )

    return {
        "media_type": media_type,
        "mime_type": final_mime,
        "extension": extension,
        "blob_path": blob_path,
        "blob_url": blob_client.url,
    }
