from app.core import mailer


def test_auth_email_has_plain_text_and_html_parts(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert host == "smtp.example.test"
            assert port == 587
            assert timeout == 10

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, username, password):
            sent["login"] = (username, password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr(mailer.settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(mailer.settings, "smtp_port", 587)
    monkeypatch.setattr(mailer.settings, "smtp_username", "nexus@example.test")
    monkeypatch.setattr(mailer.settings, "smtp_password", "test-password")
    monkeypatch.setattr(mailer.settings, "smtp_from", "nexus@example.test")
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)

    mailer.send_auth_email(
        "person@example.test",
        "Verify your email address — NEXUS",
        "Welcome to NEXUS.\n\nYour NEXUS verification code is: ABC234\n\nThis code expires in 15 minutes.",
    )

    message = sent["message"]
    assert sent["tls"] is True
    assert sent["login"] == ("nexus@example.test", "test-password")
    assert message["To"] == "person@example.test"
    assert message.get_content_type() == "multipart/alternative"

    parts = list(message.iter_parts())
    assert len(parts) == 2
    assert parts[0].get_content_type() == "text/plain"
    assert "ABC234" in parts[0].get_content()
    html = parts[1].get_content()
    assert "NEXUS" in html
    assert "ABC234" in html
    assert html.count("verification or recovery code") == 1
    assert "Your secure code" in html
    assert "Expires in 15 minutes" in html
    assert "This code expires in 15 minutes" not in html


def test_auth_email_html_escapes_dynamic_content():
    html = mailer._email_html(
        "Verify <NEXUS>",
        "Hello <user@example.com>\n\nYour NEXUS verification code is: ABC234\n\nThis code expires in 15 minutes.",
    )
    assert "&lt;NEXUS&gt;" in html
    assert "&lt;user@example.com&gt;" in html
    assert "<user@example.com>" not in html
