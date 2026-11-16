"""Packaging: templates and conditions, the rules engine, and the package API with a fake writer."""

import re
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import session
from app.models import Event, Fact, LibraryItem, Research, Segment, Video
from app.services.llm.base import LLMResult
from app.services.packaging import (
    PhraseFit,
    SlotValue,
    ThumbnailIdea,
    TitleNote,
    WriterOut,
    chapter_list,
    export_filename,
    parse_chapters,
    short_window,
)
from app.services.presets import ChannelProfile, Condition, load_presets
from app.services.research import name_key
from app.services.rules import RuleContext, _tags_length, check
from app.services.templating import holds, render_block, render_title

CONFIG = Path(__file__).resolve().parents[2] / "config"
PRESETS = load_presets(CONFIG)[0]
BOSS = PRESETS["boss_fight"]


# ---- conditions and templates -----------------------------------------------------


def test_conditions_use_confirmed_facts_and_research():
    facts, research = {"hits_taken": 2, "counter_count": 12}, {"is_final_boss": True}
    assert holds(Condition(fact="hits_taken", op="between", value=[2, 3]), facts, research)
    assert not holds(Condition(fact="hits_taken", op="eq", value=0), facts, research)
    assert holds(Condition(fact="counter_count", op="gte", value=3), facts, research)
    assert holds(Condition(research="is_final_boss", op="eq", value=True), facts, research)
    assert not holds(Condition(fact="missing", op="eq", value=0), facts, research)  # unconfirmed is never true
    assert holds(Condition(fact="hits_taken", op="in", value=[1, 2]), facts, research)


def test_titles_drop_empty_variables_with_their_separators():
    pattern = "{topic} - {subject} Boss Fight ({hook})"
    assert render_title(pattern, {"topic": "Phantom Blade Zero", "subject": "Zhuo Bi", "hook": "12 Counters"}) == \
        "Phantom Blade Zero - Zhuo Bi Boss Fight (12 Counters)"
    assert render_title(pattern, {"topic": "", "subject": "Zhuo Bi", "hook": ""}) == "Zhuo Bi Boss Fight"
    assert render_title("{topic} {subject} - {hook}", {"topic": "X", "subject": "Y"}) == "X Y"


def test_blocks_drop_empty_lines_and_lonely_headings():
    template = "{hook_line}\n\nFull playlist: {playlist_url}\nSubscribe: {subscribe_url}\n\nCHAPTERS\n{chapters}\n\n{credit_block}\n\n{hashtags}"
    text = render_block(template, {"hook_line": "Hi.", "subscribe_url": "s", "chapters": "", "credit_block": "Studio: X",
                                   "hashtags": "#a #b"})
    assert text == "Hi.\n\nSubscribe: s\n\nStudio: X\n\n#a #b"
    with_chapters = render_block(template, {"chapters": "0:00 Start\n0:30 Mid", "hashtags": "#a"})
    assert with_chapters.startswith("CHAPTERS\n0:00 Start")


def test_chapters_need_three_sections_ten_seconds_apart():
    def seg(t, label):
        return Segment(video_id="v", kind="section", t_start=t, t_end=t + 1, label=label)
    chapters = chapter_list([seg(2.0, "Intro"), seg(5.0, "Too close"), seg(40.0, "Phase two"), seg(90.0, "Finisher")])
    assert chapters == [{"t": 0.0, "label": "Intro"}, {"t": 40.0, "label": "Phase two"}, {"t": 90.0, "label": "Finisher"}]
    assert chapter_list([seg(0, "a"), seg(30, "b")]) == []
    # A section starting less than 10 s before the end joins the chapter before it (YouTube rejects it).
    tail = [seg(0, "a"), seg(65, "b"), seg(155, "c"), seg(213, "Loot")]
    assert [c["label"] for c in chapter_list(tail, duration_s=216.9)] == ["a", "b", "c"]
    assert [c["label"] for c in chapter_list(tail)] == ["a", "b", "c", "Loot"]


def test_short_window_is_twenty_to_sixty_seconds_inside_the_video():
    def peak(a, b):
        return Segment(video_id="v", kind="peak", t_start=a, t_end=b)
    assert short_window(peak(210.5, 212.5), 216.9) == (196.9, 216.9)
    assert short_window(peak(1.0, 3.0), 216.9) == (0.0, 20.0)
    assert short_window(peak(50.0, 80.0), 216.9) == (50.0, 80.0)
    assert short_window(peak(10.0, 100.0), 216.9) == (10.0, 70.0)
    assert parse_chapters("0:00 Intro\n1:02:03 Late\nnot a chapter") == [
        {"t": 0.0, "label": "Intro"}, {"t": 3723.0, "label": "Late"},
    ]


# ---- rules ------------------------------------------------------------------------


def channel() -> ChannelProfile:
    return ChannelProfile(name="TheLazyRonin", display_name="The Lazy Ronin", hashtags={"youtube": 3}, tags_target=20)


def fields(**over) -> dict:
    base = {
        "title": "Phantom Blade Zero - Zhuo Bi Boss Fight (No Hit)", "hook_line": "I beat him.",
        "description": "Text", "title_alternates": [{"text": "Phantom Blade Zero - Zhuo Bi Final Boss"}],
        "thumbnail": {"word_options": ["NO HIT", "2 V 1"]}, "tags": [f"tag {i}" for i in range(20)] + ["Soulslike"],
        "hashtags": ["#PhantomBladeZero", "Zhuo Bi", "#a", "#b"], "chapter_list": [],
    }
    return base | over


def ctx(**over) -> RuleContext:
    base = {"platform": "youtube", "preset": BOSS, "channel": channel(), "topic": "Phantom Blade Zero",
            "subject": "Zhuo Bi", "facts": {"hits_taken": 2}, "research": {"is_final_boss": None}}
    return RuleContext(**(base | over))


def by_key(results: list[dict]) -> dict:
    return {r["key"]: r for r in results}


def test_claims_without_facts_are_blocked_and_backed_claims_pass():
    _, results = check(fields(), ctx())
    r = by_key(results)
    assert r["claim_needs_fact.no_hit_claim:title"]["severity"] == "block"
    assert r["claim_needs_fact.no_hit_claim:thumbnail.word_options[0]"]["severity"] == "block"
    final = r["claim_needs_fact.final_boss_claim:title_alternates[0]"]
    assert final["severity"] == "block" and "Final Fight" in final["message"]
    _, ok = check(fields(), ctx(facts={"hits_taken": 0}))
    assert by_key(ok)["claim_needs_fact.no_hit_claim:title"]["severity"] == "pass"


def test_auto_fixes_numbers_and_counts():
    fixed, results = check(fields(title="Phantom Blade Zero - zhuo bi in 7 Tries", hashtags=["#A", "B c", "#a", "#D", "#E"]),
                           ctx(research={"canonical_name": "Zhuo Bi"}))
    r = by_key(results)
    assert fixed["title"] == "Phantom Blade Zero - Zhuo Bi in 7 Tries" and r["canonical_spelling:title"]["fixed"]
    assert fixed["hashtags"] == ["#A", "#Bc", "#D"] and r["hashtag_count:hashtags"]["fixed"]
    assert "Soulslike" not in fixed["tags"] and r["banned_tags:tags"]["fixed"]
    assert r["number_needs_fact:title"]["severity"] == "warn" and r["number_needs_fact:title"]["evidence"] == ["7"]
    assert "number_needs_fact:thumbnail.word_options[1]" not in r  # a preset thumbnail word is claim-free
    assert r["search_first_title:title"]["severity"] == "pass"
    assert r["tags_count:tags"]["severity"] == "pass"
    assert r["cannibalization:title"]["message"] == "No past uploads recorded"


def test_chapters_length_cannibalization_and_dismissals():
    bad = [{"t": 5.0, "label": "a"}, {"t": 10.0, "label": "b"}]
    _, results = check(fields(chapter_list=bad, title="x" * 101, title_alternates=[], thumbnail={},
                              tags=["a"]), ctx(past_subjects=[{"title": "Zhuo Bi No Hit", "subject": "Zhuo Bi"}],
                                               dismissed={"tags_count:tags"}))
    r = by_key(results)
    assert r["chapters_valid:chapters"]["severity"] == "block" and "0:00" in r["chapters_valid:chapters"]["message"]
    assert r["length_limits:title"]["severity"] == "block"
    assert r["search_first_title:title"]["severity"] == "warn"
    assert r["cannibalization:title"]["severity"] == "warn"
    assert r["tags_count:tags"]["dismissed"] is True and r["search_first_title:title"]["dismissed"] is False


def test_tags_past_the_limit_are_dropped_from_the_end():
    long_tags = [f"Phantom Blade Zero tag number {i:02d}" for i in range(20)]  # 34 characters each, quoted
    fixed, results = check(fields(tags=long_tags), ctx())
    r = by_key(results)
    assert fixed["tags"] == long_tags[:14] and _tags_length(fixed["tags"]) <= 500
    assert r["tags_fit:tags"]["fixed"] and r["tags_fit:tags"]["evidence"] == long_tags[14:]
    assert "length_limits:tags" not in r
    _, short = check(fields(), ctx())
    assert "tags_fit:tags" not in by_key(short)


def test_last_chapter_and_long_alternates():
    chapters = [{"t": 0.0, "label": "a"}, {"t": 65.0, "label": "b"}, {"t": 213.0, "label": "c"}]
    _, results = check(fields(chapter_list=chapters, title_alternates=[{"text": "y" * 101}]), ctx(duration_s=216.9))
    r = by_key(results)
    assert r["chapters_valid:chapters"]["severity"] == "block"
    assert "last chapter" in r["chapters_valid:chapters"]["message"]
    assert r["length_limits:title_alternates[0]"]["severity"] == "warn"
    _, ok = check(fields(chapter_list=chapters[:2] + [{"t": 150.0, "label": "c"}]), ctx(duration_s=216.9))
    assert by_key(ok)["chapters_valid:chapters"]["severity"] == "pass"


def test_export_filename_is_windows_safe():
    video = Video(title="t", topic="Phantom Blade: Zero?", subject='Zhuo "Bi"')
    assert export_filename(channel(), video) == "TheLazyRonin_PhantomBladeZero_ZhuoBi_YouTube_SEO.md"
    video = Video(title="t", topic="Phantom Blade Zero", subject="Hua Qianxiao, the Sword Fanatic's")
    assert export_filename(channel(), video) == "TheLazyRonin_PhantomBladeZero_HuaQianxiaotheSwordFanatics_YouTube_SEO.md"


# ---- the API ----------------------------------------------------------------------


class FakeWriter:
    model = "fake-writer"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.extra_slots: dict[str, str] = {}

    async def search(self, *args, **kwargs):  # research is not exercised here
        raise AssertionError("no research in these tests")

    async def generate_json(self, prompt, schema, search=False, effort="low"):
        assert schema is WriterOut
        self.prompts.append(prompt)
        ids = [m.group(1) for m in re.finditer(r"^- (t\d+) \(", prompt, flags=re.MULTILINE)]
        # Search phrases ("- p3: text (suggestion #2)"): everything fits except music and trailers.
        phrase_lines = [line[2:].split(": ", 1) for line in prompt.splitlines() if re.match(r"- p\d+: ", line)]
        out = WriterOut(
            phrase_fit=[PhraseFit(id=i, fits=not re.search(r"music|trailer", text)) for i, text in phrase_lines],
            slots=[SlotValue(name="hook_line", value="Zhuo Bi hits like a wall, so I let him come to me."),
                   SlotValue(name="body_paragraph", value="I parried his shield combo and countered every opening."),
                   SlotValue(name="not_a_slot", value="ignored")]
            + [SlotValue(name=k, value=v) for k, v in self.extra_slots.items()],
            claim_free_hook="Shield Breaker",
            recommended_title_id=ids[-1],
            title_notes=[TitleNote(id=i, why=f"why {i}", goal="click_through") for i in ids],
            tags=["Phantom Blade Zero", "Zhuo Bi", "soulslike", "Zhuo Bi"] + [f"tag {n}" for n in range(16)],
            hashtags=["PhantomBladeZero", "#ZhuoBi", "#BossFight", "#Extra"],
            opening_5s="Open on the first shield bash at 0:03.", pinned_comment="Parry or dodge?",
            community_post="Poll: hardest gatekeeper?",
            thumbnail=ThumbnailIdea(frame_ts=[12.0, 40.5], prompt="Warrior facing a giant shield.",
                                    fallback_words=["SHIELD"]),
        )
        return LLMResult(parsed=out, raw_text="{}", model=self.model, usage={"input_tokens": 3000, "output_tokens": 800},
                         latency_s=2.0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = tmp_path / "config"
    shutil.copytree(CONFIG, config)
    (tmp_path / "inbox").mkdir()
    (tmp_path / "data").mkdir()
    for key, value in {
        "INBOX_DIR": tmp_path / "inbox", "DATA_DIR": tmp_path / "data", "CONFIG_DIR": config,
        "DB_PATH": tmp_path / "db" / "app.db", "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": "",
    }.items():
        monkeypatch.setenv(key, str(value))
    from app import main
    from app.settings import get_settings

    get_settings.cache_clear()
    writer = FakeWriter()
    monkeypatch.setattr(main, "claude_factory", lambda _settings: lambda: writer)
    with TestClient(main.app) as test_client:
        test_client.writer = writer
        yield test_client
    get_settings.cache_clear()


def seed(client: TestClient) -> str:
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", subject="Zhuo Bi", topic="Phantom Blade Zero", preset_id="boss_fight",
                      status="ready", duration_s=200.0)
        s.add(video)
        s.flush()
        s.add_all([
            Event(video_id=video.id, t_start=t, t_end=t + 1, type="counter", source="model")
            for t in (10.0, 50.0, 90.0, 120.0)
        ] + [
            Segment(video_id=video.id, kind="section", t_start=t, t_end=t + 30, label=label)
            for t, label in [(1.0, "Opening"), (60.0, "Second phase"), (150.0, "Finisher")]
        ] + [
            Research(subject_key=name_key("Zhuo Bi"), topic_key=name_key("Phantom Blade Zero"),
                     payload={"method": "search", "canonical_name": "Zhuo Bi", "fields": {
                         "real_name": {"value": "Zhuo Bi", "source_urls": []},
                         "studio": {"value": "S-GAME", "source_urls": []},
                     }}),
        ])
        s.commit()
        return video.id


def wait(client: TestClient, job: dict) -> dict:
    for _ in range(300):
        state = client.get(f"/jobs/{job['id']}").json()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def confirm(client: TestClient, video_id: str, key: str, value) -> None:
    fact = next(f for f in client.get(f"/videos/{video_id}/facts").json() if f["key"] == key)
    assert client.put(f"/facts/{fact['id']}", json={"value": value, "confirmed": True}).status_code == 200


def test_package_generation_edits_dismissals_staleness_and_export(client):
    video_id = seed(client)
    state = client.get(f"/videos/{video_id}/packages").json()
    assert state["missing_facts"] == ["Hits taken"] and state["can_generate"] is False and state["packages"] == []
    refused = client.post(f"/videos/{video_id}/packages", json={"platforms": ["youtube"]})
    assert refused.status_code == 409 and "Hits taken" in refused.json()["detail"]
    assert client.post(f"/videos/{video_id}/packages", json={"platforms": ["shorts"]}).status_code == 422

    confirm(client, video_id, "hits_taken", 2)
    confirm(client, video_id, "counter_count", 4)
    job = client.post(f"/videos/{video_id}/packages", json={"platforms": ["youtube"]})
    assert job.status_code == 202 and wait(client, job.json())["status"] == "done"

    data = client.get(f"/videos/{video_id}/packages").json()
    pkg = data["packages"][0]
    f = pkg["fields"]
    prompt = client.writer.prompts[0]
    # Eligible hooks become title candidates; the forbidden claim phrases are listed for the writer.
    assert "Only 2 Hits Taken" in prompt and "4 Counters" in prompt and "No Hit" in prompt.split("must NOT")[1]
    assert f["title"].startswith("Phantom Blade Zero - Zhuo Bi")
    assert len(f["title_alternates"]) <= 4 and all(a["why"] for a in f["title_alternates"])
    assert f["hashtags"] == ["#PhantomBladeZero", "#ZhuoBi", "#BossFight"]
    assert "soulslike" not in [t.lower() for t in f["tags"]] and f["tags"].count("Zhuo Bi") == 1
    assert f["chapters"] == "0:00 Opening\n1:00 Second phase\n2:30 Finisher"
    assert f["credit_block"] == "Boss: Zhuo Bi\nGame: Phantom Blade Zero (S-GAME)"  # credit_lines; empty parts drop
    assert f["seo"]["source"] is None and f["seo"]["picked_by"] == "writer"  # no search data in this test
    assert any(c["item"] == "Playlist" and "All Boss Fights" in c["detail"] for c in f["checklist"])
    assert "CHAPTERS\n0:00 Opening" in f["description"] and f["description"].endswith("#PhantomBladeZero #ZhuoBi #BossFight")
    assert "Full playlist" not in f["description"]  # no playlist for this topic: the line is dropped
    assert f["thumbnail"]["word_options"] == ["2 HITS", "SHIELD", "2 V 1"]  # hook, writer's own, preset extra
    assert f["end_screen_target"]["kind"] == "none"
    assert pkg["stale"] is False and pkg["version"] == 1 and pkg["blocked_fields"] == []
    assert client.get(f"/videos/{video_id}").json()["display_status"] == "packaged"

    backed = [r for r in pkg["rule_results"] if r["rule_id"].startswith("claim_needs_fact") and r["severity"] == "pass"]
    assert all(r["evidence"]["phrase"] for r in backed)

    # Picking an alternate takes its reasoning; putting the generated title back clears the edit.
    original = (f["title"], f["title_why"])
    alt = f["title_alternates"][0]
    picked = client.patch(f"/packages/{pkg['id']}", json={"field": "title", "value": alt["text"]}).json()
    assert picked["fields"]["title_why"] == alt["why"] and "title" in picked["edited_fields"]
    back = client.patch(f"/packages/{pkg['id']}", json={"field": "title", "value": original[0]}).json()
    assert (back["fields"]["title"], back["fields"]["title_why"]) == original and back["edited_fields"] == []

    # A manual edit re-runs the rules: a no-hit claim with 2 hits is blocked.
    edited = client.patch(f"/packages/{pkg['id']}", json={"field": "title", "value": "Phantom Blade Zero - Zhuo Bi No Hit"}).json()
    assert "title" in edited["edited_fields"] and "title" in edited["blocked_fields"]
    assert edited["fields"]["title_why"] == "Your own title"
    assert client.patch(f"/packages/{pkg['id']}", json={"field": "checklist", "value": "x"}).status_code == 422
    tags = client.patch(f"/packages/{pkg['id']}", json={"field": "tags", "value": "one, two"}).json()
    warn = next(r for r in tags["rule_results"] if r["key"] == "tags_count:tags")
    assert warn["severity"] == "warn" and tags["counts"]["warn"] >= 1
    dismissed = client.patch(f"/packages/{pkg['id']}", json={"dismiss": "tags_count:tags"}).json()
    assert next(r for r in dismissed["rule_results"] if r["key"] == "tags_count:tags")["dismissed"] is True
    assert client.patch(f"/packages/{pkg['id']}", json={"dismiss": "chapters_valid:chapters"}).status_code == 422

    # Regenerate all keeps edited fields; replace_edits drops them.
    job = client.post(f"/packages/{pkg['id']}/regenerate", json={"all": True})
    assert wait(client, job.json())["status"] == "done"
    again = client.get(f"/videos/{video_id}/packages").json()["packages"][0]
    assert again["version"] == 2 and again["fields"]["tags"] == ["one", "two"]
    assert next(r for r in again["rule_results"] if r["key"] == "tags_count:tags")["dismissed"] is True
    job = client.post(f"/packages/{pkg['id']}/regenerate", json={"field": "tags"})
    assert wait(client, job.json())["status"] == "done"
    third = client.get(f"/videos/{video_id}/packages").json()["packages"][0]
    assert "tags" not in third["edited_fields"] and "title" in third["edited_fields"]
    assert len(third["fields"]["tags"]) > 2

    # Changing an event makes the package stale; undoing the change makes it current again.
    event = client.get(f"/videos/{video_id}/timeline").json()["events"][0]
    client.patch(f"/events/{event['id']}", json={"hidden": True})
    assert client.get(f"/videos/{video_id}/packages").json()["packages"][0]["stale"] is True
    client.patch(f"/events/{event['id']}", json={"hidden": False})
    assert client.get(f"/videos/{video_id}/packages").json()["packages"][0]["stale"] is False

    export = client.get(f"/videos/{video_id}/export.md")
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/markdown")
    assert 'filename="TheLazyRonin_PhantomBladeZero_ZhuoBi_YouTube_SEO.md"' in export.headers["content-disposition"]
    assert "## Description" in export.text and "BLOCK title" in export.text


def test_past_uploads_pick_the_end_screen_and_warn_about_repeats(client):
    video_id = seed(client)
    confirm(client, video_id, "hits_taken", 0)
    with session(client.app.state.engine) as s:
        s.add(LibraryItem(title="Phantom Blade Zero - Zhuo Bi First Try", subject="Zhuo Bi", topic="Phantom Blade Zero",
                          url="https://youtu.be/x", published_at="2026-10-01"))
        s.commit()
    assert wait(client, client.post(f"/videos/{video_id}/packages", json={}).json())["status"] == "done"
    pkg = client.get(f"/videos/{video_id}/packages").json()["packages"][0]
    assert pkg["fields"]["end_screen_target"]["url"] == "https://youtu.be/x"
    assert next(r for r in pkg["rule_results"] if r["rule_id"] == "cannibalization")["severity"] == "warn"
    assert "No Hit" in pkg["fields"]["thumbnail"]["word_options"][0].title()
    with session(client.app.state.engine) as s:
        assert s.get(Fact, next(f["id"] for f in client.get(f"/videos/{video_id}/facts").json()
                                if f["key"] == "hits_taken")).confirmed
