"""SQLite tables (BUILD_SPEC section 4).

String UUID ids, UTC ISO timestamps, JSON columns for nested data. Tables that later
phases fill (clips, packages, research, library) are declared now so the schema
does not need a migration when those phases land.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(default: list | dict | None = None) -> Any:
    """A JSON column. Each call makes its own Column, as SQLAlchemy requires."""
    if default is None:
        return Field(default=None, sa_column=Column(JSON, nullable=True))
    return Field(default_factory=type(default), sa_column=Column(JSON, nullable=False))


class Video(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    title: str
    subject: str = ""
    topic: str = ""
    topic_terms: str = ""
    kind: str = "long"  # long | clip
    preset_id: str = "general"
    status: str = "importing"  # importing | ready | error
    import_source: str = "local"
    import_ref: str = ""
    source_path: str | None = None
    proxy_path: str | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    size_bytes: int | None = None
    is_hdr: bool = False
    published_url: str | None = None
    published_at: str | None = None
    created_at: str = Field(default_factory=utc_now)


class Analysis(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True, ondelete="CASCADE")
    model: str = ""
    fps: float | None = None
    summary: str | None = None
    basics: dict | None = _json()
    raw: dict | None = _json()
    created_at: str = Field(default_factory=utc_now)


class Event(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True, ondelete="CASCADE")
    t_start: float
    t_end: float
    t_model_start: float | None = None
    t_model_end: float | None = None
    type: str
    label: str = ""
    intensity: str = "medium"
    crop_safe_9x16: bool = True
    confidence: str = "certain"
    source: str = "model"  # model | user
    detected_by: list = _json([])
    verified: bool = False
    hidden: bool = False
    edited: bool = False  # the user moved, retyped or relabelled a model event (kept on re-analysis, 7.12)


class Segment(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True, ondelete="CASCADE")
    kind: str  # dead_time | peak | section
    t_start: float
    t_end: float
    label: str = ""


class IntensitySample(SQLModel, table=True):
    __tablename__ = "intensity_sample"

    video_id: str = Field(foreign_key="video.id", primary_key=True, ondelete="CASCADE")
    t: float = Field(primary_key=True)
    score: float


class Fact(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True, ondelete="CASCADE")
    key: str
    label: str = ""
    value: Any = _json()
    proposed_value: Any = _json()
    confirmed: bool = False
    evidence_ts: list = _json([])
    evidence_event_ids: list = _json([])
    confirmed_at: str | None = None


class Clip(SQLModel, table=True):
    """One continuous range of a video (D9): start and end only, never a cut in the middle."""

    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True, ondelete="CASCADE")
    name: str = ""
    t_start: float
    t_end: float
    prompt: str | None = None
    reason: str | None = None
    payoff_t: float | None = None
    dead_time_s: float | None = None
    crop_warning: bool = False
    status: str = "candidate"  # candidate (a finder proposal nobody touched) | selected | exported
    platform: str | None = None  # shorts | reels | tiktok: the platform it was found or trimmed for
    source: str = "user"  # finder | user | import
    # The range it was created with, for Reset.
    orig_start: float | None = None
    orig_end: float | None = None
    created_at: str = Field(default_factory=utc_now)


class ClipExport(SQLModel, table=True):
    __tablename__ = "clip_export"

    id: str = Field(default_factory=new_id, primary_key=True)
    clip_id: str = Field(foreign_key="clip.id", index=True, ondelete="CASCADE")
    crop: str = "none"
    mode: str = "accurate"
    path: str = ""
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    # The range asked for, and what the file really holds (lossless cuts snap to keyframes, 7.6).
    t_start: float | None = None
    t_end: float | None = None
    real_start: float | None = None
    real_end: float | None = None
    duration_s: float | None = None
    size_bytes: int | None = None
    created_at: str = Field(default_factory=utc_now)


class Research(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    subject_key: str = Field(index=True)
    topic_key: str = ""
    kind: str = "subject"  # subject | competitors
    payload: dict = _json({})
    overrides: dict = _json({})
    sources: list = _json([])
    created_at: str = Field(default_factory=utc_now)


class Package(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True, ondelete="CASCADE")
    clip_id: str | None = Field(default=None, foreign_key="clip.id", ondelete="CASCADE")
    platform: str
    fields: dict = _json({})
    alternates: dict = _json({})
    edited_fields: list = _json([])
    rule_results: list = _json([])
    inputs_hash: str = ""
    version: int = 1
    created_at: str = Field(default_factory=utc_now)


class Job(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str | None = Field(default=None, foreign_key="video.id", index=True, ondelete="CASCADE")
    kind: str
    status: str = "queued"  # queued | running | done | error
    progress: float = 0.0
    message: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class LibraryItem(SQLModel, table=True):
    __tablename__ = "library_item"

    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str | None = Field(default=None, foreign_key="video.id", ondelete="SET NULL")
    title: str
    subject: str = ""
    topic: str = ""
    angle: str = ""
    hook: str = ""
    url: str = ""
    playlist: str = ""
    published_at: str | None = None
    # Phase 3, imported from the channel (schema v5). A Short is kept for the record but never
    # counts as an end-screen target or a repeat of a subject.
    youtube_id: str | None = Field(default=None, index=True)
    kind: str = "long"  # long | short
    duration_s: float | None = None
    views: int | None = None
    # How topic and subject were filled: "playlist" / "repeated" (read from the title), "you"
    # (typed or edited by the owner), or "" (not read). A re-import never overwrites "you".
    read_by: str = ""


class Thumbnail(SQLModel, table=True):
    """One generated thumbnail (7.13): its source, the request sent to the image model, the result and its review."""

    id: str = Field(default_factory=new_id, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True, ondelete="CASCADE")
    batch_id: str = ""               # thumbnails made by one Generate click (several models or aspects)
    source_kind: str = "frame"       # frame | upload
    source_t: float | None = None
    source_path: str = ""
    aspect: str = "16:9"
    model: str = ""                  # the id in config/thumbnails.yaml
    params: dict = _json({})
    prompt: str = ""
    custom_prompt: bool = False
    text_mode: str = "app"           # app | model
    word: str = ""
    text_style: str = ""
    text_corner: str = "top_right"
    font: str = "bebas"
    status: str = "queued"           # queued | running | done | failed | nsfw
    request_id: str | None = None
    raw_path: str | None = None      # the image as the model returned it
    final_path: str | None = None    # sized for the platform, with the word drawn when text_mode is app
    review: dict | None = _json()
    cost_usd: float | None = None
    chosen: bool = False
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)


class AppSetting(SQLModel, table=True):
    """Settings the app's own pages change (Advanced settings), layered over the YAML defaults."""

    __tablename__ = "app_setting"

    key: str = Field(primary_key=True)
    value: dict = _json({})
    updated_at: str = Field(default_factory=utc_now)


class LLMCall(SQLModel, table=True):
    __tablename__ = "llm_call"

    id: str = Field(default_factory=new_id, primary_key=True)
    job_id: str | None = Field(default=None, foreign_key="job.id", ondelete="SET NULL")
    provider: str
    model: str = ""
    purpose: str = ""
    prompt: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    status: str = "ok"
    created_at: str = Field(default_factory=utc_now)
