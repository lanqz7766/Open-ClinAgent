from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlencode


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    public_url: str
    starttls: bool
    use_ssl: bool

    @classmethod
    def from_env(cls) -> "SMTPSettings":
        return cls(
            host=os.getenv("CLINAGENT_SMTP_HOST", "").strip(),
            port=int(os.getenv("CLINAGENT_SMTP_PORT", "587")),
            username=os.getenv("CLINAGENT_SMTP_USERNAME", "").strip(),
            password=os.getenv("CLINAGENT_SMTP_PASSWORD", ""),
            sender=os.getenv("CLINAGENT_SMTP_FROM", "").strip(),
            public_url=os.getenv("CLINAGENT_PUBLIC_URL", "").strip().rstrip("/"),
            starttls=_flag("CLINAGENT_SMTP_STARTTLS", True),
            use_ssl=_flag("CLINAGENT_SMTP_SSL", False),
        )

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender and self.public_url.startswith("https://"))


class ClinAgentEmailSender:
    def __init__(self, settings: SMTPSettings) -> None:
        self.settings = settings

    @classmethod
    def from_env(cls) -> "ClinAgentEmailSender":
        return cls(SMTPSettings.from_env())

    @property
    def configured(self) -> bool:
        return self.settings.configured

    def invitation_url(self, token: str) -> str:
        return f"{self.settings.public_url}/auth?{urlencode({'invite_token': token})}"

    def reset_url(self, token: str) -> str:
        return f"{self.settings.public_url}/auth?{urlencode({'reset_token': token})}"

    def send_invitation(self, *, email: str, name: str, token: str, expires_hours: int = 72) -> None:
        self._send(
            recipient=email,
            subject="Your ClinAgent physician preview invitation",
            body=(
                f"Hello {name},\n\n"
                "You have been invited to the ClinAgent closed physician preview. "
                f"This single-use invitation expires in {expires_hours} hours.\n\n"
                f"Accept invitation: {self.invitation_url(token)}\n\n"
                "Use only de-identified research data. ClinAgent is not for clinical diagnosis.\n"
            ),
        )

    def send_password_reset(self, *, email: str, name: str, token: str) -> None:
        self._send(
            recipient=email,
            subject="Reset your ClinAgent password",
            body=(
                f"Hello {name},\n\n"
                "A password reset was requested for your ClinAgent account. "
                "This single-use link expires in 30 minutes.\n\n"
                f"Reset password: {self.reset_url(token)}\n\n"
                "If you did not request this reset, you can ignore this message.\n"
            ),
        )

    def _send(self, *, recipient: str, subject: str, body: str) -> None:
        if not self.configured:
            raise RuntimeError("SMTP delivery is not configured.")
        message = EmailMessage()
        message["From"] = self.settings.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        smtp_class = smtplib.SMTP_SSL if self.settings.use_ssl else smtplib.SMTP
        kwargs = {"host": self.settings.host, "port": self.settings.port, "timeout": 15}
        if self.settings.use_ssl:
            kwargs["context"] = ssl.create_default_context()
        with smtp_class(**kwargs) as client:
            if self.settings.starttls and not self.settings.use_ssl:
                client.starttls(context=ssl.create_default_context())
            if self.settings.username:
                client.login(self.settings.username, self.settings.password)
            client.send_message(message)
