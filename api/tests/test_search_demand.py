"""Search demand (BUILD_SPEC 7.7.1): the harvest, anchoring, ambiguity, title scoring, and how the
package uses it. The canned suggestions are real ones captured on 2026-11-15."""

import asyncio

from app.db import session
from app.models import Research
from app.services import search_demand as sd
from app.services.research import name_key
from app.services.rules import check
from tests.test_packaging import BOSS, client, confirm, ctx, fields, seed, wait  # noqa: F401 - shared fixture

PBZ = "phantom blade zero"
CANNED = {
    PBZ: ["phantom blade zero", "phantom blade zero review", "phantom blade zero gameplay"],
    f"{PBZ} boss": ["phantom blade zero boss fight", "phantom blade zero bosses ranked", "phantom blade zero bosses",
                    "phantom blade zero boss guide", "phantom blade zero boss music"],
    f"{PBZ} sword fanatic": ["phantom blade zero sword fanatic", "phantom blade zero review"],
    f"{PBZ} hua qianxiao": ["phantom blade zero hua qianxiao"],
    f"{PBZ} drunk boss": ["phantom blade zero drunk boss"],
    "sword fanatic": ["sword fanatic wanders through the night recap", "sword fanatic wanders through the night manhwa",
                      "sword fanatic manhwa", "sword manga"],
    "drunk boss": ["drunk boss", "drunk boss manga", "sekiro how to beat drunk boss", "drunk boss kiss"],
    "hua qianxiao": ["hua qian xiao"],
    f"{PBZ} zhuo bi": [],
    "zhuo bi": ["zuo bian", "zuo bian rainie yang", "zuo bian karaoke", "zou bisou"],
}


class FakeSuggest:
    def __init__(self, canned=None, fail=False):
        self.canned, self.fail, self.queries = canned or CANNED, fail, []

    async def suggest(self, query):
        self.queries.append(query)
        if self.fail:
            raise OSError("offline")
        return self.canned.get(query.strip(), [])


def test_names_cover_the_canonical_parts_epithet_and_nicknames():
    names = sd.subject_names("Hua Qianxiao, the Sword Fanatic",
                             {"canonical_name": "Hua Qianxiao, the Sword Fanatic", "real_name": "Hua Qianxiao",
                              "epithet": "the Sword Fanatic", "nicknames": "Drunk Boss, The Drunkard"},
                             before="The Sword Fanatic")
    assert names[:4] == ["hua qianxiao", "sword fanatic", "drunk boss", "drunkard"]
    assert "hua qianxiao the sword fanatic" in names  # the long form comes last


def test_harvest_anchors_phrases_and_finds_ambiguous_names():
    fake = FakeSuggest()
    payload = asyncio.run(sd.harvest(fake, "Phantom Blade Zero", ["hua qianxiao", "sword fanatic", "drunk boss"],
                                     BOSS.search_seeds))
    assert payload["source"] == "youtube_suggest" and payload["errors"] == 0
    assert "phantom blade zero boss" in fake.queries and "how to beat drunk boss" in fake.queries
    assert sd.ambiguous_names(payload) == {"sword fanatic", "drunk boss"}  # a manhwa; a trope
    texts = [p["text"] for p in sd.candidate_phrases(payload, "Phantom Blade Zero")]
    assert "phantom blade zero drunk boss" in texts and "phantom blade zero boss fight" in texts
    assert "drunk boss manga" not in texts and "sekiro how to beat drunk boss" not in texts
    assert "hua qian xiao" not in texts  # names no topic, and is not one of our names as written
    top = sd.candidate_phrases(payload, "Phantom Blade Zero")[0]
    assert top["demand"] >= 1.0 and top["id"] == "p1"


def test_a_failed_harvest_is_soft():
    payload = asyncio.run(sd.harvest(FakeSuggest(fail=True), "Phantom Blade Zero", ["zhuo bi"], []))
    assert payload["phrases"] == [] and payload["errors"] > 0
    assert sd.candidate_phrases(None, "x") == [] and not sd.is_fresh(payload)


def test_titles_score_by_demand_coverage_and_position():
    phrases = [{"text": "phantom blade zero boss fight", "demand": 1.0, "fits": True},
               {"text": "phantom blade zero sword fanatic", "demand": 1.0, "fits": True},
               {"text": "phantom blade zero boss music", "demand": 0.6, "fits": False}]
    exact = sd.score_title("Phantom Blade Zero - Sword Fanatic Boss Fight", phrases)
    assert exact.score == 1.6  # both phrases' words (one in order), the music phrase does not fit
    assert {c["match"] for c in exact.covers} == {"exact", "words"}
    plain = sd.score_title("Phantom Blade Zero - How to Beat the Sword Fanatic Made Easy", phrases)
    assert plain.score == 0.6  # loses "boss fight", and the name is split by "How to Beat"
    late = sd.score_title("A very long and winding introduction to a fight in Phantom Blade Zero - Sword Fanatic",
                          phrases)
    assert late.covers and late.covers[0]["front"] is False and late.score < 1.0
    assert sd.coverage("Phantom Blade Zero – Hua Qianxiao, the Sword Fanatic", "phantom blade zero sword fanatic")[0] == 0.6


def test_stuffing_does_not_pay():
    phrases = [{"text": "phantom blade zero boss fight", "demand": 1.0, "fits": True},
               {"text": "phantom blade zero boss guide", "demand": 0.7, "fits": True}]
    clean = sd.score_title("Phantom Blade Zero - Zhuo Bi, the Gatekeeper Boss Fight", phrases)
    stuffed = sd.score_title("Phantom Blade Zero - Zhuo Bi, the Gatekeeper Boss Fight (Village of Lu Boss Guide)", phrases)
    assert stuffed.score < clean.score  # "Boss" twice and 82 characters cost more than "boss guide" earns
    assert sd.tag_key("Phantom Blade Zero the Sword Fanatic") == sd.tag_key("phantom blade zero sword fanatic")


def test_rules_drop_ambiguous_names_swap_hashtags_and_watch_the_title():
    demand_ctx = ctx(ambiguous={"sword fanatic"}, fallback_hashtags=["#BossFight"],
                     phrases=[{"text": "phantom blade zero boss fight", "demand": 1.0, "fits": True}],
                     research={"is_soulslike": None})
    fixed, results = check(fields(title="Phantom Blade Zero - Sword Fanatic Boss Fight",
                                  tags=["Sword Fanatic", "phantom blade zero sword fanatic", "Souls-like"],
                                  hashtags=["#PhantomBladeZero", "#SwordFanatic", "#Extra"]), demand_ctx)
    r = {x["key"]: x for x in results}
    assert fixed["tags"] == ["phantom blade zero sword fanatic"]
    assert r["ambiguous_names:tags"]["fixed"] and r["banned_tags:tags"]["evidence"] == ["Souls-like"]
    assert fixed["hashtags"] == ["#PhantomBladeZero", "#BossFight", "#Extra"]
    assert r["search_demand:title"]["severity"] == "pass"
    _, edited = check(fields(title="Phantom Blade Zero - A Drunken Duel"), demand_ctx)
    assert {x["key"]: x for x in edited}["search_demand:title"]["severity"] == "warn"
    # The soulslike ban lifts when research confirms the genre.
    kept, _ = check(fields(tags=["soulslike"]), ctx(research={"is_soulslike": True}))
    assert kept["tags"] == ["soulslike"]


def test_package_picks_the_title_people_search_for(client):  # noqa: F811
    video_id = seed(client)
    with session(client.app.state.engine) as s:
        s.add(Research(kind=sd.DEMAND, subject_key=name_key("Zhuo Bi"), topic_key=name_key("Phantom Blade Zero"),
                       payload=asyncio.run(sd.harvest(FakeSuggest(), "Phantom Blade Zero", ["zhuo bi"],
                                                      BOSS.search_seeds))))
        s.commit()
    confirm(client, video_id, "hits_taken", 2)
    client.writer.extra_slots = {"search_tail": "Chapter 1"}  # an unbacked number in the search-max title
    job = client.post(f"/videos/{video_id}/packages", json={"platforms": ["youtube"]}).json()
    assert wait(client, job)["status"] == "done"
    pkg = client.get(f"/videos/{video_id}/packages").json()["packages"][0]
    f, seo = pkg["fields"], pkg["fields"]["seo"]
    prompt = client.writer.prompts[0]
    assert "phantom blade zero boss fight (suggestion #1)" in prompt
    # The writer picked the last candidate; code picked the one carrying "boss fight".
    assert seo["picked_by"] == "search_score" and "Boss Fight" in f["title"]
    assert seo["title_score"]["score"] == seo["title_score"]["best_candidate"] > 0
    numbered = next(s for s in seo["title_scores"] if "Chapter 1" in s["text"])
    assert numbered["issues"] and numbered["score"] == round(numbered["demand_score"] * 0.8, 3)
    assert "Chapter 1" not in f["title"]
    # Fitting phrases lead the tags, most in demand first (the bare game name came back from more seeds).
    assert f["tags"][:2] == ["phantom blade zero", "phantom blade zero boss fight"]
    assert "zhuo bi" in seo["ambiguous_names"] and "Zhuo Bi" not in f["tags"]
    music = next(p for p in seo["phrases"] if "music" in p["text"])
    assert music["fits"] is False and music["in_tags"] is False
    export = client.get(f"/videos/{video_id}/export.md").text
    assert "## Search demand" in export and "| phantom blade zero boss fight | " in export
