"""Email service for portal notifications.

Supports SendGrid (default) and Office 365 SMTP.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

logger = logging.getLogger(__name__)


class EmailService:
    """Email service supporting SendGrid and Office 365 SMTP."""

    def __init__(
        self,
        provider: str = "sendgrid",
        from_email: Optional[str] = None,
        from_name: str = "Kanban Portal",
        sendgrid_api_key: Optional[str] = None,
        smtp_host: str = "smtp.office365.com",
        smtp_port: int = 587,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
    ):
        self.provider = provider.lower()
        self.from_email = from_email
        self.from_name = from_name
        self.sendgrid_api_key = sendgrid_api_key
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password

    def _send_with_sendgrid(
        self,
        to_email: str,
        subject: str,
        plain_content: str,
        html_content: str,
    ) -> dict:
        """Send email using SendGrid."""
        if not self.sendgrid_api_key or not self.from_email:
            return {"sent": False, "error": "SendGrid is not configured"}

        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            mail = Mail(
                from_email=(self.from_email, self.from_name),
                to_emails=to_email,
                subject=subject,
                plain_text_content=plain_content,
                html_content=html_content,
            )

            client = SendGridAPIClient(self.sendgrid_api_key)
            response = client.send(mail)
            sent = 200 <= response.status_code < 300
            if sent:
                logger.info(f"Email sent via SendGrid to {to_email}")
            return {"sent": sent, "status_code": response.status_code, "provider": "sendgrid"}
        except ImportError:
            return {"sent": False, "error": "SendGrid library not installed"}
        except Exception as exc:
            logger.error(f"SendGrid email error: {exc}")
            return {"sent": False, "error": str(exc)}

    def _send_with_office365(
        self,
        to_email: str,
        subject: str,
        plain_content: str,
        html_content: str,
    ) -> dict:
        """Send email using Office 365 SMTP."""
        if not (self.from_email and self.smtp_username and self.smtp_password):
            return {"sent": False, "error": "Office 365 SMTP is not configured"}

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((self.from_name, self.from_email))
        msg["To"] = to_email

        msg.attach(MIMEText(plain_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.sendmail(self.from_email, [to_email], msg.as_string())
            logger.info(f"Email sent via Office 365 to {to_email}")
            return {"sent": True, "provider": "office365"}
        except Exception as exc:
            logger.error(f"Office 365 SMTP email error: {exc}")
            return {"sent": False, "error": str(exc)}

    def send_email(
        self,
        to_email: str,
        subject: str,
        plain_content: str,
        html_content: str,
    ) -> dict:
        """Send an email using the configured provider."""
        if self.provider == "office365":
            result = self._send_with_office365(to_email, subject, plain_content, html_content)
            if result.get("sent"):
                return result
            # Fall back to SendGrid if configured
            if self.sendgrid_api_key:
                fallback = self._send_with_sendgrid(to_email, subject, plain_content, html_content)
                return {"sent": fallback.get("sent", False), "error": result.get("error")}
            return result

        # Default to SendGrid
        return self._send_with_sendgrid(to_email, subject, plain_content, html_content)

    def send_workspace_invitation(
        self,
        to_email: str,
        invite_link: str,
        workspace_name: str,
        invited_by: Optional[str] = None,
        role: str = "member",
    ) -> dict:
        """Send a workspace invitation email."""
        inviter = invited_by or "A workspace administrator"
        subject = f"You're invited to join {workspace_name}"

        plain_content = f"""{inviter} has invited you to join the workspace "{workspace_name}" as a {role}.

Click the link below to accept the invitation:
{invite_link}

This invitation will expire in 7 days.

If you didn't expect this invitation, you can safely ignore this email.

- The Kanban Portal Team"""

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">You're Invited!</h1>
    </div>
    <div style="background: #ffffff; padding: 30px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
        <p style="font-size: 16px; margin-bottom: 20px;">
            <strong>{inviter}</strong> has invited you to join the workspace:
        </p>
        <div style="background: #f3f4f6; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
            <h2 style="margin: 0 0 10px 0; color: #1f2937;">{workspace_name}</h2>
            <span style="display: inline-block; background: #667eea; color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px; text-transform: capitalize;">{role}</span>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{invite_link}" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; padding: 14px 40px; border-radius: 8px; font-weight: 600; font-size: 16px;">Accept Invitation</a>
        </div>
        <p style="font-size: 14px; color: #6b7280; text-align: center;">
            This invitation will expire in 7 days.
        </p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
        <p style="font-size: 12px; color: #9ca3af; text-align: center;">
            If you didn't expect this invitation, you can safely ignore this email.
        </p>
    </div>
</body>
</html>"""

        return self.send_email(to_email, subject, plain_content, html_content)


# Singleton instance (initialized lazily)
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get or create the email service singleton."""
    global _email_service

    if _email_service is None:
        import os

        _email_service = EmailService(
            provider=os.getenv("EMAIL_PROVIDER", "sendgrid"),
            from_email=os.getenv("EMAIL_FROM_EMAIL") or os.getenv("SENDGRID_FROM_EMAIL"),
            from_name=os.getenv("EMAIL_FROM_NAME", "Kanban Portal"),
            sendgrid_api_key=os.getenv("SENDGRID_API_KEY"),
            smtp_host=os.getenv("SMTP_HOST", "smtp.office365.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
        )

    return _email_service


# Convenience function
def send_workspace_invitation_email(
    to_email: str,
    invite_link: str,
    workspace_name: str,
    invited_by: Optional[str] = None,
    role: str = "member",
) -> dict:
    """Send a workspace invitation email."""
    return get_email_service().send_workspace_invitation(
        to_email=to_email,
        invite_link=invite_link,
        workspace_name=workspace_name,
        invited_by=invited_by,
        role=role,
    )
