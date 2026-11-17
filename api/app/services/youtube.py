"""YouTube Data API v3, read-only with an API key (public data only).

Free daily quota (10,000 units by default). Every call here costs 1 unit except `search.list`
(100), which only competitor research uses. The key never appears in logs or error messages.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx

API = "https://www.googleapis.com/youtube/v3"
SHORTS_CHECK = "https://www.youtube.com/shorts/{id}"
DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")
SHORT_MAX_S = 180.0  # nothing longer can be a Short


class YouTubeError(RuntimeError):
    pass


def seconds(iso: str) -> float:
    """ISO 8601 duration ("PT3M24S") to seconds."""
    m = DURATION.fullmatch(iso or "")
    if not m:
        return 0.0
    d, h, mins, s = m.groups()
    return int(d or 0) * 86400 + int(h or 0) * 3600 + int(mins or 0) * 60 + float(s or 0)


@dataclass
class Upload:
    id: str
    title: str
    published_at: str
    duration_s: float
    views: int | None
    description: str = ""


@dataclass
class Playlist:
    id: str
    title: str
    count: int
    video_ids: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self.id}"


@dataclass
class Channel:
    id: str
    title: str
    handle: str
    uploads_playlist: str
    subscribers: int | None
    video_count: int


class YouTubeClient(Protocol):
    units: int

    async def channel(self, handle: str) -> Channel: ...
    async def uploads(self, channel: Channel) -> list[Upload]: ...
    async def playlists(self, channel: Channel) -> list[Playlist]: ...
    async def is_short(self, video_id: str) -> bool | None: ...


class YouTubeData:
    def __init__(self, api_key: str, timeout_s: float = 20.0):
        self._key = api_key
        self._timeout = timeout_s
        self.units = 0  # quota units spent by this client

    async def _get(self, client: httpx.AsyncClient, path: str, **params) -> dict:
        self.units += 1
        try:
            res = await client.get(f"{API}/{path}", params=params | {"key": self._key})
        except httpx.HTTPError as exc:
            raise YouTubeError(f"Could not reach the YouTube Data API ({type(exc).__name__})") from None
        if res.status_code == 200:
            return res.json()
        reason, message = "", ""
        try:
            err = res.json().get("error") or {}
            reason = ((err.get("errors") or [{}])[0]).get("reason", "")
            message = err.get("message", "")
        except ValueError:
            pass
        message = message.replace(self._key, "***") if self._key else message
        if reason in ("quotaExceeded", "dailyLimitExceeded"):
            raise YouTubeError("The YouTube Data API's daily quota is used up; it resets at midnight Pacific time")
        if res.status_code in (400, 403) and reason in ("keyInvalid", "accessNotConfigured", "forbidden", "badRequest"):
            raise YouTubeError(f"YouTube refused the API key ({reason}): check YOUTUBE_API_KEY and that "
                               "YouTube Data API v3 is enabled for it")
        raise YouTubeError(f"YouTube Data API error {res.status_code}: {message or reason or 'no message'}")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout)

    async def channel(self, handle: str) -> Channel:
        handle = handle if handle.startswith("@") else f"@{handle}"
        async with self._client() as c:
            data = await self._get(c, "channels", part="snippet,contentDetails,statistics", forHandle=handle)
        items = data.get("items") or []
        if not items:
            raise YouTubeError(f"No YouTube channel has the handle {handle}")
        it = items[0]
        stats = it.get("statistics") or {}
        return Channel(
            id=it["id"], title=it["snippet"]["title"], handle=handle,
            uploads_playlist=it["contentDetails"]["relatedPlaylists"]["uploads"],
            subscribers=None if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount") or 0),
            video_count=int(stats.get("videoCount") or 0),
        )

    async def _playlist_ids(self, c: httpx.AsyncClient, playlist_id: str) -> list[str]:
        ids: list[str] = []
        token = None
        while True:
            page = await self._get(c, "playlistItems", part="contentDetails", playlistId=playlist_id, maxResults=50,
                                   **({"pageToken": token} if token else {}))
            ids += [i["contentDetails"]["videoId"] for i in page.get("items") or []]
            token = page.get("nextPageToken")
            if not token:
                return ids

    async def uploads(self, channel: Channel) -> list[Upload]:
        async with self._client() as c:
            ids = await self._playlist_ids(c, channel.uploads_playlist)
            out: list[Upload] = []
            for i in range(0, len(ids), 50):
                page = await self._get(c, "videos", part="snippet,contentDetails,statistics", id=",".join(ids[i:i + 50]))
                for v in page.get("items") or []:
                    stats = v.get("statistics") or {}
                    out.append(Upload(
                        id=v["id"], title=v["snippet"]["title"], published_at=v["snippet"]["publishedAt"],
                        duration_s=seconds(v["contentDetails"]["duration"]),
                        views=int(stats["viewCount"]) if "viewCount" in stats else None,
                        description=v["snippet"].get("description", ""),
                    ))
        return out

    async def playlists(self, channel: Channel) -> list[Playlist]:
        async with self._client() as c:
            found: list[Playlist] = []
            token = None
            while True:
                page = await self._get(c, "playlists", part="snippet,contentDetails", channelId=channel.id, maxResults=50,
                                       **({"pageToken": token} if token else {}))
                found += [Playlist(p["id"], p["snippet"]["title"], int(p["contentDetails"]["itemCount"]))
                          for p in page.get("items") or []]
                token = page.get("nextPageToken")
                if not token:
                    break
            for p in found:
                p.video_ids = await self._playlist_ids(c, p.id)
        return found

    async def is_short(self, video_id: str) -> bool | None:
        """Whether YouTube serves the video as a Short: /shorts/<id> answers 200 for a Short and
        redirects for anything else. Unofficial and free (no key, no quota); None when it cannot tell."""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"}) as c:
                res = await c.head(SHORTS_CHECK.format(id=video_id))
        except httpx.HTTPError:
            return None
        if res.status_code == 200:
            return True
        if res.status_code in (301, 302, 303, 307, 308):
            return False
        return None


async def gather_limited(coros, limit: int = 4):
    """Run coroutines a few at a time, so a page of checks never floods one host."""
    sem = asyncio.Semaphore(limit)

    async def one(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(one(c) for c in coros))
