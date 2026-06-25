import asyncio
import hashlib
import json
import logging
import threading
import time
from typing import Optional, Tuple

import aiohttp
import requests
from aiocache import cached
from extension_modules.agent import UnifiedAgent
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from open_webui.config import (
    CACHE_DIR,
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    AIOHTTP_CLIENT_TIMEOUT,
    AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST,
    BYPASS_MODEL_ACCESS_CONTROL,
    ENABLE_FORWARD_USER_INFO_HEADERS,
    SRC_LOG_LEVELS,
)
from open_webui.models.chats import Chats
from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.models.users import UserModel
from open_webui.utils.access_control import has_access
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.crypto import (
    is_masked,
    mask_config_dict,
    mask_sensitive_value,
    resolve_config_dict,
)
from open_webui.utils.misc import (
    convert_logit_bias_input_to_json,
)
from open_webui.utils.payload import (
    apply_model_params_to_body_openai,
    apply_model_system_prompt_to_body,
)
from pydantic import BaseModel
from starlette.background import BackgroundTask

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["OPENAI"])


##########################################
#
# Utility functions
#
##########################################

_MAX_CHAT_INPUT_PREVIEW = 500
_MAX_CHAT_OUTPUT_PREVIEW = 1000


def _extract_chat_input_preview(
    messages: list, max_len: int = _MAX_CHAT_INPUT_PREVIEW
) -> str:
    """messages 배열에서 마지막 user 메시지를 추출."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):  # multi-part content blocks
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts)
            return content[:max_len] if isinstance(content, str) else ""
    return ""


def _enrich_usage_with_preview(
    usage_data: dict,
    input_preview: str,
    output_preview: str,
    messages_count: int,
    finish_reason: str = None,
    client_type: str = None,
) -> dict:
    """usage_data에 대화 로그 preview 정보를 추가."""
    enriched = dict(usage_data) if usage_data else {}
    enriched["request_summary"] = {
        "input_preview": input_preview,
        "message_count": messages_count,
    }
    if client_type:
        enriched["client_type"] = client_type
    if output_preview:
        enriched["output_preview"] = output_preview[:_MAX_CHAT_OUTPUT_PREVIEW]
    if finish_reason:
        enriched["finish_reason"] = finish_reason
    return enriched


async def stream_with_usage_tracking(
    response,
    session,
    user_id: str,
    chat_id: str,
    message_id: str,
    model_id: str,
    agent_id: str = None,
    task_type: str = None,
    input_preview: str = "",
    messages_count: int = 0,
    client_type: str = "web",
    is_external_service: bool = False,
):
    """
    스트리밍 응답을 래핑하여 usage 정보를 추출하고 기록합니다.
    OpenAI의 stream_options.include_usage=true 설정 시 마지막 청크에 usage가 포함됩니다.

    Args:
        task_type: 백그라운드 태스크 타입 (title_generation, tags_generation 등)
        input_preview: 채팅 입력 미리보기 (일반 채팅 시)
        messages_count: 메시지 수 (일반 채팅 시)
    """
    usage_data = None
    output_parts = []
    finish_reason = None

    try:
        async for chunk in response.content:
            yield chunk

            # SSE 청크에서 usage 정보 추출 시도
            try:
                chunk_str = chunk.decode("utf-8")
                for line in chunk_str.split("\n"):
                    if line.startswith("data: ") and line != "data: [DONE]":
                        json_str = line[6:]  # "data: " 제거
                        if json_str.strip():
                            data = json.loads(json_str)
                            # usage가 있는 청크 저장 (마지막 청크에 포함됨)
                            if "usage" in data and data["usage"]:
                                usage_data = data["usage"]

                            # 일반 채팅: output content 버퍼링
                            if not task_type:
                                choices = data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    if (
                                        content
                                        and len("".join(output_parts))
                                        < _MAX_CHAT_OUTPUT_PREVIEW
                                    ):
                                        output_parts.append(content)
                                    fr = choices[0].get("finish_reason")
                                    if fr:
                                        finish_reason = fr
            except Exception:
                # 파싱 실패 시 무시하고 계속 스트리밍
                pass
    finally:
        # 스트림 종료 후 세션 정리
        if response:
            response.close()
        if session:
            await session.close()

        # Usage 기록
        # 일반 채팅: chat_id와 message_id 필요
        # 백그라운드 태스크: chat_id만으로도 기록 (message_id는 task_type으로 대체 가능)
        should_record = (
            usage_data
            and (
                (chat_id and message_id)  # 일반 채팅
                or (chat_id and task_type)  # 백그라운드 태스크
                or is_external_service  # 외부 서비스(Presenton 등) API 키 호출, chat_id 없음
            )
        )

        if should_record:
            try:
                # 태스크인 경우 message_type을 task_type으로, message_id는 task_type 사용
                if task_type:
                    message_type = task_type
                    effective_message_id = message_id or f"task:{task_type}"
                elif is_external_service:
                    message_type = UsageMessageType.EXTERNAL_SERVICE
                    effective_message_id = None
                    chat_id = None
                else:
                    message_type = UsageMessageType.CHAT
                    effective_message_id = message_id

                # 일반 채팅: preview 정보 enrichment
                usage_to_save = usage_data
                if not task_type and not is_external_service and input_preview:
                    output_text = "".join(output_parts)
                    usage_to_save = _enrich_usage_with_preview(
                        usage_data,
                        input_preview,
                        output_text,
                        messages_count,
                        finish_reason,
                        client_type=client_type,
                    )

                Usages.insert_new_usage(
                    user_id=user_id,
                    chat_id=chat_id,
                    agent_id=agent_id,
                    model_id=model_id,
                    message_id=effective_message_id,
                    message_type=message_type,
                    total_tokens=usage_data.get("total_tokens", 0),
                    usage=usage_to_save,
                )
            except Exception as e:
                log.error(f"Failed to insert usage: {e}")


async def send_get_request(url, key=None, user: UserModel = None):
    timeout = aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(
                url,
                headers={
                    **({"Authorization": f"Bearer {key}"} if key else {}),
                    **(
                        {
                            "X-OpenWebUI-User-Name": user.name,
                            "X-OpenWebUI-User-Id": user.id,
                            "X-OpenWebUI-User-Email": user.email,
                            "X-OpenWebUI-User-Role": user.role,
                        }
                        if ENABLE_FORWARD_USER_INFO_HEADERS and user
                        else {}
                    ),
                },
            ) as response:
                return await response.json()
    except Exception as e:
        # Handle connection error here
        log.error(f"Connection error: {e}")
        return None


async def send_get_request_with_api_key(url, key=None):
    """Like send_get_request but uses api-key header (for Azure AI Foundry)."""
    timeout = aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(
                url,
                headers={
                    **({"api-key": key} if key else {}),
                    "Content-Type": "application/json",
                },
            ) as response:
                return await response.json()
    except Exception as e:
        log.error(f"Connection error: {e}")
        return None


def _resolve_vertex_ai_sa_key(api_config: dict, app=None) -> str:
    """Resolve Vertex AI service account key: individual or global fallback."""
    sa_key = api_config.get("service_account_key", "")
    # Treat masked values as empty (fallback to global key)
    if is_masked(sa_key):
        sa_key = ""
    if not sa_key and api_config.get("use_global_gcp_key") and app:
        sa_key = getattr(app.state.config, "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY", "")
    return sa_key


def _is_gcp_adc_enabled(app) -> bool:
    """Whether the workspace is configured to authenticate to GCP via ADC.

    True when the global GCP integration is marked enabled and no global service
    account key is set — i.e. token acquisition should defer to google.auth.default().
    """
    if app is None:
        return False
    config = app.state.config
    return bool(
        getattr(config, "GOOGLE_CLOUD_ENABLED", False)
        and not getattr(config, "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY", "")
    )


async def get_vertex_ai_models(api_config: dict, idx: int, app=None) -> dict:
    """
    Get available models from Vertex AI.
    Returns a list of Gemini models available in the specified project/location.
    """
    project_id = api_config.get("project_id", "")
    location = api_config.get("location", "us-central1")
    service_account_key = _resolve_vertex_ai_sa_key(api_config, app)
    use_adc = not service_account_key and _is_gcp_adc_enabled(app)

    if not project_id or (not service_account_key and not use_adc):
        log.warning("Vertex AI: Missing project_id or service_account_key")
        return None

    try:
        access_token = _get_vertex_ai_access_token(service_account_key)

        # Vertex AI models endpoint - list publisher models
        url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models"

        timeout = aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    log.error(
                        f"Vertex AI models error: {response.status} - {error_text}"
                    )
                    return None

                data = await response.json()
                log.debug(f"Vertex AI models response: {data}")

                # Transform to OpenAI-compatible format
                models = []
                for model in data.get("models", data.get("publisherModels", [])):
                    model_name = model.get("name", "")
                    model_id = (
                        model_name.split("/")[-1] if "/" in model_name else model_name
                    )

                    # Only include Gemini models that support chat
                    if "gemini" in model_id.lower():
                        models.append(
                            {
                                "id": model_id,
                                "name": model.get("displayName", model_id),
                                "owned_by": "google",
                                "openai": {"id": model_id},
                                "urlIdx": idx,
                            }
                        )

                if not models:
                    return None

                return {
                    "object": "list",
                    "data": models,
                }

    except Exception as e:
        log.error(f"Failed to get Vertex AI models: {e}")
        return None


async def cleanup_response(
    response: Optional[aiohttp.ClientResponse],
    session: Optional[aiohttp.ClientSession],
):
    if response:
        response.close()
    if session:
        await session.close()


def openai_o1_o3_handler(payload):
    """
    Handle o1, o3 specific parameters
    """
    if "max_tokens" in payload:
        # Remove "max_tokens" from the payload
        payload["max_completion_tokens"] = payload["max_tokens"]
        del payload["max_tokens"]

    # Fix: o1 and o3 do not support the "system" role directly.
    # For older models like "o1-mini" or "o1-preview", use role "user".
    # For newer o1/o3 models, replace "system" with "developer".
    if payload["messages"][0]["role"] == "system":
        model_lower = payload["model"].lower()
        if model_lower.startswith("o1-mini") or model_lower.startswith("o1-preview"):
            payload["messages"][0]["role"] = "user"
        else:
            payload["messages"][0]["role"] = "developer"

    return payload


##########################################
#
# Vertex AI Helper Functions
#
##########################################

# Cache for Vertex AI access tokens: cache_key -> (token, real_expiry_epoch).
# Guarded by per-key locks so async (run-in-threadpool) and sync callers share one
# refresh domain and never serve an expired token (root cause of intermittent 401s).
_vertex_ai_token_cache: dict[str, Tuple[str, float]] = {}
_vertex_ai_token_locks: dict[str, threading.Lock] = {}
_vertex_ai_locks_guard = threading.Lock()
# Refresh this many seconds BEFORE the token's real expiry.
_VERTEX_AI_TOKEN_BUFFER = 300


def _vertex_ai_lock_for(cache_key: str) -> threading.Lock:
    with _vertex_ai_locks_guard:
        lock = _vertex_ai_token_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _vertex_ai_token_locks[cache_key] = lock
        return lock


def _mint_vertex_ai_token(service_account_key: str) -> Tuple[str, float]:
    """Acquire a fresh access token and its REAL expiry epoch. Raises on failure."""
    from datetime import timezone

    import google.auth
    import google.auth.transport.requests

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    if not service_account_key:
        credentials, _ = google.auth.default(scopes=scopes)
    else:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(
            json.loads(service_account_key),
            scopes=scopes,
        )

    credentials.refresh(google.auth.transport.requests.Request())

    # Use the token's REAL expiry (credentials.expiry is naive UTC), not now + 3600.
    # The metadata server can return a token with much less than 1h remaining; the old
    # now+3600 assumption cached an already-expired token -> "access_token_expired" 401.
    if credentials.expiry:
        expiry = credentials.expiry.replace(tzinfo=timezone.utc).timestamp()
    else:
        expiry = time.time() + 3600
    return credentials.token, expiry


def _get_vertex_ai_access_token(
    service_account_key: str,
    force_refresh: bool = False,
    stale_token: Optional[str] = None,
) -> str:
    """
    Get a Google Cloud OAuth2 access token (SA key JSON, or ADC if key is empty).

    - Caches until the token's REAL expiry minus a buffer (proactive, lazy refresh).
    - force_refresh=True (used after an upstream 401) re-mints the token; stale_token
      lets concurrent 401 callers skip a redundant refresh if another already replaced
      the bad token.
    - Thread-safe via per-key lock so the blocking refresh + cache write are atomic
      across async (run-in-threadpool) and sync call paths.
    """
    use_adc = not service_account_key
    # Sentinel cache key for ADC to avoid hashing an empty string.
    cache_key = (
        "__adc__"
        if use_adc
        else hashlib.sha256(service_account_key.encode()).hexdigest()[:16]
    )

    def _fresh(entry: Optional[Tuple[str, float]]) -> bool:
        return bool(entry) and time.time() < entry[1] - _VERTEX_AI_TOKEN_BUFFER

    # Fast path: valid cached token and not a forced refresh.
    if not force_refresh:
        entry = _vertex_ai_token_cache.get(cache_key)
        if _fresh(entry):
            return entry[0]

    lock = _vertex_ai_lock_for(cache_key)
    with lock:
        entry = _vertex_ai_token_cache.get(cache_key)
        if force_refresh:
            # Someone may have already refreshed past the stale token while we waited.
            if (
                stale_token is not None
                and entry
                and entry[0] != stale_token
                and _fresh(entry)
            ):
                return entry[0]
        elif _fresh(entry):
            return entry[0]

        try:
            token, expiry = _mint_vertex_ai_token(service_account_key)
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
            hint = (
                " (ADC not configured — set GOOGLE_APPLICATION_CREDENTIALS, run 'gcloud auth application-default login', or run on GCP with a service account)"
                if use_adc
                else ""
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to authenticate with Google Cloud: {str(e)}{hint}",
            )

        # Cache only after a successful mint (no broken state on failure).
        _vertex_ai_token_cache[cache_key] = (token, expiry)
        return token


def _build_vertex_ai_url(
    project_id: str, location: str, model_id: str, stream: bool = False
) -> str:
    """
    Build Vertex AI Gemini API URL.

    Args:
        project_id: Google Cloud project ID
        location: Vertex AI location (e.g., us-central1, global)
        model_id: Model ID (e.g., gemini-2.0-flash, google/gemini-2.0-flash)
        stream: Whether to use streaming endpoint

    Returns:
        Full Vertex AI API URL
    """
    # Remove 'google/' prefix if present
    if model_id.startswith("google/"):
        model_id = model_id[7:]

    # Gemini 3 preview models require global endpoint
    # Also support explicit 'global' location setting
    is_global = location == "global" or model_id.startswith("gemini-3")

    if is_global:
        base = "https://aiplatform.googleapis.com"
        api_location = "global"
    else:
        base = f"https://{location}-aiplatform.googleapis.com"
        api_location = location

    # Use streamGenerateContent for streaming, generateContent for non-streaming
    endpoint = "streamGenerateContent" if stream else "generateContent"

    return f"{base}/v1/projects/{project_id}/locations/{api_location}/publishers/google/models/{model_id}:{endpoint}"


def _convert_openai_to_gemini(payload: dict) -> dict:
    """
    Convert OpenAI chat completion request to Gemini generateContent format.
    """
    messages = payload.get("messages", [])

    # Convert messages to Gemini format
    contents = []
    system_instruction = None

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            # Gemini uses systemInstruction for system messages
            system_instruction = {"parts": [{"text": content}]}
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:  # user
            contents.append({"role": "user", "parts": [{"text": content}]})

    gemini_request = {"contents": contents, "generationConfig": {}}

    if system_instruction:
        gemini_request["systemInstruction"] = system_instruction

    # Convert generation parameters
    if "max_tokens" in payload:
        gemini_request["generationConfig"]["maxOutputTokens"] = payload["max_tokens"]
    if "temperature" in payload:
        gemini_request["generationConfig"]["temperature"] = payload["temperature"]
    if "top_p" in payload:
        gemini_request["generationConfig"]["topP"] = payload["top_p"]
    if "stop" in payload:
        gemini_request["generationConfig"]["stopSequences"] = (
            payload["stop"] if isinstance(payload["stop"], list) else [payload["stop"]]
        )

    return gemini_request


def _convert_gemini_to_openai(gemini_response: dict, model: str) -> dict:
    """
    Convert Gemini generateContent response to OpenAI chat completion format.
    """
    candidates = gemini_response.get("candidates", [])

    choices = []
    for i, candidate in enumerate(candidates):
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        text = "".join(part.get("text", "") for part in parts)

        finish_reason = candidate.get("finishReason", "stop")
        # Map Gemini finish reasons to OpenAI
        finish_reason_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
        }

        choices.append(
            {
                "index": i,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason_map.get(finish_reason, "stop"),
            }
        )

    # Build usage info
    usage_metadata = gemini_response.get("usageMetadata", {})
    usage = {
        "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
        "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
        "total_tokens": usage_metadata.get("totalTokenCount", 0),
    }

    return {
        "id": f"chatcmpl-{gemini_response.get('modelVersion', 'gemini')}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
        "usage": usage,
    }


async def _stream_gemini_to_openai(
    response,
    model: str,
    user_id: str = None,
    chat_id: str = None,
    message_id: str = None,
    agent_id: str = None,
    task_type: str = None,
    input_preview: str = "",
    messages_count: int = 0,
    client_type: str = "web",
):
    """
    Convert streaming Gemini response to OpenAI SSE format with usage tracking.
    """
    buffer = ""
    usage_data = None
    output_parts = []
    gemini_finish_reason = None

    async for chunk in response.content:
        buffer += chunk.decode("utf-8")

        # Process complete JSON objects from buffer
        while True:
            # Find complete JSON object (ends with newline or is the full response)
            try:
                # Try to parse as JSON array element
                if buffer.strip().startswith("["):
                    buffer = buffer.strip()[1:]  # Remove opening bracket
                if buffer.strip().startswith(","):
                    buffer = buffer.strip()[1:]  # Remove comma
                if buffer.strip() == "]":
                    break

                # Find the end of current JSON object
                brace_count = 0
                json_end = -1
                in_string = False
                escape_next = False

                for i, char in enumerate(buffer):
                    if escape_next:
                        escape_next = False
                        continue
                    if char == "\\":
                        escape_next = True
                        continue
                    if char == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if char == "{":
                        brace_count += 1
                    elif char == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break

                if json_end == -1:
                    break  # Need more data

                json_str = buffer[:json_end]
                buffer = buffer[json_end:]

                gemini_chunk = json.loads(json_str)

                # Convert to OpenAI SSE format
                candidates = gemini_chunk.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    text = "".join(part.get("text", "") for part in parts)

                    if text:
                        openai_chunk = {
                            "id": f"chatcmpl-{int(time.time())}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": text},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(openai_chunk)}\n\n".encode()

                        # 일반 채팅: output content 버퍼링
                        if (
                            not task_type
                            and len("".join(output_parts)) < _MAX_CHAT_OUTPUT_PREVIEW
                        ):
                            output_parts.append(text)

                # Check for finish and capture usage
                chunk_finish_reason = (
                    candidates[0].get("finishReason") if candidates else None
                )
                if chunk_finish_reason:
                    gemini_finish_reason = chunk_finish_reason
                    # Send final chunk with finish_reason
                    final_chunk = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }

                    # Capture usage if available
                    usage_metadata = gemini_chunk.get("usageMetadata", {})
                    if usage_metadata:
                        usage_data = {
                            "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                            "completion_tokens": usage_metadata.get(
                                "candidatesTokenCount", 0
                            ),
                            "total_tokens": usage_metadata.get("totalTokenCount", 0),
                        }
                        final_chunk["usage"] = usage_data

                    yield f"data: {json.dumps(final_chunk)}\n\n".encode()

            except json.JSONDecodeError:
                break  # Need more data

    yield b"data: [DONE]\n\n"

    # Record usage after streaming completes
    if usage_data and user_id:
        should_record = (chat_id and message_id) or (chat_id and task_type)
        if should_record:
            try:
                if task_type:
                    message_type = task_type
                    effective_message_id = message_id or f"task:{task_type}"
                else:
                    message_type = UsageMessageType.CHAT
                    effective_message_id = message_id

                # 일반 채팅: preview 정보 enrichment
                usage_to_save = usage_data
                if not task_type and input_preview:
                    output_text = "".join(output_parts)
                    usage_to_save = _enrich_usage_with_preview(
                        usage_data,
                        input_preview,
                        output_text,
                        messages_count,
                        gemini_finish_reason,
                        client_type=client_type,
                    )

                Usages.insert_new_usage(
                    user_id=user_id,
                    chat_id=chat_id,
                    agent_id=agent_id,
                    model_id=model,
                    message_id=effective_message_id,
                    message_type=message_type,
                    total_tokens=usage_data.get("total_tokens", 0),
                    usage=usage_to_save,
                )
                log.debug(f"Vertex AI usage recorded: {usage_data}")
            except Exception as e:
                log.error(f"Failed to insert Vertex AI usage: {e}")


##########################################
#
# API routes
#
##########################################

router = APIRouter()


@router.get("/config")
async def get_config(request: Request, user=Depends(get_admin_user)):
    return mask_config_dict(
        {
            "ENABLE_OPENAI_API": request.app.state.config.ENABLE_OPENAI_API,
            "OPENAI_API_BASE_URLS": request.app.state.config.OPENAI_API_BASE_URLS,
            "OPENAI_API_KEYS": request.app.state.config.OPENAI_API_KEYS,
            "OPENAI_API_CONFIGS": request.app.state.config.OPENAI_API_CONFIGS,
        }
    )


class OpenAIConfigForm(BaseModel):
    ENABLE_OPENAI_API: Optional[bool] = None
    OPENAI_API_BASE_URLS: list[str]
    OPENAI_API_KEYS: list[str]
    OPENAI_API_CONFIGS: dict


def _get_configured_model_ids(api_configs: dict) -> set:
    """OPENAI_API_CONFIGS에서 명시적으로 지정된 model_ids를 추출 (prefix 적용 포함)."""
    model_ids = set()
    for api_config in api_configs.values():
        ids = api_config.get("model_ids", [])
        prefix = api_config.get("prefix_id", None)
        for model_id in ids:
            full_id = f"{prefix}.{model_id}" if prefix else model_id
            model_ids.add(full_id)
    return model_ids


@router.post("/config/update")
async def update_config(
    request: Request, form_data: OpenAIConfigForm, user=Depends(get_admin_user)
):
    request.app.state.config.ENABLE_OPENAI_API = form_data.ENABLE_OPENAI_API

    # Snapshot previous state BEFORE overwriting so masked secrets can be
    # resolved back to their real values.
    #
    # A masked placeholder ("***...wxyz") is resolved by matching its masked
    # value against the previous keys — NOT by list index (delete/reorder
    # shifts it) and NOT by base URL. The URL is unreliable: it can change
    # between save and resave (the UI strips trailing slashes, an admin may
    # edit the endpoint) and several connections may share one URL. Matching on
    # the masked value itself — which encodes a stable suffix — keeps each key
    # tied to its own connection regardless of order, URL edits, or duplicate
    # URLs. (Earlier URL-based matching silently wiped a key whenever its URL
    # was edited or normalized.)
    prev_urls = list(request.app.state.config.OPENAI_API_BASE_URLS or [])
    prev_keys = list(request.app.state.config.OPENAI_API_KEYS or [])
    prev_configs = dict(request.app.state.config.OPENAI_API_CONFIGS or {})

    new_urls = form_data.OPENAI_API_BASE_URLS
    new_keys = list(form_data.OPENAI_API_KEYS or [])

    def _prev_key(j) -> str:
        return prev_keys[j] if j is not None and 0 <= j < len(prev_keys) else ""

    # Previous slots grouped by masked value (suffix identity) and by URL.
    prev_slots_by_mask: dict[str, list[int]] = {}
    prev_slots_by_url: dict[str, list[int]] = {}
    for j, k in enumerate(prev_keys):
        prev_slots_by_mask.setdefault(mask_sensitive_value(k), []).append(j)
    for j, u in enumerate(prev_urls):
        prev_slots_by_url.setdefault(u, []).append(j)

    # Map each new connection to the previous slot it descends from.
    matched_prev = [None] * len(new_urls)
    consumed: set[int] = set()

    # Pass 1: masked key → previous slot with the same masked value. When more
    # than one previous key masks identically, prefer the slot whose URL also
    # matches so duplicate-URL connections stay paired with their own slot.
    for i, url in enumerate(new_urls):
        nv = new_keys[i] if i < len(new_keys) else ""
        if not (isinstance(nv, str) and is_masked(nv)):
            continue
        chosen = None
        for j in prev_slots_by_mask.get(nv, []):
            if j in consumed:
                continue
            if chosen is None:
                chosen = j
            if j < len(prev_urls) and prev_urls[j] == url:
                chosen = j
                break
        if chosen is not None:
            matched_prev[i] = chosen
            consumed.add(chosen)

    # Pass 2: connections sent with a real (non-masked) key → align to a
    # previous slot on the same URL (best-effort) so their per-connection config
    # secrets still resolve. A masked key left unmatched above stays unresolved
    # (cleared) rather than risk restoring another connection's secret.
    for i, url in enumerate(new_urls):
        nv = new_keys[i] if i < len(new_keys) else ""
        if matched_prev[i] is not None or (isinstance(nv, str) and is_masked(nv)):
            continue
        for j in prev_slots_by_url.get(url, []):
            if j not in consumed:
                matched_prev[i] = j
                consumed.add(j)
                break

    request.app.state.config.OPENAI_API_BASE_URLS = new_urls

    # Restore masked keys from their matched connection; keep real keys as sent.
    resolved_keys = []
    for i, nv in enumerate(new_keys):
        j = matched_prev[i] if i < len(matched_prev) else None
        if isinstance(nv, str) and is_masked(nv):
            resolved_keys.append(_prev_key(j))
        else:
            resolved_keys.append(nv)
    request.app.state.config.OPENAI_API_KEYS = resolved_keys

    # Check if API KEYS length is same than API URLS length
    if len(request.app.state.config.OPENAI_API_KEYS) != len(new_urls):
        if len(request.app.state.config.OPENAI_API_KEYS) > len(new_urls):
            request.app.state.config.OPENAI_API_KEYS = (
                request.app.state.config.OPENAI_API_KEYS[: len(new_urls)]
            )
        else:
            request.app.state.config.OPENAI_API_KEYS += [""] * (
                len(new_urls) - len(request.app.state.config.OPENAI_API_KEYS)
            )

    # Capture old model_ids before overwriting config
    old_model_ids = _get_configured_model_ids(prev_configs)

    # Align each new connection's previous config from its matched slot before
    # resolving masked sensitive values inside them (mirrors the key matching,
    # so a same-URL connection's config secrets are not collapsed either).
    aligned_prev_configs = {
        str(i): (
            prev_configs.get(str(matched_prev[i]), {})
            if matched_prev[i] is not None
            else {}
        )
        for i in range(len(new_urls))
    }
    request.app.state.config.OPENAI_API_CONFIGS = resolve_config_dict(
        form_data.OPENAI_API_CONFIGS,
        aligned_prev_configs,
    )

    # Remove the API configs that are not in the API URLS
    keys = list(map(str, range(len(new_urls))))
    request.app.state.config.OPENAI_API_CONFIGS = {
        key: value
        for key, value in request.app.state.config.OPENAI_API_CONFIGS.items()
        if key in keys
    }

    # Sync model table: add new model_ids, delete removed model_ids
    new_model_ids = _get_configured_model_ids(
        request.app.state.config.OPENAI_API_CONFIGS
    )

    for model_id in old_model_ids - new_model_ids:
        Models.delete_model_by_id(model_id)

    for model_id in new_model_ids - old_model_ids:
        if not Models.get_model_by_id(model_id):
            Models.insert_new_model(
                ModelForm(
                    id=model_id,
                    base_model_id=None,
                    name=model_id,
                    meta=ModelMeta(),
                    params=ModelParams(),
                    access_control=None,
                    is_active=True,
                ),
                user.id,
            )

    AuditLogger.log_settings_change(
        "connections/openai", after_data=form_data.model_dump()
    )
    return mask_config_dict(
        {
            "ENABLE_OPENAI_API": request.app.state.config.ENABLE_OPENAI_API,
            "OPENAI_API_BASE_URLS": request.app.state.config.OPENAI_API_BASE_URLS,
            "OPENAI_API_KEYS": request.app.state.config.OPENAI_API_KEYS,
            "OPENAI_API_CONFIGS": request.app.state.config.OPENAI_API_CONFIGS,
        }
    )


@router.post("/audio/speech")
async def speech(request: Request, user=Depends(get_verified_user)):
    idx = None
    try:
        idx = request.app.state.config.OPENAI_API_BASE_URLS.index(
            "https://api.openai.com/v1"
        )

        body = await request.body()
        name = hashlib.sha256(body).hexdigest()

        SPEECH_CACHE_DIR = CACHE_DIR / "audio" / "speech"
        SPEECH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        file_path = SPEECH_CACHE_DIR.joinpath(f"{name}.mp3")
        file_body_path = SPEECH_CACHE_DIR.joinpath(f"{name}.json")

        # Check if the file already exists in the cache
        if file_path.is_file():
            return FileResponse(file_path)

        url = request.app.state.config.OPENAI_API_BASE_URLS[idx]

        r = None
        try:
            r = requests.post(
                url=f"{url}/audio/speech",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {request.app.state.config.OPENAI_API_KEYS[idx]}",
                    **(
                        {
                            "HTTP-Referer": "https://cloosphere.com/",
                            "X-Title": "ClooSphere",
                        }
                        if "openrouter.ai" in url
                        else {}
                    ),
                    **(
                        {
                            "X-OpenWebUI-User-Name": user.name,
                            "X-OpenWebUI-User-Id": user.id,
                            "X-OpenWebUI-User-Email": user.email,
                            "X-OpenWebUI-User-Role": user.role,
                        }
                        if ENABLE_FORWARD_USER_INFO_HEADERS
                        else {}
                    ),
                },
                stream=True,
            )

            r.raise_for_status()

            # Save the streaming content to a file
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            with open(file_body_path, "w") as f:
                json.dump(json.loads(body.decode("utf-8")), f)

            # Return the saved file
            return FileResponse(file_path)

        except Exception as e:
            log.exception(e)

            detail = None
            if r is not None:
                try:
                    res = r.json()
                    if "error" in res:
                        detail = f"External: {res['error']}"
                except Exception:
                    detail = f"External: {e}"

            raise HTTPException(
                status_code=r.status_code if r else 500,
                detail=detail if detail else "Server Connection Error",
            )

    except ValueError:
        raise HTTPException(status_code=401, detail=ERROR_MESSAGES.OPENAI_NOT_FOUND)


async def get_all_models_responses(request: Request, user: UserModel) -> list:
    if not request.app.state.config.ENABLE_OPENAI_API:
        return []

    # Check if API KEYS length is same than API URLS length
    num_urls = len(request.app.state.config.OPENAI_API_BASE_URLS)
    num_keys = len(request.app.state.config.OPENAI_API_KEYS)

    if num_keys != num_urls:
        # if there are more keys than urls, remove the extra keys
        if num_keys > num_urls:
            new_keys = request.app.state.config.OPENAI_API_KEYS[:num_urls]
            request.app.state.config.OPENAI_API_KEYS = new_keys
        # if there are more urls than keys, add empty keys
        else:
            request.app.state.config.OPENAI_API_KEYS += [""] * (num_urls - num_keys)

    request_tasks = []
    for idx, url in enumerate(request.app.state.config.OPENAI_API_BASE_URLS):
        if (str(idx) not in request.app.state.config.OPENAI_API_CONFIGS) and (
            url not in request.app.state.config.OPENAI_API_CONFIGS  # Legacy support
        ):
            request_tasks.append(
                send_get_request(
                    f"{url}/models",
                    request.app.state.config.OPENAI_API_KEYS[idx],
                    user=user,
                )
            )
        else:
            api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
                str(idx),
                request.app.state.config.OPENAI_API_CONFIGS.get(
                    url, {}
                ),  # Legacy support
            )

            enable = api_config.get("enable", True)
            model_ids = api_config.get("model_ids", [])
            provider_type = api_config.get("provider_type", "openai")

            if enable:
                if len(model_ids) == 0:
                    # No explicit model IDs - fetch from API
                    if provider_type == "vertex-ai":
                        # Use Vertex AI specific model fetching
                        request_tasks.append(
                            get_vertex_ai_models(api_config, idx, app=request.app)
                        )
                    elif provider_type == "azure-ai-foundry":
                        # Azure AI Foundry — OpenAI-compatible via /openai/v1
                        request_tasks.append(
                            send_get_request(
                                f"{url}/openai/v1/models",
                                request.app.state.config.OPENAI_API_KEYS[idx],
                                user=user,
                            )
                        )
                    else:
                        # Standard OpenAI-compatible model fetching
                        request_tasks.append(
                            send_get_request(
                                f"{url}/models",
                                request.app.state.config.OPENAI_API_KEYS[idx],
                                user=user,
                            )
                        )
                else:
                    # Use explicit model IDs from config
                    owned_by = (
                        "google"
                        if provider_type == "vertex-ai"
                        else "azure"
                        if provider_type in ("azure-openai", "azure-ai-foundry")
                        else "openai"
                    )
                    model_list = {
                        "object": "list",
                        "data": [
                            {
                                "id": model_id,
                                "name": model_id,
                                "owned_by": owned_by,
                                "openai": {"id": model_id},
                                "urlIdx": idx,
                            }
                            for model_id in model_ids
                        ],
                    }

                    request_tasks.append(
                        asyncio.ensure_future(asyncio.sleep(0, model_list))
                    )
            else:
                request_tasks.append(asyncio.ensure_future(asyncio.sleep(0, None)))

    responses = await asyncio.gather(*request_tasks)

    for idx, response in enumerate(responses):
        if response:
            url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
            api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
                str(idx),
                request.app.state.config.OPENAI_API_CONFIGS.get(
                    url, {}
                ),  # Legacy support
            )

            prefix_id = api_config.get("prefix_id", None)
            tags = api_config.get("tags", [])

            if prefix_id:
                for model in (
                    response if isinstance(response, list) else response.get("data", [])
                ):
                    model["id"] = f"{prefix_id}.{model['id']}"

            if tags:
                for model in (
                    response if isinstance(response, list) else response.get("data", [])
                ):
                    model["tags"] = tags

    log.debug(f"get_all_models:responses() {responses}")
    return responses


async def get_filtered_models(models, user):
    # Filter models based on user access control
    filtered_models = []
    for model in models.get("data", []):
        model_info = Models.get_model_by_id(model["id"])
        if model_info:
            if user.id == model_info.user_id or has_access(
                user.id, type="read", access_control=model_info.access_control
            ):
                filtered_models.append(model)
    return filtered_models


@cached(ttl=1)
async def get_all_models(request: Request, user: UserModel) -> dict[str, list]:
    log.info("get_all_models()")

    if not request.app.state.config.ENABLE_OPENAI_API:
        return {"data": []}

    responses = await get_all_models_responses(request, user=user)

    def extract_data(response):
        if response and "data" in response:
            return response["data"]
        if isinstance(response, list):
            return response
        return None

    def merge_models_lists(model_lists):
        log.debug(f"merge_models_lists {model_lists}")
        merged_list = []

        for idx, models in enumerate(model_lists):
            if models is not None and "error" not in models:
                merged_list.extend(
                    [
                        {
                            **model,
                            "name": model.get("name", model["id"]),
                            "owned_by": "openai",
                            "openai": model,
                            "urlIdx": idx,
                        }
                        for model in models
                        if (model.get("id") or model.get("name"))
                        and (
                            "api.openai.com"
                            not in request.app.state.config.OPENAI_API_BASE_URLS[idx]
                            or not any(
                                name in model["id"]
                                for name in [
                                    "babbage",
                                    "dall-e",
                                    "davinci",
                                    "embedding",
                                    "tts",
                                    "whisper",
                                ]
                            )
                        )
                    ]
                )

        return merged_list

    models = {"data": merge_models_lists(map(extract_data, responses))}
    log.debug(f"models: {models}")

    request.app.state.OPENAI_MODELS = {model["id"]: model for model in models["data"]}
    return models


@router.get("/models")
@router.get("/models/{url_idx}")
async def get_models(
    request: Request, url_idx: Optional[int] = None, user=Depends(get_verified_user)
):
    models = {
        "data": [],
    }

    if url_idx is None:
        models = await get_all_models(request, user=user)
    else:
        # Validate url_idx bounds
        urls = request.app.state.config.OPENAI_API_BASE_URLS
        keys = request.app.state.config.OPENAI_API_KEYS
        if url_idx >= len(urls) or url_idx >= len(keys):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid connection index: {url_idx}. Available connections: {len(urls)}",
            )

        url = urls[url_idx]
        key = keys[url_idx]

        r = None
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
        ) as session:
            try:
                async with session.get(
                    f"{url}/models",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        **(
                            {
                                "X-OpenWebUI-User-Name": user.name,
                                "X-OpenWebUI-User-Id": user.id,
                                "X-OpenWebUI-User-Email": user.email,
                                "X-OpenWebUI-User-Role": user.role,
                            }
                            if ENABLE_FORWARD_USER_INFO_HEADERS
                            else {}
                        ),
                    },
                ) as r:
                    if r.status != 200:
                        # Extract response error details if available
                        error_detail = f"HTTP Error: {r.status}"
                        try:
                            res = await r.json()
                            if "error" in res:
                                error_detail = f"External Error: {res['error']}"
                        except Exception:
                            # Response might be HTML or non-JSON (e.g., Vertex AI 404)
                            pass
                        raise Exception(error_detail)

                    response_data = await r.json()

                    # Check if we're calling OpenAI API based on the URL
                    if "api.openai.com" in url:
                        # Filter models according to the specified conditions
                        response_data["data"] = [
                            model
                            for model in response_data.get("data", [])
                            if not any(
                                name in model["id"]
                                for name in [
                                    "babbage",
                                    "dall-e",
                                    "davinci",
                                    "embedding",
                                    "tts",
                                    "whisper",
                                ]
                            )
                        ]

                    models = response_data
            except aiohttp.ClientError as e:
                # ClientError covers all aiohttp requests issues
                log.warning(f"Client error for connection {url_idx} ({url}): {str(e)}")
                # Return empty models instead of failing - connection might not support /models
                models = {"data": []}
            except Exception as e:
                log.warning(
                    f"Failed to get models for connection {url_idx} ({url}): {e}"
                )
                # Return empty models instead of failing - some providers don't support /models endpoint
                models = {"data": []}

    if user.role == "user" and not BYPASS_MODEL_ACCESS_CONTROL:
        models["data"] = await get_filtered_models(models, user)

    return models


class ConnectionVerificationForm(BaseModel):
    url: str
    key: str
    idx: Optional[int] = None  # index into OPENAI_API_KEYS for resolving masked keys
    api_version: Optional[str] = None


def _set_provider(api_config: dict) -> dict:
    """
    Set provider-specific configurations.

    Args:
        api_config: API configuration dictionary

    Returns:
        Updated API configuration
    """
    provider_type = api_config.get("provider_type", "openai")

    if provider_type == "azure-openai":
        api_config["api_version"] = api_config.get("api_version", "2024-02-15-preview")

    elif provider_type == "azure-ai-foundry":
        api_config["api_version"] = api_config.get("api_version", "2024-05-01-preview")

    elif provider_type == "vertex-ai":
        # Vertex AI configuration
        api_config["project_id"] = api_config.get("project_id", "")
        api_config["location"] = api_config.get("location", "us-central1")
        api_config["service_account_key"] = api_config.get("service_account_key", "")

    elif provider_type == "vertex-gemini":
        # Legacy vertex-gemini support (for ReAct agents)
        api_config["json_credentials"] = api_config.get("json_credentials", {})

    return api_config


class VertexAIVerificationForm(BaseModel):
    project_id: str
    location: str = "us-central1"
    service_account_key: str = ""
    use_global_gcp_key: bool = False
    idx: Optional[int] = None


class AzureOpenAIVerificationForm(BaseModel):
    url: str
    key: str
    api_version: str = "2024-02-15-preview"
    idx: Optional[int] = None


@router.post("/verify/azure-openai")
async def verify_azure_openai_connection(
    request: Request,
    form_data: AzureOpenAIVerificationForm,
    user=Depends(get_admin_user),
):
    """
    Verify Azure OpenAI connection by listing deployments.
    Azure OpenAI uses a different endpoint format than standard OpenAI.
    """
    url = form_data.url.rstrip("/")
    key = _resolve_masked_api_key(request, url, form_data.key, form_data.idx)
    api_version = form_data.api_version

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    if not key or is_masked(key):
        raise HTTPException(status_code=400, detail="API Key is required")

    headers = {"api-key": key}

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
        trust_env=True,
    ) as session:
        try:
            # 사용자 API 버전으로 모델 목록 조회 (URL + Key + API Version 동시 검증)
            verify_url = f"{url}/openai/models?api-version={api_version}"
            log.debug(f"Azure OpenAI verify URL: {verify_url}")

            async with session.get(verify_url, headers=headers) as r:
                if r.status != 200:
                    error_detail = f"HTTP Error: {r.status}"
                    try:
                        res = await r.json()
                        if "error" in res:
                            error_msg = res["error"]
                            if isinstance(error_msg, dict):
                                error_detail = f"Azure OpenAI: {error_msg.get('message', error_msg)}"
                            else:
                                error_detail = f"Azure OpenAI: {error_msg}"
                    except Exception:
                        error_text = await r.text()
                        error_detail = f"Azure OpenAI: {error_text[:200]}"
                    raise HTTPException(status_code=r.status, detail=error_detail)

                response_data = await r.json()

                # /openai/models 응답에서 모델 목록 추출
                raw_models = response_data.get("data", [])
                models = []
                seen = set()
                for m in raw_models:
                    model_id = m.get("id", "")
                    if model_id and model_id not in seen:
                        seen.add(model_id)
                        models.append(
                            {
                                "id": model_id,
                                "name": model_id,
                                "owned_by": m.get("owned_by", "azure"),
                            }
                        )

            return {
                "status": "success",
                "message": "Connection verified",
                "model_count": len(models),
                "data": models,
            }

        except HTTPException:
            raise
        except aiohttp.ClientError as e:
            log.exception(f"Azure OpenAI client error: {str(e)}")
            raise HTTPException(
                status_code=500, detail="Azure OpenAI: Server Connection Error"
            )
        except Exception as e:
            log.exception(f"Azure OpenAI unexpected error: {e}")
            raise HTTPException(status_code=500, detail=f"Azure OpenAI: {str(e)}")


@router.post("/verify/azure-ai-foundry")
async def verify_azure_ai_foundry_connection(
    request: Request,
    form_data: ConnectionVerificationForm,
    user=Depends(get_admin_user),
):
    """
    Verify Azure AI Foundry connection by calling /models endpoint.
    Azure AI Foundry serverless API uses api-key header for authentication.
    """
    url = form_data.url.rstrip("/")
    key = _resolve_masked_api_key(request, url, form_data.key, form_data.idx)

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    if not key:
        raise HTTPException(status_code=400, detail="API Key is required")

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
        trust_env=True,
    ) as session:
        try:
            verify_url = f"{url}/openai/v1/models"

            async with session.get(
                verify_url,
                headers={
                    "Authorization": f"Bearer {key}",
                },
            ) as r:
                if r.status != 200:
                    error_detail = f"HTTP Error: {r.status}"
                    try:
                        res = await r.json()
                        if "error" in res:
                            error_msg = res["error"]
                            if isinstance(error_msg, dict):
                                error_detail = f"Azure AI Foundry: {error_msg.get('message', error_msg)}"
                            else:
                                error_detail = f"Azure AI Foundry: {error_msg}"
                    except Exception:
                        error_text = await r.text()
                        error_detail = f"Azure AI Foundry: {error_text[:200]}"
                    raise HTTPException(status_code=r.status, detail=error_detail)

                response_data = await r.json()

                models = []
                model_data = response_data.get("data", [])
                for model in model_data:
                    model_id = model.get("id", "")
                    if model_id:
                        models.append(
                            {
                                "id": model_id,
                                "name": model_id,
                                "owned_by": model.get("owned_by", "azure"),
                            }
                        )

                return {
                    "status": "success",
                    "message": "Connection verified",
                    "model_count": len(models),
                    "data": models,
                }

        except HTTPException:
            raise
        except aiohttp.ClientError as e:
            log.exception(f"Azure AI Foundry client error: {str(e)}")
            raise HTTPException(
                status_code=500, detail="Azure AI Foundry: Server Connection Error"
            )
        except Exception as e:
            log.exception(f"Azure AI Foundry unexpected error: {e}")
            raise HTTPException(status_code=500, detail=f"Azure AI Foundry: {str(e)}")


@router.post("/verify/vertex-ai")
async def verify_vertex_ai_connection(
    request: Request,
    form_data: VertexAIVerificationForm,
    user=Depends(get_admin_user),
):
    """
    Verify Vertex AI connection and return available models.
    """
    project_id = form_data.project_id
    location = form_data.location

    sa_key = form_data.service_account_key
    # Resolve masked service_account_key from stored API configs
    if is_masked(sa_key):
        stored_configs = request.app.state.config.OPENAI_API_CONFIGS
        # Try by explicit index
        if form_data.idx is not None:
            stored_config = stored_configs.get(str(form_data.idx), {})
            sa_key = stored_config.get("service_account_key", sa_key)
        else:
            # Fallback: match by project_id + location
            for cfg in stored_configs.values():
                if (
                    cfg.get("provider_type") == "vertex-ai"
                    and cfg.get("project_id") == form_data.project_id
                    and cfg.get("location", "us-central1") == form_data.location
                ):
                    sa_key = cfg.get("service_account_key", sa_key)
                    break

    service_account_key = _resolve_vertex_ai_sa_key(
        {
            "service_account_key": sa_key,
            "use_global_gcp_key": form_data.use_global_gcp_key,
        },
        request.app,
    )

    if not project_id:
        raise HTTPException(status_code=400, detail="Project ID is required")

    if is_masked(service_account_key):
        service_account_key = ""

    if not service_account_key and not _is_gcp_adc_enabled(request.app):
        raise HTTPException(status_code=400, detail="Service Account Key is required")

    try:
        # Get OAuth2 access token - this verifies the service account credentials
        access_token = _get_vertex_ai_access_token(service_account_key)

        # Vertex AI doesn't have a models listing API for OpenAI-compatible endpoint
        # Just verify the token works by checking it was obtained successfully
        log.info(
            f"Vertex AI connection verified for project {project_id} (token obtained)"
        )

        return {
            "status": "success",
            "message": "Connection verified",
            "models": [],
        }

    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Vertex AI verification failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Vertex AI connection failed: {str(e)}",
        )


def _resolve_masked_api_key(
    request: Request, url: str, key: str, idx: int = None
) -> str:
    """Resolve a masked API key against stored keys by index or URL matching."""
    if not is_masked(key):
        return key

    stored_urls = request.app.state.config.OPENAI_API_BASE_URLS
    stored_keys = request.app.state.config.OPENAI_API_KEYS

    # Try by explicit index first
    if idx is not None and 0 <= idx < len(stored_keys):
        return stored_keys[idx]

    # Fallback: match by URL
    for i, stored_url in enumerate(stored_urls):
        if stored_url == url and i < len(stored_keys):
            return stored_keys[i]

    return key  # return as-is if no match


@router.post("/verify")
async def verify_connection(
    request: Request,
    form_data: ConnectionVerificationForm,
    user=Depends(get_admin_user),
):
    url = form_data.url
    key = _resolve_masked_api_key(request, url, form_data.key, form_data.idx)

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
        trust_env=True,
    ) as session:
        try:
            async with session.get(
                f"{url}/models",
                headers={
                    "Authorization": f"Bearer {key}",
                    **(
                        {
                            "X-OpenWebUI-User-Name": user.name,
                            "X-OpenWebUI-User-Id": user.id,
                            "X-OpenWebUI-User-Email": user.email,
                            "X-OpenWebUI-User-Role": user.role,
                        }
                        if ENABLE_FORWARD_USER_INFO_HEADERS
                        else {}
                    ),
                },
            ) as r:
                if r.status != 200:
                    # Extract response error details if available
                    error_detail = f"HTTP Error: {r.status}"
                    try:
                        res = await r.json()
                        if "error" in res:
                            error_detail = f"External Error: {res['error']}"
                    except Exception:
                        pass
                    raise Exception(error_detail)

                response_data = await r.json()
                return response_data

        except aiohttp.ClientError as e:
            log.exception(f"Client error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Server Connection Error: {e}")
        except Exception as e:
            log.exception(f"Unexpected error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


async def _handle_agent_flow(
    request: Request,
    flow_id: str,
    payload: dict,
    metadata: dict,
    user,
    bypass_filter: bool = False,
):
    """Handle Agent Flow execution."""
    from extension_modules.agent_flow.agent_flow_runner import AgentFlowRunner
    from open_webui.models.models import Models

    # Get flow model from Models table
    flow_model = Models.get_model_by_id(flow_id)
    if not flow_model:
        raise HTTPException(status_code=404, detail=f"Flow not found: {flow_id}")

    # Verify this is an agent flow model
    meta = flow_model.meta.model_dump() if flow_model.meta else {}
    if meta.get("type") != "agent_flow":
        raise HTTPException(
            status_code=400, detail=f"Model is not an agent flow: {flow_id}"
        )

    # Check access control
    if not bypass_filter and user.role != "admin":
        if not (
            user.id == flow_model.user_id
            or has_access(
                user.id, type="read", access_control=flow_model.access_control
            )
        ):
            raise HTTPException(status_code=403, detail="Model not found")

    if not flow_model.is_active:
        raise HTTPException(
            status_code=400, detail=f"Flow is not active: {flow_model.name}"
        )

    # Set trace context on request for flow tracing
    try:
        from open_webui.utils.tracing import create_trace_context, set_trace_context

        chat_id = metadata.get("chat_id") if metadata else None
        message_id = metadata.get("message_id") if metadata else None
        if (
            not hasattr(request.state, "trace_context")
            or not request.state.trace_context
        ):
            tc = create_trace_context(
                user_id=user.id,
                chat_id=chat_id,
                message_id=message_id,
            )
            set_trace_context(request, tc)
    except Exception:
        pass

    # Get flow_data from meta
    flow_data = meta.get("flow_data", {})

    # Resolve the correct API endpoint for the flow's models
    # Find the most commonly used endpoint from flow nodes, or use model lookup
    api_config = {}
    url = ""
    key = ""

    # Try to find correct endpoint by looking up models in the flow
    await get_all_models(request, user=user)
    flow_nodes = flow_data.get("nodes", [])
    resolved_idx = None
    for fnode in flow_nodes:
        fdata = fnode.get("data", {})
        rid = fdata.get("resourceId") or (fdata.get("config") or {}).get("modelId")
        if rid:
            # Check if it's a registered model with base_model_id
            fmodel = Models.get_model_by_id(rid)
            base_id = fmodel.base_model_id if fmodel and fmodel.base_model_id else rid
            model_entry = request.app.state.OPENAI_MODELS.get(base_id)
            if model_entry and "urlIdx" in model_entry:
                resolved_idx = model_entry["urlIdx"]
                break

    if resolved_idx is not None:
        idx = resolved_idx
    else:
        idx = 0  # fallback to first endpoint

    if request.app.state.config.OPENAI_API_BASE_URLS:
        url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
        key = (
            request.app.state.config.OPENAI_API_KEYS[idx]
            if request.app.state.config.OPENAI_API_KEYS
            and len(request.app.state.config.OPENAI_API_KEYS) > idx
            else ""
        )
        api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
            str(idx),
            request.app.state.config.OPENAI_API_CONFIGS.get(url, {}),
        )

    runner = AgentFlowRunner(
        api_config=api_config,
        base_url=url,
        api_key=key,
        metadata=metadata or {},
        request=request,
        flow_data=flow_data,
    )

    return await runner.run(
        request=request,
        payload=payload,
        metadata=metadata or {},
        user=user,
    )


@router.post("/chat/completions")
async def generate_chat_completion(
    request: Request,
    form_data: dict,
    user=Depends(get_verified_user),
    bypass_filter: Optional[bool] = False,
):
    if BYPASS_MODEL_ACCESS_CONTROL:
        bypass_filter = True

    idx = 0

    payload = {**form_data}
    # metadata 없이 호출하는 외부 OpenAI 클라이언트(예: Presenton)도 지원하려면 None 대신
    # 빈 dict 로 정규화 — 일부 downstream 이 metadata.get(...) 을 가드 없이 호출(예: L1943)한다.
    # {} 는 falsy 라 기존 `... if metadata else None` 분기 의미는 그대로 보존된다.
    metadata = payload.pop("metadata", None) or {}

    # 직접 /openai 호출(프론트의 /api/chat/completions 를 우회하는 외부 API 클라이언트 등)은
    # metadata 에 user_id 가 없을 수 있다. 등록 모델은 UnifiedAgent 로 라우팅되며
    # get_event_emitter 가 metadata["user_id"] 를 요구하므로, 인증된 user 로 보강한다.
    if user is not None and not metadata.get("user_id"):
        metadata["user_id"] = user.id

    # 외부 서비스(예: Presenton)가 Cloosphere API 키로 /openai 게이트웨이를 직접 호출하는
    # 경우 — chat 컨텍스트(chat_id/message_id/task)가 없다. 이때도 usage 를 기록하기 위한
    # 플래그 (message_type=external_service). 기존 채팅/태스크 흐름은 영향 없음.
    _md = metadata or {}
    is_external_service = (
        getattr(request.state, "auth_type", None) == "api_key"
        and not _md.get("chat_id")
        and not _md.get("message_id")
        and not _md.get("task")
    )

    if metadata and metadata.get("project_context"):
        log.info(
            f"[openai] project_context found in metadata: type={metadata['project_context'].get('type')}"
        )

    model_id = form_data.get("model")
    original_model_id = model_id  # Usage 추적을 위해 원본 모델 ID 저장

    # Usage limit check (per-model, agent → base 자동 전개)
    from open_webui.utils.usage_limit import enforce_usage_limit

    usage_check = enforce_usage_limit(request, user.id, user.role, model_id)
    if not usage_check.allowed:
        raise HTTPException(
            status_code=429,
            detail=usage_check.to_detail(),
        )

    model_info = Models.get_model_by_id(model_id)

    # Check if this is an Agent Flow model (registered via Models table with meta.type = "agent_flow")
    # Flow models have ID format: "flow_{id}" and are stored directly in the Model table
    is_agent_flow = False
    if model_info:
        model_meta = model_info.meta.model_dump() if model_info.meta else {}
        is_agent_flow = model_meta.get("type") == "agent_flow"
    elif model_id.startswith("flow_") or model_id.startswith("flow."):
        # Fallback: if model_id has flow prefix but wasn't found (DB session timing),
        # try fetching again to handle race condition after flow creation
        model_info = Models.get_model_by_id(model_id)
        if model_info:
            model_meta = model_info.meta.model_dump() if model_info.meta else {}
            is_agent_flow = model_meta.get("type") == "agent_flow"

    if is_agent_flow:
        return await _handle_agent_flow(
            request=request,
            flow_id=model_id,
            payload=payload,
            metadata=metadata,
            user=user,
            bypass_filter=bypass_filter,
        )

    enhanced_params = metadata.get("enhanced_params", {}) if metadata else {}

    # Check model info and override the payload
    if model_info:
        if model_info.base_model_id:
            payload["model"] = model_info.base_model_id
            model_id = model_info.base_model_id

        params = model_info.params.model_dump()
        payload = apply_model_params_to_body_openai(params, payload)
        payload = apply_model_system_prompt_to_body(params, payload, metadata, user)

        # Check if user has access to the model
        if not bypass_filter and user.role == "user":
            if not (
                user.id == model_info.user_id
                or has_access(
                    user.id, type="read", access_control=model_info.access_control
                )
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Model not found",
                )
    elif not bypass_filter:
        if user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Model not found",
            )

    await get_all_models(request, user=user)
    model = request.app.state.OPENAI_MODELS.get(model_id)
    if model:
        idx = model["urlIdx"]
    else:
        raise HTTPException(
            status_code=404,
            detail="Model not found",
        )

    # Get the API config for the model
    api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
        str(idx),
        request.app.state.config.OPENAI_API_CONFIGS.get(
            request.app.state.config.OPENAI_API_BASE_URLS[idx], {}
        ),  # Legacy support
    )

    api_config = _set_provider(api_config)

    # Resolve Vertex AI service account key (global fallback support)
    if api_config.get("provider_type") == "vertex-ai":
        api_config["service_account_key"] = _resolve_vertex_ai_sa_key(
            api_config, request.app
        )
        # ADC 모드 플래그 주입 — agent 경로 (UnifiedAgent → react_base → create_llm)
        # 가 use_adc 를 보고 google.auth.default() 분기로 진입하도록.
        # extension_modules/utils/llm.py 의 _resolve_vertex_global_key 와 동일한 정책.
        if (
            not api_config["service_account_key"]
            and api_config.get("use_global_gcp_key")
            and _is_gcp_adc_enabled(request.app)
        ):
            api_config["use_adc"] = True

    prefix_id = api_config.get("prefix_id", None)
    if prefix_id:
        payload["model"] = payload["model"].replace(f"{prefix_id}.", "")

    # Add user info to the payload if the model is a pipeline
    if "pipeline" in model and model.get("pipeline"):
        payload["user"] = {
            "name": user.name,
            "id": user.id,
            "email": user.email,
            "role": user.role,
        }

    url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
    key = request.app.state.config.OPENAI_API_KEYS[idx]

    if not metadata.get("task", None):
        # Add model info to metadata for agents to access knowledge/dbsphere config
        if model_info and metadata:
            metadata["model"] = {
                "id": model_info.id,
                "name": model_info.name,
                "info": {
                    "base_model_id": model_info.base_model_id,
                    "meta": model_info.meta.model_dump() if model_info.meta else {},
                },
            }

        # === Unified Agent: auto-detect capabilities from resources ===
        # Only route to UnifiedAgent if the agent has knowledge or dbsphere resources
        # agent_config = metadata.get("agent_config")
        # has_resources = (
        #     (
        #         agent_config
        #         and (agent_config.has_knowledge() or agent_config.has_dbsphere())
        #     )
        #     if agent_config and hasattr(agent_config, "has_knowledge")
        #     else False
        # )

        # if model_info and model_info.base_model_id and has_resources:
        if model_info:
            runner = UnifiedAgent(
                api_config=api_config,
                base_url=url,
                api_key=key,
                metadata=metadata,
                request=request,
            )
            payload_for_runner = {**payload}

            # HITL resume 분기: 클라이언트가 metadata.hitl_resume 마킹 시
            # 멈춰있는 그래프를 사용자 결정으로 깨운다.
            hitl_resume = (metadata or {}).get("hitl_resume")
            if hitl_resume:
                return await runner.resume(
                    request=request,
                    payload=payload_for_runner,
                    metadata=metadata or {},
                    user=user,
                    thread_id=hitl_resume["thread_id"],
                    decisions=hitl_resume["decisions"],
                    chain_run_id=hitl_resume.get("chain_run_id"),
                    trace_id=hitl_resume.get("trace_id"),
                )

            result = await runner.run(
                request=request,
                payload=payload_for_runner,
                metadata=metadata or {},
                user=user,
            )
            return result

    # Inject conversation summary for models not routed through UnifiedAgent.
    # Summaries are generated by UnifiedAgent's compression trigger (background task).
    # This path activates when a user switches from an agent model to a raw model
    # in the same chat, or when model_info is None (unregistered model).
    if metadata and metadata.get("chat_id"):
        try:
            chat_id = metadata["chat_id"]
            chat_obj = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
            if chat_obj and chat_obj.chat:
                summary = (chat_obj.chat or {}).get("summary", "")
                if summary and summary.strip():
                    messages = payload.get("messages", [])
                    if messages and messages[0].get("role") == "system":
                        messages[0]["content"] += (
                            "\n\n## Previous Conversation Summary\n" + summary
                        )
                    else:
                        messages.insert(
                            0,
                            {
                                "role": "system",
                                "content": (
                                    "## Previous Conversation Summary\n" + summary
                                ),
                            },
                        )
                    payload["messages"] = messages
        except Exception:
            log.debug("[Summary] Failed to inject conversation summary", exc_info=True)

    # Fix: o1, o3, gpt-5 do not support the "max_tokens" parameter, use "max_completion_tokens" instead
    model_lower = payload["model"].lower()
    is_o1_o3 = model_lower.startswith(("o1", "o3-"))
    needs_max_completion_tokens = is_o1_o3 or model_lower.startswith(
        ("gpt-4.1", "gpt-5")
    )

    if is_o1_o3:
        payload = openai_o1_o3_handler(payload)
    elif needs_max_completion_tokens:
        # gpt-5.x requires max_completion_tokens but supports system role (unlike o1/o3)
        if "max_tokens" in payload:
            payload["max_completion_tokens"] = payload["max_tokens"]
            del payload["max_tokens"]
    elif "api.openai.com" not in url:
        # Remove "max_completion_tokens" from the payload for backward compatibility
        if "max_completion_tokens" in payload:
            payload["max_tokens"] = payload["max_completion_tokens"]
            del payload["max_completion_tokens"]

    if "max_tokens" in payload and "max_completion_tokens" in payload:
        del payload["max_tokens"]

    # Convert the modified body back to JSON
    if "logit_bias" in payload:
        payload["logit_bias"] = json.loads(
            convert_logit_bias_input_to_json(payload["logit_bias"])
        )

    # 스트리밍 시 usage 정보를 받기 위해 stream_options 추가
    is_streaming = payload.get("stream", False)
    if is_streaming:
        payload["stream_options"] = {"include_usage": True}

    # 대화 로그: payload가 JSON 직렬화되기 전에 preview 추출
    _chat_input_preview = _extract_chat_input_preview(payload.get("messages", []))
    _chat_messages_count = len(payload.get("messages", []))

    payload = json.dumps(payload)

    r = None
    session = None
    streaming = False
    response = None

    try:
        session = aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
        )

        request_url = None
        headers = {"Content-Type": "application/json"}
        provider_type = api_config.get("provider_type", "openai")

        if provider_type == "vertex-ai":
            # Vertex AI: Use native Gemini API with request/response conversion
            project_id = api_config.get("project_id", "")
            location = api_config.get("location", "us-central1")
            service_account_key = _resolve_vertex_ai_sa_key(api_config, request.app)

            if not project_id:
                raise HTTPException(
                    status_code=400,
                    detail="Vertex AI requires a project ID",
                )

            if not service_account_key and not _is_gcp_adc_enabled(request.app):
                raise HTTPException(
                    status_code=400,
                    detail="Vertex AI requires a service account key",
                )

            # Get OAuth2 access token
            access_token = _get_vertex_ai_access_token(service_account_key)
            headers["Authorization"] = f"Bearer {access_token}"

            # Parse OpenAI payload and convert to Gemini format
            openai_payload = json.loads(payload)
            is_streaming = openai_payload.get("stream", False)
            gemini_payload = _convert_openai_to_gemini(openai_payload)

            # Build Vertex AI Gemini API URL
            request_url = _build_vertex_ai_url(
                project_id, location, model_id, stream=is_streaming
            )
            payload = json.dumps(gemini_payload)
            log.debug(f"Vertex AI request URL: {request_url}")

            # Make request to Vertex AI
            r = await session.request(
                method="POST",
                url=request_url,
                data=payload,
                headers=headers,
            )

            # Backstop: an expired/stale access token surfaces as a 401 on the initial
            # response (before any streaming). Force-refresh the token and retry once.
            if r.status == 401:
                log.warning(
                    "Vertex AI returned 401 — refreshing access token and retrying once"
                )
                r.release()
                access_token = _get_vertex_ai_access_token(
                    service_account_key,
                    force_refresh=True,
                    stale_token=access_token,
                )
                headers["Authorization"] = f"Bearer {access_token}"
                r = await session.request(
                    method="POST",
                    url=request_url,
                    data=payload,
                    headers=headers,
                )

            if r.status != 200:
                error_text = await r.text()
                log.error(f"Vertex AI error: {r.status} - {error_text}")
                raise HTTPException(
                    status_code=r.status, detail=f"Vertex AI Error: {error_text}"
                )

            if is_streaming:
                streaming = True
                # Extract usage tracking info
                agent_id = (
                    original_model_id
                    if (model_info and model_info.base_model_id)
                    else None
                )
                chat_id = metadata.get("chat_id") if metadata else None
                message_id = metadata.get("message_id") if metadata else None
                task_type = metadata.get("task") if metadata else None

                return StreamingResponse(
                    _stream_gemini_to_openai(
                        r,
                        model_id,
                        user_id=user.id,
                        chat_id=chat_id,
                        message_id=message_id,
                        agent_id=agent_id,
                        task_type=task_type,
                        input_preview=_chat_input_preview,
                        messages_count=_chat_messages_count,
                    ),
                    status_code=200,
                    headers={"Content-Type": "text/event-stream"},
                    background=BackgroundTask(
                        cleanup_response, response=r, session=session
                    ),
                )
            else:
                gemini_response = await r.json()
                response = _convert_gemini_to_openai(gemini_response, model_id)

                # Record usage
                if response and "usage" in response:
                    usage_data = response.get("usage")
                    agent_id = (
                        original_model_id
                        if (model_info and model_info.base_model_id)
                        else None
                    )
                    chat_id = metadata.get("chat_id") if metadata else None
                    message_id = metadata.get("message_id") if metadata else None
                    task_type = metadata.get("task") if metadata else None

                    should_record = (
                        (chat_id and message_id)
                        or (chat_id and task_type)
                        or is_external_service
                    )
                    if should_record:
                        try:
                            if task_type:
                                message_type = task_type
                                effective_message_id = message_id or f"task:{task_type}"
                            elif is_external_service:
                                message_type = UsageMessageType.EXTERNAL_SERVICE
                                effective_message_id = None
                                chat_id = None
                            else:
                                message_type = UsageMessageType.CHAT
                                effective_message_id = message_id

                            # 일반 채팅: preview 정보 enrichment
                            usage_to_save = usage_data
                            if (
                                not task_type
                                and not is_external_service
                                and _chat_input_preview
                            ):
                                output_text = ""
                                choices = response.get("choices", [])
                                if choices:
                                    output_text = (
                                        choices[0].get("message", {}).get("content", "")
                                        or ""
                                    )
                                    finish_reason = choices[0].get("finish_reason")
                                else:
                                    finish_reason = None
                                usage_to_save = _enrich_usage_with_preview(
                                    usage_data,
                                    _chat_input_preview,
                                    output_text,
                                    _chat_messages_count,
                                    finish_reason,
                                    client_type=metadata.get("client_type"),
                                )

                            Usages.insert_new_usage(
                                user_id=user.id,
                                chat_id=chat_id,
                                agent_id=agent_id,
                                model_id=model_id,
                                message_id=effective_message_id,
                                message_type=message_type,
                                total_tokens=usage_data.get("total_tokens", 0),
                                usage=usage_to_save,
                            )
                        except Exception as e:
                            log.error(f"Failed to insert usage: {e}")

                await session.close()
                return response

        elif provider_type == "azure-openai":
            # Azure OpenAI
            api_version = api_config.get("api_version", "2024-02-15-preview")
            headers["Authorization"] = f"Bearer {key}"
            headers["api-key"] = key
            request_url = f"{url}/openai/deployments/{model_id}/chat/completions?api-version={api_version}"

        elif provider_type == "azure-ai-foundry":
            # Azure AI Foundry — OpenAI-compatible via /openai/v1
            headers["Authorization"] = f"Bearer {key}"
            request_url = f"{url}/openai/v1/chat/completions"

        else:
            # Standard OpenAI or OpenAI-compatible
            headers["Authorization"] = f"Bearer {key}"
            request_url = f"{url}/chat/completions"

        r = await session.request(
            method="POST",
            url=request_url,
            data=payload,
            headers=headers,
        )

        # Check if response is SSE
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            streaming = True

            # Usage 추적을 위한 정보 추출
            agent_id = (
                original_model_id if (model_info and model_info.base_model_id) else None
            )
            task_type = metadata.get("task") if metadata else None

            return StreamingResponse(
                stream_with_usage_tracking(
                    response=r,
                    session=session,
                    user_id=user.id,
                    chat_id=metadata.get("chat_id") if metadata else None,
                    message_id=metadata.get("message_id") if metadata else None,
                    model_id=model_id,  # 실제 LLM 모델 ID
                    agent_id=agent_id,  # 워크스페이스 에이전트 ID (있는 경우)
                    task_type=task_type,  # 백그라운드 태스크 타입
                    input_preview=_chat_input_preview,
                    messages_count=_chat_messages_count,
                    client_type=metadata.get("client_type") if metadata else "web",
                    is_external_service=is_external_service,
                ),
                status_code=r.status,
                headers=dict(r.headers),
            )
        else:
            try:
                response = await r.json()
            except Exception as e:
                log.error(e)
                response = await r.text()

            r.raise_for_status()

            # Non-streaming 응답도 usage 기록
            if response and isinstance(response, dict) and "usage" in response:
                usage_data = response.get("usage")
                agent_id = (
                    original_model_id
                    if (model_info and model_info.base_model_id)
                    else None
                )
                chat_id = metadata.get("chat_id") if metadata else None
                message_id = metadata.get("message_id") if metadata else None
                task_type = metadata.get("task") if metadata else None

                # 일반 채팅: chat_id와 message_id 필요
                # 백그라운드 태스크: chat_id만으로도 기록
                # 외부 서비스(Presenton 등): API 키 호출, chat_id 없이도 기록
                should_record = (
                    (chat_id and message_id)
                    or (chat_id and task_type)
                    or is_external_service
                )

                if should_record:
                    try:
                        # 태스크인 경우 message_type을 task_type으로
                        if task_type:
                            message_type = task_type
                            effective_message_id = message_id or f"task:{task_type}"
                        elif is_external_service:
                            message_type = UsageMessageType.EXTERNAL_SERVICE
                            effective_message_id = None
                            chat_id = None
                        else:
                            message_type = UsageMessageType.CHAT
                            effective_message_id = message_id

                        # 일반 채팅: preview 정보 enrichment
                        usage_to_save = usage_data
                        if (
                            not task_type
                            and not is_external_service
                            and _chat_input_preview
                        ):
                            output_text = ""
                            choices = response.get("choices", [])
                            if choices:
                                output_text = (
                                    choices[0].get("message", {}).get("content", "")
                                    or ""
                                )
                                finish_reason = choices[0].get("finish_reason")
                            else:
                                finish_reason = None
                            usage_to_save = _enrich_usage_with_preview(
                                usage_data,
                                _chat_input_preview,
                                output_text,
                                _chat_messages_count,
                                finish_reason,
                                client_type=metadata.get("client_type"),
                            )

                        Usages.insert_new_usage(
                            user_id=user.id,
                            chat_id=chat_id,
                            agent_id=agent_id,
                            model_id=model_id,
                            message_id=effective_message_id,
                            message_type=message_type,
                            total_tokens=usage_data.get("total_tokens", 0),
                            usage=usage_to_save,
                        )
                    except Exception as e:
                        log.error(f"Failed to insert usage: {e}")

            return response
    except Exception as e:
        log.exception(e)

        detail = None
        if isinstance(response, dict):
            if "error" in response:
                detail = f"{response['error']['message'] if 'message' in response['error'] else response['error']}"
        elif isinstance(response, str):
            detail = response

        raise HTTPException(
            status_code=r.status if r else 500,
            detail=detail if detail else "Server Connection Error",
        )
    finally:
        if not streaming and session:
            if r:
                r.close()
            await session.close()


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request, user=Depends(get_verified_user)):
    """
    Deprecated: proxy all requests to OpenAI API
    """

    body = await request.body()

    idx = 0
    url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
    key = request.app.state.config.OPENAI_API_KEYS[idx]

    r = None
    session = None
    streaming = False

    try:
        session = aiohttp.ClientSession(trust_env=True)
        r = await session.request(
            method=request.method,
            url=f"{url}/{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                **(
                    {
                        "X-OpenWebUI-User-Name": user.name,
                        "X-OpenWebUI-User-Id": user.id,
                        "X-OpenWebUI-User-Email": user.email,
                        "X-OpenWebUI-User-Role": user.role,
                    }
                    if ENABLE_FORWARD_USER_INFO_HEADERS
                    else {}
                ),
            },
        )
        r.raise_for_status()

        # Check if response is SSE
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            streaming = True
            return StreamingResponse(
                r.content,
                status_code=r.status,
                headers=dict(r.headers),
                background=BackgroundTask(
                    cleanup_response, response=r, session=session
                ),
            )
        else:
            response_data = await r.json()
            return response_data

    except Exception as e:
        log.exception(e)

        detail = None
        if r is not None:
            try:
                res = await r.json()
                log.error(res)
                if "error" in res:
                    detail = f"External: {res['error']['message'] if 'message' in res['error'] else res['error']}"
            except Exception:
                detail = f"External: {e}"
        raise HTTPException(
            status_code=r.status if r else 500,
            detail=detail if detail else "Server Connection Error",
        )
    finally:
        if not streaming and session:
            if r:
                r.close()
            await session.close()
