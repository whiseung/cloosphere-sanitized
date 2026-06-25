import hashlib
import hmac
import logging
import os
import time
import uuid
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS, WEBUI_SECRET_KEY
from open_webui.models.files import (
    FileForm,
    FileModel,
    FileModelResponse,
    Files,
)
from open_webui.models.knowledge import Knowledges
from open_webui.routers.audio import transcribe
from open_webui.routers.retrieval import ProcessFileForm, process_file
from open_webui.storage.provider import ImageStorage, Storage
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.file_guardrails import (
    run_post_storage_guardrails,
    run_pre_storage_guardrails,
)
from open_webui.utils.license import is_feature_enabled
from open_webui.utils.pdf_converter import (
    convert_file_to_pdf,
    is_libreoffice_available,
    should_convert_to_pdf,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


router = APIRouter()


############################
# Check if the current user has access to a file through any knowledge bases the user may be in.
############################


def has_access_to_file(
    file_id: Optional[str], access_type: str, user=Depends(get_verified_user)
) -> bool:
    file = Files.get_file_by_id(file_id)
    log.debug(f"Checking if user has {access_type} access to file")

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    has_access = False
    knowledge_base_id = file.meta.get("collection_name") if file.meta else None

    if knowledge_base_id:
        knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(
            user.id, access_type
        )
        for knowledge_base in knowledge_bases:
            if knowledge_base.id == knowledge_base_id:
                has_access = True
                break

    return has_access


############################
# Upload File
############################


@router.post("/", response_model=FileModelResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
    file_metadata: dict = {},
    process: bool = Query(True),
    storage_type: str = Query("local"),
    context: str = Query(""),
):
    log.info(f"file.content_type: {file.content_type}")
    try:
        unsanitized_filename = file.filename
        filename = os.path.basename(unsanitized_filename)

        # Check allowed file extensions
        allowed_extensions = request.app.state.config.ALLOWED_FILE_EXTENSIONS
        if allowed_extensions:
            file_ext = Path(filename).suffix.lstrip(".").lower()
            allowed = [e.strip().lower() for e in allowed_extensions if e.strip()]
            if file_ext not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT(
                        f"File type '.{file_ext}' is not allowed. Allowed types: {', '.join(allowed)}"
                    ),
                )

        # replace filename with uuid
        id = str(uuid.uuid4())
        name = filename
        filename = f"{id}_{filename}"

        # Read file contents for guardrail checks
        file_bytes = await file.read()
        await file.seek(0)

        # Check if guardrails apply to this upload context
        guardrail_scopes = getattr(
            request.app.state.config,
            "FILE_GUARDRAIL_SCOPES",
            ["chat", "knowledge", "project"],
        )
        guardrail_applicable = (
            is_feature_enabled(request.app, "file_guardrail")
            and getattr(request.app.state.config, "FILE_GUARDRAIL_ENABLED", False)
            and (not context or context in guardrail_scopes)
        )

        # === Stage 1: Pre-Storage Guardrails (macro detection) ===
        if guardrail_applicable:
            pre_results = await run_pre_storage_guardrails(
                request.app, file_bytes, name
            )
            for r in pre_results:
                if r.action == "block":
                    detail_msg = f"File blocked by {r.check_name}"
                    if r.details:
                        detail_msg += (
                            f": {r.details.get('macros_found', '')} macros detected"
                        )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=ERROR_MESSAGES.DEFAULT(detail_msg),
                    )

        # Use ImageStorage for image uploads, otherwise use local Storage
        storage = ImageStorage if storage_type == "image" else Storage
        contents, file_path = storage.upload_file(file.file, filename)

        file_item = Files.insert_new_file(
            user.id,
            FileForm(
                **{
                    "id": id,
                    "filename": name,
                    "path": file_path,
                    "meta": {
                        "name": name,
                        "content_type": file.content_type,
                        "size": len(contents),
                        **({"source": context} if context else {}),
                        "data": file_metadata,
                    },
                }
            ),
        )

        # === Stage 2: Post-Storage Guardrails (EXIF strip, NSFW) ===
        if guardrail_applicable:
            actual_file_path = (
                Storage.get_file(file_path)
                if storage_type != "image"
                else ImageStorage.get_file(file_path)
            )
            post_results = await run_post_storage_guardrails(
                request.app,
                actual_file_path,
                name,
                file.content_type or "",
                file_bytes,
            )
            for r in post_results:
                if r.action == "block":
                    # Clean up: delete the stored file and DB record
                    try:
                        storage.delete_file(file_path)
                    except Exception:
                        pass
                    Files.delete_file_by_id(id)
                    # Build detailed block message
                    block_detail = f"File blocked by {r.check_name}"
                    if r.details:
                        extra = (
                            r.details.get("raw_response")
                            or r.details.get("flagged_reason")
                            or ""
                        )
                        if extra:
                            block_detail = f"{block_detail}: {extra}"
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=ERROR_MESSAGES.DEFAULT(block_detail),
                    )
                if r.details:
                    Files.update_file_metadata_by_id(
                        id, {f"guardrail_{r.check_name}": r.details}
                    )

        # PDF conversion for Office files (non-fatal on failure)
        convert_extensions = request.app.state.config.PDF_CONVERT_EXTENSIONS
        if should_convert_to_pdf(name, convert_extensions):
            try:
                if not is_libreoffice_available():
                    log.warning("LibreOffice not available, skipping PDF conversion")
                else:
                    local_path = Storage.get_file(file_path)
                    pdf_path = convert_file_to_pdf(local_path)

                    # Build new storage path
                    stem = Path(name).stem
                    pdf_filename = f"{id}_{stem}.pdf"
                    pdf_size = os.path.getsize(pdf_path)

                    # Upload converted PDF to storage and remove temp
                    with open(pdf_path, "rb") as pdf_file:
                        _, new_file_path = Storage.upload_file(pdf_file, pdf_filename)

                    # Remove original file from storage
                    try:
                        Storage.delete_file(file_path)
                    except Exception:
                        pass

                    # Clean up temp PDF
                    try:
                        os.unlink(pdf_path)
                        # Also clean up the temp output dir
                        parent = Path(pdf_path).parent
                        if parent.name.startswith("lo_output_"):
                            import shutil

                            shutil.rmtree(parent, ignore_errors=True)
                    except Exception:
                        pass

                    # Update DB records
                    Files.update_file_metadata_by_id(
                        id,
                        {
                            "content_type": "application/pdf",
                            "size": pdf_size,
                            "original_filename": name,
                            "pdf_converted": True,
                        },
                    )
                    Files.update_file_path_by_id(id, new_file_path)

                    file_item = Files.get_file_by_id(id=id)
                    log.info(f"Converted {name} to PDF for file {id}")
            except Exception as e:
                log.warning(
                    f"PDF conversion failed for {name}, continuing with original: {e}"
                )

        if process:
            try:
                if file.content_type in [
                    "audio/mpeg",
                    "audio/wav",
                    "audio/ogg",
                    "audio/x-m4a",
                ]:
                    file_path = Storage.get_file(file_path)
                    result = transcribe(request, file_path)

                    await process_file(
                        request,
                        ProcessFileForm(file_id=id, content=result.get("text", "")),
                        user=user,
                    )
                elif file.content_type not in ["image/png", "image/jpeg", "image/gif"]:
                    # Chat file uploads must be synchronous so content is ready immediately
                    await process_file(request, ProcessFileForm(file_id=id), user=user)

                file_item = Files.get_file_by_id(id=id)
            except Exception as e:
                log.exception(e)
                log.error(f"Error processing file: {file_item.id}")
                file_item = FileModelResponse(
                    **{
                        **file_item.model_dump(),
                        "error": str(e.detail) if hasattr(e, "detail") else str(e),
                    }
                )

        if file_item:
            return file_item
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error uploading file"),
            )

    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


############################
# List Files
############################


@router.get("/", response_model=list[FileModelResponse])
async def list_files(user=Depends(get_verified_user), content: bool = Query(True)):
    if user.role == "admin":
        files = Files.get_files()
    else:
        files = Files.get_files_by_user_id(user.id)

    if not content:
        for file in files:
            del file.data["content"]

    return files


############################
# Search Files
############################


@router.get("/search", response_model=list[FileModelResponse])
async def search_files(
    filename: str = Query(
        ...,
        description="Filename pattern to search for. Supports wildcards such as '*.txt'",
    ),
    content: bool = Query(True),
    user=Depends(get_verified_user),
):
    """
    Search for files by filename with support for wildcard patterns.
    """
    # Get files according to user role
    if user.role == "admin":
        files = Files.get_files()
    else:
        files = Files.get_files_by_user_id(user.id)

    # Get matching files
    matching_files = [
        file for file in files if fnmatch(file.filename.lower(), filename.lower())
    ]

    if not matching_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No files found matching the pattern.",
        )

    if not content:
        for file in matching_files:
            del file.data["content"]

    return matching_files


############################
# Delete All Files
############################


@router.delete("/all")
async def delete_all_files(user=Depends(get_admin_user)):
    result = Files.delete_all_files()
    if result:
        try:
            Storage.delete_all_files()
        except Exception as e:
            log.exception(e)
            log.error("Error deleting files")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error deleting files"),
            )
        return {"message": "All files deleted successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting files"),
        )


############################
# Get File By Id
############################


@router.get("/{id}", response_model=Optional[FileModel])
async def get_file_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "read", user)
    ):
        return file
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Get File Data Content By Id
############################


@router.get("/{id}/data/content")
async def get_file_data_content_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "read", user)
    ):
        return {"content": file.data.get("content", "")}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update File Data Content By Id
############################


class ContentForm(BaseModel):
    content: str


@router.post("/{id}/data/content/update")
async def update_file_data_content_by_id(
    request: Request, id: str, form_data: ContentForm, user=Depends(get_verified_user)
):
    file = Files.get_file_by_id(id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "write", user)
    ):
        try:
            process_file(
                request,
                ProcessFileForm(file_id=id, content=form_data.content),
                user=user,
            )
            file = Files.get_file_by_id(id=id)
        except Exception as e:
            log.exception(e)
            log.error(f"Error processing file: {file.id}")

        return {"content": file.data.get("content", "")}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Get File Content By Id
############################


@router.get("/{id}/content")
async def get_file_content_by_id(
    id: str, user=Depends(get_verified_user), attachment: bool = Query(False)
):
    file = Files.get_file_by_id(id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "read", user)
    ):
        try:
            file_path = Storage.get_file(file.path)
            file_path = Path(file_path)

            # Check if the file already exists in the cache
            if file_path.is_file():
                # Handle Unicode filenames
                filename = file.meta.get("name", file.filename)
                encoded_filename = quote(filename)  # RFC5987 encoding

                content_type = file.meta.get("content_type")
                filename = file.meta.get("name", file.filename)
                encoded_filename = quote(filename)
                headers = {}

                if attachment:
                    headers["Content-Disposition"] = (
                        f"attachment; filename*=UTF-8''{encoded_filename}"
                    )
                else:
                    if content_type == "application/pdf" or filename.lower().endswith(
                        ".pdf"
                    ):
                        headers["Content-Disposition"] = (
                            f"inline; filename*=UTF-8''{encoded_filename}"
                        )
                        content_type = "application/pdf"
                    elif content_type != "text/plain":
                        headers["Content-Disposition"] = (
                            f"attachment; filename*=UTF-8''{encoded_filename}"
                        )

                return FileResponse(file_path, headers=headers, media_type=content_type)

            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
        except Exception as e:
            log.exception(e)
            log.error("Error getting file content")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error getting file content"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.get("/{id}/content/html")
async def get_html_file_content_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "read", user)
    ):
        try:
            file_path = Storage.get_file(file.path)
            file_path = Path(file_path)

            # Check if the file already exists in the cache
            if file_path.is_file():
                log.info(f"file_path: {file_path}")
                return FileResponse(file_path)
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
        except Exception as e:
            log.exception(e)
            log.error("Error getting file content")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error getting file content"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.get("/{id}/content/{file_name}")
async def get_file_content_by_id(id: str, user=Depends(get_verified_user)):  # noqa
    file = Files.get_file_by_id(id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "read", user)
    ):
        file_path = file.path

        # Handle Unicode filenames
        filename = file.meta.get("name", file.filename)
        encoded_filename = quote(filename)  # RFC5987 encoding
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }

        if file_path:
            file_path = Storage.get_file(file_path)
            file_path = Path(file_path)

            # Check if the file already exists in the cache
            if file_path.is_file():
                return FileResponse(file_path, headers=headers)
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
        else:
            # File path doesn’t exist, return the content as .txt if possible
            file_content = file.content.get("content", "")
            file_name = file.filename

            # Create a generator that encodes the file content
            def generator():
                yield file_content.encode("utf-8")

            return StreamingResponse(
                generator(),
                media_type="text/plain",
                headers=headers,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Delete File By Id
############################


@router.delete("/{id}")
async def delete_file_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "write", user)
    ):
        # We should add Chroma cleanup here

        result = Files.delete_file_by_id(id)
        if result:
            try:
                Storage.delete_file(file.path)
            except Exception as e:
                log.exception(e)
                log.error("Error deleting files")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("Error deleting files"),
                )
            return {"message": "File deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error deleting file"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Public file access (signed URL — no auth required)
############################

SIGNED_URL_MAX_AGE = 3600  # 1 hour


def generate_signed_url(
    base_url: str, file_id: str, expires_in: int = SIGNED_URL_MAX_AGE
) -> str:
    """Generate a time-limited signed URL for public file access."""
    expires = int(time.time()) + expires_in
    message = f"{file_id}:{expires}"
    sig = hmac.new(
        WEBUI_SECRET_KEY.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return f"{base_url}/api/v1/files/{file_id}/public?expires={expires}&sig={sig}"


@router.get("/{id}/public")
async def get_file_public(id: str, expires: int = Query(...), sig: str = Query(...)):
    """Serve a file without authentication, verified by HMAC signature + expiry."""
    # Verify expiry
    if int(time.time()) > expires:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Link expired"
        )

    # Verify signature
    message = f"{id}:{expires}"
    expected_sig = hmac.new(
        WEBUI_SECRET_KEY.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature"
        )

    file = Files.get_file_by_id(id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    try:
        file_path = Storage.get_file(file.path)
        file_path = Path(file_path)
        if file_path.is_file():
            content_type = file.meta.get("content_type", "application/octet-stream")
            # filename 명시 — 미설정 시 브라우저가 URL path 마지막(`public`)을
            # 다운로드 파일명으로 쓰는 문제 방지. file.filename 은 sanitized 상태.
            return FileResponse(
                file_path, media_type=content_type, filename=file.filename
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
    except HTTPException:
        raise
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error getting file"),
        )
