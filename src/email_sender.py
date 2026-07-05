import os
from typing import Dict

import requests

from src.settings import load_local_env


load_local_env()


RESEND_API_URL = "https://api.resend.com/emails"


def email_sender_status() -> Dict:
    provider = (os.getenv("EMAIL_PROVIDER") or "").strip().lower()
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    email_from = os.getenv("EMAIL_FROM", "").strip()
    reply_to = os.getenv("EMAIL_REPLY_TO", "").strip()
    return {
        "provider": provider or "not_configured",
        "configured": provider == "resend" and bool(api_key and email_from),
        "from": email_from,
        "reply_to": reply_to,
        "message": "Resend email sending is configured." if provider == "resend" and api_key and email_from else "Set EMAIL_PROVIDER=resend, RESEND_API_KEY, and EMAIL_FROM.",
    }


def send_email_via_resend(to_email: str, subject: str, body: str) -> Dict:
    status = email_sender_status()
    if not status.get("configured"):
        return {"ok": False, "error": status.get("message") or "Email sending is not configured."}
    payload = {
        "from": status["from"],
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if status.get("reply_to"):
        payload["reply_to"] = [status["reply_to"]]
    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {os.getenv('RESEND_API_KEY', '').strip()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        data = resp.json() if resp.content else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code >= 400:
        return {"ok": False, "error": data.get("message") or data.get("error") or f"Resend returned HTTP {resp.status_code}.", "raw": data}
    return {"ok": True, "provider_id": data.get("id", ""), "raw": data}
