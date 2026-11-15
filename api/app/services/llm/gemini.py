"""Gemini video provider on the Interactions API (google-genai 3.x).

Gemini only watches video here. All text reasoning goes to Claude (D24).

Checked against the SDK source and https://aistudio.google.com/docs on 2026-11-14:

* a video part is `{"type": "video", "uri", "mime_type", "processing", "resolution"}`;
* `processing` is `"agentic"` or `{"type": "static", "fps": ...}`; fps only works in static mode;
* structured output is `response_format={"type": "text", "mime_type": "application/json", "schema": ...}`;
* token usage is on `interaction.usage` (`total_input_tokens`, ...).
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services.llm.base import (
    LLMError,
    LLMParseError,
    LLMResult,
    MediaResolution,
    Processing,
)

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
_USAGE_FIELDS = (
    "total_input_tokens",
    "total_output_tokens",
    "total_thought_tokens",
    "total_tool_use_tokens",
    "total_cached_tokens",
    "total_tokens",
)


def strip_fences(text: str) -> str:
    return _FENCE.sub("", text or "").strip()


def classify_error(exc: Exception) -> str:
    """Return `rate_limit`, `server` or `fatal`.

    A used-up daily allowance is fatal: waiting a minute will not bring it back, and
    every retry is another request (the free tier allowed 20 a day on 2026-11-14).
    """
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    message = str(exc)
    if "per day" in message.lower() or "PerDay" in message:
        return "fatal"
    if code == 429 or "RESOURCE_EXHAUSTED" in message or "429" in message:
        return "rate_limit"
    if isinstance(exc, _GaveUp):
        return "server"
    if (isinstance(code, int) and 500 <= code < 600) or "UNAVAILABLE" in message or "INTERNAL" in message:
        return "server"
    return "fatal"


class _GaveUp(Exception):
    """Gemini accepted a background call and then ended it without an answer."""


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        video_model: str,
        on_status: Callable[[str], None] | None = None,
        max_attempts: int = 5,
        request_timeout_s: float = 600.0,
        background: bool = False,
    ) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        if not video_model:
            raise LLMError("GEMINI_VIDEO_MODEL is not set")
        from google import genai  # imported here so tests can run without the SDK configured

        self._client = genai.Client(api_key=api_key)
        self._video_model = video_model
        self._status = on_status or (lambda _msg: None)
        self._max_attempts = max_attempts
        self._timeout = request_timeout_s
        self._background = background

    # -- public -----------------------------------------------------------------

    async def analyze_video[T: BaseModel](
        self,
        path: Path,
        prompt: str,
        schema: type[T],
        fps: float | None = None,
        media_resolution: MediaResolution | None = None,
        processing: Processing = "static",
    ) -> LLMResult[T]:
        self._status("Uploading video")
        remote = await asyncio.to_thread(self._client.files.upload, file=str(path))
        try:
            remote = await self._wait_until_active(remote)
            video: dict[str, Any] = {"type": "video", "uri": remote.uri, "mime_type": remote.mime_type}
            if processing == "agentic":
                video["processing"] = "agentic"
            elif fps is not None:
                video["processing"] = {"type": "static", "fps": fps}
            if media_resolution is not None:
                video["resolution"] = media_resolution
            self._status("Watching video")
            # The docs say to put the text prompt after the video part.
            return await self._create(self._video_model, [video, {"type": "text", "text": prompt}], schema)
        finally:
            try:
                await asyncio.to_thread(self._client.files.delete, name=remote.name)
            except Exception as exc:  # noqa: BLE001 - the file expires after 48 h anyway
                log.warning("Could not delete the uploaded video from Gemini: %s", exc)

    # -- internals --------------------------------------------------------------

    async def _wait_until_active(self, remote: Any, timeout_s: float = 600.0) -> Any:
        deadline = time.monotonic() + timeout_s
        while True:
            state = getattr(getattr(remote, "state", None), "name", None)
            if state == "ACTIVE":
                return remote
            if state == "FAILED":
                raise LLMError("Gemini could not process the uploaded video")
            if time.monotonic() > deadline:
                raise LLMError("Timed out waiting for Gemini to process the uploaded video")
            self._status("Waiting for Gemini to process the upload")
            await asyncio.sleep(5)
            remote = await asyncio.to_thread(self._client.files.get, name=remote.name)

    async def _create_in_background(self, model: str, input_: Any, response_format: dict) -> Any:
        """Start the call, hang up, and ask for the answer every few seconds.

        No connection is held open while Gemini works, so a slow answer cannot be lost
        to a dropped connection. Background calls must be stored; the stored copy is
        deleted as soon as the answer is read.
        """
        interactions = self._client.aio.interactions
        started = await asyncio.wait_for(
            interactions.create(
                model=model, input=input_, response_format=response_format,
                background=True, store=True, timeout=60,
            ),
            timeout=90,
        )
        deadline = time.monotonic() + self._timeout
        current, last_status = started, None
        try:
            while True:
                status = getattr(current, "status", None)
                if status not in ("queued", "in_progress"):
                    break
                if status != last_status:
                    self._status("Gemini has queued the video" if status == "queued" else "Gemini is watching the video")
                    last_status = status
                if time.monotonic() > deadline:
                    try:
                        await asyncio.wait_for(interactions.cancel(started.id), timeout=30)
                    except Exception as exc:  # noqa: BLE001 - best effort
                        log.warning("Could not cancel the Gemini call: %s", exc)
                    raise TimeoutError
                await asyncio.sleep(10)
                try:
                    current = await asyncio.wait_for(interactions.get(started.id, timeout=30), timeout=45)
                except TimeoutError:
                    continue  # one slow status check is not a failed call
            if status != "completed":
                errors = " ".join(str(getattr(current, "errors", None) or "no reason given").split())[:300]
                waited = time.monotonic() - (deadline - self._timeout)
                # `failed` is Gemini giving up on its side; it is worth another attempt.
                raise _GaveUp(f"call ended as {status} after {waited:.0f} s: {errors}")
            return current
        finally:
            try:
                await asyncio.wait_for(interactions.delete(started.id), timeout=30)
            except Exception as exc:  # noqa: BLE001 - nothing more can be done here
                log.warning("Could not delete the stored Gemini call: %s", exc)

    async def _create[T: BaseModel](self, model: str, input_: Any, schema: type[T]) -> LLMResult[T]:
        response_format = {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        }
        delay = 15.0
        for attempt in range(1, self._max_attempts + 1):
            started = time.monotonic()
            try:
                # The SDK's own timeout did not stop a call that hung for 84 minutes (2026-11-14),
                # so the async client is used and cancelled from outside as well.
                if self._background:
                    interaction = await self._create_in_background(model, input_, response_format)
                else:
                    interaction = await asyncio.wait_for(
                        self._client.aio.interactions.create(
                            model=model,
                            input=input_,
                            response_format=response_format,
                            store=False,
                            timeout=self._timeout,
                        ),
                        timeout=self._timeout + 30,
                    )
            except Exception as exc:
                if isinstance(exc, TimeoutError):
                    exc = TimeoutError(f"no answer after {self._timeout:.0f} s")
                kind = "server" if isinstance(exc, TimeoutError) else classify_error(exc)
                if kind == "fatal" or attempt == self._max_attempts:
                    raise LLMError(f"Gemini call failed ({kind}): {exc}") from exc
                detail = " ".join(str(exc).split())[:240]
                log.warning("Gemini attempt %d failed (%s): %s", attempt, kind, detail)
                self._status(
                    f"Waiting for rate limit ({delay:.0f} s): {detail}" if kind == "rate_limit"
                    else f"Gemini is busy, retrying in {delay:.0f} s: {detail}"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 240.0)
                continue

            latency = time.monotonic() - started
            raw_text = getattr(interaction, "output_text", None) or ""
            usage_obj = getattr(interaction, "usage", None)
            usage = {
                name: int(value)
                for name in _USAGE_FIELDS
                if (value := getattr(usage_obj, name, None)) is not None
            }
            try:
                parsed = schema.model_validate_json(strip_fences(raw_text))
            except ValidationError as exc:
                status = getattr(interaction, "status", None)
                raise LLMParseError(
                    f"Gemini's answer did not match the schema (status: {status}): {exc.error_count()} problem(s)",
                    raw_text,
                ) from exc
            return LLMResult(parsed=parsed, raw_text=raw_text, model=model, usage=usage, latency_s=latency)
        raise LLMError("Gemini call failed")  # unreachable; keeps type checkers satisfied
