import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_auth_email(to_email: str, subject: str, body: str) -> None:
    if settings.smtp_host:
        if not settings.smtp_from:
            raise RuntimeError("SMTP_FROM must be configured when SMTP is enabled.")
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
        return

    if settings.environment == "local":
        logger.warning("NEXUS local auth email for %s: %s", to_email, body)
        return

    raise RuntimeError("Email delivery is not configured.")
