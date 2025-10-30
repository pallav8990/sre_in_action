import os
import contextlib
from email.message import EmailMessage
import aiosmtplib

class SMTPClient:
    """
    Async SMTP client with connection reuse.
    Uses internal relay (no username/password auth).
    Reconnects automatically on failure.
    """
    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "smtp.corp.local")
        self.port = int(os.getenv("SMTP_PORT", "25"))
        self.starttls = os.getenv("SMTP_STARTTLS", "false").lower() in ("1", "true", "yes")
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

    async def send_message(self, msg: EmailMessage):
        await self._ensure_connected()
        try:
            await self._client.send_message(msg)
        except Exception:
            # reconnect once on error
            with contextlib.suppress(Exception):
                await self._client.quit()
            self._client = None
            await self._ensure_connected()
            await self._client.send_message(msg)

# Singleton SMTP client per worker
smtp_client = SMTPClient()