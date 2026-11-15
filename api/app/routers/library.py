"""Past uploads (typed in by hand, D22) and "Mark as published" (BUILD_SPEC 7.8)."""

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import AfterValidator, BaseModel, Field
from sqlmodel import Session, col, select

from app.db import session
from app.models import LibraryItem, Package, Video, utc_now
from app.services import packaging
from app.services.presets import load_channel, load_presets
from app.settings import get_settings
from app.views import video_dict

router = APIRouter()


def _check_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a full link starting with https://")
    return value


Url = Annotated[str, AfterValidator(_check_url)]


def item_dict(item: LibraryItem) -> dict:
    return item.model_dump() | {"from_app": item.video_id is not None}


# ---- past uploads -----------------------------------------------------------------


class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    subject: str = ""
    topic: str = ""
    angle: str = ""
    hook: str = ""
    url: Url = ""
    playlist: str = ""
    published_at: str | None = None  # a date (YYYY-MM-DD) or full timestamp


class ItemEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    subject: str | None = None
    topic: str | None = None
    angle: str | None = None
    hook: str | None = None
    url: Url | None = None
    playlist: str | None = None
    published_at: str | None = None


def _item(s: Session, item_id: str) -> LibraryItem:
    item = s.get(LibraryItem, item_id)
    if item is None:
        raise HTTPException(404, "No such past upload")
    return item


@router.get("/library")
def list_library(request: Request) -> list[dict]:
    with session(request.app.state.engine) as s:
        items = s.exec(select(LibraryItem)).all()
    items = sorted(items, key=lambda i: (i.published_at or "", i.title.lower()), reverse=True)
    return [item_dict(i) for i in items]


@router.post("/library", status_code=201)
def add_item(body: ItemIn, request: Request) -> dict:
    with session(request.app.state.engine) as s:
        item = LibraryItem(**{k: v.strip() if isinstance(v, str) else v for k, v in body.model_dump().items()})
        s.add(item)
        s.commit()
        return item_dict(item)


@router.patch("/library/{item_id}")
def edit_item(item_id: str, body: ItemEdit, request: Request) -> dict:
    with session(request.app.state.engine) as s:
        item = _item(s, item_id)
        for key, value in body.model_dump(exclude_unset=True).items():
            if key == "title" and value is None:
                raise HTTPException(422, "A past upload needs a title")
            setattr(item, key, value.strip() if isinstance(value, str) else value)
        s.add(item)
        s.commit()
        return item_dict(item)


@router.delete("/library/{item_id}", status_code=204)
def delete_item(item_id: str, request: Request) -> Response:
    with session(request.app.state.engine) as s:
        s.delete(_item(s, item_id))
        s.commit()
    return Response(status_code=204)


# ---- mark as published ------------------------------------------------------------


class Publish(BaseModel):
    url: Url
    published_at: str | None = None


@router.post("/videos/{video_id}/publish")
def publish(video_id: str, body: Publish, request: Request) -> dict:
    """Set the published link and date, and add (or update) the video's past-upload entry from its package."""
    if not body.url:
        raise HTTPException(422, "Paste the video's link")
    settings = get_settings()
    presets, _ = load_presets(settings.config_dir)
    channel, _ = load_channel(settings.config_dir)
    with session(request.app.state.engine) as s:
        video = s.get(Video, video_id)
        if video is None:
            raise HTTPException(404, "No such video")
        preset = presets.get(video.preset_id) or presets["general"]
        pkg = s.exec(select(Package).where(Package.video_id == video_id, Package.platform == "youtube")
                     .order_by(col(Package.created_at).desc())).first()
        fields = (pkg.fields or {}) if pkg else {}
        inp = packaging.gather(s, video, preset, channel)
        hooks = {h["id"]: h["text"] for h in packaging.eligible_hooks(inp)}
        playlist = packaging.playlist_for(channel, video.topic)

        video.published_url = body.url
        video.published_at = (body.published_at or "").strip() or utc_now()
        item = s.exec(select(LibraryItem).where(LibraryItem.video_id == video_id)).first() or LibraryItem(
            video_id=video_id, title="")
        item.title = fields.get("title") or video.title
        item.subject, item.topic = video.subject, video.topic
        item.hook = hooks.get(fields.get("title_hook_id") or "", "")
        item.angle = item.angle or item.hook
        item.url, item.published_at = body.url, video.published_at
        item.playlist = (playlist or {}).get("name", "")
        s.add_all([video, item])
        s.commit()
        return video_dict(s, video, presets) | {"library_item": item_dict(item)}


@router.delete("/videos/{video_id}/publish")
def unpublish(video_id: str, request: Request) -> dict:
    """Undo "Mark as published": clears the link and removes the past-upload entry it created."""
    presets, _ = load_presets(get_settings().config_dir)
    with session(request.app.state.engine) as s:
        video = s.get(Video, video_id)
        if video is None:
            raise HTTPException(404, "No such video")
        video.published_url = video.published_at = None
        for item in s.exec(select(LibraryItem).where(LibraryItem.video_id == video_id)).all():
            s.delete(item)
        s.add(video)
        s.commit()
        return video_dict(s, video, presets)
