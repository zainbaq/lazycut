"""The `competitors` job (7.7, Phase 3): search once per subject per day, then read the field with Claude."""

import datetime as dt
import re

import httpx

from app.db import session
from app.models import Research, Video, utc_now
from app.services import competitors as cp
from app.services import packaging
from app.services.channel_import import last_sync
from app.services.jobs import JobContext
from app.services.llm.base import LLMError
from app.services.pipeline import _log_call, deps_of, preset_for
from app.services.presets import Preset, load_channel
from app.services.research import name_key
from app.services.templating import holds


def unbacked_claims(text: str, preset: Preset, facts: dict, research: dict) -> list[str]:
    """Claim rules an angle would break (a phrase whose fact or research value does not hold)."""
    out = []
    for rule in preset.claim_rules:
        if any(re.search(rf"(?i)\b{re.escape(p)}\b", text) for p in rule.phrases) and not holds(rule.requires, facts, research):
            out.append(rule.id)
    return out


async def _thumbnails(rows: list[dict]) -> list[tuple[int, bytes]]:
    picked = []
    async with httpx.AsyncClient(timeout=15) as c:
        for i, r in enumerate(rows[: cp.THUMBS_TO_READ], 1):
            try:
                res = await c.get(r["thumbnail"])
            except httpx.HTTPError:
                continue
            if res.status_code == 200 and res.headers.get("content-type", "").startswith("image/"):
                picked.append((i, res.content))
    return picked


async def competitors_job(ctx: JobContext) -> None:
    deps = deps_of(ctx)
    settings = deps.settings
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        preset, _note = preset_for(settings, video.preset_id)
        channel, _ = load_channel(settings.config_dir)
        inp = packaging.gather(s, video, preset, channel)
        facts, research = dict(inp.facts), dict(inp.research)
        hooks = [h["text"] for h in packaging.eligible_hooks(inp)]
        sync = last_sync(s) or {}
        row = cp.find_row(s, video.subject or video.title, video.topic)
        payload = dict(row.payload) if row else {}
    own_id = (sync.get("channel") or {}).get("id")
    subs = (sync.get("channel") or {}).get("subscribers")
    query = cp.build_query(preset.competitor_query, video.topic, video.subject or video.title)

    if not cp.is_fresh(payload) or payload.get("query") != query:
        if not settings.youtube_api_key:
            raise RuntimeError("Set YOUTUBE_API_KEY in .env to search for competing videos")
        ctx.progress(0.1, f"Searching YouTube for “{query}”")
        units: list[int] = []
        rows = await cp.search(settings.youtube_api_key, query, units)
        payload = {"query": query, "searched_at": dt.datetime.now(dt.UTC).isoformat(), "rows": rows,
                   "units": sum(units)}
    else:
        ctx.progress(0.1, "Using today's search (YouTube allows one per subject per day here)")
    rows = cp.enrich(payload["rows"], own_id)
    payload["rows"], payload["metrics"] = rows, cp.metrics(rows)

    provider = deps.text_provider()
    want_read = provider is not None and (ctx.options.get("read_again") or payload.get("read_for") != payload["searched_at"])
    if want_read and payload["metrics"]["videos"]:
        ctx.progress(0.5, "Reading titles and thumbnails")
        others = [r for r in rows if not r["own"]][: cp.TOP]
        thumbs = await _thumbnails(others)
        prompt = cp.read_prompt(query, rows, payload["metrics"], video.subject or video.title, video.topic, facts,
                                hooks, subs, [i for i, _ in thumbs])
        images = [(f"Thumbnail #{i}:", data, "image/jpeg") for i, data in thumbs]
        try:
            result = await provider.look_json(prompt, images, cp.CompetitorRead, effort="low")
        except LLMError:
            _log_call(ctx, "competitor_read", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
            raise
        _log_call(ctx, "competitor_read", prompt, result.model, result.usage, result.latency_s)
        read = result.parsed.model_dump()
        ids = [r["id"] for r in others]
        for p in read["patterns"]:
            p["examples"] = [ids[n - 1] for n in p["examples"] if 0 < n <= len(ids)]
        for u in read["unclaimed"]:
            u["blocked_by"] = unbacked_claims(u["angle"], preset, facts, research)
        payload |= {"read": read, "read_for": payload["searched_at"], "read_at": utc_now(),
                    "read_usage": result.usage, "read_model": result.model}
    elif provider is None:
        payload["read"] = payload.get("read")

    with session(ctx.engine) as s:
        found = cp.find_row(s, video.subject or video.title, video.topic) or Research(
            kind=cp.KIND, subject_key=name_key(video.subject or video.title), topic_key=name_key(video.topic), payload={})
        found.payload = payload
        s.add(found)
        s.commit()
    m = payload["metrics"]
    ctx.progress(1.0, f"{m['videos']} competing videos; views {m['concentration'] or 'none'}"
                      + ("; read by Claude" if payload.get("read_for") == payload["searched_at"] else ""))
