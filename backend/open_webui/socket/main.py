import asyncio
import logging
import sys
import time
from urllib.parse import urlparse

import socketio

from open_webui.env import (
    ENABLE_WEBSOCKET_SUPPORT,
    GLOBAL_LOG_LEVEL,
    SRC_LOG_LEVELS,
    WEBSOCKET_MANAGER,
    WEBSOCKET_PING_INTERVAL,
    WEBSOCKET_PING_TIMEOUT,
    WEBSOCKET_REDIS_LOCK_TIMEOUT,
    WEBSOCKET_REDIS_URL,
    WEBSOCKET_SENTINEL_HOSTS,
    WEBSOCKET_SENTINEL_PORT,
)
from open_webui.models.channels import Channels
from open_webui.models.chats import Chats
from open_webui.models.users import UserNameResponse, Users
from open_webui.socket.utils import RedisDict, RedisLock
from open_webui.utils.auth import decode_token
from open_webui.utils.redis import (
    get_sentinel_url_from_env,
    get_sentinels_from_env,
)

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["SOCKET"])


_use_redis = False


def _make_redis_manager(url):
    """Create AsyncRedisManager with SSL support for rediss:// URLs.

    python-socketio 5.14.0 _get_redis_module_and_error() rejects 'rediss://'.
    Workaround: subclass to accept 'rediss' scheme, then pass the original URL
    so that redis.asyncio.Redis.from_url() handles SSL natively.
    """

    class _PatchedAsyncRedisManager(socketio.AsyncRedisManager):
        def _get_redis_module_and_error(self):
            parsed = urlparse(self.redis_url)
            schema = parsed.scheme.split("+", 1)[0].lower()
            if schema in ("redis", "rediss"):
                try:
                    import redis.asyncio as aioredis
                    from redis.exceptions import RedisError

                    return aioredis, RedisError
                except ImportError:
                    raise RuntimeError(
                        "Redis package is not installed "
                        '(Run "pip install redis" in your virtualenv).'
                    )
            return super()._get_redis_module_and_error()

    return _PatchedAsyncRedisManager(url)


if WEBSOCKET_MANAGER == "redis":
    try:
        if WEBSOCKET_SENTINEL_HOSTS:
            mgr = _make_redis_manager(
                get_sentinel_url_from_env(
                    WEBSOCKET_REDIS_URL,
                    WEBSOCKET_SENTINEL_HOSTS,
                    WEBSOCKET_SENTINEL_PORT,
                )
            )
        else:
            mgr = _make_redis_manager(WEBSOCKET_REDIS_URL)
        sio = socketio.AsyncServer(
            cors_allowed_origins=[],
            async_mode="asgi",
            transports=(["websocket"] if ENABLE_WEBSOCKET_SUPPORT else ["polling"]),
            allow_upgrades=ENABLE_WEBSOCKET_SUPPORT,
            always_connect=True,
            ping_interval=WEBSOCKET_PING_INTERVAL,
            ping_timeout=WEBSOCKET_PING_TIMEOUT,
            client_manager=mgr,
        )
        _use_redis = True
    except Exception as e:
        log.warning(
            f"Failed to connect to Redis for websocket manager: {e}. "
            "Falling back to in-memory mode (single worker only)."
        )

if not _use_redis:
    sio = socketio.AsyncServer(
        cors_allowed_origins=[],
        async_mode="asgi",
        transports=(["websocket"] if ENABLE_WEBSOCKET_SUPPORT else ["polling"]),
        allow_upgrades=ENABLE_WEBSOCKET_SUPPORT,
        always_connect=True,
        ping_interval=WEBSOCKET_PING_INTERVAL,
        ping_timeout=WEBSOCKET_PING_TIMEOUT,
    )


# Timeout duration in seconds
TIMEOUT_DURATION = 3

# Dictionary to maintain the user pool

if _use_redis:
    try:
        log.debug("Using Redis to manage websockets.")
        redis_sentinels = get_sentinels_from_env(
            WEBSOCKET_SENTINEL_HOSTS, WEBSOCKET_SENTINEL_PORT
        )
        SESSION_POOL = RedisDict(
            "open-webui:session_pool",
            redis_url=WEBSOCKET_REDIS_URL,
            redis_sentinels=redis_sentinels,
        )
        USER_POOL = RedisDict(
            "open-webui:user_pool",
            redis_url=WEBSOCKET_REDIS_URL,
            redis_sentinels=redis_sentinels,
        )
        USAGE_POOL = RedisDict(
            "open-webui:usage_pool",
            redis_url=WEBSOCKET_REDIS_URL,
            redis_sentinels=redis_sentinels,
        )

        clean_up_lock = RedisLock(
            redis_url=WEBSOCKET_REDIS_URL,
            lock_name="usage_cleanup_lock",
            timeout_secs=WEBSOCKET_REDIS_LOCK_TIMEOUT,
            redis_sentinels=redis_sentinels,
        )
        aquire_func = clean_up_lock.aquire_lock
        renew_func = clean_up_lock.renew_lock
        release_func = clean_up_lock.release_lock
    except Exception as e:
        log.warning(
            f"Failed to initialize Redis pools: {e}. "
            "Falling back to in-memory pools (single worker only)."
        )
        _use_redis = False

if not _use_redis:
    if WEBSOCKET_MANAGER == "redis":
        log.warning("Redis unavailable. Using in-memory pools (single worker only).")
    SESSION_POOL = {}
    USER_POOL = {}
    USAGE_POOL = {}
    aquire_func = release_func = renew_func = lambda: True


async def periodic_usage_pool_cleanup():
    while True:
        if not aquire_func():
            await asyncio.sleep(TIMEOUT_DURATION)
            continue

        log.debug("Acquired usage pool cleanup lock")
        try:
            while True:
                try:
                    if not renew_func():
                        log.warning("Unable to renew cleanup lock. Will re-acquire.")
                        break

                    now = int(time.time())
                    changed = False
                    for model_id, connections in list(USAGE_POOL.items()):
                        expired_sids = [
                            sid
                            for sid, details in connections.items()
                            if now - details["updated_at"] > TIMEOUT_DURATION
                        ]

                        if not expired_sids:
                            continue

                        changed = True
                        for sid in expired_sids:
                            del connections[sid]

                        if not connections:
                            log.debug(f"Cleaning up model {model_id} from usage pool")
                            del USAGE_POOL[model_id]
                        else:
                            # Write back to RedisDict
                            USAGE_POOL[model_id] = connections

                    if changed:
                        # Emit updated usage information after cleaning
                        await sio.emit("usage", {"models": get_models_in_use()})
                except Exception as e:
                    log.warning(f"Usage pool cleanup error (will retry): {e}")

                await asyncio.sleep(TIMEOUT_DURATION)
        finally:
            release_func()


app = socketio.ASGIApp(
    sio,
    socketio_path="/ws/socket.io",
)


def get_models_in_use():
    # List models that are currently in use
    models_in_use = list(USAGE_POOL.keys())
    return models_in_use


@sio.on("usage")
async def usage(sid, data):
    model_id = data["model"]
    # Record the timestamp for the last update
    current_time = int(time.time())

    # Store the new usage data and task
    USAGE_POOL[model_id] = {
        **(USAGE_POOL[model_id] if model_id in USAGE_POOL else {}),
        sid: {"updated_at": current_time},
    }

    # Broadcast the usage data to all clients
    await sio.emit("usage", {"models": get_models_in_use()})


@sio.event
async def connect(sid, environ, auth):
    user = None
    if auth and "token" in auth:
        data = decode_token(auth["token"])

        if data is not None and "id" in data:
            user = Users.get_user_by_id(data["id"])

        if user:
            SESSION_POOL[sid] = user.model_dump()
            if user.id in USER_POOL:
                USER_POOL[user.id] = USER_POOL[user.id] + [sid]
            else:
                USER_POOL[user.id] = [sid]

            await sio.enter_room(sid, f"user:{user.id}")

            # print(f"user {user.name}({user.id}) connected with session ID {sid}")
            await sio.emit("user-list", {"user_ids": list(USER_POOL.keys())})
            await sio.emit("usage", {"models": get_models_in_use()})


@sio.on("user-join")
async def user_join(sid, data):
    auth = data["auth"] if "auth" in data else None
    if not auth or "token" not in auth:
        return

    data = decode_token(auth["token"])
    if data is None or "id" not in data:
        return

    user = Users.get_user_by_id(data["id"])
    if not user:
        return

    SESSION_POOL[sid] = user.model_dump()
    if user.id in USER_POOL:
        USER_POOL[user.id] = USER_POOL[user.id] + [sid]
    else:
        USER_POOL[user.id] = [sid]

    await sio.enter_room(sid, f"user:{user.id}")

    # Join all the channels
    channels = Channels.get_channels_by_user_id(user.id)
    log.debug(f"{channels=}")
    for channel in channels:
        await sio.enter_room(sid, f"channel:{channel.id}")

    # print(f"user {user.name}({user.id}) connected with session ID {sid}")

    await sio.emit("user-list", {"user_ids": list(USER_POOL.keys())})
    return {"id": user.id, "name": user.name}


@sio.on("join-channels")
async def join_channel(sid, data):
    auth = data["auth"] if "auth" in data else None
    if not auth or "token" not in auth:
        return

    data = decode_token(auth["token"])
    if data is None or "id" not in data:
        return

    user = Users.get_user_by_id(data["id"])
    if not user:
        return

    # Join all the channels
    channels = Channels.get_channels_by_user_id(user.id)
    log.debug(f"{channels=}")
    for channel in channels:
        await sio.enter_room(sid, f"channel:{channel.id}")


@sio.on("channel-events")
async def channel_events(sid, data):
    room = f"channel:{data['channel_id']}"
    participants = sio.manager.get_participants(
        namespace="/",
        room=room,
    )

    sids = [sid for sid, _ in participants]
    if sid not in sids:
        return

    event_data = data["data"]
    event_type = event_data["type"]

    if event_type == "typing":
        await sio.emit(
            "channel-events",
            {
                "channel_id": data["channel_id"],
                "message_id": data.get("message_id", None),
                "data": event_data,
                "user": UserNameResponse(**SESSION_POOL[sid]).model_dump(),
            },
            room=room,
        )


@sio.on("user-list")
async def user_list(sid):
    await sio.emit("user-list", {"user_ids": list(USER_POOL.keys())})


@sio.on("ui:response")
async def ui_response(sid, data):
    """Receive UI command execution results from embed widget clients.

    Forwards to the UIActionManager's pending future registry.
    """
    try:
        from extension_modules.agent.ui_action_tools import register_ui_response

        request_id = data.get("request_id") if isinstance(data, dict) else None
        result = data.get("result") if isinstance(data, dict) else None
        if request_id:
            await register_ui_response(request_id, result)
    except Exception as e:
        log.error(f"[ui:response] failed to handle: {e}")


@sio.event
async def disconnect(sid):
    if sid in SESSION_POOL:
        user = SESSION_POOL[sid]
        del SESSION_POOL[sid]

        user_id = user["id"]
        USER_POOL[user_id] = [_sid for _sid in USER_POOL[user_id] if _sid != sid]

        if len(USER_POOL[user_id]) == 0:
            del USER_POOL[user_id]

        await sio.emit("user-list", {"user_ids": list(USER_POOL.keys())})
    else:
        pass
        # print(f"Unknown session ID {sid} disconnected")


def get_event_emitter(request_info, update_db=True):
    user_id = request_info["user_id"]
    _user_room = f"user:{user_id}"

    async def __event_emitter__(event_data):
        try:
            await sio.emit(
                "chat-events",
                {
                    "chat_id": request_info.get("chat_id", None),
                    "message_id": request_info.get("message_id", None),
                    "data": event_data,
                },
                room=_user_room,
            )
        except Exception:
            return  # 소켓 전송 실패 시 무시

        if update_db:
            try:
                loop = asyncio.get_event_loop()

                if "type" in event_data and event_data["type"] == "status":
                    await loop.run_in_executor(
                        None,
                        Chats.add_message_status_to_chat_by_id_and_message_id,
                        request_info["chat_id"],
                        request_info["message_id"],
                        event_data.get("data", {}),
                    )

                if "type" in event_data and event_data["type"] == "message":
                    message = await loop.run_in_executor(
                        None,
                        Chats.get_message_by_id_and_message_id,
                        request_info["chat_id"],
                        request_info["message_id"],
                    )

                    if message:
                        content = message.get("content", "")
                        content += event_data.get("data", {}).get("content", "")

                        await loop.run_in_executor(
                            None,
                            Chats.upsert_message_to_chat_by_id_and_message_id,
                            request_info["chat_id"],
                            request_info["message_id"],
                            {
                                "content": content,
                            },
                        )

                if "type" in event_data and event_data["type"] in (
                    "source",
                    "citation",
                ):
                    source_data = event_data.get("data", {})
                    if source_data:
                        await loop.run_in_executor(
                            None,
                            Chats.add_message_source_to_chat_by_id_and_message_id,
                            request_info["chat_id"],
                            request_info["message_id"],
                            source_data,
                        )

                if "type" in event_data and event_data["type"] == "replace":
                    content = event_data.get("data", {}).get("content", "")

                    await loop.run_in_executor(
                        None,
                        Chats.upsert_message_to_chat_by_id_and_message_id,
                        request_info["chat_id"],
                        request_info["message_id"],
                        {
                            "content": content,
                        },
                    )
            except Exception as e:
                log.warning(f"Event emitter DB update failed: {e}")

    return __event_emitter__


def get_event_call(request_info):
    async def __event_caller__(event_data):
        response = await sio.call(
            "chat-events",
            {
                "chat_id": request_info.get("chat_id", None),
                "message_id": request_info.get("message_id", None),
                "data": event_data,
            },
            to=request_info["session_id"],
        )
        return response

    return __event_caller__


get_event_caller = get_event_call


def get_user_id_from_session_pool(sid):
    user = SESSION_POOL.get(sid)
    if user:
        return user["id"]
    return None


def get_user_ids_from_room(room):
    active_session_ids = sio.manager.get_participants(
        namespace="/",
        room=room,
    )

    active_user_ids = list(
        set(
            [SESSION_POOL.get(session_id[0])["id"] for session_id in active_session_ids]
        )
    )
    return active_user_ids


def get_active_status_by_user_id(user_id):
    if user_id in USER_POOL:
        return True
    return False


async def send_notification_to_user(user_id: str, event_type: str, data: dict):
    """
    Send a notification to a specific user via Socket.IO.

    Args:
        user_id: The user ID to send notification to
        event_type: Type of notification (e.g., "task-completed", "task-failed")
        data: Notification data payload

    Returns:
        True if notification was sent to at least one session
    """
    if user_id not in USER_POOL:
        log.debug(f"User {user_id} not connected, skipping notification")
        return False

    session_ids = USER_POOL.get(user_id, [])
    if not session_ids:
        return False

    for session_id in session_ids:
        await sio.emit(
            "notification",
            {
                "type": event_type,
                "data": data,
                "timestamp": int(time.time()),
            },
            to=session_id,
        )

    log.debug(
        f"Sent {event_type} notification to user {user_id} ({len(session_ids)} sessions)"
    )
    return True
