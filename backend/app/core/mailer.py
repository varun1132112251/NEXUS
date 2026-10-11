import json
import logging
import os
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from html import escape
import resend

from app.core.config import settings

logger = logging.getLogger(__name__)

# Verification and reset codes contain six characters from the alphabet defined
# in app.core.security.create_verification_code.
_CODE_PATTERN = re.compile(
    r"(?:verification code is:|password reset code is:)\s*([A-Z2-9]{6})",
    re.IGNORECASE,
)


def _email_html(subject: str, body: str) -> str:
    """Render an email-client-compatible NEXUS transactional email."""
    title = escape(subject)
    code_match = _CODE_PATTERN.search(body)
    code = code_match.group(1) if code_match else None

    # Remove the code line and expiry line from the prose; they are displayed
    # separately in the prominent code card below.
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", body.strip()):
        if code and (
            _CODE_PATTERN.search(block)
            or re.search(r"this code expires in 15 minutes", block, re.IGNORECASE)
        ):
            continue
        content = "<br>".join(escape(line) for line in block.splitlines())
        if content:
            paragraphs.append(
                '<p style="margin:0 0 18px;color:#334155;font-size:15px;'
                'line-height:1.7;">' + content + "</p>"
            )
    content_html = "\n".join(paragraphs)

    code_html = ""
    if code:
        code_html = (
            '<div style="margin:24px 0;padding:22px 16px;text-align:center;'
            'background:#f1f5f9;border:1px solid #dbe3ee;border-radius:12px;">'
            '<div style="font-size:11px;font-weight:700;letter-spacing:2px;'
            'color:#64748b;text-transform:uppercase;margin-bottom:10px;">'
            'Your secure code</div>'
            f'<div style="font-family:Consolas,Monaco,monospace;font-size:30px;'
            f'font-weight:700;letter-spacing:7px;color:#0f172a;">{escape(code)}</div>'
            '<div style="margin-top:12px;color:#475569;font-size:13px;">'
            'Expires in 15 minutes</div></div>'
        )

    # The prose already includes the relevant "didn't request" warning. Keep
    # a single generic footer instead of repeating the same warning.
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{title}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#eef2f7;padding:28px 10px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;">
        <tr><td style="background:#0f172a;padding:28px 32px;">
          <div style="font-size:12px;color:#93c5fd;font-weight:700;letter-spacing:3px;">PERSONAL OPERATING SYSTEM</div>
          <div style="font-size:32px;line-height:1.2;font-weight:800;letter-spacing:2px;color:#ffffff;margin-top:8px;">NEXUS</div>
        </td></tr>
        <tr><td style="padding:32px;">
          <h1 style="margin:0 0 22px;color:#0f172a;font-size:23px;line-height:1.35;">{title}</h1>
          {content_html}
          {code_html}
          <div style="margin-top:26px;padding-top:18px;border-top:1px solid #e2e8f0;color:#64748b;font-size:12px;line-height:1.7;">
            NEXUS will never ask you to share your verification or recovery code with anyone.
          </div>
        </td></tr>
        <tr><td style="background:#f8fafc;padding:18px 32px;color:#64748b;font-size:12px;line-height:1.6;">
          <strong style="color:#334155;">NEXUS Team</strong><br>
          Your goals. Your routines. Your progress.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_auth_email(to_email: str, subject: str, body: str) -> None:
    # Prefer Brevo's HTTPS API: some hosting providers restrict outbound SMTP.
    brevo_api_key = os.getenv("BREVO_API_KEY")
    if brevo_api_key:
        sender_email = settings.smtp_from or os.getenv("EMAIL_FROM")
        if not sender_email:
            raise RuntimeError("SMTP_FROM or EMAIL_FROM must be configured as a verified Brevo sender.")
        payload = {
            "sender": {"name": "NEXUS", "email": sender_email},
            "to": [{"email": to_email.strip().lower()}],
            "subject": subject,
            "textContent": body,
            "htmlContent": _email_html(subject, body),
        }
        request = urllib.request.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "accept": "application/json",
                "api-key": brevo_api_key,
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                logger.info("BREVO_API_ACCEPTED auth email to %s status=%s", to_email.strip().lower(), response.status)
        except (urllib.error.URLError, urllib.error.HTTPError):
            logger.exception("BREVO_API_DELIVERY_FAILED for %s", to_email.strip().lower())
            raise
        return

    # Prefer Brevo SMTP when configured. This lets deployments migrate away from
    # Resend without having to remove the old key until delivery is verified.
    if settings.smtp_host and settings.smtp_username and settings.smtp_password:
        if not settings.smtp_from:
            raise RuntimeError("SMTP_FROM must be configured when SMTP is enabled.")
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to_email.strip().lower()
        message["Subject"] = subject
        message.set_content(body)
        message.add_alternative(_email_html(subject, body), subtype="html")
        logger.info("SMTP_CONNECT attempt host=%s port=%s recipient=%s", settings.smtp_host, settings.smtp_port, to_email.strip().lower())
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=25) as smtp:
                smtp.starttls()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        except Exception as exc:
            logger.exception("SMTP_DELIVERY_FAILED host=%s port=%s error_type=%s", settings.smtp_host, settings.smtp_port, type(exc).__name__)
            raise
        logger.info("SMTP_ACCEPTED auth email to %s via %s", to_email.strip().lower(), settings.smtp_host)
        return

    # Resend remains available as fallback when SMTP is not configured.
    resend_api_key = os.getenv("RESEND_API_KEY")
    email_from = os.getenv("EMAIL_FROM")
    if resend_api_key:
        if not email_from:
            raise RuntimeError("EMAIL_FROM must be configured when Resend is enabled.")
        resend.api_key = resend_api_key
        try:
            result = resend.Emails.send({
                "from": email_from,
                "to": [to_email.strip().lower()],
                "subject": subject,
                "text": body,
                "html": _email_html(subject, body),
            })
            logger.info("RESEND_ACCEPTED auth email to %s: %s", to_email.strip().lower(), result)
        except Exception:
            logger.exception("Resend SDK failed to send auth email to %s.", to_email.strip().lower())
            raise
        return

    if settings.environment == "local":
        logger.warning("Email delivery is not configured; no email was sent to %s.", to_email.strip().lower())
        return
    raise RuntimeError("Email delivery is not configured.")
