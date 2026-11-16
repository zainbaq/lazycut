"""Thumbnail jobs (BUILD_SPEC 7.13): find good source frames, and generate, size and review thumbnails."""

import asyncio
import io
import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image
from sqlmodel import Session, col, select

from app.db import session
from app.models import (
    AppSetting,
    Event,
    IntensitySample,
    LLMCall,
    Package,
    Segment,
    Thumbnail,
    Video,
    utc_now,
)
from app.services import packaging
from app.services import thumbnails as tn
from app.services.higgsfield import HiggsfieldError
from app.services.jobs import JobContext
from app.services.llm.base import LLMError
from app.services.media import MediaError, frame_at
from app.services.pipeline import _log_call, deps_of, video_folder
from app.services.presets import load_channel
from app.services.rules import claim_and_number_results
from app.settings import Settings

log = logging.getLogger(__name__)

SCORE_WIDTH, RANK_WIDTH, SOURCE_WIDTH = 480, 640, 1920
RANK_TOP = 8
FRAMES_FILE = "frames.json"


def thumbs_dir(settings: Settings, video_id: str) -> Path:
    return video_folder(settings, video_id) / "thumbs"


# ---- settings -----------------------------------------------------------------------


def load_effective(s: Session, settings: Settings) -> tuple[tn.Effective | None, str | None]:
    cfg, error = tn.load_config(settings.config_dir)
    if cfg is None:
        return None, error
    row = s.get(AppSetting, tn.SETTINGS_KEY)
    try:
        ov = tn.Overrides.model_validate(row.value) if row else None
    except ValueError:
        ov = None  # a saved value the YAML no longer allows falls back to the defaults
    return tn.effective(cfg, ov), None


def channel_style(channel: Any) -> tuple[str, str, dict]:
    """(default text style, what to avoid, vertical safe margins) from channel.yaml."""
    extra = (channel.model_extra or {}) if channel else {}
    style = extra.get("thumbnail_style") or {}
    return style.get("text_default") or "", style.get("avoid") or "", extra.get("vertical_safe_margins") or {}


# ---- words --------------------------------------------------------------------------


def word_choices(inp: packaging.Inputs, pkg: Package | None) -> list[dict]:
    """The result words the package offers (each hook's word keeps its own text style), blocked ones left out."""
    hooks = packaging.eligible_hooks(inp)
    styles = {h["thumbnail_word"].upper(): h.get("thumbnail_text_style") for h in hooks if h.get("thumbnail_word")}
    fields = (pkg.fields if pkg else {}) or {}
    thumb = fields.get("thumbnail") or {}
    blocked = {r["field"] for r in (pkg.rule_results if pkg else []) or [] if r["severity"] == "block"}
    default_style, _avoid, _safe = channel_style(inp.channel)
    out: list[dict] = []
    for i, word in enumerate(thumb.get("word_options") or []):
        if f"thumbnail.word_options[{i}]" in blocked or not str(word).strip():
            continue
        out.append({"word": word, "text_style": styles.get(str(word).upper()) or thumb.get("text_style")
                    or default_style, "from": "hook" if str(word).upper() in styles else "package"})
    return out


def word_issues(inp: packaging.Inputs, pkg: Package | None, word: str) -> list[dict]:
    """Claim and number rules on a word the user typed (the package's own words are already checked)."""
    if not word.strip():
        return []
    ctx = packaging.rule_context(inp, set(), (pkg.fields if pkg else None))
    return [r for r in claim_and_number_results([("thumbnail.word", word)], ctx) if r["severity"] != "pass"]


# ---- frame finder -------------------------------------------------------------------


def _drama(t: float, samples: list[tuple[float, float]]) -> float:
    near = [score for ts, score in samples if abs(ts - t) <= 1.0]
    return max(near) if near else 0.0


async def thumb_frames_job(ctx: JobContext) -> None:
    """Score frames around the video's best moments, then let Claude rank the top few (7.13.1)."""
    deps = deps_of(ctx)
    settings = deps.settings
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        if not video.proxy_path or not Path(video.proxy_path).is_file() or not video.duration_s:
            raise RuntimeError("The video is still importing")
        pkg = s.exec(select(Package).where(Package.video_id == video.id, Package.platform == "youtube")).first()
        writer_ts = list(((pkg.fields or {}).get("thumbnail") or {}).get("frame_ts") or []) if pkg else []
        peaks = [(g.t_start, g.t_end) for g in s.exec(select(Segment).where(
            Segment.video_id == video.id, Segment.kind == "peak")).all()]
        events = [(e.t_start, e.t_end, e.label or e.type) for e in s.exec(select(Event).where(
            Event.video_id == video.id, Event.hidden == False, Event.intensity == "high")
            .order_by(col(Event.t_start))).all()]
        samples = [(i.t, i.score) for i in s.exec(select(IntensitySample).where(
            IntensitySample.video_id == video.id)).all()]
        proxy, duration, topic, subject = Path(video.proxy_path), video.duration_s, video.topic, video.subject
    times = tn.candidate_times(duration, writer_ts=writer_ts, peaks=peaks, events=events, intensity=samples)
    cache = thumbs_dir(settings, ctx.video_id) / "candidates"
    sem = asyncio.Semaphore(4)
    done = 0

    async def look(t: float, why: str, offset: float) -> dict | None:
        nonlocal done
        at = min(max(0.0, t + offset), duration - 0.05)
        async with sem:
            try:
                path = await frame_at(proxy, at, SCORE_WIDTH, cache / f"{round(at * 1000)}_{SCORE_WIDTH}.jpg")
            except MediaError:
                return None
        stats = await asyncio.to_thread(lambda: tn.frame_stats(Image.open(path)))
        done += 1
        ctx.progress(0.05 + 0.55 * done / (len(times) * 3), "Scoring frames")
        return {"t": round(at, 2), "moment": t, "why": why, "stats": stats, "drama": _drama(at, samples)}

    looked = await asyncio.gather(*(look(t, why, off) for t, why in times for off in (-0.4, 0.0, 0.4)))
    frames = tn.score_frames([f for f in looked if f is not None])
    if not frames:
        raise RuntimeError("No frames could be read from the video")
    top = frames[:RANK_TOP]
    ranked_by = "code"
    provider = deps.text_provider()
    if provider is not None and len(top) > 1:
        ctx.progress(0.65, "Asking Claude which frames work best")
        images = []
        for i, f in enumerate(top):
            path = await frame_at(proxy, f["t"], RANK_WIDTH, cache / f"{round(f['t'] * 1000)}_{RANK_WIDTH}.jpg")
            images.append((f"Frame {i}:", path.read_bytes(), "image/jpeg"))
        prompt = tn.ranking_prompt(topic, subject, len(top))
        try:
            result = await provider.look_json(prompt, images, tn.FrameRanking)
            _log_call(ctx, "thumbnail_frames", prompt, result.model, result.usage, result.latency_s)
            for j in result.parsed.frames:
                if 0 <= j.index < len(top):
                    top[j.index]["claude"] = j.model_dump(exclude={"index"})
            ranked_by = "claude"
        except LLMError as exc:  # the code ranking still stands
            _log_call(ctx, "thumbnail_frames", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
            log.warning("frame ranking failed: %s", exc)
    for f in top:
        judged = f.get("claude")
        f["score"] = round(0.6 * judged["score"] / 10 + 0.4 * f["code_score"], 3) if judged else f["code_score"]
        f["text_corner"] = (judged or {}).get("text_corner") or f["stats"].free_corner
    top.sort(key=lambda f: -f["score"])
    payload = {
        "created_at": utc_now(), "ranked_by": ranked_by, "looked_at": len(looked),
        "frames": [{
            "t": f["t"], "why": f["why"], "score": f["score"], "code_score": f["code_score"],
            "text_corner": f["text_corner"], "claude": f.get("claude"),
            "sharpness": round(f["stats"].sharpness, 1), "brightness": round(f["stats"].brightness, 1),
        } for f in top],
    }
    out = thumbs_dir(settings, ctx.video_id) / FRAMES_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload), encoding="utf-8")
    ctx.publish("thumbnail.frames", payload)
    best = payload["frames"][0]
    ctx.progress(1.0, f"Best frame at {best['t']:.1f} s" + (" · ranked by Claude" if ranked_by == "claude" else ""))


def read_frames(settings: Settings, video_id: str) -> dict | None:
    path = thumbs_dir(settings, video_id) / FRAMES_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# ---- generation ---------------------------------------------------------------------


def thumbnail_dict(row: Thumbnail) -> dict:
    out = row.model_dump(exclude={"raw_path", "final_path", "source_path"})
    base = f"/thumbnails/{row.id}/image"
    out["urls"] = {
        "source": f"{base}?v=source" if row.source_path else None,
        "raw": f"{base}?v=raw&r={row.created_at}" if row.raw_path else None,
        "final": f"{base}?v=final&r={_mtime(row.final_path)}" if row.final_path else None,
    }
    return out


def _mtime(path: str | None) -> int:
    try:
        return int(Path(path).stat().st_mtime) if path else 0
    except OSError:
        return 0


def _update(ctx: JobContext, thumb_id: str, **changes: Any) -> Thumbnail | None:
    with session(ctx.engine) as s:
        row = s.get(Thumbnail, thumb_id)
        if row is None:
            return None
        for key, value in changes.items():
            setattr(row, key, value)
        s.add(row)
        s.commit()
        ctx.publish("thumbnail.updated", thumbnail_dict(row))
        return row


async def source_bytes(settings: Settings, video: Video, row: Thumbnail) -> tuple[bytes, str, Path]:
    """The source image: a full-resolution frame cut from the original, or the user's upload."""
    if row.source_kind == "upload":
        path = Path(row.source_path)
        if not path.is_file():
            raise RuntimeError("The uploaded image is gone; upload it again")
        media = {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")
        return path.read_bytes(), media, path
    if not video.source_path or not Path(video.source_path).is_file():
        raise RuntimeError("The video file is not available")
    t = float(row.source_t or 0.0)
    width = min(SOURCE_WIDTH, video.width or SOURCE_WIDTH)
    dest = thumbs_dir(settings, video.id) / "sources" / f"{round(t * 1000)}_{width}.jpg"
    path = await frame_at(Path(video.source_path), t, width, dest)
    return path.read_bytes(), "image/jpeg", path


def render_row(row: Thumbnail, channel: Any) -> bytes:
    _style, _avoid, safe = channel_style(channel)
    raw = Image.open(row.raw_path)  # type: ignore[arg-type]
    return tn.render_final(raw, aspect=row.aspect, word=row.word, text_style=row.text_style,
                           corner=row.text_corner, font=row.font, text_mode=row.text_mode, safe=safe)


def code_checks(row: Thumbnail, final: bytes) -> list[dict]:
    img = Image.open(io.BytesIO(final))
    w, h = img.size
    checks = [{"id": "file", "ok": len(final) <= tn.MAX_BYTES and (w, h) == tn.OUTPUT_SIZE[row.aspect],
               "note": f"{w}×{h}, {len(final) / 1024:.0f} KB" + ("" if len(final) <= tn.MAX_BYTES else " (over 2 MB)")}]
    if row.text_mode == "app" and row.word and row.raw_path and Path(row.raw_path).exists():
        # Measure the picture behind the word, not the final image: the word's own outline would always read as busy.
        busy = tn.text_contrast(tn.fit_cover(Image.open(row.raw_path), tn.OUTPUT_SIZE[row.aspect]), row.text_corner)
        checks.append({"id": "backdrop", "ok": busy < 62,
                       "note": "calm area behind the word" if busy < 62 else "busy area behind the word; try another corner"})
    return checks


async def review_row(ctx: JobContext, row: Thumbnail, src_small: bytes, final: bytes, channel: Any) -> dict | None:
    provider = deps_of(ctx).text_provider()
    if provider is None:
        return None
    _style, avoid, _safe = channel_style(channel)
    with session(ctx.engine) as s:
        video = s.get(Video, row.video_id)
        subject = video.subject if video else ""
    prompt = tn.review_prompt(word=row.word, text_mode=row.text_mode, subject=subject, avoid=avoid, aspect=row.aspect)
    try:
        result = await provider.look_json(prompt, [("Image 1:", src_small, "image/jpeg"),
                                                   ("Image 2:", final, "image/jpeg")], tn.ReviewOut)
    except LLMError as exc:
        _log_call(ctx, "thumbnail_review", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
        log.warning("thumbnail review failed: %s", exc)
        return None
    _log_call(ctx, "thumbnail_review", prompt, result.model, result.usage, result.latency_s)
    return tn.review_dict(result.parsed, result.model)


def _small_jpeg(data: bytes, width: int = 768) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = img.resize((width, max(1, round(img.height * width / img.width))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _log_image_call(ctx: JobContext, model: str, prompt: str, latency_s: float, status: str) -> None:
    with session(ctx.engine) as s:
        s.add(LLMCall(job_id=ctx.job_id, provider="higgsfield", model=model, purpose="thumbnail",
                      prompt=prompt, latency_ms=round(latency_s * 1000), status=status))
        s.commit()


async def thumbnail_job(ctx: JobContext) -> None:
    """Generate the queued thumbnails of one batch (options: ids), or only review them again (review_only)."""
    deps = deps_of(ctx)
    settings = deps.settings
    ids: list[str] = list(ctx.options.get("ids") or [])
    review_only = bool(ctx.options.get("review_only"))
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        eff, error = load_effective(s, settings)
        rows = [r for r in (s.get(Thumbnail, i) for i in ids) if r is not None]
    if eff is None:
        raise RuntimeError(error or "Thumbnail settings are missing")
    channel, _errors = load_channel(settings.config_dir)
    client = deps.image_client()
    if client is None and not review_only:
        raise RuntimeError("Set HIGGSFIELD_API_KEY in .env to generate thumbnails")

    if review_only:
        for row in rows:
            ctx.progress(None, "Reviewing")
            src, _media, _path = await source_bytes(settings, video, row)
            final = Path(row.final_path).read_bytes()  # type: ignore[arg-type]
            review = await review_row(ctx, row, _small_jpeg(src), final, channel)
            checks = code_checks(row, final)
            _update(ctx, row.id, review=(review or {"verdict": None, "checks": []}) | {"code": checks})
        return

    uploaded: dict[str, str] = {}
    locks: dict[str, asyncio.Lock] = {}
    sem = asyncio.Semaphore(3)
    finished = 0

    async def run(row: Thumbnail) -> bool:
        nonlocal finished
        model = eff.cfg.models[row.model]
        async with sem:
            try:
                _update(ctx, row.id, status="running")
                key = f"{row.source_kind}:{row.source_t}:{row.source_path}"
                async with locks.setdefault(key, asyncio.Lock()):  # one cut and one upload per source
                    data, media, _path = await source_bytes(settings, video, row)
                    if key not in uploaded:
                        uploaded[key] = await client.upload(data, media)
                body = tn.request_body(model, row.params, row.prompt, uploaded[key], row.aspect, row.text_mode)
                try:
                    cost = await client.estimate(model.path, body)
                except HiggsfieldError:
                    cost = None
                _update(ctx, row.id, cost_usd=cost)
                gen = await client.generate(
                    model.path, body, on_status=lambda st: ctx.progress(None, f"{model.label}: {st.replace('_', ' ')}"))
                _log_image_call(ctx, model.path, row.prompt, gen.latency_s, gen.status)
                if gen.status != "completed" or not gen.images:
                    message = {"nsfw": "Higgsfield's safety filter stopped this one (not charged)",
                               "canceled": "The request was cancelled"}.get(gen.status) or gen.error or "Generation failed"
                    _update(ctx, row.id, status="nsfw" if gen.status == "nsfw" else "failed", error=message,
                            request_id=gen.request_id, cost_usd=None)
                    return False
                raw = await client.download(gen.images[0])
                folder = thumbs_dir(settings, video.id) / row.id
                folder.mkdir(parents=True, exist_ok=True)
                raw_img = Image.open(io.BytesIO(raw))
                raw_path = folder / ("raw.png" if raw_img.format == "PNG" else "raw.jpg")
                raw_path.write_bytes(raw)
                if tn.same_image(raw_img, Image.open(io.BytesIO(data))):
                    _update(ctx, row.id, status="failed", raw_path=str(raw_path), request_id=gen.request_id,
                            error="The model returned the source unchanged; try another model or prompt")
                    return False
                row.raw_path = str(raw_path)
                final = await asyncio.to_thread(render_row, row, channel)
                final_path = folder / "final.jpg"
                final_path.write_bytes(final)
                _update(ctx, row.id, status="done", raw_path=str(raw_path), final_path=str(final_path),
                        request_id=gen.request_id, error=None)
                checks = code_checks(row, final)
                review = await review_row(ctx, row, _small_jpeg(data), final, channel) if eff.review else None
                _update(ctx, row.id, review=(review or {"verdict": None, "checks": []}) | {"code": checks})
                return True
            except (HiggsfieldError, MediaError, RuntimeError, OSError) as exc:
                # Refused or never finished: nothing was charged, so the quote is cleared.
                _update(ctx, row.id, status="failed", error=str(exc), cost_usd=None)
                return False
            finally:
                finished += 1
                ctx.progress(finished / max(1, len(rows)), f"{finished} of {len(rows)} done")

    results = await asyncio.gather(*(run(r) for r in rows))
    ok = sum(results)
    if ok == 0 and rows:
        with session(ctx.engine) as s:
            first = s.get(Thumbnail, rows[0].id)
        raise RuntimeError(first.error if first and first.error else "No thumbnail was made")
    ctx.progress(1.0, f"{ok} of {len(rows)} thumbnails ready")
