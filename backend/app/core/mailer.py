import logging
import smtplib
from email.message import EmailMessage
from html import escape

from app.core.config import settings

logger = logging.getLogger(__name__)


def _email_html(subject: str, body: str) -> str:
    """Render a small, email-client-compatible NEXUS transactional email."""
    title = escape(subject)
    paragraphs = []
    for block in body.split("\n\n"):
        lines = block.splitlines()
        content = "<br>".join(escape(line) for line in lines)
        paragraphs.append(
            '<p style="margin:0 0 18px;color:#334155;font-size:15px;'
            'line-height:1.7;">' + content + "</p>"
        )
    content_html = "\n".join(paragraphs)

    # Codes are identified by the stable phrase used by auth email callers.
    # Escape all dynamic content before inserting it into HTML.
    import re

    code_match = re.search(r"(?:verification code is:|password reset code is:)\s*([A-Z2-9]{6})", body, re.IGNORECASE)
    code_html = ""
    if code_match:
        code = escape(code_match.group(1))
        code_html = (
            '<div style="margin:24px 0;padding:20px 16px;text-align:center;'
            'background:#f1f5f9;border:1px solid #dbe3ee;border-radius:12px;">'
            '<div style="font-size:11px;font-weight:700;letter-spacing:2px;'
            'color:#64748b;text-transform:uppercase;margin-bottom:8px;">'
            'Your verification code</div>'
            f'<div style="font-family:Consolas,Monaco,monospace;font-size:30px;'
            f'font-weight:700;letter-spacing:7px;color:#0f172a;">{code}</div>'
            '</div>'
        )
        content_html = content_html.replace(
            f"<p style=\"margin:0 0 18px;color:#334155;font-size:15px;line-height:1.7;\">"
            f"Your NEXUS verification code is: {code_match.group(1)}<br><br>"
            f"This code expires in 15 minutes.</p>",
            "",
        )
        content_html = content_html.replace(
            f"<p style=\"margin:0 0 18px;color:#334155;font-size:15px;line-height:1.7;\">"
            f"Your NEXUS password reset code is: {code_match.group(1)}<br><br>"
            f"This code expires in 15 minutes.</p>",
            "",
        )

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
            If you didn't request this message, you can safely ignore it. Never share a verification code with anyone.
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
    if settings.smtp_host:
        if not settings.smtp_from:
            raise RuntimeError("SMTP_FROM must be configured when SMTP is enabled.")
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        message.add_alternative(_email_html(subject, body), subtype="html")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
        return

    if settings.environment == "local":
        # Development-only fallback; do not send codes to logs in non-local environments.
        logger.warning("NEXUS local auth email for %s: %s", to_email, body)
        return

    raise RuntimeError("Email delivery is not configured.")
