import os
import re
from urllib.parse import urlparse, urlunparse

import requests

from src.settings import load_local_env
from src.web_enricher import (
    EMAIL_RE,
    generic_contact_result,
    looks_submit,
    score_contact_method,
    valid_contact_email,
)

load_local_env()

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
URL_RE = re.compile(r"https?://[^\s<>'\"\])}]+", re.I)
LINK_HUB_DOMAINS = {"linktr.ee", "beacons.ai", "carrd.co", "bio.site", "solo.to"}
MAX_EMAILS_PER_RESULT = 5
IGNORED_DOMAINS = {
    "amazon.com",
    "amzn.to",
    "discord.gg",
    "open.spotify.com",
    "spotify.com",
    "chartmetric.com",
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "youtube.com",
    "youtu.be",
}
EMAIL_UNSAFE_DOMAINS = {
    "github.com",
    "huggingface.co",
}
EMAIL_UNSAFE_SUFFIXES = {
    ".csv",
    ".diff",
    ".doc",
    ".docx",
    ".json",
    ".pdf",
    ".txt",
    ".xls",
    ".xlsx",
}
SUBMISSION_DOMAINS = {"dailyplaylists.com", "groover.co", "submithub.com"}
STOP_WORDS = {
    "a", "an", "and", "by", "for", "from", "in", "music", "of", "on",
    "playlist", "spotify", "the", "to", "with",
}


def tavily_status():
    configured = bool(os.getenv("TAVILY_API_KEY", "").strip())
    return {"configured": configured, "provider": "Tavily"}


def _clean_url(value):
    value = (value or "").strip().rstrip(".,;:!?")
    if not value.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(value)
    if not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _domain(value):
    return urlparse(value or "").netloc.lower().removeprefix("www.")


def _tokens(value):
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def _identity_score(playlist_name, curator_name, evidence):
    evidence_low = (evidence or "").lower()
    score = 0
    playlist_low = (playlist_name or "").strip().lower()
    curator_low = (curator_name or "").strip().lower()
    if playlist_low and playlist_low in evidence_low:
        score += 3
    else:
        overlap = len(_tokens(playlist_name) & _tokens(evidence))
        score += min(2, overlap)
    if curator_low and curator_low not in {"unknown", "unknown curator"}:
        if curator_low in evidence_low:
            score += 3
        elif len(_tokens(curator_name) & _tokens(evidence)) >= 1:
            score += 1
    return score


def _contact_type(value, label=""):
    value = _clean_url(value)
    domain = _domain(value)
    if not value or not domain or domain in IGNORED_DOMAINS:
        return ""
    if domain == "instagram.com" or domain.endswith(".instagram.com"):
        path = urlparse(value).path.strip("/")
        if not path or path.split("/")[0] in {"p", "reel", "explore", "accounts"}:
            return ""
        return "instagram"
    if domain in LINK_HUB_DOMAINS:
        return "link_hub"
    if domain in SUBMISSION_DOMAINS or any(domain.endswith(f".{item}") for item in SUBMISSION_DOMAINS):
        return "submission_page"
    if looks_submit(value, label):
        return "submission_page"
    return "website"


def _unsafe_email_source(value):
    parsed = urlparse(value or "")
    domain = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    if domain in EMAIL_UNSAFE_DOMAINS or any(domain.endswith(f".{item}") for item in EMAIL_UNSAFE_DOMAINS):
        return True
    return any(path.endswith(suffix) for suffix in EMAIL_UNSAFE_SUFFIXES)


def _query_for(playlist):
    name = (playlist.get("name") or playlist.get("playlist_name") or "").strip()
    curator = (playlist.get("curator_name") or "").strip()
    identity = f'"{name}"' if name else (playlist.get("url") or playlist.get("playlist_url") or "")
    if curator and curator.lower() not in {"unknown", "unknown curator"}:
        identity += f' "{curator}"'
    return f"{identity} playlist curator email Instagram submissions contact"


def _add_method(methods, seen, contact_type, value, source_url, confidence):
    value = value.strip() if isinstance(value, str) else ""
    if not value or (contact_type, value.lower()) in seen:
        return
    if generic_contact_result(value, source_url):
        return
    if contact_type == "email" and not valid_contact_email(value, source_url):
        return
    seen.add((contact_type, value.lower()))
    methods.append(
        {
            "type": contact_type,
            "value": value,
            "source_url": source_url,
            "confidence_score": score_contact_method(
                contact_type, value, source_url, confidence
            ),
            "status": "new",
        }
    )


def enrich_playlist_with_tavily(playlist, api_key=None, post=None):
    api_key = (api_key or os.getenv("TAVILY_API_KEY", "")).strip()
    if not api_key:
        return {"ok": False, "error": "Set TAVILY_API_KEY to enable contact enrichment.", "contact_methods": []}

    name = (playlist.get("name") or playlist.get("playlist_name") or "").strip()
    curator = (playlist.get("curator_name") or "").strip()
    playlist_url = playlist.get("url") or playlist.get("playlist_url") or ""
    description = playlist.get("spotify_description") or ""
    methods = []
    seen = set()

    if not curator or curator.lower() in {"unknown", "unknown curator"}:
        return {
            "ok": True,
            "error": "",
            "playlist_url": playlist_url,
            "query": "",
            "contact_methods": [],
            "credits": 0,
        }

    # Spotify descriptions are first-party curator evidence and should win ties.
    for email in EMAIL_RE.findall(description):
        _add_method(methods, seen, "email", email, playlist_url, 94)
    for found_url in URL_RE.findall(description):
        clean = _clean_url(found_url)
        contact_type = _contact_type(clean)
        if contact_type:
            _add_method(methods, seen, contact_type, clean, playlist_url, 92)

    payload = {
        "query": _query_for(playlist),
        "topic": "general",
        "search_depth": "basic",
        "max_results": 8,
        "include_answer": False,
        "include_raw_content": "text",
        "include_usage": True,
        "exclude_domains": ["spotify.com", "open.spotify.com", "chartmetric.com"],
    }
    request_post = post or requests.post
    try:
        response = request_post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=35,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "contact_methods": methods, "query": payload["query"]}

    for result in data.get("results") or []:
        source_url = _clean_url(result.get("url") or "")
        evidence = " ".join(
            str(result.get(key) or "") for key in ("title", "content", "raw_content")
        )
        identity = _identity_score(name, curator, f"{source_url} {evidence}")
        relevance = float(result.get("score") or 0)
        if identity < 2 or relevance < 0.25:
            continue
        confidence = min(92, 58 + identity * 5 + int(relevance * 8))

        found_emails = EMAIL_RE.findall(evidence)
        if (
            found_emails
            and not _unsafe_email_source(source_url)
            and len(set(email.lower() for email in found_emails)) <= MAX_EMAILS_PER_RESULT
        ):
            for email in found_emails:
                _add_method(methods, seen, "email", email, source_url, confidence)

        candidates = [source_url, *URL_RE.findall(evidence)]
        for candidate in candidates:
            clean = _clean_url(candidate)
            contact_type = _contact_type(clean)
            if not contact_type:
                continue
            if contact_type == "website" and clean != source_url:
                continue
            type_confidence = confidence if contact_type != "website" else min(confidence, 68)
            _add_method(methods, seen, contact_type, clean, source_url, type_confidence)

    methods.sort(key=lambda item: item["confidence_score"], reverse=True)
    return {
        "ok": True,
        "error": "",
        "playlist_url": playlist_url,
        "query": payload["query"],
        "contact_methods": methods,
        "credits": int((data.get("usage") or {}).get("credits") or 1),
    }


def enrich_playlists_with_tavily(playlists, api_key=None):
    results = []
    errors = []
    credits = 0
    for playlist in playlists or []:
        result = enrich_playlist_with_tavily(playlist, api_key=api_key)
        results.append(result)
        credits += int(result.get("credits") or 0)
        if not result.get("ok"):
            errors.append(result.get("error") or "Unknown Tavily error")
    return {
        "ok": not errors,
        "results": results,
        "errors": errors,
        "credits": credits,
    }
