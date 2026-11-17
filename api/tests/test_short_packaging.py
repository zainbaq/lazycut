"""Short-form packages (BUILD_SPEC 7.8, 7.9): rendering from the preset, the rules, and the API."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import session
from app.models import Clip, Event, Fact, Video
from app.services import short_packaging as sp
from app.services.llm.base import LLMResult
from app.services.packaging import Inputs, SlotValue
from app.services.presets import load_channel, load_presets

CONFIG = Path(__file__).resolve().parents[2] / "config"
BOSS = load_presets(CONFIG)[0]["boss_fight"]
CHANNEL = load_channel(CONFIG)[0]


def inputs(**facts) -> Inputs:
    video = Video(id="v", title="Gate Keeper", topic="Phantom Blade Zero", subject="Zhuo Bi", duration_s=60.0)
    events = [Event(video_id="v", t_start=t, t_end=t + 1, type=kind) for t, kind in [(10.0, "counter"), (20.0, "finisher")]]
    return Inputs(video=video, preset=BOSS, channel=CHANNEL, facts=dict(facts), fact_rows=[],
                  research={"canonical_name": "Zhuo Bi"}, events=events, sections=[], peaks=[])


def clip(**over) -> Clip:
    data = {"id": "c1", "video_id": "v", "name": "The kill", "t_start": 9.5, "t_end": 21.5, "payoff_t": 20.0,
            "reason": "Ends on the finisher."}
    return Clip(**(data | over))


def writer(**over) -> sp.ShortWriterOut:
    data = {
        "slots": [SlotValue(name="plain_hook", value="He never touched me"), SlotValue(name="what_happens", value="One counter, then the kill."),
                  SlotValue(name="term_explained", value="A Ghoststep is a perfect dodge."), SlotValue(name="tip", value="Dodge late."),
                  SlotValue(name="question", value="Could you do it?"), SlotValue(name="emoji", value="🗡️"),
                  SlotValue(name="body_paragraph", value="Not a short-form slot.")],
        "claim_free_hook": "One clean counter", "shorts_title": "I ended zhuo-bi in one counter 🗡️",
        "hashtags": ["#PhantomBladeZero", "ZhuoBi", "#Boss Fight", "#Gaming", "#Parry", "#Souls"],
        "pinned_comment": "Full fight is on the channel.",
    }
    return sp.ShortWriterOut(**(data | over))


def by_key(results: list[dict]) -> dict:
    return {r["key"]: r for r in results}


def test_only_the_short_form_slots_are_asked_for_and_the_prompt_is_about_the_clip():
    assert set(sp.slots_needed(BOSS)) == {"emoji", "tip", "plain_hook", "what_happens", "term_explained", "question"}
    assert sp.uses_hook(BOSS)
    text = sp.writer_prompt(inputs(hits_taken=11), clip(), ["reels", "shorts"], [])
    assert "Instagram Reels, YouTube Shorts" in text and '"The kill", 12.0 s long' in text
    assert "The payoff lands 10 s in" in text and " 0.5s Counter" in text and "10.5s Finisher" in text
    assert "- hits_taken: 11" in text and "No Hit, No Damage" in text and "claim_free_hook" in text
    assert "body_paragraph" not in text
    hooked = sp.writer_prompt(inputs(hits_taken=0), clip(), ["reels"], [{"id": "no_hit", "text": "No Hit"}])
    assert "- no_hit: No Hit" in hooked and "hook_id: the id of the hook" in hooked


def test_a_reel_template_splits_into_on_screen_text_and_caption():
    on_screen, caption = sp.split_reel("ON-SCREEN: He never touched me. No cuts.\nCAPTION: One counter.\n\n\n\nA question?\n#A #B")
    assert on_screen == "He never touched me. No cuts."
    assert caption == "One counter.\n\nA question?\n#A #B"
    assert sp.split_reel("Just a caption") == ("", "Just a caption")


def test_every_platform_is_rendered_from_one_writer_answer():
    out = sp.assemble(inputs(hits_taken=11), clip(), writer(), ["shorts", "reels", "tiktok"], [])
    shorts, reels = out["shorts"], out["reels"]
    assert shorts["title"] == "I ended zhuo-bi in one counter 🗡️ #PhantomBladeZero"
    # Every hashtag the writer gave is kept here; the rules cut to the platform's count after their fixes.
    assert shorts["hashtags"] == ["#Shorts", "#PhantomBladeZero", "#ZhuoBi", "#BossFight", "#Gaming", "#Parry", "#Souls"]
    assert shorts["description"].startswith("One clean counter. That's all Zhuo Bi got. 🗡️\n\nDodge late.")
    assert shorts["description"].endswith("#Shorts #PhantomBladeZero #ZhuoBi #BossFight #Gaming #Parry #Souls")
    assert reels["on_screen_text"] == "He never touched me. No cuts."
    assert reels["caption"].startswith("One counter, then the kill. A Ghoststep is a perfect dodge.\n\nCould you do it?")
    assert "Full boss fights on YouTube: TheLazyRonin" in reels["caption"] and "CAPTION" not in reels["caption"]
    assert reels["hashtags"][:2] == ["#PhantomBladeZero", "#ZhuoBi"] and len(reels["hashtags"]) == 6
    assert reels["end_text"] == "Full fight on YouTube @thelazyronin" and reels["question"] == "Could you do it?"
    assert reels["clip"] == {"id": "c1", "name": "The kill", "t_start": 9.5, "t_end": 21.5}
    assert reels["safe_margins"] == {"top_pct": 12, "bottom_pct": 15} and "body_paragraph" in reels["slots"]
    assert out["tiktok"]["caption"] == reels["caption"]                 # TikTok mirrors the Reel
    # With a backed hook, the hook's own words are used, never the writer's phrase.
    hooked = sp.assemble(inputs(hits_taken=0), clip(), writer(hook_id="no_hit"), ["shorts"],
                         [{"id": "no_hit", "text": "No Hit"}])["shorts"]
    assert hooked["description"].startswith("No Hit. That's all Zhuo Bi got.") and hooked["hook_id"] == "no_hit"


def test_short_rules_fix_spelling_and_hashtags_and_check_claims_links_and_lengths():
    inp = inputs(hits_taken=11)
    out = sp.assemble(inp, clip(), writer(shorts_title="No hit run on zhuo-bi 🗡️"), ["shorts", "reels", "tiktok"], [])
    fields, results = sp.run_rules(inp, clip(), "shorts", out["shorts"])
    r = by_key(results)
    assert fields["title"].startswith("No hit run on Zhuo Bi") and r["canonical_spelling:title"]["fixed"]
    assert r["claim_needs_fact.no_hit_claim:title"]["severity"] == "block"        # 11 hits were taken
    assert r["hashtag_count:hashtags"]["severity"] == "pass" and r["clip_length:clip"]["severity"] == "pass"
    assert fields["hashtags"] == ["#Shorts", "#PhantomBladeZero", "#ZhuoBi", "#BossFight", "#Gaming"]      # cut to the channel's 5
    assert fields["description"].endswith("#Shorts #PhantomBladeZero #ZhuoBi #BossFight #Gaming")
    assert r["link_back:description"]["severity"] == "block"                       # no playlist for this topic yet

    fields, results = sp.run_rules(inp, clip(), "reels", out["reels"])
    r = by_key(results)
    assert r["link_back:caption"]["severity"] == "pass" and "TheLazyRonin" in r["link_back:caption"]["message"]
    assert not [x for x in results if x["severity"] == "block"]
    # Editing the hashtags rewrites the line of hashtags inside the caption too.
    fields["hashtags"] = ["#Wuxia", "#PhantomBladeZero"]
    fields, results = sp.run_rules(inp, clip(), "reels", fields)
    assert fields["caption"].endswith("#Wuxia #PhantomBladeZero") and "#Parry" not in fields["caption"]
    assert by_key(results)["hashtag_count:hashtags"]["severity"] == "warn"         # 2 of the channel's 5

    bare = dict(out["tiktok"]) | {"caption": "x" * 2300}
    r = by_key(sp.run_rules(inp, clip(t_end=700.0), "tiktok", bare)[1])
    assert r["link_back:caption"]["severity"] == "warn"                            # TikTok: a warning, not a block
    assert r["length_limits:caption"]["severity"] == "block" and r["clip_length:clip"]["severity"] == "warn"


# ---- the API ----------------------------------------------------------------------


class FakeShortWriter:
    model = "fake-claude"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.answer = writer()

    async def generate_json(self, prompt, schema, search=False, effort="low"):
        self.prompts.append(prompt)
        assert schema is sp.ShortWriterOut
        return LLMResult(parsed=self.answer, raw_text="{}", model=self.model,
                         usage={"input_tokens": 1500, "output_tokens": 300}, latency_s=0.3)


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "data").mkdir()
    for key, value in {
        "INBOX_DIR": tmp_path / "inbox", "DATA_DIR": tmp_path / "data", "CONFIG_DIR": CONFIG,
        "DB_PATH": tmp_path / "db" / "app.db", "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": "", "SEARCH_DEMAND": "off",
    }.items():
        monkeypatch.setenv(key, str(value))
    from app import main
    from app.settings import get_settings

    get_settings.cache_clear()
    fake = FakeShortWriter()
    monkeypatch.setattr(main, "claude_factory", lambda _settings: lambda: fake)
    with TestClient(main.app) as test_client:
        test_client.writer = fake
        yield test_client
    get_settings.cache_clear()


def seed(client: TestClient, confirmed: bool = True) -> tuple[str, str]:
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", topic="Phantom Blade Zero", subject="Zhuo Bi", preset_id="boss_fight",
                      status="ready", duration_s=60.0, fps=60.0)
        s.add(video)
        s.flush()
        s.add_all(Event(video_id=video.id, t_start=t, t_end=t + 1, type=kind) for t, kind in [(10.0, "counter"), (20.0, "finisher")])
        s.add(Fact(video_id=video.id, key="hits_taken", label="Hits taken", value=11, confirmed=confirmed))
        made = Clip(video_id=video.id, name="The kill", t_start=9.5, t_end=21.5, status="candidate", source="finder",
                    orig_start=9.5, orig_end=21.5, reason="Ends on the finisher.")
        s.add(made)
        s.commit()
        return video.id, made.id


def wait(client: TestClient, started) -> dict:
    assert started.status_code == 202, started.text
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{started.json()['id']}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("the package job did not finish")


def test_short_packages_are_written_per_clip_edited_and_go_stale_when_it_is_trimmed(client):
    video_id, clip_id = seed(client)
    assert client.post(f"/videos/{video_id}/packages", json={"platforms": ["reels"]}).status_code == 422   # no clip
    assert client.post(f"/videos/{video_id}/packages", json={"platforms": ["reels"], "clip_id": "nope"}).status_code == 404

    job = wait(client, client.post(f"/videos/{video_id}/packages", json={"platforms": ["reels", "shorts"], "clip_id": clip_id}))
    assert (job["kind"], job["status"]) == ("clip_package", "done")
    assert job["message"] == "Wrote Instagram Reels, YouTube Shorts · 1 blocked"   # Shorts has no link back yet
    assert len(client.writer.prompts) == 1                                          # one call for both platforms

    listing = client.get(f"/videos/{video_id}/packages").json()
    assert listing["running_short"] is False
    packages = {p["platform"]: p for p in listing["packages"]}
    assert set(packages) == {"reels", "shorts"} and all(p["clip_id"] == clip_id and not p["stale"] for p in packages.values())
    reels = packages["reels"]
    assert reels["fields"]["on_screen_text"] == "He never touched me. No cuts." and reels["counts"]["block"] == 0
    assert packages["shorts"]["blocked_fields"] == ["description"]
    assert client.get(f"/videos/{video_id}/clips").json()["clips"][0]["status"] == "selected"   # packaged = kept

    # A manual edit re-runs the rules; a blocked claim blocks the field.
    edited = client.patch(f"/packages/{reels['id']}", json={"field": "on_screen_text", "value": "No hit. No cuts."}).json()
    assert edited["edited_fields"] == ["on_screen_text"] and edited["blocked_fields"] == ["on_screen_text"]
    assert client.patch(f"/packages/{reels['id']}", json={"field": "title", "value": "x"}).status_code == 422
    tags = client.patch(f"/packages/{reels['id']}", json={"field": "hashtags", "value": "#Wuxia #PhantomBladeZero"}).json()
    assert tags["fields"]["caption"].endswith("#Wuxia #PhantomBladeZero")

    # Trimming the clip makes its packages stale; regenerating keeps the user's edits.
    client.patch(f"/clips/{clip_id}", json={"t_end": 23.0})
    assert all(p["stale"] for p in client.get(f"/videos/{video_id}/packages").json()["packages"])
    job = wait(client, client.post(f"/packages/{reels['id']}/regenerate", json={"all": True}))
    assert job["message"].startswith("Wrote Instagram Reels")
    again = {p["platform"]: p for p in client.get(f"/videos/{video_id}/packages").json()["packages"]}
    assert again["reels"]["version"] == 2 and not again["reels"]["stale"] and again["shorts"]["stale"]
    assert again["reels"]["fields"]["on_screen_text"] == "No hit. No cuts."
    job = wait(client, client.post(f"/packages/{reels['id']}/regenerate", json={"field": "on_screen_text"}))
    final = {p["platform"]: p for p in client.get(f"/videos/{video_id}/packages").json()["packages"]}["reels"]
    assert final["fields"]["on_screen_text"] == "He never touched me. No cuts." and "on_screen_text" not in final["edited_fields"]

    export = client.get(f"/videos/{video_id}/export.md").text
    assert "## Instagram Reels: The kill" in export and "## YouTube Shorts: The kill" in export
    assert "On-screen text:" in export and "BLOCK description" in export

    # Deleting the clip takes its packages with it.
    client.delete(f"/clips/{clip_id}")
    assert client.get(f"/videos/{video_id}/packages").json()["packages"] == []


def test_short_packages_wait_for_the_required_facts(client):
    video_id, clip_id = seed(client, confirmed=False)
    refused = client.post(f"/videos/{video_id}/packages", json={"platforms": ["tiktok"], "clip_id": clip_id})
    assert refused.status_code == 409 and "Hits taken" in refused.json()["detail"]
