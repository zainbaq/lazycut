"""Import, analysis, research and package jobs, and how their results are stored (BUILD_SPEC 7)."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, col, delete, select

from app.db import session
from app.models import (
    Analysis,
    Clip,
    Event,
    Fact,
    IntensitySample,
    LLMCall,
    Package,
    Segment,
    Video,
    utc_now,
)
from app.services import packaging, search_demand
from app.services.analysis import AnalysisRun, VideoContext
from app.services.events import DetectionContext, MergedEvent, build_detectors, run_engine
from app.services.events.base import CallRecord
from app.services.facts import derive
from app.services.importers.local import LocalImportSource
from app.services.jobs import JobContext
from app.services.llm.base import LLMError, VideoProvider
from app.services.media import (
    dead_time,
    intensity_samples,
    make_filmstrip,
    make_proxy,
    probe,
    scene_scores,
)
from app.services.playbook import load_playbook
from app.services.presets import FactDef, Preset, load_channel, load_presets
from app.services.research import (
    ResearchOut,
    blocked_domains,
    ensure_row,
    find_row,
    has_results,
    rate,
    research_view,
    search_prompt,
    structure_prompt,
    to_payload,
)
from app.settings import Settings

log = logging.getLogger(__name__)

DUPLICATE_WINDOW_S = 0.75  # a new model event this close to a kept one of its type is a duplicate (7.12)


@dataclass
class Deps:
    settings: Settings
    # Builds the video provider for one job, reporting status through the callback;
    # None when no Gemini key is set.
    video_provider: Callable[[Callable[[str], None]], VideoProvider | None]
    # Builds the Claude provider (search + structured answers); None when no Anthropic key is set.
    text_provider: Callable[[], Any] = lambda: None
    # The search-suggestion client (search_demand.SuggestClient); None turns the harvest off.
    suggest_client: Callable[[], Any] = lambda: None
    # The image-generation client (higgsfield.ImageClient); None when no Higgsfield key is set.
    image_client: Callable[[], Any] = lambda: None

    def can_watch(self) -> bool:
        return self.video_provider(lambda _msg: None) is not None

    def can_research(self) -> bool:
        return self.text_provider() is not None


def deps_of(ctx: JobContext) -> Deps:
    return ctx.runner.deps


def video_folder(settings: Settings, video_id: str) -> Path:
    return settings.media_dir / video_id


# ---- import -----------------------------------------------------------------------


async def import_job(ctx: JobContext) -> None:
    deps = deps_of(ctx)
    settings = deps.settings
    loop = asyncio.get_running_loop()
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        ref, kind = video.import_ref, video.kind
    folder = video_folder(settings, video.id)
    source = LocalImportSource(settings.inbox_dir)
    src_path = source.resolve(ref)
    dest = folder / f"source{src_path.suffix.lower()}"

    def stage(start: float, end: float, message: str) -> Callable[[float], None]:
        """A progress callback for one step, mapped onto [start, end] of the job, sent at most every 2 %."""
        last = [-1.0]

        def report(share: float) -> None:
            value = start + (end - start) * share
            if value - last[0] >= 0.02 or share >= 1.0:
                last[0] = value
                ctx.progress(value, message)

        return report

    try:
        copy_report = stage(0.0, 0.35, "Copying the video")
        ctx.progress(0.0, "Copying the video")
        await source.fetch(ref, dest, lambda share: loop.call_soon_threadsafe(copy_report, share))

        ctx.progress(0.36, "Reading the video")
        info = await probe(dest)
        with session(ctx.engine) as s:
            video = s.get(Video, ctx.video_id)
            if video is None:
                return
            video.source_path = str(dest)
            video.duration_s, video.width, video.height = info.duration_s, info.width, info.height
            video.fps, video.size_bytes, video.is_hdr = info.fps, info.size_bytes, info.is_hdr
            s.add(video)
            s.commit()

        proxy = folder / "proxy.mp4"
        ctx.progress(0.37, "Making the playback copy")
        await make_proxy(dest, proxy, info, stage(0.37, 0.85, "Making the playback copy"))

        ctx.progress(0.86, "Cutting the filmstrip")
        await make_filmstrip(proxy, folder / "frames", info.duration_s)

        ctx.progress(0.92, "Measuring intensity")
        times, scores = await scene_scores(proxy, folder / "scene_scores.bin")
        samples = intensity_samples(times, scores)
        quiet = dead_time(samples, threshold=settings.dead_time_threshold)
        with session(ctx.engine) as s:
            s.exec(delete(IntensitySample).where(IntensitySample.video_id == ctx.video_id))
            s.exec(delete(Segment).where(Segment.video_id == ctx.video_id, Segment.kind == "dead_time"))
            s.add_all(IntensitySample(video_id=ctx.video_id, t=t, score=round(v, 4)) for t, v in samples)
            s.add_all(Segment(video_id=ctx.video_id, kind="dead_time", t_start=a, t_end=b) for a, b in quiet)
            video = s.get(Video, ctx.video_id)
            if video is None:
                return
            video.proxy_path, video.status = str(proxy), "ready"
            s.add(video)
            if kind == "clip" and not s.exec(select(Clip).where(Clip.video_id == video.id)).first():
                # A pre-trimmed clip is one ready-made clip spanning the whole video.
                s.add(Clip(video_id=video.id, name=video.title, t_start=0.0, t_end=info.duration_s, status="selected"))
            s.commit()
    except Exception:
        with session(ctx.engine) as s:
            video = s.get(Video, ctx.video_id)
            if video is not None:
                video.status = "error"
                s.add(video)
                s.commit()
        raise

    ctx.progress(1.0, "Imported")
    if deps.can_watch():
        ctx.runner.start("analysis", ctx.video_id)
    if deps.can_research():
        # Research is shared by subject: a second video on the same subject reuses it (7.7).
        with session(ctx.engine) as s:
            video = s.get(Video, ctx.video_id)
            reusable = video is not None and has_results(find_row(s, video))
        if video is not None and not reusable:
            ctx.runner.start("research", ctx.video_id)


# ---- analysis ---------------------------------------------------------------------


def preset_for(settings: Settings, preset_id: str) -> tuple[Preset, str | None]:
    """The video's preset, or General with a note when it is missing or invalid."""
    presets, _errors = load_presets(settings.config_dir)
    if preset_id in presets:
        return presets[preset_id], None
    return presets["general"], f"Preset `{preset_id}` is missing or invalid; used General"


async def analysis_job(ctx: JobContext) -> None:
    deps = deps_of(ctx)
    settings = deps.settings
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        if video.status != "ready" or not video.proxy_path or not video.duration_s:
            raise RuntimeError("The import has not finished")
    video_info = video  # detached; its loaded fields stay readable
    preset, note = preset_for(settings, video_info.preset_id)
    try:
        playbook = load_playbook(settings.playbook_dir, video_info.topic)
    except Exception as exc:  # noqa: BLE001 - a broken playbook must not stop analysis
        log.warning("Ignoring the playbook for %r: %s", video_info.topic, exc)
        playbook = None

    def on_status(message: str) -> None:
        ctx.progress(None, message)

    def on_call(call: CallRecord) -> None:
        with session(ctx.engine) as s:
            s.add(LLMCall(job_id=ctx.job_id, **call.__dict__))
            s.commit()

    dctx = DetectionContext(
        proxy=Path(video_info.proxy_path),
        duration_s=video_info.duration_s,
        preset=preset,
        video=VideoContext(
            video_info.kind, video_info.duration_s, video_info.topic, video_info.subject, video_info.topic_terms
        ),
        playbook=playbook,
        video_provider=deps.video_provider(on_status),
        fps=settings.analysis_fps,
        media_resolution=settings.analysis_media_resolution,
        on_status=on_status,
        on_call=on_call,
    )
    detectors = build_detectors(settings.detector_ids)
    ctx.progress(0.05, note or "Watching the video")
    result = await run_engine(dctx, detectors)
    if not result.ran:
        raise RuntimeError("No event detector could run. Set GEMINI_API_KEY in .env.")

    ctx.progress(0.9, "Saving the timeline")
    run: AnalysisRun | None = dctx.outputs.get("gemini")
    events = persist_analysis(
        ctx.engine, ctx.video_id, preset, result.events, run,
        discard_user_work=bool(ctx.options.get("discard_user_work")),
        fps=settings.analysis_fps,
        detectors={"ran": result.ran, "skipped": result.skipped, "detections": len(result.detections)},
        playbook=playbook.topic if playbook else None,
    )
    for event in events:
        ctx.publish("analysis.event", event_dict(event))
    ctx.progress(1.0, f"{sum(not e.hidden for e in events)} events")


def _moved(event: Event) -> bool:
    return event.t_model_start is not None and abs(event.t_start - event.t_model_start) > 1e-6


def keeps(event: Event) -> bool:
    """Events a re-analysis keeps unless the user discards their work (7.12)."""
    return event.source == "user" or event.verified or event.hidden or event.edited or _moved(event)


def parse_fact_value(fact: FactDef, raw: Any) -> Any:
    if raw is None:
        return None
    text = str(raw).strip()
    if fact.type == "int":
        try:
            return int(float(text.split()[0]))
        except (ValueError, IndexError):
            return None
    if fact.type == "bool":
        lowered = text.lower()
        return True if lowered in {"true", "yes", "1"} else False if lowered in {"false", "no", "0"} else None
    if fact.type == "enum":
        return next((o for o in fact.options if o.lower() == text.lower()), None)
    return text or None


def persist_analysis(
    engine: Engine,
    video_id: str,
    preset: Preset,
    merged: list[MergedEvent],
    run: AnalysisRun | None,
    discard_user_work: bool = False,
    fps: float | None = None,
    detectors: dict | None = None,
    playbook: str | None = None,
) -> list[Event]:
    """Store one analysis. Returns every event of the video afterwards, in time order."""
    with session(engine) as s:
        existing = s.exec(select(Event).where(Event.video_id == video_id)).all()
        kept = [] if discard_user_work else [e for e in existing if keeps(e)]
        kept_ids = {e.id for e in kept}
        for event in existing:
            if event.id not in kept_ids:
                s.delete(event)
        s.exec(delete(Segment).where(Segment.video_id == video_id, col(Segment.kind).in_(("peak", "section"))))
        facts = s.exec(select(Fact).where(Fact.video_id == video_id)).all()
        confirmed = {} if discard_user_work else {f.key: f for f in facts if f.confirmed}
        for fact in facts:
            if fact.key not in confirmed:
                s.delete(fact)

        new_events = []
        for m in merged:
            if any(k.type == m.type and abs(k.t_start - m.t_start) <= DUPLICATE_WINDOW_S for k in kept):
                continue
            new_events.append(Event(
                video_id=video_id, t_start=m.t_start, t_end=m.t_end, t_model_start=m.t_start, t_model_end=m.t_end,
                type=m.type, label=m.label, intensity=m.intensity, crop_safe_9x16=m.crop_safe_9x16,
                confidence=m.confidence, source="model", detected_by=m.detected_by(),
            ))
        s.add_all(new_events)
        events = sorted(kept + new_events, key=lambda e: (e.t_start, e.type))

        if run is not None:
            s.add_all(
                Segment(video_id=video_id, kind=seg.kind, t_start=seg.t_start, t_end=seg.t_end, label=seg.label)
                for seg in run.analysis.segments
            )
        _store_facts(s, video_id, preset, events, run, confirmed)

        counts: dict[str, int] = {}
        for e in new_events:
            counts[e.type] = counts.get(e.type, 0) + 1
        s.add(Analysis(
            video_id=video_id,
            model=run.model if run else "",
            fps=fps,
            summary=", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "no events",
            basics=run.analysis.basics.model_dump() if run else None,
            raw={
                "analysis": run.analysis.model_dump() if run else None,
                "usage": run.usage if run else {},
                "latency_s": run.latency_s if run else None,
                "detectors": detectors or {},
                "playbook": playbook,
                "preset_id": preset.id,
            },
        ))
        s.commit()
        return events


def _store_facts(
    s: Session, video_id: str, preset: Preset, events: list[Event], run: AnalysisRun | None, confirmed: dict
) -> None:
    proposals = {p.key: p for p in run.analysis.fact_proposals} if run else {}
    for fact in preset.facts:
        if fact.key in confirmed:
            continue
        proposal = proposals.get(fact.key)
        evidence_ts = list(proposal.evidence_ts) if proposal else []
        row = Fact(video_id=video_id, key=fact.key, label=fact.label, evidence_ts=evidence_ts)
        if fact.derive_from:
            derive(row, fact, events)  # derived facts follow the visible events until confirmed (7.4)
        else:
            row.proposed_value = parse_fact_value(fact, proposal.value) if proposal else None
        s.add(row)


# ---- research ---------------------------------------------------------------------


def _log_call(ctx: JobContext, purpose: str, prompt: str, model: str, usage: dict, latency_s: float,
              status: str = "ok") -> None:
    with session(ctx.engine) as s:
        s.add(LLMCall(
            job_id=ctx.job_id, provider="anthropic", model=model, purpose=purpose, prompt=prompt,
            tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
            latency_ms=round(latency_s * 1000), status=status,
        ))
        s.commit()


async def research_job(ctx: JobContext) -> None:
    """Subject research: one web-search call, then one call that sorts the findings into fields (7.7).

    With `pasted_text` in the options, the user's own notes replace the search (no-search fallback).
    """
    deps = deps_of(ctx)
    settings = deps.settings
    provider = deps.text_provider()
    if provider is None:
        raise RuntimeError("Set ANTHROPIC_API_KEY in .env to research subjects, or type the values in")
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
    preset, _note = preset_for(settings, video.preset_id)
    channel, _errors = load_channel(settings.config_dir)
    if not preset.research_fields:
        ctx.progress(1.0, "This preset has no research fields")
        return

    pasted = (ctx.options.get("pasted_text") or "").strip()
    if pasted:
        ctx.progress(0.1, "Reading your notes")
        source_url = (ctx.options.get("source_url") or "").strip()
        findings, method = pasted, "pasted"
        sources = [{"title": "Pasted by you", "url": source_url}] if source_url else []
    else:
        ctx.progress(0.05, "Searching the web")
        prompt = search_prompt(video, preset)
        try:
            run = await provider.search(prompt, blocked_domains=blocked_domains(channel))
        except LLMError:
            _log_call(ctx, "research_search", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
            raise
        _log_call(ctx, "research_search", prompt, run.model, run.usage, run.latency_s)
        findings, method = run.text, "search"
        sources = [src for src in run.sources if rate(src["url"], channel) != "blocked"]

    ctx.progress(0.7, "Sorting the findings")
    prompt = structure_prompt(video, preset, findings, sources)
    try:
        result = await provider.generate_json(prompt, ResearchOut)
    except LLMError:
        _log_call(ctx, "research_structure", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
        raise
    _log_call(ctx, "research_structure", prompt, result.model, result.usage, result.latency_s)
    payload = to_payload(preset, result.parsed, sources, method)

    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        row = ensure_row(s, video)
        previous = row.payload or {}
        overrides = row.overrides or {}
        canonical = payload.get("canonical_name")
        if previous.get("subject_before") and video.subject == canonical:
            payload["subject_before"] = previous["subject_before"]
        elif canonical and video.subject and canonical.strip() != video.subject.strip() \
                and "canonical_name" not in overrides:
            # Correct the spelling and remember the user's version for a one-click revert (7.7).
            payload["subject_before"] = video.subject
            video.subject = canonical.strip()
            s.add(video)
        row.payload, row.sources = payload, sources
        s.add(row)
        s.commit()
    found = sum(f["value"] is not None for f in payload["fields"].values())
    ctx.progress(0.9, f"Found {found} of {len(payload['fields'])} fields; checking what people search")
    phrases = await harvest_demand(ctx, force=True)
    ctx.progress(1.0, f"Found {found} of {len(payload['fields'])} fields"
                 + (f" · {phrases} search phrases" if phrases is not None else ""))


async def harvest_demand(ctx: JobContext, force: bool = False) -> int | None:
    """Collect search suggestions for the video's topic and subject names (7.7.1). Free and soft:
    returns the number of phrases kept, or None when the harvest is off, fresh enough or failed."""
    client = deps_of(ctx).suggest_client()
    if client is None:
        return None
    settings = deps_of(ctx).settings
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None or not (video.topic or video.subject):
            return None
        preset, _note = preset_for(settings, video.preset_id)
        channel, _errors = load_channel(settings.config_dir)
        row = ensure_row(s, video)
        existing = search_demand.find_row(s, row)
        if not force and existing and search_demand.is_fresh(existing.payload):
            return None
        effective = research_view(row, video, preset, channel)["effective"]
        names = search_demand.subject_names(video.subject or video.title, effective,
                                            (row.payload or {}).get("subject_before"))
        topic = video.topic
        s.commit()
    payload = await search_demand.harvest(client, topic, names, preset.search_seeds)
    if not payload["phrases"]:
        log.warning("search demand: no suggestions (%s errors)", payload["errors"])
        if existing is not None:
            return None  # keep the last good harvest
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return None
        search_demand.save(s, ensure_row(s, video), payload)
        s.commit()
    return len(payload["phrases"])


# ---- packaging --------------------------------------------------------------------


async def package_job(ctx: JobContext) -> None:
    """Generate (or regenerate) the YouTube long-form package (7.8): one writer call, then code and rules.

    Options: `field` regenerates that one field; `replace_edits` lets a full run overwrite the
    user's manual edits (kept by default).
    """
    deps = deps_of(ctx)
    settings = deps.settings
    provider = deps.text_provider()
    if provider is None:
        raise RuntimeError("Set ANTHROPIC_API_KEY in .env to write packages")
    ctx.progress(0.02, "Checking what people search")
    await harvest_demand(ctx)
    with session(ctx.engine) as s:
        video = s.get(Video, ctx.video_id)
        if video is None:
            return
        preset, _note = preset_for(settings, video.preset_id)
        channel, _errors = load_channel(settings.config_dir)
        inp = packaging.gather(s, video, preset, channel)
        s.commit()
    missing = packaging.missing_required(preset, inp.fact_rows)
    if missing:
        raise RuntimeError(f"Confirm {', '.join(missing)} before generating the package")

    ctx.progress(0.1, "Writing the package")
    hooks = packaging.eligible_hooks(inp)
    candidates = packaging.title_candidates(inp, hooks)
    prompt = packaging.writer_prompt(inp, candidates, hooks)
    try:
        result = await provider.generate_json(prompt, packaging.WriterOut, effort="medium")
    except LLMError:
        _log_call(ctx, "package_youtube", prompt, getattr(provider, "model", ""), {}, 0.0, "error")
        raise
    _log_call(ctx, "package_youtube", prompt, result.model, result.usage, result.latency_s)
    fresh = packaging.assemble(inp, result.parsed, candidates, hooks)

    ctx.progress(0.85, "Checking the rules")
    only = ctx.options.get("field")
    replace_edits = bool(ctx.options.get("replace_edits"))
    with session(ctx.engine) as s:
        pkg = s.exec(select(Package).where(
            Package.video_id == ctx.video_id, Package.platform == "youtube", Package.clip_id == None,
        )).first()
        if pkg is None:
            pkg = Package(video_id=ctx.video_id, platform="youtube", version=0)
        old = dict(pkg.fields or {})
        edited = list(pkg.edited_fields or [])
        if only:
            fields = old | {k: v for k, v in fresh.items()
                            if k in (only, "seo") or (only == "title" and k.startswith("title_"))}
            if only == "chapters":
                fields["chapter_list"] = fresh["chapter_list"]
            edited = [e for e in edited if e != only]
        elif replace_edits or not old:
            fields, edited = fresh, []
        else:
            fields = fresh | {k: old[k] for k in edited if k in old}
            if "chapters" in edited and "chapter_list" in old:
                fields["chapter_list"] = old["chapter_list"]
        fields, results = packaging.run_rules(inp, fields, pkg.rule_results)
        fields = packaging.remember_generated(fields, old, edited)
        pkg.fields, pkg.rule_results, pkg.edited_fields = fields, results, edited
        pkg.inputs_hash = packaging.inputs_hash(inp)
        pkg.version = (pkg.version or 0) + 1
        pkg.created_at = utc_now()
        s.add(pkg)
        s.commit()
        blocks = sum(r["severity"] == "block" for r in results)
    ctx.progress(1.0, f"Package v{pkg.version} ready" + (f" · {blocks} blocked" if blocks else ""))


# ---- payloads ---------------------------------------------------------------------


def event_dict(event: Event) -> dict:
    return event.model_dump()
