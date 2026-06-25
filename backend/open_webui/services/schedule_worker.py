"""
Schedule Worker Loop — runs every 5 seconds on all instances.

Responsibilities:
1. Claim a pending task using SKIP LOCKED (PostgreSQL) or simple claim (SQLite).
2. Execute the task:
   - Agents (base_model_id): directly invoke UnifiedAgent with run_flow=True
   - Plain models: call generate_chat_completion with stream=False
3. Always create a chat record with the result.
4. Send notifications (email/webhook) based on schedule delivery config.
5. Update task status (completed/failed).
"""

import asyncio
import base64
import json as _json
import logging
import re
import time
import uuid
from typing import List

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

WORKER_INTERVAL = 5  # seconds

# Regex: [[dbsphere:chart]] followed by ```json\n...\n```
_CHART_BLOCK_RE = re.compile(
    r"\[\[\s*dbsphere:chart\s*\]\]\s*```json\n([\s\S]*?)\n```",
    re.IGNORECASE,
)

# Regex: consecutive lines starting/ending with |
_MD_TABLE_BLOCK_RE = re.compile(
    r"((?:^\|.+\|[ \t]*\n?){2,})",
    re.MULTILINE,
)
WORKER_ID = str(uuid.uuid4())[:8]


async def worker_loop(app):
    """Main worker loop — runs as an asyncio task in the lifespan."""
    log.info(f"Schedule worker started (worker_id={WORKER_ID})")

    # Wait for the app to fully start
    await asyncio.sleep(15)

    while True:
        try:
            from open_webui.models.schedules import ScheduleTasks

            task = ScheduleTasks.claim_pending_task(WORKER_ID)
            if task:
                await _execute_task(app, task)
            else:
                await asyncio.sleep(WORKER_INTERVAL)
        except Exception as e:
            log.error(f"Worker loop error: {e}", exc_info=True)
            await asyncio.sleep(WORKER_INTERVAL)


async def _execute_task(app, task):
    """Execute a single scheduled task."""
    from open_webui.models.schedules import Schedules, ScheduleTasks
    from open_webui.models.users import Users

    # 취소된 태스크 확인
    current_task = ScheduleTasks.get_task_by_id(task.id)
    if not current_task or current_task.status == "cancelled":
        log.info(f"Task {task.id} was cancelled, skipping execution")
        return

    schedule = Schedules.get_schedule_by_id(task.schedule_id)
    if not schedule:
        ScheduleTasks.update_task_status(
            task.id, "failed", error_message="Schedule not found"
        )
        return

    user = Users.get_user_by_id(schedule.user_id)
    if not user:
        ScheduleTasks.update_task_status(
            task.id, "failed", error_message="User not found"
        )
        # Deactivate schedule if user is gone
        Schedules.toggle_schedule_by_id(schedule.id)
        return

    message_id = str(uuid.uuid4())

    # Determine chat_id: reuse existing or generate new
    existing_chat = None
    if schedule.chat_id:
        from open_webui.models.chats import Chats

        existing_chat = Chats.get_chat_by_id(schedule.chat_id)

    # Use existing chat_id for agent/model context, or a temporary one
    chat_id = existing_chat.id if existing_chat else str(uuid.uuid4())

    try:
        # Delivery config
        delivery = schedule.delivery or {}
        chart_images: List[bytes] = []
        notification_content = ""
        dashboard_html_attachment = None

        if schedule.target_type == "dashboard":
            (
                result_content,
                chart_images,
                dashboard_html_attachment,
            ) = await _execute_dashboard_task(app, schedule, task)
            notification_content = result_content
        else:
            # Check if target is an agent (has base_model_id)
            from open_webui.models.models import Models

            model_info = Models.get_model_by_id(schedule.target_model_id)
            if not model_info:
                raise Exception(f"Model not found: {schedule.target_model_id}")
            is_agent = model_info and model_info.base_model_id

            if is_agent:
                result_content = await _execute_agent_task(
                    app, model_info, user, task, chat_id, message_id
                )
            else:
                result_content = await _execute_model_task(
                    app, schedule, user, task, chat_id, message_id
                )

            # Extract chart images for notifications (server-side rendering)
            notification_content = result_content
            if _CHART_BLOCK_RE.search(result_content):
                try:
                    chart_images = _extract_chart_images(result_content)
                    notification_content = _strip_chart_block(result_content)
                except Exception as e:
                    log.warning(f"Chart image extraction failed: {e}")

        # Chat title
        chat_title = f"[Scheduled Task] {schedule.name}"
        title_tpl = delivery.get("title_template", "")
        if title_tpl:
            tpl_vars = {
                "schedule_name": schedule.name,
                "prompt": task.prompt,
                "result": result_content,
                "completed_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            }
            try:
                parsed = _json.loads(result_content)
                if isinstance(parsed, dict):
                    tpl_vars["result"] = parsed
            except (ValueError, TypeError):
                pass
            chat_title = _render_template(title_tpl, tpl_vars)

        # Create or append to chat (keep raw result_content with chart markers)
        if existing_chat:
            _append_to_chat(
                existing_chat,
                task.prompt,
                result_content,
                message_id,
                schedule.target_model_id,
            )
        else:
            created_chat_id = _create_chat(
                user.id,
                chat_title,
                task.prompt,
                result_content,
                message_id,
                schedule.target_model_id,
            )
            if created_chat_id:
                chat_id = created_chat_id
                # Tag chat with schedule_id for identification
                from open_webui.models.chats import Chats as ChatsModel

                ChatsModel.update_chat_meta_by_id(
                    created_chat_id, {"schedule_id": schedule.id}
                )
                # Save chat_id to schedule for future reuse
                Schedules.update_chat_id(schedule.id, chat_id)

        # Upload chart images and get HTTP URLs for webhook notifications
        chart_image_urls: List[str] = []
        if chart_images:
            chart_image_urls = _upload_chart_images(app, chart_images, schedule.id)

        # Send notifications (0 or more) — failures don't affect task status
        # Use cleaned notification_content + chart_images for notifications
        log.info(
            f"Task {task.id}: About to send notifications. delivery keys={list(delivery.keys())}, notifications count={len(delivery.get('notifications', []))}"
        )
        await _send_notifications(
            app,
            delivery,
            schedule,
            task,
            notification_content,
            status="completed",
            chart_images=chart_images,
            chart_image_urls=chart_image_urls,
            chat_id=chat_id,
            attachments=dashboard_html_attachment,
        )

        # Legacy: plain webhook delivery ({"type": "webhook", "url": "..."})
        delivery_type = delivery.get("type", "chat")
        if delivery_type == "webhook" and delivery.get("url"):
            await _send_legacy_webhook(
                delivery.get("url", ""), schedule, task, notification_content
            )

        ScheduleTasks.update_task_status(
            task.id,
            "completed",
            result={"content": result_content},
            chat_id=chat_id,
        )
        log.info(f"Task {task.id} completed for schedule '{schedule.name}'")

    except Exception as e:
        error_msg = str(e)[:500]
        log.error(f"Task {task.id} failed: {error_msg}")

        # Check if retriable
        if _is_retriable_error(e) and task.retry_count < task.max_retries:
            ScheduleTasks.retry_task(task.id)
            log.info(
                f"Task {task.id} queued for retry ({task.retry_count + 1}/{task.max_retries})"
            )
        else:
            ScheduleTasks.update_task_status(task.id, "failed", error_message=error_msg)
            # Send failure notifications
            try:
                delivery = schedule.delivery or {}
                await _send_notifications(
                    app, delivery, schedule, task, error_msg, status="failed"
                )
            except Exception as ne:
                log.warning(f"Failed to send failure notifications: {ne}")


async def _execute_agent_task(app, model_info, user, task, chat_id, message_id) -> str:
    """Execute a scheduled task via UnifiedAgent (for agents with base_model_id)."""
    from extension_modules.agent.unified_agent import UnifiedAgent
    from starlette.requests import Request

    from open_webui.models.agent_config import AgentConfig
    from open_webui.routers.openai import (
        _resolve_vertex_ai_sa_key,
        _set_provider,
        get_all_models,
    )

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "state": {},
        "app": app,
    }
    request = Request(scope)

    # Build AgentConfig from model_info (same as main.py)
    agent_config = AgentConfig.from_model_info(
        params=model_info.params.model_dump() if model_info.params else {},
        meta=model_info.meta.model_dump() if model_info.meta else {},
        model_id=model_info.id,
        base_model_id=model_info.base_model_id,
    )
    # KG attached → KG.sources를 effective set에 union (main.py와 동일)
    # 스케줄 작업의 user는 schedule.user_id 소유자
    agent_config.resolve_kg_inheritance(user=user)

    metadata = {
        "user_id": user.id,
        "chat_id": chat_id,
        "message_id": message_id,
        "session_id": None,
        "tool_ids": None,
        "tool_servers": None,
        "files": None,
        "features": {},
        "variables": None,
        "agent_config": agent_config,
    }

    # Ensure OPENAI_MODELS is populated (retry once on failure)
    await get_all_models(request, user=user)

    # Resolve the base model to get API config
    base_model_id = model_info.base_model_id
    model = app.state.OPENAI_MODELS.get(base_model_id)
    if not model:
        # Retry once — API may have been temporarily unavailable
        import asyncio

        await asyncio.sleep(2)
        await get_all_models(request, user=user)
        model = app.state.OPENAI_MODELS.get(base_model_id)

    if not model:
        raise Exception(f"Base model '{base_model_id}' not found in OPENAI_MODELS")

    idx = model["urlIdx"]
    url = app.state.config.OPENAI_API_BASE_URLS[idx]
    key = app.state.config.OPENAI_API_KEYS[idx]
    api_config = app.state.config.OPENAI_API_CONFIGS.get(
        str(idx),
        app.state.config.OPENAI_API_CONFIGS.get(url, {}),
    )
    api_config = _set_provider(api_config)

    # Resolve Vertex AI service account key (global fallback support)
    if api_config.get("provider_type") == "vertex-ai":
        api_config["service_account_key"] = _resolve_vertex_ai_sa_key(api_config, app)

    # Add model info to metadata (same as openai.py routing)
    metadata["model"] = {
        "id": model_info.id,
        "info": {
            "base_model_id": model_info.base_model_id,
            "meta": model_info.meta.model_dump() if model_info.meta else {},
        },
    }

    # Apply model params to payload
    from open_webui.utils.payload import (
        apply_model_params_to_body_openai,
        apply_model_system_prompt_to_body,
    )

    params = model_info.params.model_dump() if model_info.params else {}
    payload = {
        "model": base_model_id,
        "messages": [{"role": "user", "content": task.prompt}],
        "stream": True,
    }
    payload = apply_model_params_to_body_openai(params, payload)
    payload = apply_model_system_prompt_to_body(params, payload, metadata, user)

    runner = UnifiedAgent(
        api_config=api_config,
        base_url=url,
        api_key=key,
        metadata=metadata,
        request=request,
    )

    # run_flow=False returns StreamingResponse with SSE-formatted final answer
    # (run_flow=True only returns raw agent messages, not the final LLM answer)
    streaming_response = await runner.run(
        request=request,
        payload=payload,
        metadata=metadata,
        user=user,
        run_flow=False,
    )

    return await _consume_sse_stream(streaming_response)


async def _execute_model_task(app, schedule, user, task, chat_id, message_id) -> str:
    """Execute a scheduled task via generate_chat_completion (plain models)."""
    from starlette.requests import Request

    from open_webui.utils.chat import generate_chat_completion

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "state": {},
        "app": app,
    }
    request = Request(scope)

    # Refresh MODELS cache (includes custom models + openai + ollama)
    from open_webui.utils.models import get_all_models as get_all_models_util

    await get_all_models_util(request, user=user)

    form_data = {
        "model": schedule.target_model_id,
        "messages": [{"role": "user", "content": task.prompt}],
        "stream": False,
        "metadata": {
            "chat_id": chat_id,
            "message_id": message_id,
        },
    }

    response = await generate_chat_completion(
        request, form_data=form_data, user=user, bypass_filter=True
    )
    return _extract_response_content(response)


async def _execute_dashboard_task(
    app, schedule, task
) -> tuple[str, List[bytes], list[dict] | None]:
    """Execute a scheduled dashboard export task.

    Returns:
        (result_content, chart_images, attachments)
    """
    from open_webui.routers.bi_dashboard import (
        compute_date_range,
        generate_dashboard_export,
    )

    meta = schedule.meta or {}
    time_range = meta.get("time_range", "yesterday")
    filters = meta.get("filters", [])

    from_value, to_value = compute_date_range(time_range)

    html, panel_results = await generate_dashboard_export(
        schedule.target_model_id, from_value, to_value, filters or None
    )

    chart_images: List[bytes] = []

    # 대시보드 이름 가져오기
    from open_webui.models.bi_dashboard import BiDashboards

    dashboard = BiDashboards.get_dashboard_by_id(schedule.target_model_id)
    dashboard_name = dashboard.name if dashboard else schedule.name
    panel_count = len(panel_results)
    filter_desc = f"{from_value} ~ {to_value}" if from_value else "All"

    # 공유 URL 생성
    share_url = ""
    if dashboard and dashboard.share_id:
        from open_webui.config import WEBUI_URL

        base_url = WEBUI_URL.value.rstrip("/")
        share_url = f"{base_url}/dashboard/{dashboard.share_id}"

    result_content = (
        f"대시보드 '{dashboard_name}' 내보내기 완료 "
        f"({panel_count}개 패널, 기간: {filter_desc})"
    )
    if share_url:
        result_content += f"\n{share_url}"

    # HTML 첨부파일 생성
    attachments = [
        {
            "filename": f"{dashboard_name}.html",
            "content": html.encode("utf-8"),
            "mime_type": "text/html",
        }
    ]

    return result_content, chart_images, attachments


async def _consume_sse_stream(streaming_response) -> str:
    """Consume a StreamingResponse (SSE) and extract concatenated text content.

    The UnifiedAgent streams the final answer as SSE chunks:
      data: {"choices":[{"delta":{"content":"piece"}}]}
    We collect all content pieces and return the full text.
    """
    content_parts = []
    async for chunk in streaming_response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        # Each SSE chunk can contain multiple "data: ..." lines
        for line in chunk.split("\n"):
            line = line.strip()
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                data = _json.loads(data_str)
                content = (
                    data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                )
                if content:
                    content_parts.append(content)
            except (ValueError, IndexError, KeyError):
                pass

    return "".join(content_parts) or "No content generated"


def _extract_response_content(response) -> str:
    """Extract text content from generate_chat_completion response."""
    if hasattr(response, "body"):
        import json

        try:
            body = json.loads(response.body)
            choices = body.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
        except Exception:
            pass

    if isinstance(response, dict):
        choices = response.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")

    return str(response)


def _append_to_chat(
    existing_chat,
    prompt: str,
    result: str,
    message_id: str,
    model_id: str = "",
):
    """Append a new user+assistant message pair to an existing chat."""
    from open_webui.models.chats import Chats

    chat_data = existing_chat.chat
    history = chat_data.get("history", {})
    messages = history.get("messages", {})
    current_id = history.get("currentId")

    # Ensure models list contains the target model
    if model_id:
        existing_models = chat_data.get("models", [])
        if model_id not in existing_models:
            chat_data["models"] = [model_id]

    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = message_id
    now = int(time.time())

    # Link the new user message as a child of the current last message
    if current_id and current_id in messages:
        last_msg = messages[current_id]
        if user_msg_id not in last_msg.get("childrenIds", []):
            last_msg.setdefault("childrenIds", []).append(user_msg_id)

    # Add new message pair
    messages[user_msg_id] = {
        "id": user_msg_id,
        "parentId": current_id,
        "childrenIds": [assistant_msg_id],
        "role": "user",
        "content": prompt,
        "timestamp": now,
    }
    messages[assistant_msg_id] = {
        "id": assistant_msg_id,
        "parentId": user_msg_id,
        "childrenIds": [],
        "role": "assistant",
        "model": model_id,
        "content": result,
        "timestamp": now,
    }

    # Update currentId to the new assistant message
    history["currentId"] = assistant_msg_id
    history["messages"] = messages
    chat_data["history"] = history

    try:
        Chats.update_chat_by_id(existing_chat.id, chat_data)
    except Exception as e:
        log.error(f"Failed to append to chat {existing_chat.id}: {e}")


def _create_chat(
    user_id: str,
    title: str,
    prompt: str,
    result: str,
    message_id: str,
    model_id: str = "",
) -> str | None:
    """Create a chat record with the schedule result. Returns the created chat_id."""
    from open_webui.models.chats import ChatForm, Chats

    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = message_id

    chat_data = {
        "title": title,
        "models": [model_id] if model_id else [],
        "tags": [],
        "history": {
            "messages": {
                user_msg_id: {
                    "id": user_msg_id,
                    "parentId": None,
                    "childrenIds": [assistant_msg_id],
                    "role": "user",
                    "content": prompt,
                    "timestamp": int(time.time()),
                },
                assistant_msg_id: {
                    "id": assistant_msg_id,
                    "parentId": user_msg_id,
                    "childrenIds": [],
                    "role": "assistant",
                    "model": model_id,
                    "content": result,
                    "timestamp": int(time.time()),
                },
            },
            "currentId": assistant_msg_id,
        },
    }

    try:
        created = Chats.insert_new_chat(user_id, ChatForm(chat=chat_data))
        return created.id if created else None
    except Exception as e:
        log.error(f"Failed to create chat: {e}")
        return None


# ──────────────────────────────────────────────────────
# Notification delivery
# ──────────────────────────────────────────────────────


def _render_template(template: str, variables: dict) -> str:
    """Replace {{variable}} placeholders in a template string.

    Supports dot notation for nested dict access:
      {{result}}       → full result string
      {{result.title}} → parsed_json["title"]
      {{result.data.count}} → parsed_json["data"]["count"]
    """

    def replacer(match):
        key = match.group(1).strip()
        parts = key.split(".")
        value = variables
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return match.group(0)  # lookup failed → keep original
            if value is None:
                return ""
        return str(value)

    return re.sub(r"\{\{(.+?)\}\}", replacer, template)


async def _send_notifications(
    app,
    delivery: dict,
    schedule,
    task,
    result_content: str,
    status: str = "completed",
    chart_images: List[bytes] | None = None,
    chart_image_urls: List[str] | None = None,
    chat_id: str | None = None,
    attachments: List[dict] | None = None,
):
    """Send notifications based on delivery.notifications list.

    Args:
        status: "completed" or "failed" — used to filter by notif trigger.
        chat_id: Optional chat_id to generate chat URL for notifications.
        chart_images: Optional list of PNG bytes from server-side chart rendering.
        chart_image_urls: Optional list of HTTP URLs for chart images (for webhooks).
        attachments: Optional list of {"filename": str, "content": bytes, "mime_type": str} for email.
    """
    notifications = delivery.get("notifications", [])
    log.info(
        f"_send_notifications: {len(notifications)} notification(s) in delivery, status={status}"
    )
    if not notifications:
        return

    # Try to parse result as JSON for dot-notation template access
    result_value: str | dict = result_content
    try:
        parsed = _json.loads(result_content)
        if isinstance(parsed, dict):
            result_value = parsed
    except (ValueError, TypeError):
        pass

    # Build chat_url from WEBUI_URL + chat_id
    chat_url = ""
    if chat_id:
        from open_webui.config import WEBUI_URL

        base_url = WEBUI_URL.value.rstrip("/")
        chat_url = f"{base_url}/c/{chat_id}"

    # Build dashboard_url for dashboard schedules
    dashboard_url = ""
    if schedule.target_type == "dashboard":
        from open_webui.config import WEBUI_URL as _WEBUI_URL
        from open_webui.models.bi_dashboard import BiDashboards as _BiDashboards

        base_url = _WEBUI_URL.value.rstrip("/")
        dashboard = _BiDashboards.get_dashboard_by_id(schedule.target_model_id)
        if dashboard and dashboard.share_id:
            dashboard_url = f"{base_url}/dashboard/{dashboard.share_id}"

    # 대시보드 메타 정보
    time_range = ""
    if schedule.target_type == "dashboard":
        time_range = (schedule.meta or {}).get("time_range", "")

    template_vars = {
        "schedule_name": schedule.name,
        "prompt": task.prompt,
        "result": result_value,
        "result_raw": result_content,
        "status": status,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "chat_url": chat_url,
        "dashboard_url": dashboard_url,
        "target_type": schedule.target_type,
        "time_range": time_range,
    }

    for notif in notifications:
        try:
            # Filter by trigger condition
            trigger = notif.get("trigger", "always")
            if trigger == "on_success" and status != "completed":
                continue
            if trigger == "on_failure" and status != "failed":
                continue

            channel_type = notif.get("channel_type", "")
            log.info(
                f"Processing notification: channel_type={channel_type}, channel_name={notif.get('channel_name', '')}, trigger={trigger}"
            )
            if channel_type == "email":
                _send_email_notification(
                    app,
                    notif,
                    template_vars,
                    chart_images=chart_images,
                    attachments=attachments,
                )
            elif channel_type in ("webhook", "webhook_url"):
                await _send_webhook_notification(
                    app, notif, template_vars, chart_image_urls=chart_image_urls
                )
            else:
                log.warning(f"Unknown notification channel_type: {channel_type}")
        except Exception as e:
            log.warning(
                f"Notification delivery failed (channel={notif.get('channel_name', '?')}): {e}"
            )


def _build_chart_html(chart_images: List[bytes]) -> str:
    """Build HTML img tags from chart image bytes (inline base64)."""
    parts = []
    for idx, img_bytes in enumerate(chart_images):
        b64 = base64.b64encode(img_bytes).decode("ascii")
        parts.append(
            f'<div style="margin:16px 0;">'
            f'<img src="data:image/png;base64,{b64}" '
            f'alt="Chart {idx + 1}" '
            f'style="max-width:100%;height:auto;border:1px solid #e5e7eb;border-radius:8px;" />'
            f"</div>"
        )
    return "\n".join(parts)


def _upload_chart_images(app, chart_images: List[bytes], schedule_id: str) -> List[str]:
    """Upload chart images and return publicly accessible HTTP URLs.

    - If IMAGE_UPLOAD_MODE == 'storage' (cloud): upload via ImageStorage → public blob URL
    - If IMAGE_UPLOAD_MODE == 'base64' (local): save locally via Storage + signed URL
    """
    import io

    from open_webui.models.files import FileForm, Files
    from open_webui.storage.provider import ImageStorage, Storage

    upload_mode = getattr(app.state.config, "IMAGE_UPLOAD_MODE", "base64")
    base_url = str(
        getattr(app.state.config, "WEBUI_URL", "http://localhost:3000")
    ).rstrip("/")

    urls: List[str] = []
    for idx, img_bytes in enumerate(chart_images):
        try:
            file_id = str(uuid.uuid4())
            filename = f"schedule_chart_{schedule_id}_{file_id[:8]}.png"

            if upload_mode == "storage":
                # Cloud storage (public container) — upload returns public blob URL
                _, file_path = ImageStorage.upload_file(io.BytesIO(img_bytes), filename)
                url = file_path
            else:
                # Local storage — save file + generate signed URL
                _, file_path = Storage.upload_file(io.BytesIO(img_bytes), filename)
                from open_webui.routers.files import generate_signed_url

                # Register file in DB so the signed URL endpoint can find it
                Files.insert_new_file(
                    user_id="system",
                    form_data=FileForm(
                        id=file_id,
                        filename=filename,
                        path=file_path,
                        data={},
                        meta={
                            "name": filename,
                            "content_type": "image/png",
                            "size": len(img_bytes),
                        },
                    ),
                )
                url = generate_signed_url(base_url, file_id)

            urls.append(url)
            log.info(f"Chart image #{idx} uploaded: {url[:80]}...")
        except Exception as e:
            log.warning(f"Failed to upload chart image #{idx}: {e}")
    return urls


def _send_email_notification(
    app,
    notif: dict,
    template_vars: dict,
    chart_images: List[bytes] | None = None,
    attachments: List[dict] | None = None,
):
    """Send an email notification using the named channel from admin config."""
    from open_webui.utils.email import EmailSender, SendGridSender

    channel_name = notif.get("channel_name", "")
    recipients = notif.get("recipients", [])
    if not recipients:
        log.warning("Email notification skipped: no recipients")
        return

    # Find channel by name (with legacy fallback)
    channels = list(app.state.config.NOTIFICATION_EMAIL_CHANNELS)
    if not channels:
        # Legacy fallback: individual SMTP/SendGrid config fields
        legacy_engine = getattr(app.state.config, "EMAIL_ENGINE", "") or ""
        if legacy_engine:
            channels = [
                {
                    "name": "기본",
                    "engine": legacy_engine,
                    "smtp": {
                        "server": getattr(app.state.config, "SMTP_SERVER", ""),
                        "port": getattr(app.state.config, "SMTP_PORT", 587),
                        "username": getattr(app.state.config, "SMTP_USERNAME", ""),
                        "password": getattr(app.state.config, "SMTP_PASSWORD", ""),
                        "use_tls": getattr(app.state.config, "SMTP_USE_TLS", True),
                        "use_ssl": getattr(app.state.config, "SMTP_USE_SSL", False),
                        "from_address": getattr(
                            app.state.config, "SMTP_FROM_ADDRESS", ""
                        ),
                        "from_name": getattr(
                            app.state.config, "SMTP_FROM_NAME", "Cloosphere"
                        ),
                    },
                    "sendgrid": {
                        "api_key": getattr(app.state.config, "SENDGRID_API_KEY", ""),
                        "from_address": getattr(
                            app.state.config, "SENDGRID_FROM_ADDRESS", ""
                        ),
                        "from_name": getattr(
                            app.state.config, "SENDGRID_FROM_NAME", "Cloosphere"
                        ),
                    },
                }
            ]
    channel = next((ch for ch in channels if ch.get("name") == channel_name), None)
    if not channel:
        log.warning(f"Email channel '{channel_name}' not found, skipping")
        return

    # Use subject_template if provided, otherwise fall back to title_template
    subject_tpl = notif.get("subject_template", "") or notif.get(
        "title_template", "[{{schedule_name}}] 결과"
    )
    subject = _render_template(subject_tpl, template_vars)
    body = _render_template(notif.get("body_template", "{{result}}"), template_vars)

    # Build HTML body
    import html as _html

    chat_url = template_vars.get("chat_url", "")
    chat_link_html = ""
    if chat_url:
        chat_link_html = (
            f'<p style="margin-top:16px;">'
            f'<a href="{_html.escape(chat_url)}" style="color:#2563eb;">채팅에서 보기 →</a>'
            f"</p>"
        )

    html_body = None
    if chart_images or chat_url:
        escaped_body = _html.escape(body).replace("\n", "<br>")
        chart_html = _build_chart_html(chart_images) if chart_images else ""
        html_body = (
            f'<div style="font-family:sans-serif;max-width:800px;">'
            f"<p>{escaped_body}</p>"
            f"{chart_html}"
            f"{chat_link_html}"
            f"</div>"
        )

    engine = channel.get("engine", "")
    if engine == "smtp":
        smtp = channel.get("smtp", {})
        sender = EmailSender(
            server=smtp.get("server", ""),
            port=smtp.get("port", 587),
            username=smtp.get("username", ""),
            password=smtp.get("password", ""),
            use_tls=smtp.get("use_tls", True),
            use_ssl=smtp.get("use_ssl", False),
            from_address=smtp.get("from_address", ""),
            from_name=smtp.get("from_name", "Cloosphere"),
        )
        success = sender.send_email(
            to=recipients,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments,
        )
    elif engine == "sendgrid":
        sg = channel.get("sendgrid", {})
        sender = SendGridSender(
            api_key=sg.get("api_key", ""),
            from_address=sg.get("from_address", ""),
            from_name=sg.get("from_name", "Cloosphere"),
        )
        success = sender.send_email(
            to=recipients,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments,
        )
    elif engine == "msgraph":
        from open_webui.utils.email import MSGraphEmailSender

        mg = channel.get("msgraph", {})
        sender = MSGraphEmailSender(
            tenant_id=mg.get("tenant_id", ""),
            client_id=mg.get("client_id", ""),
            client_secret=mg.get("client_secret", ""),
            sender_email=mg.get("sender_email", ""),
            from_name=mg.get("from_name", "Cloosphere"),
        )
        success = sender.send_email(
            to=recipients,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments,
        )
    else:
        log.warning(f"Email channel '{channel_name}' has unknown engine: {engine}")
        return

    if success:
        log.info(f"Email notification sent via '{channel_name}' to {recipients}")
    else:
        log.warning(f"Email notification failed via '{channel_name}'")


def _parse_md_table(table_text: str) -> dict | None:
    """Parse a markdown table block into an Adaptive Card Table element."""

    def _split_row(line: str) -> list[str]:
        cells = [c.strip() for c in line.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        return cells

    lines = [ln.strip() for ln in table_text.strip().split("\n") if ln.strip()]
    if len(lines) < 3:
        return None

    rows = [_split_row(ln) for ln in lines]

    # Find separator row (e.g. |---|---|)
    sep_idx = None
    for i, row in enumerate(rows):
        if all(re.match(r"^[-:]+$", c) for c in row if c):
            sep_idx = i
            break
    if sep_idx is None or sep_idx == 0:
        return None

    headers = rows[sep_idx - 1]
    data_rows = rows[sep_idx + 1 :]
    if not headers or not data_rows:
        return None

    num_cols = len(headers)
    ac_rows = [
        {
            "type": "TableRow",
            "cells": [
                {
                    "type": "TableCell",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": h,
                            "weight": "Bolder",
                            "wrap": True,
                        }
                    ],
                }
                for h in headers
            ],
        }
    ]
    for row in data_rows:
        ac_rows.append(
            {
                "type": "TableRow",
                "cells": [
                    {
                        "type": "TableCell",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": row[i] if i < len(row) else "",
                                "wrap": True,
                            }
                        ],
                    }
                    for i in range(num_cols)
                ],
            }
        )

    return {
        "type": "Table",
        "gridStyle": "accent",
        "firstRowAsHeader": True,
        "columns": [{"width": 1} for _ in range(num_cols)],
        "rows": ac_rows,
    }


def _markdown_to_adaptive_elements(text: str) -> list:
    """Convert markdown text to Adaptive Card body elements.

    - Markdown tables → Table elements (Adaptive Card 1.5)
    - Regular text → TextBlock (supports bold, italic, links)
    """
    elements: list = []
    last_end = 0

    for match in _MD_TABLE_BLOCK_RE.finditer(text):
        before = text[last_end : match.start()].strip()
        if before:
            elements.append({"type": "TextBlock", "text": before, "wrap": True})

        table_elem = _parse_md_table(match.group(1))
        if table_elem:
            elements.append(table_elem)
        else:
            elements.append(
                {"type": "TextBlock", "text": match.group(1).strip(), "wrap": True}
            )

        last_end = match.end()

    remaining = text[last_end:].strip()
    if remaining:
        elements.append({"type": "TextBlock", "text": remaining, "wrap": True})

    return elements or [{"type": "TextBlock", "text": text, "wrap": True}]


async def _send_webhook_notification(
    app,
    notif: dict,
    template_vars: dict,
    chart_image_urls: List[str] | None = None,
):
    """Send a webhook notification using named channel or direct URL."""
    channel_name = notif.get("channel_name", "")
    direct_url = notif.get("webhook_url", "")

    provider = ""
    url = ""

    log.info(
        f"_send_webhook_notification: channel_name='{channel_name}', direct_url='{direct_url}'"
    )
    if channel_name:
        # Look up channel from admin config (with legacy fallback)
        channels = list(app.state.config.NOTIFICATION_WEBHOOK_CHANNELS)
        log.info(
            f"  NOTIFICATION_WEBHOOK_CHANNELS has {len(channels)} channel(s): {[ch.get('name') for ch in channels]}"
        )
        if not channels:
            # Legacy fallback: WEBHOOK_PROVIDER / WEBHOOK_URL
            legacy_provider = getattr(app.state.config, "WEBHOOK_PROVIDER", "") or ""
            legacy_url = getattr(app.state.config, "WEBHOOK_URL", "") or ""
            if legacy_provider or legacy_url:
                channels = [
                    {"name": "기본", "provider": legacy_provider, "url": legacy_url}
                ]
        channel = next((ch for ch in channels if ch.get("name") == channel_name), None)
        if not channel:
            log.warning(f"Webhook channel '{channel_name}' not found, skipping")
            return
        provider = channel.get("provider", "")
        url = channel.get("url", "")
        log.info(f"  Resolved channel: provider='{provider}', url='{url[:50]}...' ")
    elif direct_url:
        # Direct URL input (no admin channel configured)
        url = direct_url
    else:
        log.warning("Webhook notification has no channel_name or webhook_url, skipping")
        return

    # Telegram uses bot_token + chat_id instead of url
    bot_token = ""
    telegram_chat_id = ""
    if provider == "telegram" and channel_name:
        bot_token = channel.get("bot_token", "") if channel else ""
        telegram_chat_id = channel.get("chat_id", "") if channel else ""
        if not bot_token or not telegram_chat_id:
            log.warning(
                f"Telegram channel '{channel_name}' missing bot_token or chat_id, skipping"
            )
            return
    elif not url:
        log.warning(f"Webhook channel '{channel_name}' has no URL, skipping")
        return

    schedule_name = template_vars.get("schedule_name", "")
    result_raw = template_vars.get("result_raw", "")
    prompt = template_vars.get("prompt", "")
    completed_at = template_vars.get("completed_at", "")
    chat_url = template_vars.get("chat_url", "")
    dashboard_url = template_vars.get("dashboard_url", "")
    is_dashboard = template_vars.get("target_type") == "dashboard"
    time_range = template_vars.get("time_range", "")

    # Render per-notification title_template (falls back to schedule_name)
    title_tpl = notif.get("title_template", "")
    if title_tpl:
        rendered_title = _render_template(title_tpl, template_vars)
    else:
        rendered_title = f"📋 {schedule_name}"

    # Use message_template if provided, otherwise fall back to raw result
    message_tpl = notif.get("message_template", "")
    if message_tpl:
        display_result = _render_template(message_tpl, template_vars)
    else:
        display_result = result_raw

    # Truncate for webhook payloads (max 2000 chars)
    display_result = display_result[:2000] + (
        "..." if len(display_result) > 2000 else ""
    )

    # 대시보드: 링크 및 메타 정보
    primary_url = dashboard_url if is_dashboard and dashboard_url else chat_url
    primary_label = (
        "📊 대시보드 보기" if is_dashboard and dashboard_url else "채팅에서 보기 →"
    )
    meta_label = "기간" if is_dashboard else "Prompt"
    meta_value = time_range if is_dashboard and time_range else prompt

    if provider == "slack":
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": rendered_title,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{meta_label}:*\n{meta_value}"},
                    {"type": "mrkdwn", "text": f"*Completed:*\n{completed_at}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Result:*\n{display_result}",
                },
            },
        ]
        if chart_image_urls:
            for img_url in chart_image_urls:
                blocks.append(
                    {"type": "image", "image_url": img_url, "alt_text": "Chart"}
                )
        if primary_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": primary_label},
                            "url": primary_url,
                            "style": "primary",
                        }
                    ],
                }
            )
            # 대시보드일 때 채팅 링크도 추가
            if is_dashboard and dashboard_url and chat_url:
                blocks[-1]["elements"].append(
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "채팅에서 보기"},
                        "url": chat_url,
                    }
                )
        payload = {
            "text": f"[Schedule] {rendered_title}",
            "blocks": blocks,
        }
    elif provider == "teams":
        body = [
            {
                "type": "TextBlock",
                "text": rendered_title,
                "weight": "Bolder",
                "size": "Large",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": meta_label, "value": meta_value},
                    {"title": "Completed", "value": completed_at},
                ],
            },
        ]
        body.extend(_markdown_to_adaptive_elements(display_result))
        if chart_image_urls:
            for img_url in chart_image_urls:
                body.append(
                    {
                        "type": "Image",
                        "url": img_url,
                        "size": "Stretch",
                    }
                )
        actions = []
        if primary_url:
            actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": primary_label,
                    "url": primary_url,
                }
            )
        if is_dashboard and dashboard_url and chat_url:
            actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": "채팅에서 보기",
                    "url": chat_url,
                }
            )
        if actions:
            body.append({"type": "ActionSet", "actions": actions})
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.5",
                        "body": body,
                    },
                }
            ],
        }
    elif provider == "discord":
        embed = {
            "title": rendered_title,
            "fields": [
                {"name": meta_label, "value": meta_value, "inline": False},
                {"name": "Completed", "value": completed_at, "inline": True},
            ],
            "description": display_result,
            "color": 3066993 if is_dashboard else 3447003,
        }
        if primary_url:
            embed["url"] = primary_url
        if chart_image_urls:
            embed["image"] = {"url": chart_image_urls[0]}
        payload = {"embeds": [embed]}
    elif provider == "telegram":
        link = f"\n\n[{primary_label}]({primary_url})" if primary_url else ""
        text = f"*{rendered_title}*\n\n*{meta_label}:* {meta_value}\n*Completed:* {completed_at}\n\n{display_result}{link}"
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
    elif provider == "google_chat":
        widgets = [
            {
                "keyValue": {
                    "topLabel": meta_label,
                    "content": meta_value[:500],
                }
            },
            {
                "keyValue": {
                    "topLabel": "Completed",
                    "content": completed_at,
                }
            },
            {"textParagraph": {"text": display_result}},
        ]
        if chart_image_urls:
            for img_url in chart_image_urls:
                widgets.append({"image": {"imageUrl": img_url}})
        buttons = []
        if primary_url:
            buttons.append(
                {
                    "textButton": {
                        "text": primary_label,
                        "onClick": {"openLink": {"url": primary_url}},
                    }
                }
            )
        if is_dashboard and dashboard_url and chat_url:
            buttons.append(
                {
                    "textButton": {
                        "text": "채팅에서 보기",
                        "onClick": {"openLink": {"url": chat_url}},
                    }
                }
            )
        if buttons:
            widgets.append({"buttons": buttons})
        payload = {
            "cards": [
                {
                    "header": {"title": rendered_title},
                    "sections": [{"widgets": widgets}],
                }
            ]
        }
    else:
        # Generic JSON payload
        payload = {
            "schedule_name": schedule_name,
            "prompt": prompt if not is_dashboard else meta_value,
            "result": display_result,
            "completed_at": completed_at,
        }
        if primary_url:
            payload["url"] = primary_url
        if chat_url:
            payload["chat_url"] = chat_url
        if dashboard_url:
            payload["dashboard_url"] = dashboard_url
        if chart_image_urls:
            payload["chart_images"] = chart_image_urls

    # Debug: log payload summary
    log.info(
        f"  Webhook payload: provider='{provider}', title='{rendered_title}', "
        f"result_raw_len={len(result_raw)}, display_result_len={len(display_result)}, "
        f"display_result_preview='{display_result[:200]}'"
    )

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp_body = await resp.text()
                if resp.status >= 400:
                    log.warning(
                        f"Webhook notification failed: {resp.status} body={resp_body[:500]} for channel '{channel_name}'"
                    )
                else:
                    log.info(
                        f"Webhook notification sent via '{channel_name}': status={resp.status}, body={resp_body[:200]}"
                    )

            # Telegram: send chart images via /sendPhoto
            if provider == "telegram" and chart_image_urls:
                photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                for img_url in chart_image_urls:
                    async with session.post(
                        photo_url,
                        json={
                            "chat_id": telegram_chat_id,
                            "photo": img_url,
                            "caption": rendered_title,
                        },
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as photo_resp:
                        if photo_resp.status >= 400:
                            body = await photo_resp.text()
                            log.warning(
                                f"Telegram sendPhoto failed: {photo_resp.status} body={body[:500]}"
                            )
    except Exception as e:
        log.warning(f"Webhook notification error (channel={channel_name}): {e}")


# ──────────────────────────────────────────────────────
# Legacy webhook delivery (backwards compatibility)
# ──────────────────────────────────────────────────────


async def _send_legacy_webhook(url: str, schedule, task, content: str):
    """Send task result to a webhook URL (legacy {"type": "webhook", "url": "..."} format)."""
    if not url:
        log.warning("Webhook URL is empty, skipping")
        return

    payload = {
        "schedule_id": schedule.id,
        "schedule_name": schedule.name,
        "task_id": task.id,
        "prompt": task.prompt,
        "result": content,
        "scheduled_at": task.scheduled_at,
        "completed_at": int(time.time()),
    }

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    log.warning(
                        f"Webhook delivery failed: {resp.status} for schedule {schedule.id}"
                    )
    except Exception as e:
        log.warning(f"Webhook delivery error: {e}")


# ──────────────────────────────────────────────────────
# Chart image extraction (server-side rendering)
# ──────────────────────────────────────────────────────


def _extract_chart_images(result_content: str) -> List[bytes]:
    """Extract chart images from [[dbsphere:chart]] blocks in result_content.

    The chart data is a JSON array of chart_result dicts:
      [[dbsphere:chart]]
      ```json
      [{chart_result1}, {chart_result2}, ...]
      ```

    Returns:
        List of PNG image bytes (one per chart).
    """
    match = _CHART_BLOCK_RE.search(result_content)
    if not match:
        return []

    try:
        parsed = _json.loads(match.group(1))
    except (ValueError, TypeError):
        log.warning("Failed to parse chart JSON from result content")
        return []

    # Normalize: single object → list (backwards compat)
    chart_results = parsed if isinstance(parsed, list) else [parsed]
    if not chart_results:
        return []

    try:
        from extension_modules.dbsphere.chart.plotly_generator import (
            PlotlyChartGenerator,
        )

        generator = PlotlyChartGenerator()
    except ImportError:
        log.warning("PlotlyChartGenerator not available, skipping chart rendering")
        return []

    images: List[bytes] = []
    for idx, chart_result in enumerate(chart_results):
        try:
            img_bytes = generator.chart_result_to_image(chart_result)
            images.append(img_bytes)
        except Exception as e:
            log.warning(f"Failed to render chart image #{idx}: {e}")
    return images


def _strip_chart_block(result_content: str) -> str:
    """Remove [[dbsphere:chart]] + JSON code block from result_content.

    Returns clean text suitable for notifications.
    """
    cleaned = _CHART_BLOCK_RE.sub("", result_content)
    # Collapse excessive blank lines left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _is_retriable_error(e: Exception) -> bool:
    """Check if an error is retriable (timeouts, 5xx errors)."""
    error_str = str(e).lower()
    retriable_keywords = ["timeout", "503", "502", "504", "connection", "rate limit"]
    return any(kw in error_str for kw in retriable_keywords)
