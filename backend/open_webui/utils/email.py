import base64
import logging
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

import requests

log = logging.getLogger(__name__)


def _lazy_import_azure_email():
    """Lazy import for azure-communication-email SDK."""
    try:
        from azure.communication.email import EmailClient

        return EmailClient
    except ImportError:
        raise ImportError(
            "azure-communication-email package is required for Azure Email. "
            "Install it with: pip install azure-communication-email"
        )


class EmailSender:
    """SMTP email sender utility class."""

    def __init__(
        self,
        server: str,
        port: int,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        from_address: str = "",
        from_name: str = "",
    ):
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.from_address = from_address or username
        self.from_name = from_name

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Send email to recipients.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML email body
            attachments: Optional list of {"filename": str, "content": bytes, "mime_type": str}
            cc: Optional list of CC recipient email addresses

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            if attachments:
                msg = MIMEMultipart("mixed")
                alt = MIMEMultipart("alternative")
                alt.attach(MIMEText(body, "plain", "utf-8"))
                if html_body:
                    alt.attach(MIMEText(html_body, "html", "utf-8"))
                msg.attach(alt)
                for att in attachments:
                    part = MIMEApplication(att["content"])
                    part.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=att["filename"],
                    )
                    if att.get("mime_type"):
                        part.set_type(att["mime_type"])
                    msg.attach(part)
            else:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body, "plain", "utf-8"))
                if html_body:
                    msg.attach(MIMEText(html_body, "html", "utf-8"))

            msg["Subject"] = subject
            if self.from_name:
                msg["From"] = f"{self.from_name} <{self.from_address}>"
            else:
                msg["From"] = self.from_address
            msg["To"] = ", ".join(to)
            cc_list = [c for c in (cc or []) if c]
            if cc_list:
                msg["Cc"] = ", ".join(cc_list)
            envelope_recipients = list(to) + cc_list

            context = ssl.create_default_context()

            if self.use_ssl:
                with smtplib.SMTP_SSL(
                    self.server,
                    self.port,
                    context=context,
                    local_hostname="localhost",
                ) as server:
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.sendmail(
                        self.from_address, envelope_recipients, msg.as_string()
                    )
            else:
                with smtplib.SMTP(
                    self.server,
                    self.port,
                    local_hostname="localhost",
                ) as server:
                    if self.use_tls:
                        server.starttls(context=context)
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.sendmail(
                        self.from_address, envelope_recipients, msg.as_string()
                    )

            log.info(f"Email sent successfully to {to}")
            return True
        except Exception as e:
            log.error(f"Failed to send email: {e}")
            return False

    def test_connection(self) -> dict:
        """Test SMTP server connection.

        Returns:
            Dictionary with 'success' boolean and 'message' string
        """
        try:
            context = ssl.create_default_context()

            if self.use_ssl:
                with smtplib.SMTP_SSL(
                    self.server,
                    self.port,
                    context=context,
                    timeout=10,
                    local_hostname="localhost",
                ) as server:
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.noop()
            else:
                with smtplib.SMTP(
                    self.server,
                    self.port,
                    timeout=10,
                    local_hostname="localhost",
                ) as server:
                    if self.use_tls:
                        server.starttls(context=context)
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.noop()

            return {"success": True, "message": "Connection successful"}
        except smtplib.SMTPAuthenticationError as e:
            log.error(f"SMTP authentication failed: {e}")
            return {"success": False, "message": "Authentication failed"}
        except smtplib.SMTPConnectError as e:
            log.error(f"SMTP connection failed: {e}")
            return {"success": False, "message": "Connection failed"}
        except TimeoutError:
            log.error("SMTP connection timed out")
            return {"success": False, "message": "Connection timed out"}
        except Exception as e:
            log.error(f"SMTP connection test failed: {e}")
            return {"success": False, "message": str(e)}


class SendGridSender:
    """SendGrid email sender utility class."""

    SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(
        self,
        api_key: str,
        from_address: str = "",
        from_name: str = "",
    ):
        self.api_key = api_key
        self.from_address = from_address
        self.from_name = from_name

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Send email via SendGrid API.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML email body
            attachments: Optional list of {"filename": str, "content": bytes, "mime_type": str}
            cc: Optional list of CC recipient email addresses

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            cc_list = [c for c in (cc or []) if c]
            personalization = {"to": [{"email": email} for email in to]}
            if cc_list:
                personalization["cc"] = [{"email": email} for email in cc_list]
            personalizations = [personalization]

            from_obj = {"email": self.from_address}
            if self.from_name:
                from_obj["name"] = self.from_name

            content = [{"type": "text/plain", "value": body}]
            if html_body:
                content.append({"type": "text/html", "value": html_body})

            payload = {
                "personalizations": personalizations,
                "from": from_obj,
                "subject": subject,
                "content": content,
            }

            if attachments:
                payload["attachments"] = [
                    {
                        "content": base64.b64encode(att["content"]).decode("ascii"),
                        "filename": att["filename"],
                        "type": att.get("mime_type", "application/octet-stream"),
                    }
                    for att in attachments
                ]

            response = requests.post(
                self.SENDGRID_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code in [200, 201, 202]:
                log.info(f"SendGrid email sent successfully to {to}")
                return True
            else:
                log.error(
                    f"SendGrid API error: {response.status_code} - {response.text}"
                )
                return False
        except Exception as e:
            log.error(f"Failed to send SendGrid email: {e}")
            return False

    def test_connection(self) -> dict:
        """Test SendGrid API key validity.

        Returns:
            Dictionary with 'success' boolean and 'message' string
        """
        try:
            # Use the API key validation endpoint
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            # Check API key by getting scopes
            response = requests.get(
                "https://api.sendgrid.com/v3/scopes",
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                return {"success": True, "message": "API key is valid"}
            elif response.status_code == 401:
                return {"success": False, "message": "Invalid API key"}
            else:
                return {
                    "success": False,
                    "message": f"API error: {response.status_code}",
                }
        except requests.exceptions.Timeout:
            return {"success": False, "message": "Connection timed out"}
        except Exception as e:
            log.error(f"SendGrid connection test failed: {e}")
            return {"success": False, "message": str(e)}


class MSGraphEmailSender:
    """Microsoft Graph API email sender using Client Credentials Flow."""

    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    SEND_MAIL_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        sender_email: str,
        from_name: str = "",
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.sender_email = sender_email
        self.from_name = from_name

    def _get_access_token(self) -> str:
        """Get access token via Client Credentials Flow."""
        url = self.TOKEN_URL.format(tenant_id=self.tenant_id)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        response = requests.post(url, data=data, timeout=30)
        response.raise_for_status()
        return response.json()["access_token"]

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Send email via Microsoft Graph API.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML email body
            attachments: Optional list of {"filename": str, "content": bytes, "mime_type": str}
            cc: Optional list of CC recipient email addresses

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            token = self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            message = {
                "subject": subject,
                "body": {
                    "contentType": "HTML" if html_body else "Text",
                    "content": html_body or body,
                },
                "toRecipients": [{"emailAddress": {"address": email}} for email in to],
            }
            cc_list = [c for c in (cc or []) if c]
            if cc_list:
                message["ccRecipients"] = [
                    {"emailAddress": {"address": email}} for email in cc_list
                ]

            if attachments:
                message["attachments"] = [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att["filename"],
                        "contentType": att.get("mime_type", "application/octet-stream"),
                        "contentBytes": base64.b64encode(att["content"]).decode(
                            "ascii"
                        ),
                    }
                    for att in attachments
                ]

            payload = {"message": message, "saveToSentItems": "true"}

            url = self.SEND_MAIL_URL.format(sender=self.sender_email)
            response = requests.post(url, headers=headers, json=payload, timeout=30)

            if response.status_code == 202:
                log.info(f"Graph API email sent successfully to {to}")
                return True
            else:
                error_detail = (
                    f"Graph API error: {response.status_code} - {response.text}"
                )
                log.error(error_detail)
                raise RuntimeError(error_detail)
        except RuntimeError:
            raise
        except Exception as e:
            error_detail = f"Failed to send Graph API email: {e}"
            log.error(error_detail)
            raise RuntimeError(error_detail)

    def test_connection(self) -> dict:
        """Test Graph API connection by acquiring an access token.

        Returns:
            Dictionary with 'success' boolean and 'message' string
        """
        try:
            self._get_access_token()
            return {"success": True, "message": "Graph API authentication successful"}
        except requests.exceptions.HTTPError as e:
            log.error(f"Graph API auth failed: {e}")
            error_detail = ""
            if e.response is not None:
                try:
                    error_detail = e.response.json().get("error_description", str(e))
                except Exception:
                    error_detail = str(e)
            return {
                "success": False,
                "message": f"Authentication failed: {error_detail}",
            }
        except requests.exceptions.Timeout:
            return {"success": False, "message": "Connection timed out"}
        except Exception as e:
            log.error(f"Graph API connection test failed: {e}")
            return {"success": False, "message": str(e)}


class AzureEmailSender:
    """Azure Communication Services email sender utility class."""

    def __init__(
        self,
        connection_string: str,
        from_address: str = "",
        from_name: str = "",
    ):
        self.connection_string = connection_string
        self.from_address = from_address
        self.from_name = from_name

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Send email via Azure Communication Services.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML email body
            cc: Optional list of CC recipient email addresses

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            EmailClient = _lazy_import_azure_email()
            client = EmailClient.from_connection_string(self.connection_string)

            content = {"subject": subject, "plainText": body}
            if html_body:
                content["html"] = html_body

            recipients = {"to": [{"address": email} for email in to]}
            cc_list = [c for c in (cc or []) if c]
            if cc_list:
                recipients["cc"] = [{"address": email} for email in cc_list]

            message = {
                "senderAddress": self.from_address,
                "content": content,
                "recipients": recipients,
            }

            poller = client.begin_send(message)
            result = poller.result()

            if result["status"] == "Succeeded":
                log.info(f"Azure email sent successfully to {to}")
                return True
            else:
                log.error(f"Azure email failed with status: {result['status']}")
                return False
        except Exception as e:
            log.error(f"Failed to send Azure email: {e}")
            return False

    def test_connection(self) -> dict:
        """Test Azure Communication Services connection.

        Returns:
            Dictionary with 'success' boolean and 'message' string
        """
        try:
            EmailClient = _lazy_import_azure_email()
            # Validate by creating the client — will fail if connection string is invalid
            EmailClient.from_connection_string(self.connection_string)
            return {"success": True, "message": "Connection string is valid"}
        except ImportError as e:
            return {"success": False, "message": str(e)}
        except Exception as e:
            log.error(f"Azure email connection test failed: {e}")
            return {"success": False, "message": str(e)}
