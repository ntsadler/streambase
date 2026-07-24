"""Authenticated, read-only HTTP surface for the Streambase catalog."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from src.catalog_repository import (
    AudioUnavailable,
    CatalogRepository,
    CatalogUnavailable,
    TrackNotFound,
)


TOKEN_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Vary": "Authorization",
}
ALLOWED_LIST_PARAMS = {"q", "mood", "energy", "limit", "cursor"}


class SecurityHeadersMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in PRIVATE_HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _json(payload: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    response_headers = dict(PRIVATE_HEADERS)
    if headers:
        response_headers.update(headers)
    return JSONResponse(payload, status_code=status_code, headers=response_headers)


def _error(code: str, message: str, status_code: int, headers: dict[str, str] | None = None) -> JSONResponse:
    return _json({"error": {"code": code, "message": message}}, status_code, headers)


def _valid_token_hash(value: str) -> bool:
    return bool(TOKEN_HASH_PATTERN.fullmatch(value or ""))


def _authorize(request: Request, configured_hash: str) -> Response | None:
    if not _valid_token_hash(configured_hash):
        return _error("service_not_configured", "Catalog service is not configured.", 503)
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        return _error(
            "unauthorized",
            "Valid bearer authentication is required.",
            401,
            {"WWW-Authenticate": "Bearer"},
        )
    presented_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
    if not hmac.compare_digest(presented_hash, configured_hash.casefold()):
        return _error(
            "unauthorized",
            "Valid bearer authentication is required.",
            401,
            {"WWW-Authenticate": "Bearer"},
        )
    return None


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _filter_hash(search: str, mood: str, energy: str) -> str:
    payload = json.dumps(
        {
            "q": search.strip().casefold(),
            "mood": mood.strip().casefold(),
            "energy": energy.strip().casefold(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _encode_cursor(last_id: int, search: str, mood: str, energy: str, configured_hash: str) -> str:
    payload = json.dumps(
        {"v": 1, "lastId": int(last_id), "filtersHash": _filter_hash(search, mood, energy)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    key = bytes.fromhex(configured_hash)
    signature = hmac.new(key, payload, hashlib.sha256).digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(signature)}"


def _decode_cursor(cursor: str, search: str, mood: str, energy: str, configured_hash: str) -> int:
    try:
        encoded_payload, encoded_signature = cursor.split(".", 1)
        payload = _b64url_decode(encoded_payload)
        signature = _b64url_decode(encoded_signature)
        expected = hmac.new(bytes.fromhex(configured_hash), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("invalid payload")
        if decoded.get("v") != 1 or decoded.get("filtersHash") != _filter_hash(search, mood, energy):
            raise ValueError("invalid filters")
        last_id = decoded.get("lastId")
        if isinstance(last_id, bool) or not isinstance(last_id, int) or last_id < 0:
            raise ValueError("invalid id")
        return last_id
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("Invalid pagination cursor.") from exc


def create_app(
    repository: CatalogRepository | None = None,
    *,
    token_hash: str | None = None,
) -> Starlette:
    catalog = repository or CatalogRepository()
    configured_hash = (
        token_hash if token_hash is not None else os.getenv("STREAMBASE_CATALOG_TOKEN_SHA256", "")
    ).strip()

    async def healthz(_request: Request) -> JSONResponse:
        return _json({"ok": True})

    async def list_tracks(request: Request) -> JSONResponse:
        denied = _authorize(request, configured_hash)
        if denied:
            return denied
        for key in request.query_params:
            if key not in ALLOWED_LIST_PARAMS or len(request.query_params.getlist(key)) != 1:
                return _error("invalid_query", "Unknown or repeated query parameter.", 400)
        search = request.query_params.get("q", "").strip()
        mood = request.query_params.get("mood", "").strip()
        energy = request.query_params.get("energy", "").strip()
        if any(len(value) > 100 for value in (search, mood, energy)):
            return _error("invalid_query", "Filters must be 100 characters or fewer.", 400)
        try:
            limit = int(request.query_params.get("limit", "25"))
        except ValueError:
            return _error("invalid_query", "Limit must be an integer from 1 to 100.", 400)
        if not 1 <= limit <= 100:
            return _error("invalid_query", "Limit must be an integer from 1 to 100.", 400)
        cursor = request.query_params.get("cursor", "").strip()
        try:
            last_id = _decode_cursor(cursor, search, mood, energy, configured_hash) if cursor else 0
        except ValueError as exc:
            return _error("invalid_cursor", str(exc), 400)
        try:
            items, total, has_more = await run_in_threadpool(
                catalog.list_tracks,
                search=search,
                mood=mood,
                energy=energy,
                limit=limit,
                last_id=last_id,
            )
        except CatalogUnavailable:
            return _error("catalog_unavailable", "Catalog is temporarily unavailable.", 503, {"Retry-After": "3"})
        next_cursor = _encode_cursor(items[-1]["id"], search, mood, energy, configured_hash) if has_more and items else None
        return _json({"items": items, "total": total, "nextCursor": next_cursor})

    async def track_detail(request: Request) -> JSONResponse:
        denied = _authorize(request, configured_hash)
        if denied:
            return denied
        try:
            track = await run_in_threadpool(catalog.get_track, request.path_params["track_id"])
        except TrackNotFound:
            return _error("track_not_found", "Track not found.", 404)
        except CatalogUnavailable:
            return _error("catalog_unavailable", "Catalog is temporarily unavailable.", 503, {"Retry-After": "3"})
        return _json({"track": track})

    async def track_audio(request: Request) -> Response:
        denied = _authorize(request, configured_hash)
        if denied:
            return denied
        try:
            audio_path = await run_in_threadpool(catalog.get_audio_path, request.path_params["track_id"])
        except TrackNotFound:
            return _error("track_not_found", "Track not found.", 404)
        except AudioUnavailable:
            return _error("audio_unavailable", "Audio is unavailable.", 404)
        except CatalogUnavailable:
            return _error("catalog_unavailable", "Catalog is temporarily unavailable.", 503, {"Retry-After": "3"})
        media_type = "audio/mpeg" if audio_path.suffix.casefold() == ".mp3" else "audio/wav"
        return FileResponse(
            audio_path,
            media_type=media_type,
            headers=PRIVATE_HEADERS,
        )

    async def not_found(_request: Request, _exc: HTTPException) -> JSONResponse:
        return _error("not_found", "Route not found.", 404)

    async def internal_error(_request: Request, _exc: Exception) -> JSONResponse:
        return _error("internal_error", "Internal server error.", 500)

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/v1/tracks", list_tracks, methods=["GET"]),
        Route("/v1/tracks/{track_id:int}/audio", track_audio, methods=["GET", "HEAD"]),
        Route("/v1/tracks/{track_id:int}", track_detail, methods=["GET"]),
    ]
    app = Starlette(
        debug=False,
        routes=routes,
        middleware=[Middleware(SecurityHeadersMiddleware)],
        exception_handlers={404: not_found, Exception: internal_error},
    )
    app.state.catalog_repository = catalog
    return app


app = create_app()
