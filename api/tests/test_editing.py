"""The eye test through the API: editing events, undo by restore, facts that follow the events, confirmation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import session
from app.models import Event, Fact, Video
from app.services.pipeline import keeps, persist_analysis
from app.services.presets import load_presets

CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "data").mkdir()
    for key, value in {
        "INBOX_DIR": tmp_path / "inbox", "DATA_DIR": tmp_path / "data", "CONFIG_DIR": CONFIG,
        "DB_PATH": tmp_path / "db" / "app.db", "GEMINI_API_KEY": "",
    }.items():
        monkeypatch.setenv(key, str(value))
    from app import main
    from app.settings import get_settings

    get_settings.cache_clear()
    with TestClient(main.app) as test_client:
        yield test_client
    get_settings.cache_clear()


def seed(client: TestClient) -> tuple[str, list[str]]:
    """A ready boss-fight video with two model hits and one model counter."""
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", preset_id="boss_fight", status="ready", duration_s=60.0, fps=30.0)
        s.add(video)
        s.flush()
        events = [
            Event(video_id=video.id, t_start=t, t_end=t + 1, t_model_start=t, t_model_end=t + 1, type=kind,
                  source="model", detected_by=[{"detector": "gemini", "t_start": t, "label": "", "evidence": {}}])
            for t, kind in [(10.0, "hit_taken"), (20.0, "hit_taken"), (30.0, "counter")]
        ]
        s.add_all(events)
        s.commit()
        return video.id, [e.id for e in events]


def facts_of(client: TestClient, video_id: str) -> dict[str, dict]:
    return {f["key"]: f for f in client.get(f"/videos/{video_id}/facts").json()}


def test_facts_exist_before_any_analysis_and_follow_the_events(client):
    video_id, (hit1, hit2, _counter) = seed(client)
    facts = facts_of(client, video_id)
    assert [f["key"] for f in client.get(f"/videos/{video_id}/facts").json()][:3] == [
        "hits_taken", "counter_count", "encounter",
    ]
    assert facts["hits_taken"]["proposed_value"] == 2 and facts["hits_taken"]["effective_value"] == 2
    assert (facts["hits_taken"]["event_count"], facts["hits_taken"]["verified_count"]) == (2, 0)
    assert facts["hits_taken"]["evidence_event_ids"] == [hit1, hit2]
    assert facts["encounter"]["effective_value"] is None and facts["encounter"]["event_count"] is None

    assert client.patch(f"/events/{hit2}", json={"hidden": True}).json()["hidden"] is True
    assert client.patch(f"/events/{hit1}", json={"verified": True}).status_code == 200
    added = client.post(f"/videos/{video_id}/events", json={"t_start": 40.0, "type": "hit_taken"})
    assert added.status_code == 201
    assert added.json()["source"] == "user" and added.json()["t_end"] == 40.5

    facts = facts_of(client, video_id)["hits_taken"]
    assert (facts["proposed_value"], facts["event_count"], facts["verified_count"]) == (2, 2, 1)
    client.delete(f"/events/{added.json()['id']}")
    assert facts_of(client, video_id)["hits_taken"]["proposed_value"] == 1


def test_moving_and_retyping_marks_model_events_edited_and_reanalysis_keeps_them(client):
    video_id, (hit1, hit2, counter) = seed(client)
    moved = client.patch(f"/events/{hit1}", json={"t_start": 11.5}).json()
    assert (moved["t_start"], moved["t_end"], moved["t_model_start"], moved["edited"]) == (11.5, 12.5, 10.0, True)
    retyped = client.patch(f"/events/{counter}", json={"type": "parry"}).json()
    assert retyped["type"] == "parry" and retyped["edited"] is True
    assert client.patch(f"/events/{hit2}", json={"verified": True}).json()["edited"] is False

    assert client.patch(f"/events/{hit2}", json={"type": "nope"}).status_code == 422
    assert client.patch(f"/events/{hit2}", json={"t_start": 75.0}).status_code == 422
    assert client.patch(f"/events/{hit2}", json={"t_start": 5.0, "t_end": 4.0}).status_code == 422
    assert client.patch(f"/events/{hit2}", json={"hidden": None}).status_code == 422
    assert client.post(f"/videos/{video_id}/events", json={"t_start": 1.0, "type": "nope"}).status_code == 422
    assert client.patch("/events/missing", json={"hidden": True}).status_code == 404

    # Near the end, a move keeps the event inside the video.
    assert client.patch(f"/events/{hit2}", json={"t_start": 59.8}).json()["t_end"] == 60.0

    engine = client.app.state.engine
    preset = load_presets(CONFIG)[0]["boss_fight"]
    with session(engine) as s:
        assert {e.id for e in s.exec(select(Event)).all() if keeps(e)} == {hit1, hit2, counter}
    events = persist_analysis(engine, video_id, preset, [], None)
    assert {e.id for e in events} == {hit1, hit2, counter}
    assert persist_analysis(engine, video_id, preset, [], None, discard_user_work=True) == []


def test_a_deleted_event_comes_back_whole(client):
    video_id, (hit1, _hit2, _counter) = seed(client)
    before = next(e for e in client.get(f"/videos/{video_id}/timeline").json()["events"] if e["id"] == hit1)
    assert client.delete(f"/events/{hit1}").status_code == 204
    assert client.patch(f"/events/{hit1}", json={"hidden": True}).status_code == 404
    restored = client.post(f"/videos/{video_id}/events", json=before)
    assert restored.status_code == 201 and restored.json() == before
    assert client.post(f"/videos/{video_id}/events", json=before).status_code == 409
    assert facts_of(client, video_id)["hits_taken"]["evidence_event_ids"][0] == hit1


def test_confirming_locks_a_fact_and_warns_when_the_events_change(client):
    video_id, (_hit1, hit2, _counter) = seed(client)
    facts = facts_of(client, video_id)
    hits, encounter = facts["hits_taken"], facts["encounter"]
    assert client.get(f"/videos/{video_id}").json()["display_status"] == "needs_confirmation"

    assert client.put(f"/facts/{encounter['id']}", json={"confirmed": True}).status_code == 422  # nothing to confirm
    assert client.put(f"/facts/{hits['id']}", json={"value": -1}).status_code == 422
    assert client.put(f"/facts/{hits['id']}", json={"value": 1.5}).status_code == 422
    assert client.put(f"/facts/{hits['id']}", json={"value": True}).status_code == 422
    named = client.put(f"/facts/{encounter['id']}", json={"value": "  Gate Keeper "}).json()
    assert (named["value"], named["effective_value"], named["confirmed"]) == ("Gate Keeper", "Gate Keeper", False)
    assert client.put(f"/facts/{encounter['id']}", json={"value": ""}).json()["value"] is None

    locked = client.put(f"/facts/{hits['id']}", json={"confirmed": True}).json()
    assert (locked["value"], locked["confirmed"], locked["out_of_date"]) == (2, True, False)
    assert locked["confirmed_at"]
    assert client.get(f"/videos/{video_id}").json()["display_status"] == "ready"

    client.patch(f"/events/{hit2}", json={"hidden": True})
    hits = facts_of(client, video_id)["hits_taken"]
    assert (hits["value"], hits["event_count"], hits["out_of_date"]) == (2, 1, True)
    assert client.put(f"/facts/{hits['id']}", json={"value": 1}).json()["out_of_date"] is False

    unlocked = client.put(f"/facts/{hits['id']}", json={"confirmed": False}).json()
    assert (unlocked["confirmed"], unlocked["value"], unlocked["effective_value"]) == (False, None, 1)
    client.patch(f"/events/{hit2}", json={"hidden": False})
    assert facts_of(client, video_id)["hits_taken"]["effective_value"] == 2

    with session(client.app.state.engine) as s:
        assert len(s.exec(select(Fact).where(Fact.video_id == video_id)).all()) == len(facts)
