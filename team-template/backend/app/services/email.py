"""Email helpers for team notifications.

Supports SendGrid (default) and Office 365 SMTP.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


# Provider selection: "sendgrid" (default) or "office365"
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "sendgrid").lower()

# Common defaults
FROM_EMAIL = (
    os.getenv("EMAIL_FROM_EMAIL")
    or os.getenv("SENDGRID_FROM_EMAIL")
    or os.getenv("SMTP_FROM_EMAIL")
)
FROM_NAME = os.getenv("EMAIL_FROM_NAME") or os.getenv("SENDGRID_FROM_NAME", "Kanban")

# SendGrid
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

# Office 365 SMTP
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


def _build_invite_content(
    invite_link: str,
    team_name: str,
    invited_by: Optional[str],
    message: Optional[str],
):
    inviter = invited_by or "Someone on your team"
    subject = f"You're invited to join {team_name}"

    body_lines = [
        f"{inviter} invited you to join the {team_name} Kanban board.",
        f"Accept the invitation: {invite_link}",
    ]
    if message:
        body_lines.append("")
        body_lines.append(f"Message: {message}")

    html_content = "<br>".join(body_lines)
    plain_content = "\n".join(body_lines)
    return subject, plain_content, html_content


def _send_with_sendgrid(
    to_email: str,
    subject: str,
    plain_content: str,
    html_content: str,
) -> dict:
    if not SENDGRID_API_KEY or not FROM_EMAIL:
        return {"sent": False, "error": "SendGrid is not configured"}

    mail = Mail(
        from_email=(FROM_EMAIL, FROM_NAME),
        to_emails=to_email,
        subject=subject,
        plain_text_content=plain_content,
        html_content=html_content,
    )

    try:
        client = SendGridAPIClient(SENDGRID_API_KEY)
        response = client.send(mail)
        return {"sent": 200 <= response.status_code < 300, "status_code": response.status_code}
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "error": str(exc)}


def _send_with_office365(
    to_email: str,
    subject: str,
    plain_content: str,
    html_content: str,
) -> dict:
    if not (FROM_EMAIL and SMTP_USERNAME and SMTP_PASSWORD):
        return {"sent": False, "error": "Office 365 SMTP is not configured"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    msg["To"] = to_email

    msg.attach(MIMEText(plain_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        return {"sent": True, "provider": "office365"}
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "error": str(exc)}


def send_invitation_email(
    to_email: str,
    invite_link: str,
    team_name: str,
    invited_by: Optional[str] = None,
    message: Optional[str] = None,
) -> dict:
    """Send a team invitation email using the configured provider."""
    subject, plain_content, html_content = _build_invite_content(
        invite_link, team_name, invited_by, message
    )

    if EMAIL_PROVIDER == "office365":
        result = _send_with_office365(to_email, subject, plain_content, html_content)
        if result.get("sent") or "error" not in result:
            return result
        # Fall back to SendGrid if configured
        fallback = _send_with_sendgrid(to_email, subject, plain_content, html_content)
        return {"sent": fallback.get("sent", False), "error": result.get("error")}

    # Default to SendGrid
    return _send_with_sendgrid(to_email, subject, plain_content, html_content)
