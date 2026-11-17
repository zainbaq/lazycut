"""Packages: generate, read with stale state, edit, dismiss warnings, regenerate, export (BUILD_SPEC 7.8, 7.9)."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.db import session
from app.models import Clip, Package, Video
from app.services import packaging, short_packaging
from app.services.jobs import JobRunner
from app.services.presets import load_channel, load_presets
from app.settings import get_settings

router = APIRouter()


def _runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _video(s: Session, video_id: str) -> Video:
    video = s.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "No such video")
    return video


def _inputs(s: Session, video: Video) -> packaging.Inputs:
    settings = get_settings()
    presets, _ = load_presets(settings.config_dir)
    channel, _ = load_channel(settings.config_dir)
    return packaging.gather(s, video, presets.get(video.preset_id) or presets["general"], channel)


def _package(s: Session, package_id: str) -> Package:
    pkg = s.get(Package, package_id)
    if pkg is None:
        raise HTTPException(404, "No such package")
    return pkg


@router.get("/videos/{video_id}/packages")
def list_packages(video_id: str, request: Request) -> dict:
    runner = _runner(request)
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        inp = _inputs(s, video)
        s.commit()
        current = packaging.inputs_hash(inp)
        rows = s.exec(select(Package).where(Package.video_id == video_id).order_by(col(Package.created_at))).all()
        changed = [pkg for pkg in rows if pkg.clip_id is None and packaging.refresh_from_library(inp, pkg)]
        if changed:
            s.add_all(changed)
            s.commit()
        missing = packaging.missing_required(inp.preset, inp.fact_rows)
        clips = {c.id: c for c in s.exec(select(Clip).where(Clip.video_id == video_id)).all()}

        def view(pkg: Package) -> dict:
            # A clip's package also goes stale when the clip is trimmed.
            clip = clips.get(pkg.clip_id) if pkg.clip_id else None
            return packaging.package_dict(pkg, short_packaging.short_hash(inp, clip) if clip else current)

        return {
            "can_write": runner.deps.can_research(),
            "missing_facts": missing,
            "can_generate": runner.deps.can_research() and not missing,
            "running": runner.running(video_id, "package") is not None,
            "running_short": runner.running(video_id, "clip_package") is not None,
            "packages": [view(p) for p in rows],
        }


class Generate(BaseModel):
    platforms: list[Literal["youtube", "shorts", "reels", "tiktok"]] = ["youtube"]
    clip_id: str | None = None      # the clip the short-form platforms are written for


def _start(request: Request, video_id: str, **options: Any) -> dict:
    runner = _runner(request)
    if not runner.deps.can_research():
        raise HTTPException(409, "Set ANTHROPIC_API_KEY in .env to write packages")
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        inp = _inputs(s, video)
        s.commit()
    missing = packaging.missing_required(inp.preset, inp.fact_rows)
    if missing:
        raise HTTPException(409, f"Confirm {', '.join(missing)} before generating the package")
    if runner.running(video_id, "package"):
        raise HTTPException(409, "A package is already being written")
    return runner.start("package", video_id, **options).model_dump()


@router.post("/videos/{video_id}/packages", status_code=202)
async def generate(video_id: str, request: Request, body: Generate | None = None) -> dict:
    platforms = body.platforms if body else ["youtube"]
    short = [p for p in dict.fromkeys(platforms) if p != "youtube"]
    if not short:
        return _start(request, video_id)
    # Short-form packages belong to a clip; one writer call covers every platform asked for.
    if not body or not body.clip_id:
        raise HTTPException(422, "Shorts, Reels and TikTok packages are written for a clip: send its clip_id")
    with session(request.app.state.engine) as s:
        clip = s.get(Clip, body.clip_id)
        if clip is None or clip.video_id != video_id:
            raise HTTPException(404, "No such clip in this video")
    return _start_short(request, video_id, clip_id=body.clip_id, platforms=short)


def _start_short(request: Request, video_id: str, **options: Any) -> dict:
    runner = _runner(request)
    if not runner.deps.can_research():
        raise HTTPException(409, "Set ANTHROPIC_API_KEY in .env to write packages")
    with session(request.app.state.engine) as s:
        inp = _inputs(s, _video(s, video_id))
        s.commit()
    missing = packaging.missing_required(inp.preset, inp.fact_rows)
    if missing:
        raise HTTPException(409, f"Confirm {', '.join(missing)} before generating the package")
    if runner.running(video_id, "clip_package"):
        raise HTTPException(409, "A short-form package is already being written")
    return runner.start("clip_package", video_id, **options).model_dump()


class Regenerate(BaseModel):
    field: str | None = None
    all: bool = False
    replace_edits: bool = False


@router.post("/packages/{package_id}/regenerate", status_code=202)
async def regenerate(package_id: str, body: Regenerate, request: Request) -> dict:
    with session(request.app.state.engine) as s:
        pkg = _package(s, package_id)
    editable = short_packaging.EDITABLE[pkg.platform] if pkg.clip_id else packaging.EDITABLE
    if body.field is not None and body.field not in editable:
        raise HTTPException(422, f"`{body.field}` cannot be regenerated on its own")
    if body.field is None and not body.all:
        raise HTTPException(422, "Send a field, or all: true")
    options = {"field": body.field} if body.field else {"replace_edits": body.replace_edits}
    if pkg.clip_id:
        return _start_short(request, pkg.video_id, clip_id=pkg.clip_id, platforms=[pkg.platform], **options)
    return _start(request, pkg.video_id, **options)


class Edit(BaseModel):
    field: str | None = None
    value: Any = None
    dismiss: str | None = None     # a warning's key, e.g. "tags_count:tags"
    undismiss: str | None = None


def _clean(field: str, value: Any) -> Any:
    if field in ("tags", "hashtags"):
        if isinstance(value, str):
            value = [v for v in (value.split(",") if field == "tags" else value.split()) if v.strip()]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise HTTPException(422, f"`{field}` takes a list of strings")
        return [v.strip() for v in value if v.strip()]
    if not isinstance(value, str):
        raise HTTPException(422, f"`{field}` takes text")
    return value.strip()


@router.patch("/packages/{package_id}")
def edit_package(package_id: str, body: Edit, request: Request) -> dict:
    with session(request.app.state.engine) as s:
        pkg = _package(s, package_id)
        video = _video(s, pkg.video_id)
        inp = _inputs(s, video)
        fields = dict(pkg.fields or {})
        results = [dict(r) for r in pkg.rule_results or []]
        if body.dismiss or body.undismiss:
            key = body.dismiss or body.undismiss
            target = next((r for r in results if r["key"] == key), None)
            if target is None or target["severity"] != "warn":
                raise HTTPException(422, "Only a current warning can be dismissed")
            target["dismissed"] = bool(body.dismiss)
        clip = s.get(Clip, pkg.clip_id) if pkg.clip_id else None
        if pkg.clip_id and clip is None:
            raise HTTPException(404, "The clip of this package is gone")
        editable = short_packaging.EDITABLE[pkg.platform] if clip else packaging.EDITABLE
        if body.field is not None:
            if body.field not in editable:
                raise HTTPException(422, f"`{body.field}` cannot be edited")
            apply = short_packaging.apply_edit if clip else packaging.apply_edit
            fields, pkg.edited_fields = apply(fields, list(pkg.edited_fields or []), body.field, _clean(body.field, body.value))
        if clip:
            fields, results = short_packaging.run_rules(inp, clip, pkg.platform, fields, results)
            current = short_packaging.short_hash(inp, clip)
        else:
            fields, results = packaging.run_rules(inp, fields, results)
            current = packaging.inputs_hash(inp)
        pkg.fields, pkg.rule_results = fields, results
        s.add(pkg)
        s.commit()
        return packaging.package_dict(pkg, current)


@router.get("/videos/{video_id}/export.md")
def export_markdown(video_id: str, request: Request) -> Response:
    with session(request.app.state.engine) as s:
        video = _video(s, video_id)
        rows = s.exec(select(Package).where(Package.video_id == video_id).order_by(col(Package.created_at))).all()
        if not rows:
            raise HTTPException(404, "Generate the package first")
    channel, _ = load_channel(get_settings().config_dir)
    name = packaging.export_filename(channel, video)
    long_form = next((p for p in rows if p.clip_id is None), None)
    parts = [packaging.markdown(video, long_form)] if long_form else [f"# {video.title}\n"]
    # Each clip's short-form packages follow, in the order the clips sit in the video.
    short = sorted((p for p in rows if p.clip_id), key=lambda p: ((p.fields or {}).get("clip") or {}).get("t_start", 0))
    parts += [short_packaging.markdown(p) for p in short]
    return Response(
        "\n".join(parts), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
