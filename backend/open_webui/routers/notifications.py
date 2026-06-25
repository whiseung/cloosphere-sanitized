import logging
from typing import List

from fastapi import APIRouter, Depends, Query, Request
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.crypto import is_masked, mask_config_dict
from open_webui.utils.email import (
    AzureEmailSender,
    EmailSender,
    MSGraphEmailSender,
    SendGridSender,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


############################
# Request/Response Models
############################


class SmtpConfig(BaseModel):
    server: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    from_address: str = ""
    from_name: str = "Cloosphere"


class SendGridConfig(BaseModel):
    api_key: str = ""
    from_address: str = ""
    from_name: str = "Cloosphere"


class AzureEmailConfig(BaseModel):
    connection_string: str = ""
    from_address: str = ""
    from_name: str = "Cloosphere"


class MsGraphConfig(BaseModel):
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    sender_email: str = ""
    from_name: str = "Cloosphere"


class EmailChannelConfig(BaseModel):
    name: str = ""
    engine: str = ""  # "smtp" | "sendgrid" | "azure" | "msgraph"
    smtp: SmtpConfig = SmtpConfig()
    sendgrid: SendGridConfig = SendGridConfig()
    azure: AzureEmailConfig = AzureEmailConfig()
    msgraph: MsGraphConfig = MsGraphConfig()


class WebhookChannelConfig(BaseModel):
    name: str = ""
    provider: str = ""  # "slack" | "teams" | "discord" | "telegram"
    url: str = ""  # Slack/Teams webhook URL
    bot_token: str = ""  # Telegram bot token
    chat_id: str = ""  # Telegram chat ID


class NotificationConfig(BaseModel):
    emails: List[EmailChannelConfig] = []
    webhooks: List[WebhookChannelConfig] = []
    events: List[str] = []


class TestEmailRequest(BaseModel):
    to: str
    index: int = 0


class TestResponse(BaseModel):
    success: bool
    message: str


############################
# Helpers
############################


def _mask_email_channel(ch: dict) -> dict:
    """Return a copy of the channel dict with sensitive values masked."""
    return mask_config_dict(ch)


def _build_email_channels(request: Request) -> list:
    """Read stored channels, migrating from legacy fields if the list is empty."""
    channels = list(request.app.state.config.NOTIFICATION_EMAIL_CHANNELS)
    if not channels:
        engine = request.app.state.config.EMAIL_ENGINE
        if engine:
            channels = [
                {
                    "name": "기본",
                    "engine": engine,
                    "smtp": {
                        "server": request.app.state.config.SMTP_SERVER,
                        "port": request.app.state.config.SMTP_PORT,
                        "username": request.app.state.config.SMTP_USERNAME,
                        "password": request.app.state.config.SMTP_PASSWORD,
                        "use_tls": request.app.state.config.SMTP_USE_TLS,
                        "use_ssl": request.app.state.config.SMTP_USE_SSL,
                        "from_address": request.app.state.config.SMTP_FROM_ADDRESS,
                        "from_name": request.app.state.config.SMTP_FROM_NAME,
                    },
                    "sendgrid": {
                        "api_key": request.app.state.config.SENDGRID_API_KEY,
                        "from_address": request.app.state.config.SENDGRID_FROM_ADDRESS,
                        "from_name": request.app.state.config.SENDGRID_FROM_NAME,
                    },
                }
            ]
    return channels


def _build_webhook_channels(request: Request) -> list:
    """Read stored channels, migrating from legacy fields if the list is empty."""
    channels = list(request.app.state.config.NOTIFICATION_WEBHOOK_CHANNELS)
    if not channels:
        provider = request.app.state.config.WEBHOOK_PROVIDER
        url = request.app.state.config.WEBHOOK_URL
        if provider or url:
            channels = [{"name": "기본", "provider": provider, "url": url}]
    return channels


############################
# GET /channels (for schedule form dropdown — no secrets)
############################


@router.get("/channels")
async def get_notification_channel_list(
    request: Request, user=Depends(get_verified_user)
):
    """Return channel names/types only (no secrets). Used by schedule delivery UI."""
    email_channels = _build_email_channels(request)
    webhook_channels = _build_webhook_channels(request)

    return {
        "emails": [
            {"name": ch.get("name", ""), "engine": ch.get("engine", "")}
            for ch in email_channels
        ],
        "webhooks": [
            {"name": ch.get("name", ""), "provider": ch.get("provider", "")}
            for ch in webhook_channels
        ],
    }


############################
# GET /config
############################


@router.get("/config")
async def get_notification_config(request: Request, user=Depends(get_admin_user)):
    """Get notification configuration."""
    email_channels = _build_email_channels(request)
    webhook_channels = _build_webhook_channels(request)

    return mask_config_dict(
        {
            "emails": [_mask_email_channel(ch) for ch in email_channels],
            "webhooks": webhook_channels,
            "events": request.app.state.config.NOTIFICATION_EVENTS,
        }
    )


############################
# POST /config
############################


@router.post("/config")
async def update_notification_config(
    request: Request,
    form_data: NotificationConfig,
    user=Depends(get_admin_user),
):
    """Update notification configuration."""
    new_email_channels = [ch.model_dump() for ch in form_data.emails]
    # Resolve masked sensitive values back to current values
    current_channels = list(request.app.state.config.NOTIFICATION_EMAIL_CHANNELS)
    for i, ch in enumerate(new_email_channels):
        if i < len(current_channels):
            cur = current_channels[i]
            # SMTP password
            smtp = ch.get("smtp", {})
            cur_smtp = cur.get("smtp", {})
            if (
                smtp
                and isinstance(smtp.get("password"), str)
                and is_masked(smtp["password"])
            ):
                smtp["password"] = cur_smtp.get("password", "")
            # SendGrid API key
            sg = ch.get("sendgrid", {})
            cur_sg = cur.get("sendgrid", {})
            if sg and isinstance(sg.get("api_key"), str) and is_masked(sg["api_key"]):
                sg["api_key"] = cur_sg.get("api_key", "")
            # Azure connection string
            az = ch.get("azure", {})
            cur_az = cur.get("azure", {})
            if (
                az
                and isinstance(az.get("connection_string"), str)
                and is_masked(az["connection_string"])
            ):
                az["connection_string"] = cur_az.get("connection_string", "")
            # MS Graph client secret
            mg = ch.get("msgraph", {})
            cur_mg = cur.get("msgraph", {})
            if (
                mg
                and isinstance(mg.get("client_secret"), str)
                and is_masked(mg["client_secret"])
            ):
                mg["client_secret"] = cur_mg.get("client_secret", "")
    request.app.state.config.NOTIFICATION_EMAIL_CHANNELS = new_email_channels
    request.app.state.config.NOTIFICATION_WEBHOOK_CHANNELS = [
        ch.model_dump() for ch in form_data.webhooks
    ]
    request.app.state.config.NOTIFICATION_EVENTS = form_data.events

    AuditLogger.log_settings_change(
        "notifications",
        after_data={
            "email_channels_count": len(new_email_channels),
            "webhook_channels_count": len(form_data.webhooks),
            "events": form_data.events,
        },
    )

    return await get_notification_config(request, user)


############################
# POST /email/test-connection
############################


@router.post("/email/test-connection", response_model=TestResponse)
async def test_email_connection(
    request: Request,
    user=Depends(get_admin_user),
    index: int = Query(default=0),
):
    """Test email connection for the channel at the given index."""
    channels = _build_email_channels(request)
    if index >= len(channels):
        return TestResponse(success=False, message="Channel index out of range")

    ch = channels[index]
    engine = ch.get("engine", "")

    if engine == "smtp":
        smtp = ch.get("smtp", {})
        sender = EmailSender(
            server=smtp.get("server", ""),
            port=smtp.get("port", 587),
            username=smtp.get("username", ""),
            password=smtp.get("password", ""),
            use_tls=smtp.get("use_tls", True),
            use_ssl=smtp.get("use_ssl", False),
        )
        result = sender.test_connection()
        return TestResponse(**result)
    elif engine == "sendgrid":
        sendgrid = ch.get("sendgrid", {})
        sender = SendGridSender(api_key=sendgrid.get("api_key", ""))
        result = sender.test_connection()
        return TestResponse(**result)
    elif engine == "azure":
        azure = ch.get("azure", {})
        sender = AzureEmailSender(
            connection_string=azure.get("connection_string", ""),
        )
        result = sender.test_connection()
        return TestResponse(**result)
    elif engine == "msgraph":
        mg = ch.get("msgraph", {})
        sender = MSGraphEmailSender(
            tenant_id=mg.get("tenant_id", ""),
            client_id=mg.get("client_id", ""),
            client_secret=mg.get("client_secret", ""),
            sender_email=mg.get("sender_email", ""),
        )
        result = sender.test_connection()
        return TestResponse(**result)
    else:
        return TestResponse(success=False, message="No email engine configured")


############################
# POST /email/test
############################


@router.post("/email/test", response_model=TestResponse)
async def send_test_email(
    request: Request,
    form_data: TestEmailRequest,
    user=Depends(get_admin_user),
):
    """Send a test email using the channel at form_data.index."""
    channels = _build_email_channels(request)
    index = form_data.index
    if index >= len(channels):
        return TestResponse(success=False, message="Channel index out of range")

    ch = channels[index]
    engine = ch.get("engine", "")

    subject = "[Cloosphere] Test Email"
    body = "This is a test email from Cloosphere notification system.\n\nIf you received this email, your email configuration is working correctly."
    html_body = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px;">
    <h1 style="color: #333;">Test Email</h1>
    <p>This is a test email from <strong>Cloosphere</strong> notification system.</p>
    <p>If you received this email, your email configuration is working correctly.</p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
    <p style="color: #666; font-size: 12px;">Sent by Cloosphere</p>
</body>
</html>
"""

    if engine == "smtp":
        smtp = ch.get("smtp", {})
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
            to=[form_data.to],
            subject=subject,
            body=body,
            html_body=html_body,
        )
    elif engine == "sendgrid":
        sendgrid = ch.get("sendgrid", {})
        sender = SendGridSender(
            api_key=sendgrid.get("api_key", ""),
            from_address=sendgrid.get("from_address", ""),
            from_name=sendgrid.get("from_name", "Cloosphere"),
        )
        success = sender.send_email(
            to=[form_data.to],
            subject=subject,
            body=body,
            html_body=html_body,
        )
    elif engine == "azure":
        azure = ch.get("azure", {})
        sender = AzureEmailSender(
            connection_string=azure.get("connection_string", ""),
            from_address=azure.get("from_address", ""),
            from_name=azure.get("from_name", "Cloosphere"),
        )
        success = sender.send_email(
            to=[form_data.to],
            subject=subject,
            body=body,
            html_body=html_body,
        )
    elif engine == "msgraph":
        mg = ch.get("msgraph", {})
        sender = MSGraphEmailSender(
            tenant_id=mg.get("tenant_id", ""),
            client_id=mg.get("client_id", ""),
            client_secret=mg.get("client_secret", ""),
            sender_email=mg.get("sender_email", ""),
            from_name=mg.get("from_name", "Cloosphere"),
        )
        success = sender.send_email(
            to=[form_data.to],
            subject=subject,
            body=body,
            html_body=html_body,
        )
    else:
        return TestResponse(success=False, message="No email engine configured")

    if success:
        return TestResponse(success=True, message="Test email sent successfully")
    else:
        return TestResponse(success=False, message="Failed to send test email")


############################
# POST /webhook/test
############################


@router.post("/webhook/test", response_model=TestResponse)
async def test_webhook(
    request: Request,
    user=Depends(get_admin_user),
    index: int = Query(default=0),
):
    """Send a test message to the webhook channel at the given index."""
    import requests as http_requests

    channels = _build_webhook_channels(request)
    if index >= len(channels):
        return TestResponse(success=False, message="Channel index out of range")

    ch = channels[index]
    provider = ch.get("provider", "")
    url = ch.get("url", "")

    if provider == "telegram":
        bot_token = ch.get("bot_token", "")
        chat_id = ch.get("chat_id", "")
        if not bot_token or not chat_id:
            return TestResponse(
                success=False, message="Bot Token and Chat ID are required for Telegram"
            )
    elif not url:
        return TestResponse(success=False, message="No webhook URL configured")

    try:
        if provider == "slack":
            payload = {
                "text": "Cloosphere Test Notification",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Cloosphere Test Notification*\n\nThis is a test message from Cloosphere. If you see this message, your Slack webhook is configured correctly.",
                        },
                    }
                ],
            }
        elif provider == "teams":
            payload = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "themeColor": "0076D7",
                "summary": "Cloosphere Test Notification",
                "sections": [
                    {
                        "activityTitle": "Cloosphere Test Notification",
                        "text": "This is a test message from Cloosphere. If you see this message, your Teams webhook is configured correctly.",
                    }
                ],
            }
        elif provider == "discord":
            payload = {
                "content": "**Cloosphere Test Notification**\n\nThis is a test message from Cloosphere. If you see this message, your Discord webhook is configured correctly.",
            }
        elif provider == "telegram":
            telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            telegram_payload = {
                "chat_id": chat_id,
                "text": "*Cloosphere Test Notification*\n\nThis is a test message from Cloosphere. If you see this message, your Telegram bot is configured correctly.",
                "parse_mode": "Markdown",
            }
            response = http_requests.post(
                telegram_url, json=telegram_payload, timeout=10
            )
            if response.status_code == 200:
                return TestResponse(
                    success=True, message="Webhook test sent successfully"
                )
            else:
                return TestResponse(
                    success=False,
                    message=f"Telegram API returned status {response.status_code}",
                )
        elif provider == "google_chat":
            payload = {
                "cards": [
                    {
                        "header": {
                            "title": "Cloosphere Test Notification",
                            "imageUrl": "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/check_circle/default/48px.svg",
                        },
                        "sections": [
                            {
                                "widgets": [
                                    {
                                        "textParagraph": {
                                            "text": "This is a test message from Cloosphere. If you see this message, your Google Chat webhook is configured correctly."
                                        }
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        else:
            return TestResponse(
                success=False, message=f"Unsupported webhook provider: {provider}"
            )

        response = http_requests.post(url, json=payload, timeout=10)

        if response.status_code in [200, 201, 202, 204]:
            return TestResponse(success=True, message="Webhook test sent successfully")
        else:
            return TestResponse(
                success=False,
                message=f"Webhook returned status {response.status_code}",
            )
    except http_requests.exceptions.Timeout:
        return TestResponse(success=False, message="Webhook request timed out")
    except Exception as e:
        log.error(f"Webhook test failed: {e}")
        return TestResponse(success=False, message=str(e))
