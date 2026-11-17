"""Presets (5): read, check, create, save (form or YAML) and delete."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.db import session
from app.models import Video
from app.services import preset_store
from app.services.preset_store import PresetProblem
from app.services.presets import load_channel, load_presets
from app.settings import get_settings

router = APIRouter(tags=["presets"])


def _fail(exc: PresetProblem) -> HTTPException:
    # The same shape as FastAPI's validation errors, so every client reads it the same way.
    return HTTPException(exc.status, [{"loc": [p["path"]] if p["path"] else [], "msg": p["message"]} for p in exc.problems])


def _usage(request: Request) -> dict[str, int]:
    with session(request.app.state.engine) as s:
        rows = s.exec(select(Video.preset_id)).all()
    counts: dict[str, int] = {}
    for preset_id in rows:
        counts[preset_id] = counts.get(preset_id, 0) + 1
    return counts


READ_ONLY = ("file", "video_count")  # added by `_out`; a form sends them back, the preset has no such keys


def _editable(body: dict) -> dict:
    return {k: v for k, v in body.items() if k not in READ_ONLY}


def _out(preset: Any, usage: dict[str, int], files: dict) -> dict:
    path = files.get(preset.id)
    return preset.model_dump() | {
        "file": f"presets/{path.name}" if path else None,
        "video_count": usage.get(preset.id, 0),
    }


@router.get("/presets")
def presets(request: Request) -> list[dict]:
    config = get_settings().config_dir
    found, _errors = load_presets(config)
    files, usage = preset_store.preset_files(config), _usage(request)
    order = sorted(found, key=lambda pid: (pid != "general", found[pid].name.lower()))
    return [_out(found[pid], usage, files) for pid in order]


@router.get("/presets/{preset_id}")
def preset(preset_id: str, request: Request) -> dict:
    config = get_settings().config_dir
    found, _errors = load_presets(config)
    if preset_id not in found:
        raise HTTPException(404, f"No preset `{preset_id}`")
    return _out(found[preset_id], _usage(request), preset_store.preset_files(config))


@router.get("/presets/{preset_id}/yaml")
def preset_yaml(preset_id: str) -> dict:
    """The file as written, for the YAML tab (also for a file that fails validation)."""
    config = get_settings().config_dir
    text = preset_store.read_text(config, preset_id)
    if text is None:
        if preset_id != "general":
            raise HTTPException(404, f"No preset `{preset_id}`")
        text = preset_store.as_yaml(load_presets(config)[0]["general"])  # the built-in copy has no file yet
    return {"id": preset_id, "text": text}


class Check(BaseModel):
    preset: dict | None = None
    yaml: str | None = None


@router.post("/presets/{preset_id}/check")
def check(preset_id: str, body: Check) -> dict:
    """Validate an edit without saving it: {ok, problems: [{path, message}]}."""
    try:
        data = preset_store.parse_yaml(body.yaml) if body.yaml is not None else _editable(body.preset or {})
        if not isinstance(data, dict):
            raise PresetProblem([{"path": "", "message": "a preset is a mapping of keys"}])
        if data.get("id", preset_id) != preset_id:
            raise PresetProblem([{"path": "id", "message": f"the id must stay `{preset_id}`"}])
        preset_store.validate(data | {"id": preset_id})
    except PresetProblem as exc:
        return {"ok": False, "problems": exc.problems}
    return {"ok": True, "problems": []}


class NewPreset(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    copy_from: str | None = None


@router.post("/presets", status_code=201)
def create(body: NewPreset, request: Request) -> dict:
    config = get_settings().config_dir
    try:
        made = preset_store.create(config, body.id.strip(), body.name, body.copy_from)
    except PresetProblem as exc:
        raise _fail(exc) from exc
    return _out(made, _usage(request), preset_store.preset_files(config))


@router.put("/presets/{preset_id}")
def save(preset_id: str, body: dict, request: Request) -> dict:
    """Save the form: the whole preset, merged into its file so comments and layout survive."""
    config = get_settings().config_dir
    try:
        saved = preset_store.update(config, preset_id, _editable(body))
    except PresetProblem as exc:
        raise _fail(exc) from exc
    return _out(saved, _usage(request), preset_store.preset_files(config))


class YamlText(BaseModel):
    text: str = Field(max_length=200_000)


@router.put("/presets/{preset_id}/yaml")
def save_yaml(preset_id: str, body: YamlText, request: Request) -> dict:
    config = get_settings().config_dir
    try:
        saved = preset_store.write_yaml(config, preset_id, body.text)
    except PresetProblem as exc:
        raise _fail(exc) from exc
    return _out(saved, _usage(request), preset_store.preset_files(config))


@router.delete("/presets/{preset_id}")
def delete(preset_id: str, request: Request) -> dict:
    """Delete a preset file; its videos switch to General (5) and the answer says how many."""
    config = get_settings().config_dir
    channel, _ = load_channel(config)
    if channel and channel.default_preset == preset_id:
        raise HTTPException(409, "This is the channel's default preset (default_preset in channel.yaml); change that first")
    try:
        preset_store.delete(config, preset_id)
    except PresetProblem as exc:
        raise _fail(exc) from exc
    with session(request.app.state.engine) as s:
        videos = s.exec(select(Video).where(col(Video.preset_id) == preset_id)).all()
        for video in videos:
            video.preset_id = "general"
            s.add(video)
        s.commit()
    return {"deleted": preset_id, "videos_switched": len(videos)}
