"""Clips: list, make by hand, trim, rename, select, delete (BUILD_SPEC 7.5, 9.4)."""

import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.db import session
from app.models import Clip, ClipExport, Video
from app.services import clipfinder
from app.services.clip_jobs import export_filename
from app.services.jobs import JobRunner
from app.services.pipeline import video_folder
from app.services.presets import Preset, load_channel, load_presets
from app.settings import get_settings

router = APIRouter()

Platform = Literal["shorts", "reels", "tiktok"]


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _session(request: Request) -> Session:
    return session(request.app.state.engine)


def _preset(video: Video) -> Preset:
    presets, _ = load_presets(get_settings().config_dir)
    return presets.get(video.preset_id) or presets["general"]


def _video(s: Session, video_id: str) -> Video:
    video = s.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "No such video")
    return video


def _clip(s: Session, clip_id: str) -> Clip:
    clip = s.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "No such clip")
    return clip


def _exports(s: Session, clip_ids: list[str]) -> dict[str, list[ClipExport]]:
    out: dict[str, list[ClipExport]] = {}
    if clip_ids:
        for row in s.exec(select(ClipExport).where(col(ClipExport.clip_id).in_(clip_ids))).all():
            out.setdefault(row.clip_id, []).append(row)
    return out


def _view(s: Session, clip: Clip, ctx: clipfinder.ClipContext) -> dict:
    return clipfinder.clip_dict(clip, ctx, _exports(s, [clip.id]).get(clip.id))


def _check_range(video: Video, t_start: float, t_end: float) -> None:
    duration = video.duration_s or 0.0
    if not (0 <= t_start <= duration and 0 <= t_end <= duration + 1e-6):
        raise HTTPException(422, f"A clip must lie between 0 and {duration:.2f} s")
    if t_end - t_start < clipfinder.MIN_CLIP_S - 1e-6:
        raise HTTPException(422, f"A clip is at least {clipfinder.MIN_CLIP_S:g} s long")


@router.get("/videos/{video_id}/clips")
def list_clips(video_id: str, request: Request) -> dict:
    runner = _runner(request)
    with _session(request) as s:
        video = _video(s, video_id)
        ctx = clipfinder.load_context(s, video, _preset(video))
        clips = s.exec(select(Clip).where(Clip.video_id == video_id).order_by(col(Clip.t_start), col(Clip.created_at))).all()
        exports = _exports(s, [c.id for c in clips])
        return {
            "can_find": runner.deps.can_research(),
            "can_refine": runner.deps.can_watch(),
            "finding": runner.running(video_id, "clip_find") is not None,
            "limits": {"min_s": clipfinder.MIN_CLIP_S, "max_s": clipfinder.PLATFORM_MAX_S},
            "clips": [clipfinder.clip_dict(c, ctx, exports.get(c.id)) for c in clips],
        }


class Find(BaseModel):
    prompt: str = Field(default="", max_length=500)
    platform: Platform = "reels"
    target_len_s: float | None = Field(default=None, ge=clipfinder.MIN_CLIP_S, le=600)


@router.post("/videos/{video_id}/clips/find", status_code=202)
async def find_clips(video_id: str, request: Request, body: Find | None = None) -> dict:
    """Start the finder: one Claude text call on the stored timeline (no model call without a key)."""
    body = body or Find()
    runner = _runner(request)
    with _session(request) as s:
        video = _video(s, video_id)
        if video.status != "ready":
            raise HTTPException(409, "The import has not finished")
        if not clipfinder.load_context(s, video, _preset(video)).events:
            raise HTTPException(409, "There are no events to find clips in yet. Analyze the video or add events "
                                     "first, or mark a clip by hand with I and O.")
    if runner.running(video_id, "clip_find"):
        raise HTTPException(409, "The finder is already running")
    job = runner.start("clip_find", video_id, prompt=body.prompt.strip(), platform=body.platform,
                       target_len_s=body.target_len_s)
    return job.model_dump()


class NewClip(BaseModel):
    t_start: float
    t_end: float
    name: str = ""
    platform: Platform | None = None


@router.post("/videos/{video_id}/clips", status_code=201)
def add_clip(video_id: str, body: NewClip, request: Request) -> dict:
    """A clip marked by hand (the I and O keys). It is the user's, so it starts out selected."""
    with _session(request) as s:
        video = _video(s, video_id)
        if video.status != "ready":
            raise HTTPException(409, "The import has not finished")
        t_start, t_end = round(body.t_start, 3), round(body.t_end, 3)
        _check_range(video, t_start, t_end)
        ctx = clipfinder.load_context(s, video, _preset(video))
        count = len(s.exec(select(Clip.id).where(Clip.video_id == video_id)).all())
        clip = clipfinder.measure(Clip(
            video_id=video_id, name=body.name.strip() or f"Clip {count + 1}", t_start=t_start, t_end=t_end,
            status="selected", platform=body.platform, source="user", orig_start=t_start, orig_end=t_end,
        ), ctx)
        s.add(clip)
        s.commit()
        return _view(s, clip, ctx)


class ClipEdit(BaseModel):
    t_start: float | None = None
    t_end: float | None = None
    name: str | None = None
    status: Literal["candidate", "selected"] | None = None
    platform: Platform | None = None
    payoff_t: float | None = None
    reset: bool = False  # back to the range it was created with


@router.patch("/clips/{clip_id}")
def edit_clip(clip_id: str, body: ClipEdit, request: Request) -> dict:
    with _session(request) as s:
        clip = _clip(s, clip_id)
        video = _video(s, clip.video_id)
        sent = body.model_dump(exclude_unset=True)
        if any(sent.get(k) is None for k in ("t_start", "t_end", "name", "status") if k in sent):
            raise HTTPException(422, "Leave a field out instead of sending null")
        t_start, t_end = sent.get("t_start", clip.t_start), sent.get("t_end", clip.t_end)
        if body.reset:
            if clip.orig_start is None or clip.orig_end is None:
                raise HTTPException(409, "This clip has no original range to go back to")
            t_start, t_end = clip.orig_start, clip.orig_end
        t_start, t_end = round(t_start, 3), round(t_end, 3)
        moved = abs(t_start - clip.t_start) > 1e-9 or abs(t_end - clip.t_end) > 1e-9
        if moved:
            _check_range(video, t_start, t_end)
            clip.t_start, clip.t_end = t_start, t_end
        if "name" in sent:
            name = sent["name"].strip()
            if not name:
                raise HTTPException(422, "A clip needs a name")
            clip.name = name
        if "platform" in sent:
            clip.platform = sent["platform"]
        if "payoff_t" in sent:
            payoff = sent["payoff_t"]
            if payoff is not None and not (clip.t_start <= payoff <= clip.t_end):
                raise HTTPException(422, "The payoff must lie inside the clip")
            clip.payoff_t = payoff
        if "status" in sent and clip.status != "exported":
            clip.status = sent["status"]
        elif (moved or "name" in sent) and clip.status == "candidate":
            clip.status = "selected"  # trimming or naming a proposal makes it the user's
        ctx = clipfinder.load_context(s, video, _preset(video))
        clipfinder.measure(clip, ctx)
        s.add(clip)
        s.commit()
        return _view(s, clip, ctx)


@router.delete("/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: str, request: Request) -> Response:
    with _session(request) as s:
        clip = _clip(s, clip_id)
        video_id = clip.video_id
        paths = [x.path for x in s.exec(select(ClipExport).where(ClipExport.clip_id == clip_id)).all()]
        s.delete(clip)  # its exports and packages go with it (ON DELETE CASCADE)
        s.commit()
    folder = video_folder(get_settings(), video_id) / "clips"
    for path in paths:
        # Only files this app wrote under the video's clips folder are removed.
        if path and Path(path).is_file() and folder in Path(path).parents:
            Path(path).unlink()
    shutil.rmtree(folder / clip_id, ignore_errors=True)
    return Response(status_code=204)


# ---- export (7.6) -----------------------------------------------------------------


class Export(BaseModel):
    crop: Literal["none", "9x16"] = "none"
    mode: Literal["accurate", "lossless"] = "accurate"


@router.post("/clips/{clip_id}/export", status_code=202)
async def export(clip_id: str, request: Request, body: Export | None = None) -> dict:
    """Cut the clip from the source file with ffmpeg (free; no model call)."""
    body = body or Export()
    runner = _runner(request)
    if body.mode == "lossless" and body.crop != "none":
        raise HTTPException(422, "A lossless export cannot be cropped: cropping needs a re-encode")
    with _session(request) as s:
        clip = _clip(s, clip_id)
        video = _video(s, clip.video_id)
    if not video.source_path or not Path(video.source_path).is_file():
        raise HTTPException(409, "The source file is missing, so there is nothing to cut from")
    if runner.running(video.id, "clip_export"):
        raise HTTPException(409, "An export is already running for this video")
    return runner.start("clip_export", video.id, clip_id=clip_id, crop=body.crop, mode=body.mode).model_dump()


@router.get("/exports/{export_id}/download")
def download(export_id: str, request: Request) -> FileResponse:
    with _session(request) as s:
        row = s.get(ClipExport, export_id)
        if row is None:
            raise HTTPException(404, "No such export")
        clip = _clip(s, row.clip_id)
        video = _video(s, clip.video_id)
    if not row.path or not Path(row.path).is_file():
        raise HTTPException(404, "The exported file is gone; export the clip again")
    channel, _ = load_channel(get_settings().config_dir)
    return FileResponse(row.path, media_type="video/mp4", filename=export_filename(channel, video, clip, row))


@router.post("/clips/{clip_id}/refine", status_code=202)
async def refine(clip_id: str, request: Request) -> dict:
    """Refine the clip's edges with a narrow, high-rate pass: two small paid Gemini calls (7.3)."""
    runner = _runner(request)
    with _session(request) as s:
        clip = _clip(s, clip_id)
        video = _video(s, clip.video_id)
        ctx = clipfinder.load_context(s, video, _preset(video))
    if not runner.deps.can_watch():
        raise HTTPException(409, "Set GEMINI_API_KEY in .env to refine edges")
    if not video.source_path or not Path(video.source_path).is_file():
        raise HTTPException(409, "The source file is missing, so there is nothing to look at")
    if not clipfinder.events_in(ctx.events, clip.t_start, clip.t_end):
        raise HTTPException(409, "There are no events in this clip to refine its edges against")
    if runner.running(video.id, "clip_refine"):
        raise HTTPException(409, "A refine is already running for this video")
    return runner.start("clip_refine", video.id, clip_id=clip_id).model_dump()
