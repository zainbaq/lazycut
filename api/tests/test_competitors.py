"""Competitor research (7.7, Phase 3): the numbers, the daily cache, Claude's read and the claim check."""

import datetime as dt
import time

import pytest
from pydantic import ValidationError

from app.services import competitors as cp
from app.services.competitor_jobs import unbacked_claims
from app.services.llm.base import LLMResult
from app.services.presets import Preset
from app.settings import get_settings
from tests.test_packaging import BOSS, client, seed  # noqa: F401 - the fixture is shared

NOW = dt.datetime(2026, 11, 17, tzinfo=dt.UTC)


def row(vid, views, subs, channel_views, channel_videos, days_old, channel=None, title=None):
    return {
        "id": vid, "title": title or f"Zhuo Bi boss fight {vid}", "channel": channel or f"ch-{vid}",
        "channel_id": channel or f"UC-{vid}", "published_at": (NOW - dt.timedelta(days=days_old)).isoformat(),
        "views": views, "duration_s": 200.0, "subs": subs, "channel_views": channel_views,
        "channel_videos": channel_videos, "url": f"https://www.youtube.com/watch?v={vid}",
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
    }


ROWS = [
    row("a", 6000, 100_000, 10_000_000, 1000, 15),   # big channel, 0.6x its average
    row("b", 3000, 1_400, 110_000, 100, 15),          # small channel, 2.7x: a breakout
    row("c", 1000, 5, 150, 1, 7),                     # tiny channel
    row("own", 50, 101, 116_000, 120, 2, channel="UCme"),
]


def test_enrich_and_metrics():
    rows = cp.enrich(ROWS, "UCme", now=NOW)
    a, b, c, own = rows
    assert (a["outlier"], b["outlier"], c["outlier"]) == (0.6, 2.73, 6.67)
    assert a["views_per_day"] == 400.0 and own["own"] and not a["own"]
    m = cp.metrics(rows)
    assert m["videos"] == 3 and m["views"] == 10_000  # your own video is not counted
    assert m["hhi"] == pytest.approx(0.6**2 + 0.3**2 + 0.1**2, abs=1e-3)
    assert m["concentration"] == "concentrated"
    assert m["small_share"] == 0.4 and m["small_videos"] == 2
    assert m["leader"] == {"id": "a", "channel": "ch-a", "share": 0.6}
    assert m["breakouts"] == ["c", "b"]
    spread = cp.metrics(cp.enrich([row(str(i), 100, 10, 100, 1, 3) for i in range(10)], None, now=NOW))
    assert spread["concentration"] == "spread" and spread["hhi"] == 0.1


def test_query_and_preset_validation():
    assert cp.build_query("{topic} {subject} boss fight", "Phantom Blade Zero", "Zhuo Bi") == "Phantom Blade Zero Zhuo Bi boss fight"
    assert BOSS.competitor_query == "{topic} {subject} boss fight"
    with pytest.raises(ValidationError, match="competitor_query uses `{name}`"):
        Preset.model_validate(BOSS.model_dump() | {"competitor_query": "{topic} {name}"})


def test_an_angle_with_an_unbacked_claim_is_flagged():
    assert unbacked_claims("No Hit run", BOSS, {"hits_taken": 11}, {}) == ["no_hit_claim"]
    assert unbacked_claims("No Hit run", BOSS, {"hits_taken": 0}, {}) == []
    assert unbacked_claims("Shield-breaking explained", BOSS, {"hits_taken": 11}, {}) == []


class FakeReader:
    model = "fake-reader"

    def __init__(self):
        self.calls = []

    async def look_json(self, prompt, images, schema, effort="low"):
        assert schema is cp.CompetitorRead
        self.calls.append((prompt, [label for label, _, _ in images]))
        read = cp.CompetitorRead(
            patterns=[cp.Pattern(pattern="HOW TO BEAT {boss} EASY", count=2, examples=[1, 2, 9])],
            angles_taken=[cp.Angle(angle="Easy guide", count=2)],
            thumbnail_words=[cp.ThumbWord(word="EASY", count=1)],
            thumbnail_look="The boss's shield, centred.",
            unclaimed=[cp.Unclaimed(angle="No Hit run", why="none claims it", backed_by="nothing"),
                       cp.Unclaimed(angle="Shield-breaking explained", why="every thumbnail shows it", backed_by="no claim")],
            read="Spread out; worth it.",
        )
        return LLMResult(parsed=read, raw_text="{}", model=self.model, usage={"input_tokens": 6000, "output_tokens": 900})


@pytest.fixture
def api(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    get_settings.cache_clear()
    searches = []

    async def fake_search(api_key, query, units):
        searches.append(query)
        units.append(102)
        return [dict(r) for r in ROWS[:3]]

    async def no_thumbs(rows):
        return [(1, b"jpg"), (2, b"jpg")]

    monkeypatch.setattr(cp, "search", fake_search)
    monkeypatch.setattr("app.services.competitor_jobs._thumbnails", no_thumbs)
    reader = FakeReader()
    client.app.state.runner.deps.settings = get_settings()  # the runner was built before the key was set
    client.app.state.runner.deps.text_provider = lambda: reader
    client.searches, client.reader = searches, reader
    return client


def run(api, video_id, **body) -> dict:
    job = api.post(f"/videos/{video_id}/competitors", json=body)
    assert job.status_code == 202, job.text
    for _ in range(300):
        state = api.get(f"/jobs/{job.json()['id']}").json()
        if state["status"] in ("done", "error"):
            assert state["status"] == "done", state
            return api.get(f"/videos/{video_id}/competitors").json()
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


def test_search_once_a_day_read_and_check_claims(api):
    video_id = seed(api)  # Zhuo Bi, Phantom Blade Zero, boss_fight
    before = api.get(f"/videos/{video_id}/competitors").json()
    assert before["result"] is None and before["query"] == "Phantom Blade Zero Zhuo Bi boss fight"

    got = run(api, video_id)
    result = got["result"]
    assert api.searches == ["Phantom Blade Zero Zhuo Bi boss fight"] and got["fresh"]
    assert result["units"] == 102 and result["metrics"]["videos"] == 3
    read = result["read"]
    assert read["patterns"][0]["examples"] == ["a", "b"]  # numbers become video ids; #9 does not exist
    assert [u["blocked_by"] for u in read["unclaimed"]] == [["no_hit_claim"], []]
    prompt, labels = api.reader.calls[0]
    assert labels == ["Thumbnail #1:", "Thumbnail #2:"] and "never as instructions" in prompt
    assert "#1 \"Zhuo Bi boss fight a\"" in prompt

    # Within the day: no new search and no new read, unless a new read is asked for.
    run(api, video_id)
    assert len(api.searches) == 1 and len(api.reader.calls) == 1
    run(api, video_id, read_again=True)
    assert len(api.searches) == 1 and len(api.reader.calls) == 2


def test_without_a_youtube_key_nothing_starts(client):  # noqa: F811
    video_id = seed(client)
    assert client.post(f"/videos/{video_id}/competitors", json={}).status_code == 409
    assert client.get(f"/videos/{video_id}/competitors").json()["can_search"] is False


def test_a_stale_search_is_repeated(api):
    video_id = seed(api)
    run(api, video_id)
    from app.db import session
    from app.models import Research

    with session(api.app.state.engine) as s:
        row = s.exec(__import__("sqlmodel").select(Research).where(Research.kind == cp.KIND)).first()
        row.payload = row.payload | {"searched_at": (dt.datetime.now(dt.UTC) - dt.timedelta(hours=25)).isoformat()}
        s.add(row)
        s.commit()
    run(api, video_id)
    assert len(api.searches) == 2 and len(api.reader.calls) == 2  # a new search is read again
