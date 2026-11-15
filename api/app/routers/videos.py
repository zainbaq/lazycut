import asyncio
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.db import session
from app.models import Event, IntensitySample, Segment, Video
from app.services.facts import fact_dict, sync_facts
from app.services.importers.base import ImportRefError
from app.services.importers.local import LocalImportSource
from app.services.jobs import JobRunner
from app.services.media import MediaError, frame_at
from app.services.pipeline import video_folder
from app.services.presets import load_presets
from app.settings import get_settings
from app.views import video_dict

router = APIRouter()


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _session(request: Request) -> Session:
    return session(request.app.state.engine)


def _video(s: Session, video_id: str) -> Video:
    video = s.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "No such video")
    return video


# ---- imports ----------------------------------------------------------------------


@router.get("/imports")
async def imports(request: Request) -> dict:
    settings = get_settings()
    items = await LocalImportSource(settings.inbox_dir).list()
    with _session(request) as s:
        videos = s.exec(select(Video).where(Video.import_source == "local").order_by(col(Video.created_at))).all()
    # Already imported = same ref and the same size as the copy that was probed.
    imported = {(v.import_ref, v.size_bytes): v.id for v in videos if v.status != "error"}
    return {
        "folder": str(settings.inbox_dir),
        "items": [
            {
                "source": "local", "ref": i.ref, "name": i.name, "size_bytes": i.size_bytes,
                "modified_at": i.modified_at, "imported_video_id": imported.get((i.ref, i.size_bytes)),
            }
            for i in items
        ],
    }


class NewVideo(BaseModel):
    source: Literal["local"] = "local"
    ref: str
    title: str = Field(min_length=1)
    subject: str = ""
    topic: str = ""
    topic_terms: str = ""
    kind: Literal["long", "clip"] = "long"
    preset_id: str = "general"


@router.post("/videos", status_code=201)
async def create_video(body: NewVideo, request: Request) -> dict:
    settings = get_settings()
    presets, _ = load_presets(settings.config_dir)
    if body.preset_id not in presets:
        raise HTTPException(422, f"No preset `{body.preset_id}`")
    try:
        LocalImportSource(settings.inbox_dir).resolve(body.ref)
    except ImportRefError as exc:
        raise HTTPException(422, str(exc)) from exc
    video = Video(
        title=body.title.strip(), subject=body.subject.strip(), topic=body.topic.strip(),
        topic_terms=body.topic_terms.strip(), kind=body.kind, preset_id=body.preset_id,
        import_source=body.source, import_ref=body.ref,
    )
    with _session(request) as s:
        s.add(video)
        s.commit()
    _runner(request).start("import", video.id)
    with _session(request) as s:
        return video_dict(s, _video(s, video.id), presets)


@router.get("/videos")
def list_videos(request: Request) -> list[dict]:
    presets, _ = load_presets(get_settings().config_dir)
    with _session(request) as s:
        videos = s.exec(select(Video).order_by(col(Video.created_at).desc())).all()
        return [video_dict(s, v, presets) for v in videos]


@router.get("/videos/{video_id}")
def get_video(video_id: str, request: Request) -> dict:
    presets, _ = load_presets(get_settings().config_dir)
    with _session(request) as s:
        return video_dict(s, _video(s, video_id), presets)


class VideoEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    subject: str | None = None
    topic: str | None = None
    topic_terms: str | None = None
    preset_id: str | None = None


@router.patch("/videos/{video_id}")
def edit_video(video_id: str, body: VideoEdit, request: Request) -> dict:
    presets, _ = load_presets(get_settings().config_dir)
    if body.preset_id is not None and body.preset_id not in presets:
        raise HTTPException(422, f"No preset `{body.preset_id}`")
    with _session(request) as s:
        video = _video(s, video_id)
        for key, value in body.model_dump(exclude_none=True).items():
            setattr(video, key, value.strip() if isinstance(value, str) else value)
        s.add(video)
        s.commit()
        return video_dict(s, video, presets)


@router.delete("/videos/{video_id}", status_code=204)
async def delete_video(video_id: str, request: Request) -> Response:
    with _session(request) as s:
        _video(s, video_id)
    await _runner(request).cancel_for_video(video_id)
    with _session(request) as s:
        video = _video(s, video_id)
        s.delete(video)  # rows of other tables go with it (ON DELETE CASCADE)
        s.commit()
    folder = video_folder(get_settings(), video_id)
    if folder.is_dir():
        await asyncio.to_thread(shutil.rmtree, folder, True)
    return Response(status_code=204)


# ---- media ------------------------------------------------------------------------


@router.get("/videos/{video_id}/media")
def media(video_id: str, request: Request, quality: Literal["proxy", "source"] = "proxy") -> FileResponse:
    with _session(request) as s:
        video = _video(s, video_id)
    path = video.proxy_path if quality == "proxy" else video.source_path
    if not path or not Path(path).is_file():
        raise HTTPException(404, "The video file is not ready yet")
    # FileResponse answers Range requests with 206 and the requested bytes.
    return FileResponse(path, media_type="video/mp4" if quality == "proxy" else None)


@router.get("/videos/{video_id}/frames")
def frames(video_id: str, request: Request) -> dict:
    with _session(request) as s:
        _video(s, video_id)
    index_path = video_folder(get_settings(), video_id) / "frames" / "index.json"
    if not index_path.is_file():
        return {"interval_s": None, "width": None, "frames": []}
    import json

    index = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        "interval_s": index["interval_s"],
        "width": index["width"],
        "frames": [
            {"t": round(n * index["interval_s"], 3), "url": f"/videos/{video_id}/frames/{n:06d}.jpg"}
            for n in range(index["count"])
        ],
    }


@router.get("/videos/{video_id}/frames/{name}")
def frame_file(video_id: str, name: str) -> FileResponse:
    if not name.endswith(".jpg") or not name[:-4].isdigit():
        raise HTTPException(404, "No such frame")
    path = video_folder(get_settings(), video_id) / "frames" / name
    if not path.is_file():
        raise HTTPException(404, "No such frame")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/videos/{video_id}/frame")
async def frame(
    video_id: str, request: Request, t: float = Query(ge=0), w: int = Query(default=640, ge=64, le=3840)
) -> FileResponse:
    with _session(request) as s:
        video = _video(s, video_id)
    if not video.source_path or not Path(video.source_path).is_file():
        raise HTTPException(404, "The video file is not ready yet")
    t = min(t, max(0.0, (video.duration_s or t) - 0.05))
    dest = video_folder(get_settings(), video_id) / "cache" / f"frame_{round(t * 1000)}_{w}.jpg"
    try:
        await frame_at(Path(video.source_path), t, w, dest)
    except MediaError as exc:
        raise HTTPException(422, str(exc)) from exc
    return FileResponse(dest, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


# ---- timeline and facts -----------------------------------------------------------


@router.get("/videos/{video_id}/timeline")
def timeline(video_id: str, request: Request) -> dict:
    presets, _ = load_presets(get_settings().config_dir)
    with _session(request) as s:
        video = _video(s, video_id)
        preset = presets.get(video.preset_id) or presets["general"]
        events = s.exec(select(Event).where(Event.video_id == video_id).order_by(col(Event.t_start))).all()
        segments = s.exec(select(Segment).where(Segment.video_id == video_id).order_by(col(Segment.t_start))).all()
        samples = s.exec(
            select(IntensitySample.score).where(IntensitySample.video_id == video_id).order_by(col(IntensitySample.t))
        ).all()
    return {
        "duration_s": video.duration_s,
        "fps": video.fps,
        "preset_id": preset.id,
        "event_types": [e.model_dump() for e in preset.event_types],
        "events": [e.model_dump() for e in events],
        "segments": [
            {"id": g.id, "kind": g.kind, "t_start": g.t_start, "t_end": g.t_end, "label": g.label}
            for g in segments if g.kind != "dead_time"
        ],
        "intensity": {"bucket_s": 0.5, "scores": list(samples)},
        "dead_time": [{"t_start": g.t_start, "t_end": g.t_end} for g in segments if g.kind == "dead_time"],
    }


@router.get("/videos/{video_id}/facts")
def facts(video_id: str, request: Request) -> list[dict]:
    presets, _ = load_presets(get_settings().config_dir)
    with _session(request) as s:
        video = _video(s, video_id)
        preset = presets.get(video.preset_id) or presets["general"]
        rows = sync_facts(s, video_id, preset)
        s.commit()
        events = list(s.exec(select(Event).where(Event.video_id == video_id)).all())
        return [fact_dict(f, preset, events) for f in rows]


# ---- analysis and updates ---------------------------------------------------------


class AnalyzeBody(BaseModel):
    discard_user_work: bool = False


@router.post("/videos/{video_id}/analyze", status_code=202)
async def analyze(video_id: str, request: Request, body: AnalyzeBody | None = None) -> dict:
    runner = _runner(request)
    with _session(request) as s:
        video = _video(s, video_id)
    if not runner.deps.can_watch():
        raise HTTPException(409, "Set GEMINI_API_KEY in .env to analyze videos")
    if video.status != "ready":
        raise HTTPException(409, "The import has not finished")
    if runner.running(video_id, "analysis"):
        raise HTTPException(409, "An analysis is already running")
    job = runner.start("analysis", video_id, discard_user_work=bool(body and body.discard_user_work))
    return job.model_dump()


@router.get("/videos/{video_id}/updates")
async def updates(video_id: str, request: Request) -> StreamingResponse:
    with _session(request) as s:
        _video(s, video_id)
    bus = request.app.state.bus

    async def stream():
        queue = bus.subscribe(video_id)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                if await request.is_disconnected():
                    break
        finally:
            bus.unsubscribe(video_id, queue)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
