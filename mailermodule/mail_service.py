import os
import json
from email.message import EmailMessage
from utils.smtp_client import smtp_client

SMTP_FROM = os.getenv("SMTP_FROM", "srehubapp@corp.local")
MAX_ATTACH_BYTES = int(os.getenv("MAILME_MAX_ATTACH_BYTES", str(200 * 1024)))  # 200 KB default

async def send_json_email(to_email: str, subject: str, payload_obj):
    """
    Builds and sends an email with JSON payload via internal SMTP relay.
    Stateless, non-blocking, no authentication.
    """
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject

    body = "Hi,\n\nYour requested API result is attached below.\n\n— SREHubApp"
    serialized = json.dumps(payload_obj, indent=2, default=str).encode("utf-8")

    if len(serialized) <= MAX_ATTACH_BYTES:
        msg.set_content(body)
        msg.add_attachment(
            serialized,
            maintype="application",
            subtype="json",
            filename="result.json",
        )
    else:
        # Inline large payload (still stateless)
        msg.set_content(body + "\n\n---\n" + serialized.decode("utf-8", errors="replace"))

    await smtp_client.send_message(msg)