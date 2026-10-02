"""SMTP delivery for account verification messages."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from markinote_api.config import Settings


class MailDeliveryError(RuntimeError):
    pass


class VerificationMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.smtp_host.strip() and self.settings.smtp_sender_email.strip())

    def send_verification(self, recipient: str, token: str) -> None:
        if not self.configured:
            raise MailDeliveryError("Email delivery is not configured.")
        public_origin = self.settings.public_origin.rstrip("/")
        verification_url = f"{public_origin}/#verify={token}"
        message = EmailMessage()
        message["Subject"] = "Verify your FinNote account"
        message["From"] = f"{self.settings.smtp_sender_name} <{self.settings.smtp_sender_email}>"
        message["To"] = recipient
        message.set_content(
            "Verify your FinNote account by opening this link:\n\n"
            f"{verification_url}\n\n"
            "The link expires in 30 minutes. If you did not request this account, ignore this email."
        )
        safe_url = escape(verification_url, quote=True)
        message.add_alternative(
            "<p>Verify your FinNote account:</p>"
            f'<p><a href="{safe_url}">Verify email address</a></p>'
            "<p>This link expires shortly. If you did not request this account, ignore this email.</p>",
            subtype="html",
        )
        password = (
            self.settings.smtp_password.get_secret_value()
            if self.settings.smtp_password
            else ""
        )
        try:
            if self.settings.smtp_security == "tls":
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=15,
                    context=ssl.create_default_context(),
                )
            else:
                client = smtplib.SMTP(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=15,
                )
            with client:
                client.ehlo()
                if self.settings.smtp_security == "starttls":
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if self.settings.smtp_username:
                    client.login(self.settings.smtp_username, password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise MailDeliveryError("Verification email could not be delivered.") from error
