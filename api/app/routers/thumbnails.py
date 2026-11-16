"""Thumbnails: find frames, upload a source, generate, adjust the word, choose, review, and the Advanced settings (7.13)."""

import io
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.db import session
from app.models import AppSetting, Package, Thumbnail, Video, new_id, utc_now
from app.services import packaging
from app.services import thumbnails as tn
from app.services.jobs import JobRunner
from app.services.presets import load_channel, load_presets
from app.services.thumbnail_jobs import (
    channel_style,
    load_effective,
    read_frames,
    render_row,
    thumbnail_dict,
    thumbs_dir,
    word_choices,
    word_issues,
)
from app.settings import get_settings

router = APIRouter()

MAX_UPLOAD = 20 * 1024 * 1024
UPLOAD_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _video(s: Session, video_id: str) -> Video:
    video = s.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "No such video")
    return video


def _thumb(s: Session, thumb_id: str) -> Thumbnail:
    row = s.get(Thumbnail, thumb_id)
    if row is None:
        raise HTTPException(404, "No such thumbnail")
    return row


def _inputs(s: Session, video: Video) -> tuple[packaging.Inputs, Package | None]:
    settings = get_settings()
    presets, _ = load_presets(settings.config_dir)
    channel, _ = load_channel(settings.config_dir)
    inp = packaging.gather(s, video, presets.get(video.preset_id) or presets["general"], channel)
    pkg = s.exec(select(Package).where(Package.video_id == video.id, Package.platform == "youtube")).first()
    return inp, pkg


def _effective(s: Session) -> tn.Effective:
    eff, error = load_effective(s, get_settings())
    if eff is None:
        raise HTTPException(409, error or "Thumbnail settings are missing")
    return eff


def _uploads(video_id: str) -> list[dict]:
    folder = thumbs_dir(get_settings(), video_id) / "uploads"
    if not folder.is_dir():
        return []
    files = sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"id": p.name, "url": f"/videos/{video_id}/thumbnails/uploads/{p.name}"} for p in files if p.is_file()]


@router.get("/videos/{video_id}/thumbnails")
def list_thumbnails(video_id: str, request: Request) -> dict:
    runner = _runner(request)
    deps = runner.deps
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        eff = _effective(s)
        inp, pkg = _inputs(s, video)
        s.commit()
        rows = s.exec(select(Thumbnail).where(Thumbnail.video_id == video_id)
                      .order_by(col(Thumbnail.created_at).desc())).all()
        words = word_choices(inp, pkg)
    default_style, _avoid, _safe = channel_style(inp.channel)
    missing = []
    if deps.image_client() is None:
        missing.append("Set HIGGSFIELD_API_KEY in .env")
    return {
        "can_generate": not missing,
        "missing": missing,
        "can_review": deps.can_research(),
        "settings": eff.view(),
        "words": words,
        "default_text_style": default_style,
        "frames": read_frames(get_settings(), video_id),
        "finding_frames": runner.running(video_id, "thumbnail_frames") is not None,
        "running": runner.running(video_id, "thumbnail") is not None,
        "uploads": _uploads(video_id),
        "thumbnails": [thumbnail_dict(r) for r in rows],
    }


@router.post("/videos/{video_id}/thumbnails/frames", status_code=202)
async def find_frames(video_id: str, request: Request) -> dict:
    runner = _runner(request)
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        if not video.proxy_path:
            raise HTTPException(409, "The video is still importing")
    if runner.running(video_id, "thumbnail_frames"):
        raise HTTPException(409, "Already looking for frames")
    return runner.start("thumbnail_frames", video_id).model_dump()


@router.post("/videos/{video_id}/thumbnails/uploads", status_code=201)
async def upload_source(video_id: str, request: Request) -> dict:
    """Your own source image, sent as the raw request body (Content-Type image/jpeg, png or webp)."""
    media = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if media not in UPLOAD_TYPES:
        raise HTTPException(415, "Upload a JPEG, PNG or WebP image")
    data = await request.body()
    if not data:
        raise HTTPException(422, "The upload was empty")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Images up to 20 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(422, "That file is not a readable image") from exc
    if min(img.size) < 360:
        raise HTTPException(422, "Use an image at least 640×360")
    with session(request.app.state.engine) as s:
        _video(s, video_id)
    folder = thumbs_dir(get_settings(), video_id) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex[:12]}{UPLOAD_TYPES[media]}"
    (folder / name).write_bytes(data)
    return {"id": name, "url": f"/videos/{video_id}/thumbnails/uploads/{name}", "width": img.width, "height": img.height}


def _upload_path(video_id: str, name: str) -> Path:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(404, "No such upload")
    path = thumbs_dir(get_settings(), video_id) / "uploads" / name
    if not path.is_file():
        raise HTTPException(404, "No such upload")
    return path


@router.get("/videos/{video_id}/thumbnails/uploads/{name}")
def upload_file(video_id: str, name: str) -> FileResponse:
    return FileResponse(_upload_path(video_id, name))


class Source(BaseModel):
    kind: Literal["frame", "upload"]
    t: float | None = Field(default=None, ge=0)
    upload_id: str | None = None


class GenerateBody(BaseModel):
    source: Source
    models: list[str] | None = None            # several models compare them on the same source
    aspects: list[Literal["16:9", "9:16"]] | None = None
    word: str | None = Field(default=None, max_length=40)
    text_style: str | None = Field(default=None, max_length=120)
    text_corner: Literal["auto", "top_left", "top_right", "bottom_left", "bottom_right"] | None = None
    text_mode: Literal["app", "model"] | None = None
    prompt: str | None = Field(default=None, max_length=4000)   # your own prompt for this run


def _corner(choice: str, source: Source, frames: dict | None) -> str:
    if choice != "auto":
        return choice
    if source.kind == "frame" and frames and source.t is not None:
        near = min(frames.get("frames") or [], key=lambda f: abs(f["t"] - source.t), default=None)
        if near and abs(near["t"] - source.t) <= 0.6:
            return near["text_corner"]
    return "top_right"


@router.post("/videos/{video_id}/thumbnails", status_code=202)
async def generate(video_id: str, body: GenerateBody, request: Request) -> dict:
    runner = _runner(request)
    if runner.deps.image_client() is None:
        raise HTTPException(409, "Set HIGGSFIELD_API_KEY in .env to generate thumbnails")
    if runner.running(video_id, "thumbnail"):
        raise HTTPException(409, "Thumbnails are already being made")
    settings = get_settings()
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        eff = _effective(s)
        inp, pkg = _inputs(s, video)
        s.commit()
        models = body.models or [eff.model]
        unknown = [m for m in models if m not in eff.cfg.models]
        if unknown:
            raise HTTPException(422, f"Unknown model {', '.join(unknown)}")
        if len(models) > 4:
            raise HTTPException(422, "Compare up to four models at a time")
        aspects = list(dict.fromkeys(body.aspects or eff.aspects))
        if body.source.kind == "frame":
            if body.source.t is None:
                raise HTTPException(422, "Pick a frame time")
            if video.duration_s and body.source.t > video.duration_s:
                raise HTTPException(422, "That time is past the end of the video")
            source_path = ""
        else:
            source_path = str(_upload_path(video_id, body.source.upload_id or ""))
        words = word_choices(inp, pkg)
        word = (body.word if body.word is not None else (words[0]["word"] if words else "")).strip()
        issues = word_issues(inp, pkg, word) if word and word not in {w["word"] for w in words} else []
        blocked = [i for i in issues if i["severity"] == "block"]
        if blocked:
            raise HTTPException(422, blocked[0]["message"])
        default_style, avoid, _safe = channel_style(inp.channel)
        style = body.text_style or next((w["text_style"] for w in words if w["word"] == word), None) or default_style
        text_mode = body.text_mode or eff.text_mode
        corner = _corner(body.text_corner or eff.text_corner, body.source, read_frames(settings, video_id))
        batch = new_id()
        rows = []
        for model_id in models:
            for aspect in aspects:
                prompt = tn.build_prompt(
                    eff, template=body.prompt, topic=video.topic, subject=video.subject or video.title, word=word,
                    text_style=style, corner=corner, aspect=aspect, avoid=avoid, text_mode=text_mode)
                rows.append(Thumbnail(
                    video_id=video_id, batch_id=batch, source_kind=body.source.kind, source_t=body.source.t,
                    source_path=source_path, aspect=aspect, model=model_id, params=eff.model_params(model_id),
                    prompt=prompt, custom_prompt=bool(body.prompt) or eff.custom_prompt, text_mode=text_mode,
                    word=word, text_style=style, text_corner=corner, font=eff.font,
                ))
        s.add_all(rows)
        s.commit()
        ids = [r.id for r in rows]
        out = [thumbnail_dict(r) for r in rows]
    job = runner.start("thumbnail", video_id, ids=ids)
    return {"batch_id": batch, "job": job.model_dump(), "thumbnails": out, "word_issues": issues}


class Adjust(BaseModel):
    chosen: bool | None = None
    word: str | None = Field(default=None, max_length=40)
    text_style: str | None = Field(default=None, max_length=120)
    text_corner: Literal["top_left", "top_right", "bottom_left", "bottom_right"] | None = None
    font: Literal["bebas", "montserrat", "league_spartan", "dejavu"] | None = None


@router.patch("/thumbnails/{thumb_id}")
def adjust(thumb_id: str, body: Adjust, request: Request) -> dict:
    """Choose a thumbnail, or change the word, style, corner or font. Redrawing the word is free (no model call)."""
    with session(request.app.state.engine) as s:
        row = _thumb(s, thumb_id)
        video = _video(s, row.video_id)
        redraw = False
        for key in ("word", "text_style", "text_corner", "font"):
            value = getattr(body, key)
            if value is not None and value != getattr(row, key):
                setattr(row, key, value.strip() if isinstance(value, str) else value)
                redraw = True
        if redraw:
            if row.text_mode != "app":
                raise HTTPException(422, "The image model drew this word; generate again to change it")
            if not row.raw_path or not Path(row.raw_path).is_file():
                raise HTTPException(409, "This thumbnail has no image yet")
            inp, pkg = _inputs(s, video)
            known = {w["word"] for w in word_choices(inp, pkg)}
            if row.word and row.word not in known:
                blocked = [i for i in word_issues(inp, pkg, row.word) if i["severity"] == "block"]
                if blocked:
                    raise HTTPException(422, blocked[0]["message"])
            row.final_path = row.final_path or str(Path(row.raw_path).with_name("final.jpg"))
            Path(row.final_path).write_bytes(render_row(row, inp.channel))
            if row.review:
                row.review = dict(row.review) | {"stale": True}
        if body.chosen is not None:
            if body.chosen:
                for other in s.exec(select(Thumbnail).where(Thumbnail.video_id == row.video_id,
                                                            Thumbnail.aspect == row.aspect, Thumbnail.id != row.id)):
                    if other.chosen:
                        other.chosen = False
                        s.add(other)
            row.chosen = body.chosen
        s.add(row)
        s.commit()
        out = thumbnail_dict(row)
    request.app.state.bus.publish(row.video_id, "thumbnail.updated", out)
    return out


@router.post("/thumbnails/{thumb_id}/review", status_code=202)
async def review_again(thumb_id: str, request: Request) -> dict:
    runner = _runner(request)
    if not runner.deps.can_research():
        raise HTTPException(409, "Set ANTHROPIC_API_KEY in .env to review thumbnails")
    with session(request.app.state.engine) as s:
        row = _thumb(s, thumb_id)
        if row.status != "done" or not row.final_path:
            raise HTTPException(409, "Only a finished thumbnail can be reviewed")
        video_id = row.video_id
    if runner.running(video_id, "thumbnail"):
        raise HTTPException(409, "Thumbnails are already being made")
    return runner.start("thumbnail", video_id, ids=[thumb_id], review_only=True).model_dump()


@router.get("/thumbnails/{thumb_id}/image")
def image(thumb_id: str, request: Request, v: Literal["final", "raw", "source"] = "final", download: bool = False):
    with session(request.app.state.engine) as s:
        row = _thumb(s, thumb_id)
        video = _video(s, row.video_id)
    if v == "source":
        if row.source_kind == "upload":
            path = Path(row.source_path)
        else:
            folder = thumbs_dir(get_settings(), row.video_id) / "sources"
            path = next(iter(sorted(folder.glob(f"{round((row.source_t or 0) * 1000)}_*.jpg"))), Path()) \
                if folder.is_dir() else Path()
    else:
        path = Path((row.final_path if v == "final" else row.raw_path) or "")
    if not path.is_file():
        raise HTTPException(404, "No image yet")
    headers = {}
    if download:
        stem = packaging.export_filename(load_channel(get_settings().config_dir)[0], video)
        stem = stem.removesuffix(".md").removesuffix("_YouTube_SEO")
        headers["Content-Disposition"] = f'attachment; filename="{stem}_thumbnail_{row.aspect.replace(":", "x")}{path.suffix}"'
    return FileResponse(path, headers=headers)


@router.delete("/thumbnails/{thumb_id}", status_code=204)
def delete(thumb_id: str, request: Request) -> None:
    with session(request.app.state.engine) as s:
        row = _thumb(s, thumb_id)
        if row.status in ("queued", "running"):
            raise HTTPException(409, "Wait until it finishes")
        for p in (row.raw_path, row.final_path):
            if p and Path(p).is_file():
                Path(p).unlink()
        s.delete(row)
        s.commit()


# ---- Advanced settings --------------------------------------------------------------


def _settings_view(s: Session, request: Request) -> dict:
    eff = _effective(s)
    deps = _runner(request).deps
    return eff.view() | {"keys": {"higgsfield": deps.image_client() is not None, "anthropic": deps.can_research()}}


@router.get("/settings/thumbnails")
def get_thumbnail_settings(request: Request) -> dict:
    with session(request.app.state.engine) as s:
        return _settings_view(s, request)


@router.put("/settings/thumbnails")
def put_thumbnail_settings(body: tn.Overrides, request: Request) -> dict:
    with session(request.app.state.engine) as s:
        eff = _effective(s)
        problems = tn.validate_overrides(eff.cfg, body)
        if problems:
            raise HTTPException(422, "; ".join(problems))
        row = s.get(AppSetting, tn.SETTINGS_KEY) or AppSetting(key=tn.SETTINGS_KEY)
        row.value, row.updated_at = body.model_dump(exclude_none=True), utc_now()
        s.add(row)
        s.commit()
        return _settings_view(s, request)


@router.delete("/settings/thumbnails")
def reset_thumbnail_settings(request: Request) -> dict:
    with session(request.app.state.engine) as s:
        row = s.get(AppSetting, tn.SETTINGS_KEY)
        if row is not None:
            s.delete(row)
            s.commit()
        return _settings_view(s, request)


class EstimateBody(BaseModel):
    models: list[str] | None = None
    aspects: list[Literal["16:9", "9:16"]] | None = None


@router.post("/settings/thumbnails/estimate")
async def estimate(body: EstimateBody, request: Request) -> dict:
    """Higgsfield's price quote per model and aspect, before anything is generated (no charge)."""
    client = _runner(request).deps.image_client()
    if client is None:
        raise HTTPException(409, "Set HIGGSFIELD_API_KEY in .env")
    with session(request.app.state.engine) as s:
        eff = _effective(s)
    out = []
    for model_id in body.models or [eff.model]:
        model = eff.cfg.models.get(model_id)
        if model is None:
            raise HTTPException(422, f"Unknown model `{model_id}`")
        for aspect in body.aspects or eff.aspects:
            req = tn.request_body(model, eff.model_params(model_id), "A thumbnail.",
                                  "https://example.com/source.jpg", aspect, eff.text_mode)
            try:
                usd = await client.estimate(model.path, req)
            except Exception as exc:  # noqa: BLE001 - a quote failure is shown, not raised
                out.append({"model": model_id, "aspect": aspect, "usd": None, "error": str(exc)})
                continue
            out.append({"model": model_id, "aspect": aspect, "usd": usd})
    return {"estimates": out}
