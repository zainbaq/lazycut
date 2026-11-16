"""Higgsfield's image API (docs.higgsfield.ai, read 2026-11-15): upload, estimate, submit, poll, download.

Auth is `Authorization: Key <id>:<secret>`, server-side only. Input images go up through a
presigned URL first; generation is a queued request polled until it reaches a terminal state.
Outputs are deleted after seven days, so results are downloaded straight away.
"""

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

TERMINAL = {"completed", "failed", "nsfw", "canceled"}
POLL_START_S, POLL_GROWTH, POLL_CAP_S = 2.0, 1.5, 10.0
DEFAULT_TIMEOUT_S = 600.0


class HiggsfieldError(Exception):
    """A request Higgsfield refused or a generation that did not finish. `retryable` says whether trying later may work."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class Generation:
    request_id: str
    status: str                      # completed | failed | nsfw | canceled
    images: list[str] = field(default_factory=list)
    error: str | None = None
    expires_at: str | None = None
    latency_s: float = 0.0


class ImageClient(Protocol):
    async def upload(self, data: bytes, content_type: str) -> str: ...
    async def estimate(self, path: str, body: dict) -> float | None: ...
    async def generate(self, path: str, body: dict, on_status: Any = None) -> Generation: ...
    async def download(self, url: str) -> bytes: ...


_MESSAGES = {
    400: "Higgsfield rejected the request",
    401: "Higgsfield did not accept the key; check HIGGSFIELD_API_KEY in .env",
    403: "Your Higgsfield balance is too low; top it up at console.higgsfield.ai",
    404: "This model is not available on your Higgsfield account",
    422: "Higgsfield could not validate the request",
    423: "This model is temporarily blocked on Higgsfield",
    429: "Higgsfield's queue is full; try again in a minute",
    503: "This Higgsfield model is not ready right now; try again shortly",
}


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return response.text[:200]
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or "")
    if isinstance(detail, list):  # validation errors
        return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)[:300]
    return str(detail or "")


def raise_for(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    code = response.status_code
    base = _MESSAGES.get(code, f"Higgsfield returned {code}")
    detail = _detail(response)
    retryable = code in (429, 500, 502, 503, 504)
    raise HiggsfieldError(f"{base}: {detail}" if detail and code not in (401, 403) else base, code, retryable)


class Higgsfield:
    def __init__(self, credential: str, base_url: str = "https://api.higgsfield.ai",
                 timeout_s: float = DEFAULT_TIMEOUT_S, transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Any = asyncio.sleep) -> None:
        """`credential` is the console's API key, "<id>:<secret>"."""
        self.base_url = base_url.rstrip("/")
        self._auth = {"Authorization": f"Key {credential}"}
        self.timeout_s = timeout_s
        self._transport = transport
        self._sleep = sleep

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=60.0, transport=self._transport)

    async def upload(self, data: bytes, content_type: str) -> str:
        """Put an image on Higgsfield's storage and return its public URL."""
        async with self._client() as http:
            r = await http.post(f"{self.base_url}/files/generate-upload-url", headers=self._auth,
                                json={"content_type": content_type})
            raise_for(r)
            info = r.json()
            # The presigned URL takes only the headers it was signed with, never our credentials.
            headers = dict(info.get("upload_headers") or {}) or {"Content-Type": content_type}
            put = await http.put(info["upload_url"], content=data, headers=headers)
            if put.status_code >= 400:
                raise HiggsfieldError(f"Uploading the source image failed ({put.status_code})", put.status_code, True)
            return info["public_url"]

    async def estimate(self, path: str, body: dict) -> float | None:
        """The price in USD Higgsfield quotes for this request, or None when it gives none."""
        async with self._client() as http:
            r = await http.post(f"{self.base_url}/estimate/{path}", headers=self._auth, json=body)
            if r.status_code == 404:
                return None
            raise_for(r)
            try:
                return float(r.json().get("usd"))
            except (TypeError, ValueError):
                return None

    async def generate(self, path: str, body: dict, on_status: Any = None) -> Generation:
        """Submit one request and poll it to the end (2 s, x1.5, capped at 10 s, with jitter)."""
        started = time.monotonic()
        async with self._client() as http:
            r = await http.post(f"{self.base_url}/{path}", json=body,
                                headers=self._auth | {"Idempotency-Key": str(uuid.uuid4())})
            raise_for(r)
            sub = r.json()
            request_id = sub.get("request_id", "")
            status_url = sub.get("status_url") or f"{self.base_url}/requests/{request_id}/status"
            delay, data, last = POLL_START_S, sub, sub.get("status")
            failures = 0
            while (data.get("status") or "") not in TERMINAL:
                if time.monotonic() - started > self.timeout_s:
                    await self._cancel(http, sub.get("cancel_url"))
                    raise HiggsfieldError("Higgsfield took too long; the request was stopped", None, True)
                await self._sleep(delay + random.uniform(0, 0.5))
                delay = min(delay * POLL_GROWTH, POLL_CAP_S)
                try:
                    p = await http.get(status_url, headers=self._auth)
                except httpx.TransportError:
                    failures += 1
                    if failures > 5:
                        raise
                    continue
                if p.status_code >= 500:
                    failures += 1
                    if failures > 5:
                        raise_for(p)
                    continue
                raise_for(p)
                data = p.json()
                if on_status and data.get("status") != last:
                    last = data.get("status")
                    on_status(last)
        return Generation(
            request_id=request_id, status=data["status"],
            images=[i["url"] for i in data.get("images") or [] if i.get("url")],
            error=data.get("error"), expires_at=data.get("expires_at"),
            latency_s=round(time.monotonic() - started, 2),
        )

    async def _cancel(self, http: httpx.AsyncClient, cancel_url: str | None) -> None:
        if cancel_url:
            try:
                await http.post(cancel_url, headers=self._auth)
            except httpx.HTTPError:
                pass

    async def download(self, url: str) -> bytes:
        async with self._client() as http:
            r = await http.get(url, follow_redirects=True)
            if r.status_code >= 400:
                raise HiggsfieldError(f"Downloading the result failed ({r.status_code})", r.status_code, True)
            return r.content
