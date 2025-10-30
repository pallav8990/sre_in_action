import os
import contextlib
from email.message import EmailMessage
import aiosmtplib

class SMTPClient:
    """
    Lightweight async SMTP client with a single pooled connection per process.
    Reconnects automatically on failure. Designed for internal org relay.
    """
    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "smtp.corp.local")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.user = os.getenv("SMTP_USER", "")
        self.password = os.getenv("SMTP_PASS", "")
        self.starttls = os.getenv("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes")
        self.timeout = float(os.getenv("SMTP_TIMEOUT_SEC", "5"))
        self._client: aiosmtplib.SMTP | None = None

    async def _ensure_connected(self):
        if self._client and self._client.is_connected:
            return
        self._client = aiosmtplib.SMTP(
            hostname=self.host,
            port=self.port,
            timeout=self.timeout,
        )
        await self._client.connect()
        if self.starttls:
            await self._client.starttls()
        if self.user and self.password:
            await self._client.login(self.user, self.password)

    async def send_message(self, msg: EmailMessage):
        await self._ensure_connected()
        try:
            await self._client.send_message(msg)
        except Exception:
            # try a clean reconnect once
            with contextlib.suppress(Exception):
                await self._client.quit()
            self._client = None
            await self._ensure_connected()
            await self._client.send_message(msg)

# Module-level singleton for each worker process
smtp_client = SMTPClient()