"""Subject research: results with sources, overrides, the paste fallback, spelling revert (BUILD_SPEC 7.7)."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import session
from app.models import Video
from app.services.jobs import JobRunner
from app.services.presets import load_channel, load_presets
from app.services.research import check_override, ensure_row, research_view
from app.settings import get_settings

router = APIRouter()

MAX_PASTE_CHARS = 20000


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _video(s: Session, video_id: str) -> Video:
    video = s.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "No such video")
    return video


def _view(s: Session, video: Video, request: Request) -> dict:
    settings = get_settings()
    presets, _ = load_presets(settings.config_dir)
    preset = presets.get(video.preset_id) or presets["general"]
    channel, _ = load_channel(settings.config_dir)
    row = ensure_row(s, video)
    s.commit()
    runner = _runner(request)
    return research_view(row, video, preset, channel) | {
        "video_id": video.id,
        "can_search": runner.deps.can_research(),
        "running": runner.running(video.id, "research") is not None,
    }


@router.get("/videos/{video_id}/research")
def get_research(video_id: str, request: Request) -> dict:
    with session(request.app.state.engine) as s:
        return _view(s, _video(s, video_id), request)


class ResearchRun(BaseModel):
    pasted_text: str | None = Field(default=None, max_length=MAX_PASTE_CHARS)
    source_url: str | None = Field(default=None, max_length=2000)


@router.post("/videos/{video_id}/research", status_code=202)
async def run_research(video_id: str, request: Request, body: ResearchRun | None = None) -> dict:
    runner = _runner(request)
    with session(request.app.state.engine) as s:
        _video(s, video_id)
    if not runner.deps.can_research():
        raise HTTPException(409, "Set ANTHROPIC_API_KEY in .env to research subjects, or type the values in")
    if runner.running(video_id, "research"):
        raise HTTPException(409, "Research is already running")
    options: dict[str, Any] = {}
    if body and body.pasted_text and body.pasted_text.strip():
        options = {"pasted_text": body.pasted_text, "source_url": (body.source_url or "").strip()}
    return runner.start("research", video_id, **options).model_dump()


class FieldEdit(BaseModel):
    key: str
    value: Any = None
    restore: bool = False  # true: drop the user's value and use the research value again


@router.patch("/videos/{video_id}/research")
def edit_research(video_id: str, body: FieldEdit, request: Request) -> dict:
    presets, _ = load_presets(get_settings().config_dir)
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        preset = presets.get(video.preset_id) or presets["general"]
        definition = next((f for f in preset.research_fields if f.key == body.key), None)
        if definition is None:
            raise HTTPException(422, f"`{body.key}` is not a research field of the {preset.name} preset")
        row = ensure_row(s, video)
        overrides = dict(row.overrides or {})
        if body.restore:
            overrides.pop(body.key, None)
        else:
            try:
                overrides[body.key] = check_override(definition, body.value)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        row.overrides = overrides
        s.add(row)
        s.commit()
        return _view(s, video, request)


@router.post("/videos/{video_id}/research/revert-spelling")
def revert_spelling(video_id: str, request: Request) -> dict:
    """Undo the spelling correction: the user's subject comes back and stays (7.7)."""
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        row = ensure_row(s, video)
        before = (row.payload or {}).get("subject_before")
        if not before:
            raise HTTPException(409, "There is no spelling correction to undo")
        video.subject = before
        row.overrides = dict(row.overrides or {}) | {"canonical_name": before}
        payload = dict(row.payload or {})
        payload.pop("subject_before", None)
        row.payload = payload
        s.add_all([video, row])
        s.commit()
        return _view(s, video, request)
