"""Clip jobs: the finder (BUILD_SPEC 7.5) and the export (7.6). The deterministic parts of the
finder live in `clipfinder.py`; the ffmpeg calls in `media.py`."""

import re
from pathlib import Path

from sqlmodel import select

from app.db import session
from app.models import Clip, ClipExport, LLMCall, Package, Video, utc_now
from app.services import clipfinder, packaging, short_packaging
from app.services.events.refine import refine_moment
from app.services.jobs import JobContext
from app.services.llm.base import LLMError
from app.services.media import export_clip, vertical_size
from app.services.pipeline import _log_call, deps_of, preset_for, video_folder
from app.services.presets import ChannelProfile, load_channel

_BAD_FILENAME = re.compile(r"[^\w\-]")


def export_filename(channel: ChannelProfile | None, video: Video, clip: Clip, export: ClipExport) -> str:
    """The name a download gets: `{Channel}_{Topic}_{Subject}_{Clip}_9x16.mp4` (Windows-safe)."""
    shape = "9x16" if export.crop == "9x16" else "full"
    parts = [channel.name if channel else "LazyCut", video.topic, video.subject or video.title, clip.name,
             shape + ("_lossless" if export.mode == "lossless" else "")]
    return "_".join(_BAD_FILENAME.sub("", p) for p in parts if _BAD_FILENAME.sub("", p or "")) + ".mp4"


def export_summary(export: ClipExport) -> str:
    size = (export.size_bytes or 0) / 1e6
    return (f"{export.width}×{export.height} at {export.fps:g} fps · {export.duration_s:.1f} s · {size:.0f} MB"
            + (" · lossless, cut on a keyframe" if export.mode == "lossless" else ""))


async def clip_export_job(ctx: JobContext) -> None:
    """Cut a clip from the source file (7.6). Options: `clip_id`, `crop` (none | 9x16), `mode`
    (accurate | lossless). An export with the same crop and mode replaces the clip's earlier one."""
    settings = deps_of(ctx).settings
    crop, mode = ctx.options.get("crop") or "none", ctx.options.get("mode") or "accurate"
    with session(ctx.engine) as s:
        clip = s.get(Clip, ctx.options.get("clip_id"))
        video = s.get(Video, ctx.video_id)
        if clip is None or video is None:
            raise RuntimeError("The clip was deleted before it could be exported")
        t_start, t_end, clip_id = clip.t_start, clip.t_end, clip.id
    if not video.source_path or not Path(video.source_path).is_file():
        raise RuntimeError("The source file is missing, so there is nothing to cut from")

    folder = video_folder(settings, video.id) / "clips" / clip_id
    dest = folder / f"{crop}_{mode}_{round(t_start * 1000)}-{round(t_end * 1000)}.mp4"
    label = "Copying the clip (lossless)" if mode == "lossless" else "Encoding the clip"
    last = [-1.0]

    def report(share: float) -> None:
        if share - last[0] >= 0.02 or share >= 1.0:
            last[0] = share
            ctx.progress(0.02 + 0.95 * share, label)

    ctx.progress(0.02, label)
    made = await export_clip(Path(video.source_path), dest, t_start, t_end, crop, mode,
                             vertical_size(settings.export_vertical_size), report)

    with session(ctx.engine) as s:
        clip = s.get(Clip, clip_id)
        if clip is None:  # deleted while encoding
            dest.unlink(missing_ok=True)
            return
        for old in s.exec(select(ClipExport).where(ClipExport.clip_id == clip_id, ClipExport.crop == crop,
                                                   ClipExport.mode == mode)).all():
            if old.path and Path(old.path) != dest:
                Path(old.path).unlink(missing_ok=True)
            s.delete(old)
        export = ClipExport(clip_id=clip_id, crop=crop, mode=mode, path=str(dest), t_start=t_start, t_end=t_end, **made)
        clip.status = "exported"
        s.add_all([export, clip])
        s.commit()
        summary = export_summary(export)
    ctx.progress(1.0, f"Exported {summary}")


async def clip_find_job(ctx: JobContext) -> None:
    """Propose clips for a prompt from the stored timeline: one text call, then code (7.5).

    Options: `prompt`, `platform`, `target_len_s`. With no text model the clips come from the
    timeline alone and say so. Proposals nobody touched from earlier runs are replaced; clips
    the user trimmed, named, kept or exported stay.
    """
    deps = deps_of(ctx)
    request = (ctx.options.get("prompt") or "").strip()
    platform = ctx.options.get("platform") or None
    target = ctx.options.get("target_len_s") or None
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        preset, _note = preset_for(deps.settings, video.preset_id)
        cctx = clipfinder.load_context(s, video, preset, full=True)
    if not cctx.events:
        raise RuntimeError("There are no events to find clips in. Analyze the video or add events first, "
                           "or mark a clip by hand with I and O.")

    provider = deps.text_provider()
    note = ""
    if provider is None:
        ctx.progress(0.3, "Reading the timeline")
        found = clipfinder.timeline_candidates(cctx, platform, target)
        note = "No ANTHROPIC_API_KEY: picked from the timeline alone, so the prompt was not read"
    else:
        ctx.progress(0.1, "Looking for clips")
        prompt = clipfinder.finder_prompt(cctx, request, platform, target, clipfinder.FINDER_MODE)
        schema = clipfinder.FinderOut if clipfinder.FINDER_MODE == "anchors" else clipfinder.TimedOut
        try:
            result = await provider.generate_json(prompt, schema, effort="low")
        except LLMError:
            _log_call(ctx, "clip_find", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
            raise
        _log_call(ctx, "clip_find", prompt, result.model, result.usage, result.latency_s)
        resolve = clipfinder.resolve_anchor if clipfinder.FINDER_MODE == "anchors" else clipfinder.resolve_timed
        found = clipfinder.finalise([resolve(p, cctx) for p in result.parsed.clips], cctx, platform)
        note = result.parsed.note.strip()

    ctx.progress(0.9, "Saving the clips")
    with session(ctx.engine) as s:
        for old in s.exec(select(Clip).where(Clip.video_id == ctx.video_id, Clip.status == "candidate",
                                             Clip.source == "finder")).all():
            s.delete(old)
        rows = [
            clipfinder.measure(Clip(
                video_id=ctx.video_id, name=c.name or "Clip", t_start=c.t_start, t_end=c.t_end, prompt=request or None,
                reason=c.reason or None, payoff_t=c.payoff_t, status="candidate", platform=platform, source="finder",
                orig_start=c.t_start, orig_end=c.t_end,
            ), cctx)
            for c in found
        ]
        s.add_all(rows)
        s.commit()
        for row in rows:
            ctx.publish("clip.candidate", clipfinder.clip_dict(row, cctx))
    count = f"{len(rows)} clip{'' if len(rows) == 1 else 's'} found" if rows else "No clip found"
    ctx.progress(1.0, f"{count}. {note}" if note else count)


async def clip_package_job(ctx: JobContext) -> None:
    """Write the short-form packages of one clip (7.8): one writer call, then code renders each
    platform and runs its rules. Options: `clip_id`, `platforms`; `field` rewrites that one field
    (on the single platform given); `replace_edits` lets a full run overwrite the user's edits."""
    deps = deps_of(ctx)
    provider = deps.text_provider()
    if provider is None:
        raise RuntimeError("Set ANTHROPIC_API_KEY in .env to write packages")
    platforms = [p for p in ctx.options.get("platforms") or [] if p in short_packaging.SHORT_PLATFORMS]
    only, replace_edits = ctx.options.get("field"), bool(ctx.options.get("replace_edits"))
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        clip = s.get(Clip, ctx.options.get("clip_id"))
        if video is None or clip is None or not platforms:
            raise RuntimeError("The clip was deleted before its package could be written")
        preset, _note = preset_for(deps.settings, video.preset_id)
        channel, _errors = load_channel(deps.settings.config_dir)
        inp = packaging.gather(s, video, preset, channel)
        s.commit()
    missing = packaging.missing_required(preset, inp.fact_rows)
    if missing:
        raise RuntimeError(f"Confirm {', '.join(missing)} before generating the package")

    names = ", ".join(short_packaging.PLATFORM_NAME[p] for p in platforms)
    ctx.progress(0.1, f"Writing for {names}")
    hooks = packaging.eligible_hooks(inp)
    prompt = short_packaging.writer_prompt(inp, clip, platforms, hooks)
    try:
        result = await provider.generate_json(prompt, short_packaging.ShortWriterOut, effort="medium")
    except LLMError:
        _log_call(ctx, "package_short", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
        raise
    _log_call(ctx, "package_short", prompt, result.model, result.usage, result.latency_s)
    fresh = short_packaging.assemble(inp, clip, result.parsed, platforms, hooks)

    ctx.progress(0.85, "Checking the rules")
    blocks = 0
    with session(ctx.engine) as s:
        clip = s.get(Clip, clip.id)
        if clip is None:
            return
        for platform in platforms:
            pkg = s.exec(select(Package).where(Package.clip_id == clip.id, Package.platform == platform)).first()
            if pkg is None:
                pkg = Package(video_id=ctx.video_id, clip_id=clip.id, platform=platform, version=0)
            old, edited = dict(pkg.fields or {}), list(pkg.edited_fields or [])
            new = fresh[platform]
            if only and old:
                fields = old | {only: new.get(only, old.get(only))}
                if only == "hashtags":
                    fields.pop("hashtags_text", None)
                edited = [e for e in edited if e != only]
            elif replace_edits or not old:
                fields, edited = new, []
            else:
                fields = new | {k: old[k] for k in edited if k in old}
            fields, results = short_packaging.run_rules(inp, clip, platform, fields, pkg.rule_results)
            fields = short_packaging.remember_generated(fields, old, edited, platform)
            pkg.fields, pkg.rule_results, pkg.edited_fields = fields, results, edited
            pkg.inputs_hash = short_packaging.short_hash(inp, clip)
            pkg.version, pkg.created_at = (pkg.version or 0) + 1, utc_now()
            s.add(pkg)
            blocks += sum(r["severity"] == "block" for r in results)
        if clip.status == "candidate":
            clip.status = "selected"  # a clip with a package is one the user is keeping
            s.add(clip)
        s.commit()
    ctx.progress(1.0, f"Wrote {names}" + (f" · {blocks} blocked" if blocks else ""))


REFINE_REACH_S = 2.0  # an edge is never moved further than this by a refine


async def clip_refine_job(ctx: JobContext) -> None:
    """Refine a clip's edges (7.3, 7.5): look closely at its first and its closing event with the
    video model (two small calls), then place the edges the preset's lead-in and tail around
    what was seen. An edge whose moment is not found, or would move too far, is left alone."""
    deps = deps_of(ctx)
    provider = deps.video_provider(lambda message: ctx.progress(None, message))
    if provider is None:
        raise RuntimeError("Set GEMINI_API_KEY in .env to refine edges")
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        clip = s.get(Clip, ctx.options.get("clip_id"))
        if video is None or clip is None:
            raise RuntimeError("The clip was deleted before it could be refined")
        preset, _note = preset_for(deps.settings, video.preset_id)
        cctx = clipfinder.load_context(s, video, preset)
    if not video.source_path or not Path(video.source_path).is_file():
        raise RuntimeError("The source file is missing, so there is nothing to look at")
    inside = clipfinder.events_in(cctx.events, clip.t_start, clip.t_end)
    if not inside:
        raise RuntimeError("There are no events in this clip to refine its edges against")
    rules = preset.clip_rules
    types = {t.id: t for t in preset.event_types}
    first, last = inside[0], clipfinder._closer(inside, rules)

    def describe(event) -> str:
        kind = types.get(event.type)
        label = f'"{event.label.strip()}"' if event.label and event.label.strip() else ""
        return " ".join(filter(None, [kind.label if kind else event.type, label, f"({kind.definition})" if kind else ""]))

    asks = [
        ("start", first.t_start, f"the first frame of this event: {describe(first)}."),
        ("end", max(last.t_end, last.t_start),
         f"the frame where this event is over: {describe(last)}." + (f" {rules.end_cue.capitalize()}." if rules.end_cue else "")),
    ]
    workdir = video_folder(deps.settings, video.id) / "cache"
    moved: dict[str, float] = {}
    notes: list[str] = []
    for i, (edge, t, cue) in enumerate(asks):
        ctx.progress(0.05 + 0.45 * i, f"Looking closely at the clip's {edge}")
        try:
            got = await refine_moment(provider, Path(video.source_path), t, cue, cctx.duration_s, workdir)
        except LLMError:
            _log_video_call(ctx, "clip_refine", cue, deps.settings.gemini_video_model, {}, 0.0, "error")
            raise
        _log_video_call(ctx, "clip_refine", got.prompt, got.result.model, got.result.usage, got.result.latency_s)
        old = clip.t_start if edge == "start" else clip.t_end
        if got.t is None:
            notes.append(f"{edge} kept (the moment was not found)")
            continue
        new = round(got.t - rules.lead_in_s if edge == "start" else got.t + rules.tail_s, 2)
        new = min(max(new, 0.0), cctx.duration_s)
        if abs(new - old) > REFINE_REACH_S:
            notes.append(f"{edge} kept (the answer was {abs(new - old):.1f} s away)")
        elif abs(new - old) < 0.05:
            notes.append(f"{edge} confirmed")
        else:
            moved[edge] = new
            notes.append(f"{edge} {clipfinder.stamp(old)} → {new // 60:.0f}:{new % 60:05.2f}")

    with session(ctx.engine) as s:
        clip = s.get(Clip, clip.id)
        if clip is None:
            return
        t_start, t_end = moved.get("start", clip.t_start), moved.get("end", clip.t_end)
        if moved and t_end - t_start >= clipfinder.MIN_CLIP_S:
            clip.t_start, clip.t_end = t_start, t_end
            if clip.status == "candidate":
                clip.status = "selected"
            clipfinder.measure(clip, cctx)
            s.add(clip)
            s.commit()
    ctx.progress(1.0, "Refined: " + "; ".join(notes))


def _log_video_call(ctx: JobContext, purpose: str, prompt: str, model: str, usage: dict, latency_s: float,
                    status: str = "ok") -> None:
    with session(ctx.engine) as s:
        s.add(LLMCall(job_id=ctx.job_id, provider="gemini", model=model, purpose=purpose, prompt=prompt,
                      tokens_in=usage.get("total_input_tokens"), tokens_out=usage.get("total_output_tokens"),
                      latency_ms=round(latency_s * 1000), status=status))
        s.commit()
