"""Claude: all text reasoning (D24). Research is a web-search call followed by a structuring call.

Structured output cannot be combined with the citations that web search returns, so a
grounded answer needs two calls (BUILD_SPEC 7.7, 7.10): `search` returns findings as text
with the pages it read, and `generate_json` turns text into a validated model.
"""

import base64
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
from pydantic import BaseModel

from app.services.llm.base import LLMError, LLMParseError, LLMResult

DEFAULT_MODEL = "claude-opus-5-5"
MAX_CONTINUATIONS = 3  # server-side search loops can pause; resume at most this often

# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class SearchRun:
    text: str
    sources: list[dict]  # [{title, url}] every page the searches returned, in order, no repeats
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_s: float = 0.0


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _usage(response: Any) -> dict[str, int]:
    usage = _attr(response, "usage")
    if usage is None:
        return {}
    out = {
        "input_tokens": _attr(usage, "input_tokens", 0) or 0,
        "output_tokens": _attr(usage, "output_tokens", 0) or 0,
    }
    server = _attr(usage, "server_tool_use")
    if server is not None:
        out["web_search_requests"] = _attr(server, "web_search_requests", 0) or 0
    return out


def _add(total: dict[str, int], part: dict[str, int]) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0) + value


def collect_sources(content: list[Any]) -> list[dict]:
    """Pages from web search results and text citations, in the order they appear."""
    seen: dict[str, dict] = {}
    for block in content:
        kind = _attr(block, "type")
        if kind == "web_search_tool_result":
            results = _attr(block, "content")
            if isinstance(results, list):  # an error result is a single object, not a list
                for result in results:
                    url = _attr(result, "url")
                    if url and url not in seen:
                        seen[url] = {"title": _attr(result, "title", "") or "", "url": url}
        elif kind == "text":
            for citation in _attr(block, "citations") or []:
                url = _attr(citation, "url")
                if url and url not in seen:
                    seen[url] = {"title": _attr(citation, "title", "") or "", "url": url}
    return list(seen.values())


def answer_text(content: list[Any]) -> str:
    return "".join(_attr(b, "text", "") or "" for b in content if _attr(b, "type") == "text").strip()


class ClaudeProvider:
    def __init__(self, api_key: str, model: str = "", client: Any = None) -> None:
        self.model = model or DEFAULT_MODEL
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, timeout=600.0, max_retries=2)

    def _extra(self) -> dict:
        if self.model in _FALLBACK_MODELS:
            return {"betas": [_FALLBACK_BETA], "fallbacks": "default"}
        return {"betas": []}

    async def search(
        self, prompt: str, max_searches: int = 6, blocked_domains: list[str] | None = None, effort: str = "medium"
    ) -> SearchRun:
        tool: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}
        if blocked_domains:
            tool["blocked_domains"] = blocked_domains
        messages: list[dict] = [{"role": "user", "content": prompt}]
        usage: dict[str, int] = {}
        content: list[Any] = []
        started = time.monotonic()
        model = self.model
        try:
            for _ in range(MAX_CONTINUATIONS + 1):
                response = await self.client.beta.messages.create(
                    model=self.model, max_tokens=16000, messages=messages, tools=[tool],
                    output_config={"effort": effort}, **self._extra(),
                )
                model = _attr(response, "model", model) or model
                _add(usage, _usage(response))
                content.extend(_attr(response, "content", []) or [])
                if _attr(response, "stop_reason") != "pause_turn":
                    break
                # Resume the paused server-side loop: send the turn back, add nothing.
                messages = [messages[0], {"role": "assistant", "content": _attr(response, "content")}]
        except anthropic.APIError as exc:
            raise LLMError(f"Claude research call failed: {exc}") from exc
        if _attr(response, "stop_reason") == "refusal":
            raise LLMError("Claude declined the research request")
        return SearchRun(
            text=answer_text(content), sources=collect_sources(content), model=model,
            usage=usage, latency_s=round(time.monotonic() - started, 2),
        )

    async def look_json[T: BaseModel](
        self, prompt: str, images: list[tuple[str, bytes, str]], schema: type[T], effort: str = "low"
    ) -> LLMResult[T]:
        """Structured answer about still images: each (label, bytes, media type) goes in before the prompt.

        Claude reads stills (frames, thumbnails); only Gemini watches video (D24)."""
        content: list[dict] = []
        for label, data, media_type in images:
            if label:
                content.append({"type": "text", "text": label})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode("ascii"),
            }})
        content.append({"type": "text", "text": prompt})
        return await self.generate_json(content, schema, effort=effort)  # type: ignore[arg-type]

    async def generate_json[T: BaseModel](
        self, prompt: str | list[dict], schema: type[T], search: bool = False, effort: str = "low"
    ) -> LLMResult[T]:
        if search:
            raise LLMError("Use search() first and pass its findings in the prompt")
        started = time.monotonic()
        try:
            response = await self.client.beta.messages.parse(
                model=self.model, max_tokens=16000, messages=[{"role": "user", "content": prompt}],
                output_format=schema, output_config={"effort": effort}, **self._extra(),
            )
        except anthropic.APIError as exc:
            raise LLMError(f"Claude call failed: {exc}") from exc
        raw = answer_text(_attr(response, "content", []) or [])
        if _attr(response, "stop_reason") == "refusal":
            raise LLMError("Claude declined the request")
        parsed = _attr(response, "parsed_output")
        if parsed is None:
            raise LLMParseError("Claude's answer did not match the expected shape", raw)
        return LLMResult(
            parsed=parsed, raw_text=raw, model=_attr(response, "model", self.model) or self.model,
            usage=_usage(response), latency_s=round(time.monotonic() - started, 2),
        )
