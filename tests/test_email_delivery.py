from __future__ import annotations

import sqlite3

from clinagent.gateway import auth_admin
from clinagent.gateway.email_delivery import ClinAgentEmailSender, SMTPSettings


def test_smtp_sender_builds_https_invitation_and_reset_messages(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, *, context):
            assert context is not None

        def login(self, username, password):
            assert username == "smtp-user"
            assert password == "smtp-password"

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("clinagent.gateway.email_delivery.smtplib.SMTP", FakeSMTP)
    sender = ClinAgentEmailSender(
        SMTPSettings(
            host="smtp.example.org",
            port=587,
            username="smtp-user",
            password="smtp-password",
            sender="preview@example.org",
            public_url="https://preview.example.org",
            starttls=True,
            use_ssl=False,
        )
    )

    sender.send_invitation(email="reader@example.org", name="Reader", token="invite-secret")
    sender.send_password_reset(email="reader@example.org", name="Reader", token="reset-secret")

    assert len(sent) == 2
    assert "https://preview.example.org/auth?invite_token=invite-secret" in sent[0].get_content()
    assert "https://preview.example.org/auth?reset_token=reset-secret" in sent[1].get_content()


def test_auth_admin_loads_the_configured_env_file(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "configured-auth.sqlite3"
    env_path = tmp_path / "preview.env"
    env_path.write_text(
        "\n".join(
            [
                f"CLINAGENT_AUTH_DB={db_path}",
                "CLINAGENT_PUBLIC_URL=https://preview.example.org",
                "CLINAGENT_ALLOW_SELF_REGISTRATION=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLINAGENT_ENV_FILE", str(env_path))
    monkeypatch.setenv("CLINAGENT_AUTH_DB", "test-sentinel")
    monkeypatch.setenv("CLINAGENT_PUBLIC_URL", "https://sentinel.invalid")
    monkeypatch.setenv("CLINAGENT_ALLOW_SELF_REGISTRATION", "1")

    from clinagent.platform import config as platform_config

    monkeypatch.setattr(platform_config, "_loaded", False)
    monkeypatch.setattr(platform_config, "_env_file", None)
    result = auth_admin.main(
        [
            "invite",
            "--email",
            "reader@example.org",
            "--name",
            "Reader",
            "--print-link",
        ]
    )

    assert result == 0
    assert capsys.readouterr().out.startswith("https://preview.example.org/auth?invite_token=")
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT email, accepted_at FROM invitations").fetchone()
    assert row == ("reader@example.org", None)
