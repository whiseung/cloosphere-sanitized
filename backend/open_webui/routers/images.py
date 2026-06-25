import asyncio
import base64
import hashlib
import io
import json
import logging
import mimetypes
import re
import time
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from open_webui.config import CACHE_DIR
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import ENABLE_FORWARD_USER_INFO_HEADERS, SRC_LOG_LEVELS
from open_webui.routers.files import upload_file
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.crypto import (
    mask_config_dict,
    resolve_config_dict,
    resolve_sensitive_value,
)
from open_webui.utils.images.comfyui import (
    ComfyUIGenerateImageForm,
    ComfyUIWorkflow,
    comfyui_generate_image,
)
from open_webui.utils.license import require_feature
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["IMAGES"])

IMAGE_CACHE_DIR = CACHE_DIR / "image" / "generations"
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Vertex AI OAuth2 token cache
_vertex_ai_token_cache: dict[str, tuple[str, float]] = {}


def _get_vertex_ai_access_token(service_account_key: str) -> str:
    cache_key = hashlib.sha256(service_account_key.encode()).hexdigest()[:16]

    if cache_key in _vertex_ai_token_cache:
        token, expiry = _vertex_ai_token_cache[cache_key]
        if time.time() < expiry - 300:
            return token

    try:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        credentials_info = json.loads(service_account_key)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)

        token = credentials.token
        # Use the token's REAL expiry (credentials.expiry is naive UTC), not now + 3600,
        # so an already-expired token is never served from cache (intermittent 401 fix).
        if credentials.expiry:
            from datetime import timezone

            expiry = credentials.expiry.replace(tzinfo=timezone.utc).timestamp()
        else:
            expiry = time.time() + 3600
        _vertex_ai_token_cache[cache_key] = (token, expiry)
        return token

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Google Cloud libraries not installed. Run: pip install google-auth",
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid service account key JSON format",
        )
    except Exception as e:
        log.error(f"Failed to get Vertex AI access token: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to authenticate with Google Cloud: {str(e)}",
        )


router = APIRouter(dependencies=[Depends(require_feature("image_generation"))])


@router.get("/config")
async def get_config(request: Request, user=Depends(get_admin_user)):
    return mask_config_dict(
        {
            "enabled": request.app.state.config.ENABLE_IMAGE_GENERATION,
            "engine": request.app.state.config.IMAGE_GENERATION_ENGINE,
            "prompt_generation": request.app.state.config.ENABLE_IMAGE_PROMPT_GENERATION,
            "openai": {
                "OPENAI_API_BASE_URL": request.app.state.config.IMAGES_OPENAI_API_BASE_URL,
                "OPENAI_API_KEY": request.app.state.config.IMAGES_OPENAI_API_KEY,
            },
            "automatic1111": {
                "AUTOMATIC1111_BASE_URL": request.app.state.config.AUTOMATIC1111_BASE_URL,
                "AUTOMATIC1111_API_AUTH": request.app.state.config.AUTOMATIC1111_API_AUTH,
                "AUTOMATIC1111_CFG_SCALE": request.app.state.config.AUTOMATIC1111_CFG_SCALE,
                "AUTOMATIC1111_SAMPLER": request.app.state.config.AUTOMATIC1111_SAMPLER,
                "AUTOMATIC1111_SCHEDULER": request.app.state.config.AUTOMATIC1111_SCHEDULER,
            },
            "comfyui": {
                "COMFYUI_BASE_URL": request.app.state.config.COMFYUI_BASE_URL,
                "COMFYUI_API_KEY": request.app.state.config.COMFYUI_API_KEY,
                "COMFYUI_WORKFLOW": request.app.state.config.COMFYUI_WORKFLOW,
                "COMFYUI_WORKFLOW_NODES": request.app.state.config.COMFYUI_WORKFLOW_NODES,
            },
            "gemini": {
                "GEMINI_API_BASE_URL": request.app.state.config.IMAGES_GEMINI_API_BASE_URL,
                "GEMINI_API_KEY": request.app.state.config.IMAGES_GEMINI_API_KEY,
            },
            "azure_openai": {
                "AZURE_OPENAI_API_BASE_URL": request.app.state.config.IMAGES_AZURE_OPENAI_API_BASE_URL,
                "AZURE_OPENAI_API_KEY": request.app.state.config.IMAGES_AZURE_OPENAI_API_KEY,
                "AZURE_OPENAI_API_VERSION": request.app.state.config.IMAGES_AZURE_OPENAI_API_VERSION,
                "AZURE_OPENAI_DEPLOYMENT_NAME": request.app.state.config.IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME,
                "AZURE_OPENAI_QUALITY": request.app.state.config.IMAGES_AZURE_OPENAI_QUALITY,
                "AZURE_OPENAI_OUTPUT_FORMAT": request.app.state.config.IMAGES_AZURE_OPENAI_OUTPUT_FORMAT,
                "AZURE_OPENAI_BACKGROUND": request.app.state.config.IMAGES_AZURE_OPENAI_BACKGROUND,
            },
            "vertex_ai": {
                "GOOGLE_PROJECT_ID": request.app.state.config.IMAGES_VERTEX_AI_PROJECT_ID,
                "GOOGLE_LOCATION": request.app.state.config.IMAGES_VERTEX_AI_LOCATION,
                "GOOGLE_SERVICE_ACCOUNT_KEY": request.app.state.config.IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY,
            },
        }
    )


class OpenAIConfigForm(BaseModel):
    OPENAI_API_BASE_URL: str
    OPENAI_API_KEY: str


class Automatic1111ConfigForm(BaseModel):
    AUTOMATIC1111_BASE_URL: str
    AUTOMATIC1111_API_AUTH: str
    AUTOMATIC1111_CFG_SCALE: Optional[str | float | int]
    AUTOMATIC1111_SAMPLER: Optional[str]
    AUTOMATIC1111_SCHEDULER: Optional[str]


class ComfyUIConfigForm(BaseModel):
    COMFYUI_BASE_URL: str
    COMFYUI_API_KEY: str
    COMFYUI_WORKFLOW: str
    COMFYUI_WORKFLOW_NODES: list[dict]


class GeminiConfigForm(BaseModel):
    GEMINI_API_BASE_URL: str
    GEMINI_API_KEY: str


class AzureOpenAIConfigForm(BaseModel):
    AZURE_OPENAI_API_BASE_URL: str
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_API_VERSION: str
    AZURE_OPENAI_DEPLOYMENT_NAME: str
    AZURE_OPENAI_QUALITY: Optional[str] = "auto"
    AZURE_OPENAI_OUTPUT_FORMAT: Optional[str] = "png"
    AZURE_OPENAI_BACKGROUND: Optional[str] = "auto"


class VertexAIConfigForm(BaseModel):
    GOOGLE_PROJECT_ID: str
    GOOGLE_LOCATION: str
    GOOGLE_SERVICE_ACCOUNT_KEY: str


class ConfigForm(BaseModel):
    enabled: bool
    engine: str
    prompt_generation: bool
    openai: OpenAIConfigForm
    automatic1111: Automatic1111ConfigForm
    comfyui: ComfyUIConfigForm
    gemini: GeminiConfigForm
    azure_openai: Optional[AzureOpenAIConfigForm] = None
    vertex_ai: Optional[VertexAIConfigForm] = None


class ImageConnectionConfigForm(BaseModel):
    IMAGE_API_URLS: list[str]
    IMAGE_API_KEYS: list[str]
    IMAGE_API_CONFIGS: dict


@router.post("/config/update")
async def update_config(
    request: Request, form_data: ConfigForm, user=Depends(get_admin_user)
):
    request.app.state.config.IMAGE_GENERATION_ENGINE = form_data.engine
    request.app.state.config.ENABLE_IMAGE_GENERATION = form_data.enabled

    request.app.state.config.ENABLE_IMAGE_PROMPT_GENERATION = (
        form_data.prompt_generation
    )

    request.app.state.config.IMAGES_OPENAI_API_BASE_URL = (
        form_data.openai.OPENAI_API_BASE_URL
    )
    request.app.state.config.IMAGES_OPENAI_API_KEY = resolve_sensitive_value(
        form_data.openai.OPENAI_API_KEY,
        request.app.state.config.IMAGES_OPENAI_API_KEY,
    )

    request.app.state.config.IMAGES_GEMINI_API_BASE_URL = (
        form_data.gemini.GEMINI_API_BASE_URL
    )
    request.app.state.config.IMAGES_GEMINI_API_KEY = resolve_sensitive_value(
        form_data.gemini.GEMINI_API_KEY,
        request.app.state.config.IMAGES_GEMINI_API_KEY,
    )

    request.app.state.config.AUTOMATIC1111_BASE_URL = (
        form_data.automatic1111.AUTOMATIC1111_BASE_URL
    )
    request.app.state.config.AUTOMATIC1111_API_AUTH = resolve_sensitive_value(
        form_data.automatic1111.AUTOMATIC1111_API_AUTH,
        request.app.state.config.AUTOMATIC1111_API_AUTH,
    )

    request.app.state.config.AUTOMATIC1111_CFG_SCALE = (
        float(form_data.automatic1111.AUTOMATIC1111_CFG_SCALE)
        if form_data.automatic1111.AUTOMATIC1111_CFG_SCALE
        else None
    )
    request.app.state.config.AUTOMATIC1111_SAMPLER = (
        form_data.automatic1111.AUTOMATIC1111_SAMPLER
        if form_data.automatic1111.AUTOMATIC1111_SAMPLER
        else None
    )
    request.app.state.config.AUTOMATIC1111_SCHEDULER = (
        form_data.automatic1111.AUTOMATIC1111_SCHEDULER
        if form_data.automatic1111.AUTOMATIC1111_SCHEDULER
        else None
    )

    request.app.state.config.COMFYUI_BASE_URL = (
        form_data.comfyui.COMFYUI_BASE_URL.strip("/")
    )
    request.app.state.config.COMFYUI_API_KEY = resolve_sensitive_value(
        form_data.comfyui.COMFYUI_API_KEY,
        request.app.state.config.COMFYUI_API_KEY,
    )

    request.app.state.config.COMFYUI_WORKFLOW = form_data.comfyui.COMFYUI_WORKFLOW
    request.app.state.config.COMFYUI_WORKFLOW_NODES = (
        form_data.comfyui.COMFYUI_WORKFLOW_NODES
    )

    if form_data.azure_openai:
        request.app.state.config.IMAGES_AZURE_OPENAI_API_BASE_URL = (
            form_data.azure_openai.AZURE_OPENAI_API_BASE_URL
        )
        request.app.state.config.IMAGES_AZURE_OPENAI_API_KEY = resolve_sensitive_value(
            form_data.azure_openai.AZURE_OPENAI_API_KEY,
            request.app.state.config.IMAGES_AZURE_OPENAI_API_KEY,
        )
        request.app.state.config.IMAGES_AZURE_OPENAI_API_VERSION = (
            form_data.azure_openai.AZURE_OPENAI_API_VERSION
        )
        request.app.state.config.IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME = (
            form_data.azure_openai.AZURE_OPENAI_DEPLOYMENT_NAME
        )
        request.app.state.config.IMAGES_AZURE_OPENAI_QUALITY = (
            form_data.azure_openai.AZURE_OPENAI_QUALITY or "auto"
        )
        request.app.state.config.IMAGES_AZURE_OPENAI_OUTPUT_FORMAT = (
            form_data.azure_openai.AZURE_OPENAI_OUTPUT_FORMAT or "png"
        )
        request.app.state.config.IMAGES_AZURE_OPENAI_BACKGROUND = (
            form_data.azure_openai.AZURE_OPENAI_BACKGROUND or "auto"
        )

    if form_data.vertex_ai:
        request.app.state.config.IMAGES_VERTEX_AI_PROJECT_ID = (
            form_data.vertex_ai.GOOGLE_PROJECT_ID
        )
        request.app.state.config.IMAGES_VERTEX_AI_LOCATION = (
            form_data.vertex_ai.GOOGLE_LOCATION
        )
        request.app.state.config.IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY = (
            resolve_sensitive_value(
                form_data.vertex_ai.GOOGLE_SERVICE_ACCOUNT_KEY,
                request.app.state.config.IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY,
            )
        )

    AuditLogger.log_settings_change("images", after_data=form_data.model_dump())
    return mask_config_dict(
        {
            "enabled": request.app.state.config.ENABLE_IMAGE_GENERATION,
            "engine": request.app.state.config.IMAGE_GENERATION_ENGINE,
            "prompt_generation": request.app.state.config.ENABLE_IMAGE_PROMPT_GENERATION,
            "openai": {
                "OPENAI_API_BASE_URL": request.app.state.config.IMAGES_OPENAI_API_BASE_URL,
                "OPENAI_API_KEY": request.app.state.config.IMAGES_OPENAI_API_KEY,
            },
            "automatic1111": {
                "AUTOMATIC1111_BASE_URL": request.app.state.config.AUTOMATIC1111_BASE_URL,
                "AUTOMATIC1111_API_AUTH": request.app.state.config.AUTOMATIC1111_API_AUTH,
                "AUTOMATIC1111_CFG_SCALE": request.app.state.config.AUTOMATIC1111_CFG_SCALE,
                "AUTOMATIC1111_SAMPLER": request.app.state.config.AUTOMATIC1111_SAMPLER,
                "AUTOMATIC1111_SCHEDULER": request.app.state.config.AUTOMATIC1111_SCHEDULER,
            },
            "comfyui": {
                "COMFYUI_BASE_URL": request.app.state.config.COMFYUI_BASE_URL,
                "COMFYUI_API_KEY": request.app.state.config.COMFYUI_API_KEY,
                "COMFYUI_WORKFLOW": request.app.state.config.COMFYUI_WORKFLOW,
                "COMFYUI_WORKFLOW_NODES": request.app.state.config.COMFYUI_WORKFLOW_NODES,
            },
            "gemini": {
                "GEMINI_API_BASE_URL": request.app.state.config.IMAGES_GEMINI_API_BASE_URL,
                "GEMINI_API_KEY": request.app.state.config.IMAGES_GEMINI_API_KEY,
            },
            "azure_openai": {
                "AZURE_OPENAI_API_BASE_URL": request.app.state.config.IMAGES_AZURE_OPENAI_API_BASE_URL,
                "AZURE_OPENAI_API_KEY": request.app.state.config.IMAGES_AZURE_OPENAI_API_KEY,
                "AZURE_OPENAI_API_VERSION": request.app.state.config.IMAGES_AZURE_OPENAI_API_VERSION,
                "AZURE_OPENAI_DEPLOYMENT_NAME": request.app.state.config.IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME,
                "AZURE_OPENAI_QUALITY": request.app.state.config.IMAGES_AZURE_OPENAI_QUALITY,
                "AZURE_OPENAI_OUTPUT_FORMAT": request.app.state.config.IMAGES_AZURE_OPENAI_OUTPUT_FORMAT,
                "AZURE_OPENAI_BACKGROUND": request.app.state.config.IMAGES_AZURE_OPENAI_BACKGROUND,
            },
            "vertex_ai": {
                "GOOGLE_PROJECT_ID": request.app.state.config.IMAGES_VERTEX_AI_PROJECT_ID,
                "GOOGLE_LOCATION": request.app.state.config.IMAGES_VERTEX_AI_LOCATION,
                "GOOGLE_SERVICE_ACCOUNT_KEY": request.app.state.config.IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY,
            },
        }
    )


def get_automatic1111_api_auth(request: Request):
    if request.app.state.config.AUTOMATIC1111_API_AUTH is None:
        return ""
    else:
        auth1111_byte_string = request.app.state.config.AUTOMATIC1111_API_AUTH.encode(
            "utf-8"
        )
        auth1111_base64_encoded_bytes = base64.b64encode(auth1111_byte_string)
        auth1111_base64_encoded_string = auth1111_base64_encoded_bytes.decode("utf-8")
        return f"Basic {auth1111_base64_encoded_string}"


@router.get("/config/url/verify")
async def verify_url(request: Request, user=Depends(get_admin_user)):
    if request.app.state.config.IMAGE_GENERATION_ENGINE == "automatic1111":
        try:
            r = requests.get(
                url=f"{request.app.state.config.AUTOMATIC1111_BASE_URL}/sdapi/v1/options",
                headers={"authorization": get_automatic1111_api_auth(request)},
            )
            r.raise_for_status()
            return True
        except Exception:
            request.app.state.config.ENABLE_IMAGE_GENERATION = False
            raise HTTPException(status_code=400, detail=ERROR_MESSAGES.INVALID_URL)
    elif request.app.state.config.IMAGE_GENERATION_ENGINE == "comfyui":
        headers = None
        if request.app.state.config.COMFYUI_API_KEY:
            headers = {
                "Authorization": f"Bearer {request.app.state.config.COMFYUI_API_KEY}"
            }

        try:
            r = requests.get(
                url=f"{request.app.state.config.COMFYUI_BASE_URL}/object_info",
                headers=headers,
            )
            r.raise_for_status()
            return True
        except Exception:
            request.app.state.config.ENABLE_IMAGE_GENERATION = False
            raise HTTPException(status_code=400, detail=ERROR_MESSAGES.INVALID_URL)
    else:
        return True


@router.get("/connections/config")
async def get_image_connections_config(request: Request, user=Depends(get_admin_user)):
    return mask_config_dict(
        {
            "IMAGE_API_URLS": request.app.state.config.IMAGE_API_URLS,
            "IMAGE_API_KEYS": request.app.state.config.IMAGE_API_KEYS,
            "IMAGE_API_CONFIGS": request.app.state.config.IMAGE_API_CONFIGS or {},
        }
    )


@router.post("/connections/config/update")
async def update_image_connections_config(
    request: Request,
    form_data: ImageConnectionConfigForm,
    user=Depends(get_admin_user),
):
    # Sync URL/Key array lengths
    urls = form_data.IMAGE_API_URLS
    keys = resolve_sensitive_value(
        form_data.IMAGE_API_KEYS,
        request.app.state.config.IMAGE_API_KEYS,
    )
    if len(keys) > len(urls):
        keys = keys[: len(urls)]
    elif len(keys) < len(urls):
        keys.extend([""] * (len(urls) - len(keys)))

    request.app.state.config.IMAGE_API_URLS = urls
    request.app.state.config.IMAGE_API_KEYS = keys

    # Resolve masked sensitive values in nested API configs
    request.app.state.config.IMAGE_API_CONFIGS = resolve_config_dict(
        form_data.IMAGE_API_CONFIGS,
        request.app.state.config.IMAGE_API_CONFIGS or {},
    )

    AuditLogger.log_settings_change(
        "images/connections", after_data=form_data.model_dump()
    )
    return mask_config_dict(
        {
            "IMAGE_API_URLS": request.app.state.config.IMAGE_API_URLS,
            "IMAGE_API_KEYS": request.app.state.config.IMAGE_API_KEYS,
            "IMAGE_API_CONFIGS": request.app.state.config.IMAGE_API_CONFIGS,
        }
    )


@router.get("/connections/list")
async def get_image_connections_list(request: Request, user=Depends(get_verified_user)):
    """Return list of enabled image connections for chat dropdown."""
    urls = request.app.state.config.IMAGE_API_URLS
    configs = request.app.state.config.IMAGE_API_CONFIGS
    connections = []
    for idx, url in enumerate(urls):
        cfg = configs.get(str(idx), configs.get(idx, {}))
        if cfg.get("enable", True):
            engine = cfg.get("engine", "openai")
            conn_info = {
                "idx": idx,
                "name": cfg.get("name", f"Image Connection {idx}"),
                "engine": engine,
                "model": cfg.get("model", ""),
                "size": cfg.get("size", ""),
            }
            if engine == "azure_openai":
                conn_info["azure_deployment_name"] = cfg.get(
                    "azure_deployment_name", ""
                )
                conn_info["azure_quality"] = cfg.get("azure_quality", "")
                conn_info["azure_output_format"] = cfg.get("azure_output_format", "")
            connections.append(conn_info)
    return connections


def set_image_model(request: Request, model: str):
    log.info(f"Setting image model to {model}")
    request.app.state.config.IMAGE_GENERATION_MODEL = model
    if request.app.state.config.IMAGE_GENERATION_ENGINE in ["", "automatic1111"]:
        api_auth = get_automatic1111_api_auth(request)
        r = requests.get(
            url=f"{request.app.state.config.AUTOMATIC1111_BASE_URL}/sdapi/v1/options",
            headers={"authorization": api_auth},
        )
        options = r.json()
        if model != options["sd_model_checkpoint"]:
            options["sd_model_checkpoint"] = model
            r = requests.post(
                url=f"{request.app.state.config.AUTOMATIC1111_BASE_URL}/sdapi/v1/options",
                json=options,
                headers={"authorization": api_auth},
            )
    return request.app.state.config.IMAGE_GENERATION_MODEL


def get_image_model(request):
    if request.app.state.config.IMAGE_GENERATION_ENGINE == "openai":
        return (
            request.app.state.config.IMAGE_GENERATION_MODEL
            if request.app.state.config.IMAGE_GENERATION_MODEL
            else "dall-e-2"
        )
    elif request.app.state.config.IMAGE_GENERATION_ENGINE == "gemini":
        return (
            request.app.state.config.IMAGE_GENERATION_MODEL
            if request.app.state.config.IMAGE_GENERATION_MODEL
            else "imagen-3.0-generate-002"
        )
    elif request.app.state.config.IMAGE_GENERATION_ENGINE == "azure_openai":
        return (
            request.app.state.config.IMAGE_GENERATION_MODEL
            if request.app.state.config.IMAGE_GENERATION_MODEL
            else request.app.state.config.IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME
        )
    elif request.app.state.config.IMAGE_GENERATION_ENGINE == "vertex_ai":
        return (
            request.app.state.config.IMAGE_GENERATION_MODEL
            if request.app.state.config.IMAGE_GENERATION_MODEL
            else "gemini-2.5-flash-preview-native-audio-dialog"
        )
    elif request.app.state.config.IMAGE_GENERATION_ENGINE == "comfyui":
        return (
            request.app.state.config.IMAGE_GENERATION_MODEL
            if request.app.state.config.IMAGE_GENERATION_MODEL
            else ""
        )
    elif (
        request.app.state.config.IMAGE_GENERATION_ENGINE == "automatic1111"
        or request.app.state.config.IMAGE_GENERATION_ENGINE == ""
    ):
        try:
            r = requests.get(
                url=f"{request.app.state.config.AUTOMATIC1111_BASE_URL}/sdapi/v1/options",
                headers={"authorization": get_automatic1111_api_auth(request)},
            )
            options = r.json()
            return options["sd_model_checkpoint"]
        except Exception as e:
            request.app.state.config.ENABLE_IMAGE_GENERATION = False
            raise HTTPException(status_code=400, detail=ERROR_MESSAGES.DEFAULT(e))


class ImageConfigForm(BaseModel):
    MODEL: str
    IMAGE_SIZE: str
    IMAGE_STEPS: int


@router.get("/image/config")
async def get_image_config(request: Request, user=Depends(get_admin_user)):
    return {
        "MODEL": request.app.state.config.IMAGE_GENERATION_MODEL,
        "IMAGE_SIZE": request.app.state.config.IMAGE_SIZE,
        "IMAGE_STEPS": request.app.state.config.IMAGE_STEPS,
    }


@router.post("/image/config/update")
async def update_image_config(
    request: Request, form_data: ImageConfigForm, user=Depends(get_admin_user)
):
    set_image_model(request, form_data.MODEL)

    pattern = r"^\d+x\d+$"
    if re.match(pattern, form_data.IMAGE_SIZE):
        request.app.state.config.IMAGE_SIZE = form_data.IMAGE_SIZE
    else:
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.INCORRECT_FORMAT("  (e.g., 512x512)."),
        )

    if form_data.IMAGE_STEPS >= 0:
        request.app.state.config.IMAGE_STEPS = form_data.IMAGE_STEPS
    else:
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.INCORRECT_FORMAT("  (e.g., 50)."),
        )

    AuditLogger.log_settings_change(
        "images/image_config", after_data=form_data.model_dump()
    )
    return {
        "MODEL": request.app.state.config.IMAGE_GENERATION_MODEL,
        "IMAGE_SIZE": request.app.state.config.IMAGE_SIZE,
        "IMAGE_STEPS": request.app.state.config.IMAGE_STEPS,
    }


@router.get("/models")
def get_models(request: Request, user=Depends(get_verified_user)):
    try:
        if request.app.state.config.IMAGE_GENERATION_ENGINE == "openai":
            return [
                {"id": "dall-e-2", "name": "DALL·E 2"},
                {"id": "dall-e-3", "name": "DALL·E 3"},
            ]
        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "gemini":
            return [
                {"id": "imagen-3-0-generate-002", "name": "imagen-3.0 generate-002"},
            ]
        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "azure_openai":
            deployment_name = (
                request.app.state.config.IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME
            )
            return [{"id": deployment_name, "name": deployment_name}]
        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "vertex_ai":
            return [
                {
                    "id": "gemini-2.5-flash-preview-native-audio-dialog",
                    "name": "Gemini 2.5 Flash Image",
                },
                {
                    "id": "gemini-2.0-flash-exp",
                    "name": "Gemini 2.0 Flash Exp",
                },
            ]
        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "comfyui":
            # TODO - get models from comfyui
            headers = {
                "Authorization": f"Bearer {request.app.state.config.COMFYUI_API_KEY}"
            }
            r = requests.get(
                url=f"{request.app.state.config.COMFYUI_BASE_URL}/object_info",
                headers=headers,
            )
            info = r.json()

            workflow = json.loads(request.app.state.config.COMFYUI_WORKFLOW)
            model_node_id = None

            for node in request.app.state.config.COMFYUI_WORKFLOW_NODES:
                if node["type"] == "model":
                    if node["node_ids"]:
                        model_node_id = node["node_ids"][0]
                    break

            if model_node_id:
                model_list_key = None

                log.info(workflow[model_node_id]["class_type"])
                for key in info[workflow[model_node_id]["class_type"]]["input"][
                    "required"
                ]:
                    if "_name" in key:
                        model_list_key = key
                        break

                if model_list_key:
                    return list(
                        map(
                            lambda model: {"id": model, "name": model},
                            info[workflow[model_node_id]["class_type"]]["input"][
                                "required"
                            ][model_list_key][0],
                        )
                    )
            else:
                return list(
                    map(
                        lambda model: {"id": model, "name": model},
                        info["CheckpointLoaderSimple"]["input"]["required"][
                            "ckpt_name"
                        ][0],
                    )
                )
        elif (
            request.app.state.config.IMAGE_GENERATION_ENGINE == "automatic1111"
            or request.app.state.config.IMAGE_GENERATION_ENGINE == ""
        ):
            r = requests.get(
                url=f"{request.app.state.config.AUTOMATIC1111_BASE_URL}/sdapi/v1/sd-models",
                headers={"authorization": get_automatic1111_api_auth(request)},
            )
            models = r.json()
            return list(
                map(
                    lambda model: {"id": model["title"], "name": model["model_name"]},
                    models,
                )
            )
    except Exception as e:
        request.app.state.config.ENABLE_IMAGE_GENERATION = False
        raise HTTPException(status_code=400, detail=ERROR_MESSAGES.DEFAULT(e))


class GenerateImageForm(BaseModel):
    model: Optional[str] = None
    prompt: str
    size: Optional[str] = None
    n: int = 1
    negative_prompt: Optional[str] = None
    connection_idx: Optional[int] = None


def load_b64_image_data(b64_str):
    try:
        if "," in b64_str:
            header, encoded = b64_str.split(",", 1)
            mime_type = header.split(";")[0]
            img_data = base64.b64decode(encoded)
        else:
            mime_type = "image/png"
            img_data = base64.b64decode(b64_str)
        return img_data, mime_type
    except Exception as e:
        log.exception(f"Error loading image data: {e}")
        return None


def load_url_image_data(url, headers=None):
    try:
        if headers:
            r = requests.get(url, headers=headers)
        else:
            r = requests.get(url)

        r.raise_for_status()
        if r.headers["content-type"].split("/")[0] == "image":
            mime_type = r.headers["content-type"]
            return r.content, mime_type
        else:
            log.error("Url does not point to an image.")
            return None

    except Exception as e:
        log.exception(f"Error saving image: {e}")
        return None


async def upload_image(request, image_metadata, image_data, content_type, user):
    image_format = mimetypes.guess_extension(content_type)
    file = UploadFile(
        file=io.BytesIO(image_data),
        filename=f"generated-image{image_format}",  # will be converted to a unique ID on upload_file
        headers={
            "content-type": content_type,
        },
    )
    file_item = await upload_file(
        request, file, user, file_metadata=image_metadata, context=""
    )
    url = request.app.url_path_for("get_file_content_by_id", id=file_item.id)
    return url


async def _generate_with_connection(
    request, form_data, user, engine, url, key, conn_config
):
    """Generate image using a specific connection's settings."""
    size = form_data.size or conn_config.get(
        "size", request.app.state.config.IMAGE_SIZE
    )
    model = form_data.model or conn_config.get("model", "")

    if engine == "openai":
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if ENABLE_FORWARD_USER_INFO_HEADERS:
            headers["X-OpenWebUI-User-Name"] = user.name
            headers["X-OpenWebUI-User-Id"] = user.id
            headers["X-OpenWebUI-User-Email"] = user.email
            headers["X-OpenWebUI-User-Role"] = user.role

        data = {
            "model": model or "dall-e-2",
            "prompt": form_data.prompt,
            "n": form_data.n,
            "size": size,
            "response_format": "b64_json",
        }

        r = await asyncio.to_thread(
            requests.post,
            url=f"{url}/images/generations",
            json=data,
            headers=headers,
        )
        r.raise_for_status()
        res = r.json()

        images = []
        for image in res["data"]:
            if image_url := image.get("url", None):
                image_data, content_type = load_url_image_data(image_url, headers)
            else:
                image_data, content_type = load_b64_image_data(image["b64_json"])
            img_url = await upload_image(request, data, image_data, content_type, user)
            images.append({"url": img_url})
        return images

    elif engine == "azure_openai":
        deployment = conn_config.get("azure_deployment_name", "")
        api_version = conn_config.get("azure_api_version", "2025-04-01-preview")
        quality = conn_config.get("azure_quality", "auto")
        output_format = conn_config.get("azure_output_format", "png")
        background = conn_config.get("azure_background", "auto")

        headers = {
            "api-key": key,
            "Content-Type": "application/json",
        }

        is_gpt_image = "gpt-image" in deployment.lower()
        data = {
            "prompt": form_data.prompt,
            "n": form_data.n,
            "size": size,
        }

        if is_gpt_image:
            data["output_format"] = output_format or "png"
            data["quality"] = quality or "auto"
            data["background"] = background or "auto"
        else:
            data["response_format"] = "b64_json"

        base_url = url.rstrip("/")
        api_url = f"{base_url}/openai/deployments/{deployment}/images/generations?api-version={api_version}"

        r = await asyncio.to_thread(
            requests.post,
            url=api_url,
            json=data,
            headers=headers,
        )
        r.raise_for_status()
        res = r.json()

        images = []
        for image in res["data"]:
            if image_url := image.get("url", None):
                image_data, content_type = load_url_image_data(image_url, headers)
            else:
                image_data, content_type = load_b64_image_data(image["b64_json"])
            img_url = await upload_image(request, data, image_data, content_type, user)
            images.append({"url": img_url})
        return images

    elif engine == "gemini":
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        }
        gemini_model = model or "imagen-3.0-generate-002"
        data = {
            "instances": {"prompt": form_data.prompt},
            "parameters": {
                "sampleCount": form_data.n,
                "outputOptions": {"mimeType": "image/png"},
            },
        }

        r = await asyncio.to_thread(
            requests.post,
            url=f"{url}/models/{gemini_model}:predict",
            json=data,
            headers=headers,
        )
        r.raise_for_status()
        res = r.json()

        images = []
        for image in res["predictions"]:
            image_data, content_type = load_b64_image_data(image["bytesBase64Encoded"])
            img_url = await upload_image(request, data, image_data, content_type, user)
            images.append({"url": img_url})
        return images

    elif engine == "vertex_ai":
        project_id = conn_config.get("vertex_project_id", "")
        location = conn_config.get("vertex_location", "us-central1")
        sa_key = conn_config.get("vertex_service_account_key", "")
        vertex_model = model or "gemini-2.5-flash-preview-native-audio-dialog"

        token = _get_vertex_ai_access_token(sa_key)

        api_url = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}"
            f"/locations/{location}/publishers/google/models/{vertex_model}:generateContent"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        data = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": form_data.prompt}],
                }
            ],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
            },
        }

        r = await asyncio.to_thread(
            requests.post,
            url=api_url,
            json=data,
            headers=headers,
        )
        r.raise_for_status()
        res = r.json()

        images = []
        for candidate in res.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline_data = part.get("inlineData")
                if inline_data and inline_data.get("data"):
                    mime_type = inline_data.get("mimeType", "image/png")
                    image_data = base64.b64decode(inline_data["data"])
                    img_url = await upload_image(
                        request, data, image_data, mime_type, user
                    )
                    images.append({"url": img_url})

        if not images:
            raise HTTPException(
                status_code=400,
                detail="No image was generated. The model may not support image generation or the prompt was filtered.",
            )
        return images

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image engine: {engine}",
        )


@router.post("/generations")
async def image_generations(
    request: Request,
    form_data: GenerateImageForm,
    user=Depends(get_verified_user),
):
    # Route to multi-connection handler if connection_idx is specified
    if form_data.connection_idx is not None:
        idx = form_data.connection_idx
        urls = request.app.state.config.IMAGE_API_URLS
        keys = request.app.state.config.IMAGE_API_KEYS
        configs = request.app.state.config.IMAGE_API_CONFIGS

        if idx < 0 or idx >= len(urls):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image connection index: {idx}",
            )

        conn_url = urls[idx]
        conn_key = keys[idx] if idx < len(keys) else ""
        conn_config = configs.get(str(idx), configs.get(idx, {}))
        engine = conn_config.get("engine", "openai")

        try:
            return await _generate_with_connection(
                request, form_data, user, engine, conn_url, conn_key, conn_config
            )
        except Exception as e:
            error = e
            if hasattr(e, "response") and e.response is not None:
                try:
                    data = e.response.json()
                    if "error" in data:
                        error = data["error"]["message"]
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail=ERROR_MESSAGES.DEFAULT(error))

    width, height = tuple(map(int, request.app.state.config.IMAGE_SIZE.split("x")))

    r = None
    try:
        if request.app.state.config.IMAGE_GENERATION_ENGINE == "openai":
            headers = {}
            headers["Authorization"] = (
                f"Bearer {request.app.state.config.IMAGES_OPENAI_API_KEY}"
            )
            headers["Content-Type"] = "application/json"

            if ENABLE_FORWARD_USER_INFO_HEADERS:
                headers["X-OpenWebUI-User-Name"] = user.name
                headers["X-OpenWebUI-User-Id"] = user.id
                headers["X-OpenWebUI-User-Email"] = user.email
                headers["X-OpenWebUI-User-Role"] = user.role

            data = {
                "model": (
                    request.app.state.config.IMAGE_GENERATION_MODEL
                    if request.app.state.config.IMAGE_GENERATION_MODEL != ""
                    else "dall-e-2"
                ),
                "prompt": form_data.prompt,
                "n": form_data.n,
                "size": (
                    form_data.size
                    if form_data.size
                    else request.app.state.config.IMAGE_SIZE
                ),
                "response_format": "b64_json",
            }

            # Use asyncio.to_thread for the requests.post call
            r = await asyncio.to_thread(
                requests.post,
                url=f"{request.app.state.config.IMAGES_OPENAI_API_BASE_URL}/images/generations",
                json=data,
                headers=headers,
            )

            r.raise_for_status()
            res = r.json()

            images = []

            for image in res["data"]:
                if image_url := image.get("url", None):
                    image_data, content_type = load_url_image_data(image_url, headers)
                else:
                    image_data, content_type = load_b64_image_data(image["b64_json"])

                url = await upload_image(request, data, image_data, content_type, user)
                images.append({"url": url})
            return images

        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "gemini":
            headers = {}
            headers["Content-Type"] = "application/json"
            headers["x-goog-api-key"] = request.app.state.config.IMAGES_GEMINI_API_KEY

            model = get_image_model(request)
            data = {
                "instances": {"prompt": form_data.prompt},
                "parameters": {
                    "sampleCount": form_data.n,
                    "outputOptions": {"mimeType": "image/png"},
                },
            }

            # Use asyncio.to_thread for the requests.post call
            r = await asyncio.to_thread(
                requests.post,
                url=f"{request.app.state.config.IMAGES_GEMINI_API_BASE_URL}/models/{model}:predict",
                json=data,
                headers=headers,
            )

            r.raise_for_status()
            res = r.json()

            images = []
            for image in res["predictions"]:
                image_data, content_type = load_b64_image_data(
                    image["bytesBase64Encoded"]
                )
                url = await upload_image(request, data, image_data, content_type, user)
                images.append({"url": url})

            return images

        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "azure_openai":
            base_url = request.app.state.config.IMAGES_AZURE_OPENAI_API_BASE_URL.rstrip(
                "/"
            )
            api_key = request.app.state.config.IMAGES_AZURE_OPENAI_API_KEY
            api_version = request.app.state.config.IMAGES_AZURE_OPENAI_API_VERSION
            deployment = request.app.state.config.IMAGES_AZURE_OPENAI_DEPLOYMENT_NAME

            headers = {
                "api-key": api_key,
                "Content-Type": "application/json",
            }

            size = (
                form_data.size
                if form_data.size
                else request.app.state.config.IMAGE_SIZE
            )

            # gpt-image models use different parameters than DALL-E
            is_gpt_image = "gpt-image" in deployment.lower()

            data = {
                "prompt": form_data.prompt,
                "n": form_data.n,
                "size": size,
            }

            if is_gpt_image:
                quality = request.app.state.config.IMAGES_AZURE_OPENAI_QUALITY
                output_format = (
                    request.app.state.config.IMAGES_AZURE_OPENAI_OUTPUT_FORMAT
                )
                background = request.app.state.config.IMAGES_AZURE_OPENAI_BACKGROUND

                data["output_format"] = output_format or "png"
                data["quality"] = quality or "auto"
                data["background"] = background or "auto"
            else:
                data["response_format"] = "b64_json"

            url = f"{base_url}/openai/deployments/{deployment}/images/generations?api-version={api_version}"

            r = await asyncio.to_thread(
                requests.post,
                url=url,
                json=data,
                headers=headers,
            )

            r.raise_for_status()
            res = r.json()

            images = []
            for image in res["data"]:
                if image_url := image.get("url", None):
                    image_data, content_type = load_url_image_data(image_url, headers)
                else:
                    image_data, content_type = load_b64_image_data(image["b64_json"])

                url = await upload_image(request, data, image_data, content_type, user)
                images.append({"url": url})
            return images

        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "vertex_ai":
            from open_webui.utils.google_cloud import resolve_gcp_credentials

            project_id = request.app.state.config.IMAGES_VERTEX_AI_PROJECT_ID
            location = request.app.state.config.IMAGES_VERTEX_AI_LOCATION
            sa_key = resolve_gcp_credentials(
                request.app,
                request.app.state.config.IMAGES_VERTEX_AI_SERVICE_ACCOUNT_KEY,
            )
            model = get_image_model(request)

            token = _get_vertex_ai_access_token(sa_key)

            url = (
                f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}"
                f"/locations/{location}/publishers/google/models/{model}:generateContent"
            )

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            data = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": form_data.prompt}],
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["TEXT", "IMAGE"],
                },
            }

            r = await asyncio.to_thread(
                requests.post,
                url=url,
                json=data,
                headers=headers,
            )

            r.raise_for_status()
            res = r.json()

            images = []
            for candidate in res.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    inline_data = part.get("inlineData")
                    if inline_data and inline_data.get("data"):
                        mime_type = inline_data.get("mimeType", "image/png")
                        image_data = base64.b64decode(inline_data["data"])
                        url = await upload_image(
                            request, data, image_data, mime_type, user
                        )
                        images.append({"url": url})

            if not images:
                raise HTTPException(
                    status_code=400,
                    detail="No image was generated. The model may not support image generation or the prompt was filtered.",
                )

            return images

        elif request.app.state.config.IMAGE_GENERATION_ENGINE == "comfyui":
            data = {
                "prompt": form_data.prompt,
                "width": width,
                "height": height,
                "n": form_data.n,
            }

            if request.app.state.config.IMAGE_STEPS is not None:
                data["steps"] = request.app.state.config.IMAGE_STEPS

            if form_data.negative_prompt is not None:
                data["negative_prompt"] = form_data.negative_prompt

            form_data = ComfyUIGenerateImageForm(
                **{
                    "workflow": ComfyUIWorkflow(
                        **{
                            "workflow": request.app.state.config.COMFYUI_WORKFLOW,
                            "nodes": request.app.state.config.COMFYUI_WORKFLOW_NODES,
                        }
                    ),
                    **data,
                }
            )
            res = await comfyui_generate_image(
                request.app.state.config.IMAGE_GENERATION_MODEL,
                form_data,
                user.id,
                request.app.state.config.COMFYUI_BASE_URL,
                request.app.state.config.COMFYUI_API_KEY,
            )
            log.debug(f"res: {res}")

            images = []

            for image in res["data"]:
                headers = None
                if request.app.state.config.COMFYUI_API_KEY:
                    headers = {
                        "Authorization": f"Bearer {request.app.state.config.COMFYUI_API_KEY}"
                    }

                image_data, content_type = load_url_image_data(image["url"], headers)
                url = await upload_image(
                    request,
                    form_data.model_dump(exclude_none=True),
                    image_data,
                    content_type,
                    user,
                )
                images.append({"url": url})
            return images
        elif (
            request.app.state.config.IMAGE_GENERATION_ENGINE == "automatic1111"
            or request.app.state.config.IMAGE_GENERATION_ENGINE == ""
        ):
            if form_data.model:
                set_image_model(form_data.model)

            data = {
                "prompt": form_data.prompt,
                "batch_size": form_data.n,
                "width": width,
                "height": height,
            }

            if request.app.state.config.IMAGE_STEPS is not None:
                data["steps"] = request.app.state.config.IMAGE_STEPS

            if form_data.negative_prompt is not None:
                data["negative_prompt"] = form_data.negative_prompt

            if request.app.state.config.AUTOMATIC1111_CFG_SCALE:
                data["cfg_scale"] = request.app.state.config.AUTOMATIC1111_CFG_SCALE

            if request.app.state.config.AUTOMATIC1111_SAMPLER:
                data["sampler_name"] = request.app.state.config.AUTOMATIC1111_SAMPLER

            if request.app.state.config.AUTOMATIC1111_SCHEDULER:
                data["scheduler"] = request.app.state.config.AUTOMATIC1111_SCHEDULER

            # Use asyncio.to_thread for the requests.post call
            r = await asyncio.to_thread(
                requests.post,
                url=f"{request.app.state.config.AUTOMATIC1111_BASE_URL}/sdapi/v1/txt2img",
                json=data,
                headers={"authorization": get_automatic1111_api_auth(request)},
            )

            res = r.json()
            log.debug(f"res: {res}")

            images = []

            for image in res["images"]:
                image_data, content_type = load_b64_image_data(image)
                url = await upload_image(
                    request,
                    {**data, "info": res["info"]},
                    image_data,
                    content_type,
                    user,
                )
                images.append({"url": url})
            return images
    except Exception as e:
        error = e
        if r != None:
            data = r.json()
            if "error" in data:
                error = data["error"]["message"]
        raise HTTPException(status_code=400, detail=ERROR_MESSAGES.DEFAULT(error))
