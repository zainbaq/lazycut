import os
import shutil

from fastapi import APIRouter, HTTPException, Request

from app.db import db_status
from app.services.presets import load_channel, load_presets
from app.settings import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/config/status")
def config_status(request: Request) -> dict:
    """Config validation errors, active models, which keys are set, and storage checks."""
    settings = get_settings()
    presets, preset_errors = load_presets(settings.config_dir)
    channel, channel_errors = load_channel(settings.config_dir)
    inbox = settings.inbox_dir
    return {
        "errors": [e.model_dump() for e in channel_errors + preset_errors],
        "channel": channel.name if channel else None,
        "presets": sorted(presets),
        "models": {
            "video": settings.gemini_video_model or None,
            "text": settings.anthropic_model or None,
        },
        "keys": {
            "gemini": bool(settings.gemini_api_key),
            "anthropic": bool(settings.anthropic_api_key),
            "youtube": bool(settings.youtube_api_key),
        },
        "event_detectors": settings.detector_ids,
        "storage": {
            "db": db_status(request.app.state.engine) | {"path": str(settings.db_path)},
            "inbox": {
                "path": str(inbox),
                "readable": inbox.is_dir() and os.access(inbox, os.R_OK),
                # The import folder must be read-only: the app never changes files there.
                "read_only": inbox.is_dir() and not os.access(inbox, os.W_OK),
            },
            "data_writable": settings.data_dir.is_dir() and os.access(settings.data_dir, os.W_OK),
        },
        "tools": {"ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe"))},
    }


@router.get("/config/channel")
def channel() -> dict:
    profile, errors = load_channel(get_settings().config_dir)
    if profile is None:
        raise HTTPException(404, errors[0].problem if errors else "channel.yaml not found")
    return profile.model_dump()


@router.get("/presets")
def presets() -> list[dict]:
    found, _errors = load_presets(get_settings().config_dir)
    order = sorted(found, key=lambda pid: (pid != "general", found[pid].name.lower()))
    return [found[pid].model_dump() for pid in order]


@router.get("/presets/{preset_id}")
def preset(preset_id: str) -> dict:
    found, _errors = load_presets(get_settings().config_dir)
    if preset_id not in found:
        raise HTTPException(404, f"No preset `{preset_id}`")
    return found[preset_id].model_dump()
