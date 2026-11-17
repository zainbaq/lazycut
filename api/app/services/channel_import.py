"""Past uploads imported from the channel (Phase 3, D22): uploads, Shorts and playlists.

One `channel_import` job reads the channel through the YouTube Data API (about 20 quota units for
120 uploads; no money), tells Shorts from long videos, reads each long title into topic, subject and
angle (title_reader, no model call) and merges the result into `library_item`:

- an upload already imported, or a typed / published entry whose link points at it, is updated in
  place; its title, views and length follow YouTube, but a topic, subject or angle the owner typed
  (`read_by == "you"`) is never overwritten;
- nothing is deleted: an entry whose video left the channel stays until the owner removes it.

The summary (counts, the channel's playlists and which of them `channel.yaml` lacks) is kept in
`app_setting` under `channel_sync`.
"""

import re
from typing import Any

from sqlmodel import Session, select

from app.db import session
from app.models import AppSetting, LibraryItem, Video, utc_now
from app.services.jobs import JobContext
from app.services.pipeline import deps_of
from app.services.presets import ChannelProfile, load_channel, load_presets
from app.services.title_reader import TitleReader
from app.services.youtube import SHORT_MAX_S, Playlist, Upload, YouTubeClient, gather_limited

SYNC_KEY = "channel_sync"
VIDEO_ID = re.compile(r"(?:youtu\.be/|[?&]v=|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")
LIST_ID = re.compile(r"[?&]list=([A-Za-z0-9_-]+)")


def video_id_of(url: str) -> str | None:
    m = VIDEO_ID.search(url or "")
    return m.group(1) if m else None


def list_id_of(url: str) -> str | None:
    m = LIST_ID.search(url or "")
    return m.group(1) if m else None


def watch_url(video_id: str, kind: str) -> str:
    return f"https://www.youtube.com/shorts/{video_id}" if kind == "short" else f"https://www.youtube.com/watch?v={video_id}"


def last_sync(s: Session) -> dict | None:
    row = s.get(AppSetting, SYNC_KEY)
    return dict(row.value) if row and row.value else None


def config_playlists(channel: ChannelProfile | None) -> dict[str, dict]:
    """channel.yaml's playlists by their list id."""
    out: dict[str, dict] = {}
    for p in (channel.playlists if channel else []):
        lid = list_id_of(p.url)
        if lid:
            out[lid] = {"topic": p.topic, "name": p.name}
    return out


def playlist_rows(playlists: list[Playlist], channel: ChannelProfile | None) -> list[dict]:
    known = config_playlists(channel)
    return [{"id": p.id, "title": p.title, "count": p.count, "url": p.url, "in_config": known.get(p.id)} for p in playlists]


def angle_phrases(config_dir) -> list[str]:
    """Claim phrases of every preset ("No Hit", "Final Boss"): in a title they are the angle, not the subject."""
    presets, _ = load_presets(config_dir)
    return sorted({phrase for p in presets.values() for rule in p.claim_rules for phrase in rule.phrases})


def merge(s: Session, uploads: list[Upload], kinds: dict[str, str], reader: TitleReader,
          membership: dict[str, str]) -> dict[str, int]:
    """Fold the uploads into library_item. Returns the counts for the summary."""
    items = list(s.exec(select(LibraryItem)).all())
    by_youtube = {i.youtube_id: i for i in items if i.youtube_id}
    by_link = {vid: i for i in items if not i.youtube_id and (vid := video_id_of(i.url))}
    counts = {"new": 0, "updated": 0, "linked": 0, "long": 0, "shorts": 0, "unread": 0}
    for u in uploads:
        item = by_youtube.get(u.id)
        linked = item is None and u.id in by_link
        item = item or by_link.get(u.id)
        kind = kinds.get(u.id) or (item.kind if item and item.youtube_id else "long")
        counts["shorts" if kind == "short" else "long"] += 1
        reading = reader.read(u.title) if kind == "long" else None
        if item is None:
            item = LibraryItem(title=u.title, url=watch_url(u.id, kind))
            counts["new"] += 1
        else:
            counts["linked" if linked else "updated"] += 1
        item.youtube_id, item.kind, item.title = u.id, kind, u.title
        item.duration_s, item.views = u.duration_s, u.views
        item.url = item.url or watch_url(u.id, kind)
        item.published_at = item.published_at or u.published_at[:10]
        item.playlist = item.playlist or membership.get(u.id, "")
        if reading is not None and item.read_by != "you":
            item.topic, item.subject, item.angle, item.read_by = reading.topic, reading.subject, reading.angle, reading.by
            counts["unread"] += not reading.by
        s.add(item)
    return counts


async def run_import(client: YouTubeClient, engine, config_dir, on_progress=lambda p, m: None) -> dict:
    """Read the channel and merge it into past uploads. Returns the summary (also stored)."""
    channel_profile, _ = load_channel(config_dir)
    handle = (channel_profile.handle if channel_profile else "").strip()
    if not handle:
        raise RuntimeError("Set `handle` in config/channel.yaml (for example \"@thelazyronin\") to import the channel")

    on_progress(0.05, f"Finding {handle}")
    channel = await client.channel(handle)
    on_progress(0.15, f"Reading {channel.video_count} uploads")
    uploads = await client.uploads(channel)
    on_progress(0.45, "Reading playlists")
    playlists = await client.playlists(channel)

    with session(engine) as s:
        known_kinds = {i.youtube_id: i.kind for i in s.exec(select(LibraryItem)).all() if i.youtube_id}
        app_topics = [t for t in s.exec(select(Video.topic)).all() if t]
    # Only new uploads short enough to be a Short are checked; an imported one keeps its kind.
    to_check = [u for u in uploads if u.id not in known_kinds and u.duration_s <= SHORT_MAX_S]
    on_progress(0.6, f"Checking which of {len(to_check)} short uploads are Shorts")
    answers = await gather_limited([client.is_short(u.id) for u in to_check])
    kinds = dict(known_kinds)
    unsure = 0
    for u, answer in zip(to_check, answers, strict=True):
        if answer is None:
            unsure += 1
            answer = u.duration_s <= 60  # the check did not answer: fall back to the old one-minute rule
        kinds[u.id] = "short" if answer else "long"
    for u in uploads:
        kinds.setdefault(u.id, "long")

    known = [p.title for p in playlists] + [p.topic for p in (channel_profile.playlists if channel_profile else [])] + app_topics
    reader = TitleReader([u.title for u in uploads], known, angle_phrases(config_dir))
    membership: dict[str, str] = {}
    for p in playlists:
        for vid in p.video_ids:
            membership.setdefault(vid, p.title)

    on_progress(0.85, "Updating past uploads")
    with session(engine) as s:
        counts = merge(s, uploads, kinds, reader, membership)
        summary: dict[str, Any] = {
            "at": utc_now(),
            "channel": {"id": channel.id, "title": channel.title, "handle": channel.handle,
                        "subscribers": channel.subscribers, "video_count": channel.video_count},
            "uploads": len(uploads), **counts, "shorts_unsure": unsure, "units": client.units,
            "playlists": playlist_rows(playlists, channel_profile),
        }
        row = s.get(AppSetting, SYNC_KEY) or AppSetting(key=SYNC_KEY)
        row.value, row.updated_at = summary, utc_now()
        s.add(row)
        s.commit()
    return summary


def summary_message(summary: dict) -> str:
    parts = [f"{summary['uploads']} uploads read: {summary['long']} videos and {summary['shorts']} Shorts"]
    if summary["new"]:
        parts.append(f"{summary['new']} new")
    if summary["linked"]:
        parts.append(f"{summary['linked']} matched to your entries")
    if summary["unread"]:
        parts.append(f"{summary['unread']} titles to check by hand")
    missing = [p for p in summary["playlists"] if not p["in_config"]]
    if missing:
        parts.append(f"{len(missing)} playlists not in channel.yaml")
    return "; ".join(parts) + "."


async def channel_import_job(ctx: JobContext) -> None:
    deps = deps_of(ctx)
    client = deps.youtube_client()
    if client is None:
        raise RuntimeError("Set YOUTUBE_API_KEY in .env to import the channel")
    summary = await run_import(client, ctx.engine, deps.settings.config_dir, lambda p, m: ctx.progress(p, m))
    ctx.progress(1.0, summary_message(summary))
