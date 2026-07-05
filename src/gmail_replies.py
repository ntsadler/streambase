import base64
import os
import re
from email.utils import parsedate_to_datetime, parseaddr
from typing import Dict, List

import requests

from src.database import get_email_queue, upsert_email_reply
from src.settings import load_local_env


load_local_env()

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


def gmail_reply_status() -> Dict:
    client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
    account = os.getenv("GMAIL_REPLY_ACCOUNT", "").strip() or os.getenv("EMAIL_REPLY_TO", "").strip()
    configured = bool(client_id and client_secret and refresh_token and account)
    return {
        "configured": configured,
        "account": account,
        "message": "Gmail reply sync is configured." if configured else "Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN, and GMAIL_REPLY_ACCOUNT.",
    }


def _access_token() -> Dict:
    try:
        resp = requests.post(
            GMAIL_TOKEN_URL,
            data={
                "client_id": os.getenv("GMAIL_CLIENT_ID", "").strip(),
                "client_secret": os.getenv("GMAIL_CLIENT_SECRET", "").strip(),
                "refresh_token": os.getenv("GMAIL_REFRESH_TOKEN", "").strip(),
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        data = resp.json() if resp.content else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code >= 400:
        return {"ok": False, "error": data.get("error_description") or data.get("error") or f"Gmail token returned HTTP {resp.status_code}."}
    return {"ok": True, "access_token": data.get("access_token", "")}


def _headers(headers: List[Dict]) -> Dict:
    return {str(h.get("name", "")).lower(): h.get("value", "") for h in headers or []}


def _plain_body(part: Dict) -> str:
    body = (part.get("body") or {}).get("data")
    if body:
        padded = body + "=" * (-len(body) % 4)
        try:
            return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:
            return ""
    for child in part.get("parts") or []:
        if child.get("mimeType") == "text/plain":
            text = _plain_body(child)
            if text:
                return text
    for child in part.get("parts") or []:
        text = _plain_body(child)
        if text:
            return text
    return ""


def _clean_subject(subject: str) -> str:
    return re.sub(r"^\\s*(re|fw|fwd):\\s*", "", subject or "", flags=re.I).strip().lower()


def _email_key(value: str) -> str:
    return parseaddr(value or "")[1].strip().lower()


def _match_reply(message: Dict, sent_rows: List[Dict]) -> Dict:
    from_email = message.get("from_email", "")
    subject = _clean_subject(message.get("subject", ""))
    candidates = [row for row in sent_rows if _email_key(row.get("to_email", "")) == from_email]
    if not candidates:
        return {"match_status": "unmatched"}
    subject_matches = [row for row in candidates if subject and _clean_subject(row.get("subject", "")) and (_clean_subject(row.get("subject", "")) in subject or subject in _clean_subject(row.get("subject", "")))]
    winner = subject_matches[0] if subject_matches else candidates[0]
    return {
        "match_status": "matched_subject" if subject_matches else "matched_sender",
        "email_queue_id": int(winner.get("id") or 0),
        "curator_id": int(winner.get("curator_id") or 0),
        "playlist_id": int(winner.get("playlist_id") or 0),
    }


def _message_from_gmail(raw: Dict) -> Dict:
    payload = raw.get("payload") or {}
    h = _headers(payload.get("headers") or [])
    from_name, from_email = parseaddr(h.get("from", ""))
    received_at = h.get("date", "")
    if received_at:
        try:
            received_at = parsedate_to_datetime(received_at).isoformat(timespec="seconds")
        except Exception:
            pass
    body = _plain_body(payload)
    snippet = (body or raw.get("snippet") or "").strip().replace("\r", " ").replace("\n", " ")
    return {
        "gmail_message_id": raw.get("id", ""),
        "gmail_thread_id": raw.get("threadId", ""),
        "from_email": (from_email or "").lower(),
        "from_name": from_name or "",
        "subject": h.get("subject", ""),
        "snippet": snippet[:500],
        "received_at": received_at,
    }


def sync_gmail_replies(days: int = 30, limit: int = 25, db_path=None) -> Dict:
    status = gmail_reply_status()
    if not status.get("configured"):
        return {"ok": False, "error": status.get("message")}
    token = _access_token()
    if not token.get("ok"):
        return {"ok": False, "error": token.get("error", "Could not get Gmail access token.")}
    account = status.get("account")
    query = f"to:{account} newer_than:{int(days)}d -from:{account}"
    headers = {"Authorization": f"Bearer {token.get('access_token')}"}
    try:
        list_resp = requests.get(
            GMAIL_MESSAGES_URL,
            headers=headers,
            params={"q": query, "maxResults": int(limit)},
            timeout=20,
        )
        listed = list_resp.json() if list_resp.content else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if list_resp.status_code >= 400:
        return {"ok": False, "error": listed.get("error", {}).get("message") or f"Gmail list returned HTTP {list_resp.status_code}."}
    sent_rows = [row for row in (get_email_queue() if db_path is None else get_email_queue(None, db_path)) if row.get("status") in {"sent", "approved"}]
    saved = 0
    matched = 0
    messages = listed.get("messages") or []
    for item in messages:
        try:
            detail_resp = requests.get(
                f"{GMAIL_MESSAGES_URL}/{item.get('id')}",
                headers=headers,
                params={"format": "full"},
                timeout=20,
            )
            detail = detail_resp.json() if detail_resp.content else {}
        except Exception:
            continue
        if detail_resp.status_code >= 400:
            continue
        reply = _message_from_gmail(detail)
        reply.update(_match_reply(reply, sent_rows))
        if reply.get("match_status", "").startswith("matched"):
            matched += 1
        reply_id = upsert_email_reply(reply) if db_path is None else upsert_email_reply(reply, db_path)
        if reply_id:
            saved += 1
    return {"ok": True, "saved": saved, "matched": matched, "checked": len(messages), "query": query}
