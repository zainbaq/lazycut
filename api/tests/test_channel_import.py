"""Past uploads imported from the channel (Phase 3): reading titles, merging, Shorts, playlists, repeats."""

import time

import pytest

from app.db import session
from app.models import LibraryItem
from app.services.rules import RuleContext, repeats
from app.services.title_reader import TitleReader
from app.services.youtube import Channel, Playlist, Upload, seconds
from app.settings import get_settings
from tests.test_packaging import client, seed  # noqa: F401 - the fixture is shared

# Real layouts from the owner's channel, oldest to newest.
TITLES = [
    "Phantom Blade Zero - Hua, Deadly Betrothed Boss Fight (Optional Boss)",
    "Onimusha Way of the Sword - Byakue No Damage Boss Fight (Issen Mastery)",
    "Onimusha Way of the Sword - Final Boss Yoshitsune (No Damage)",
    "Onimusha Way of the Sword Greater Nue Boss Fight | What Lurks in the Shadows",
    "Onimusha Way of the Sword Byakue #2 Boss Fight | Hundred Defilements",
    "Onimusha: Way of the Sword - Benkei Boss Fight (1 Hit Taken)",
    "Everdark Caligo, Miasma of Night - Elden Ring Nightreign Enhanced Bossfight",
    "Markiona, Puppeteer of Death - Lies of  P: Overture DLC Bossfight",
    "Lumacchio, Leader of the Bastards - Lies of P: Overture Bossfight",
    "Inner Owl (No HUD / No Damage) - Sekiro: Shadows Die Twice",
    "Old Demon King || Dark Souls 3",
    "Abyss Watchers (Katana Parry) | Dark Souls 3",
    "Dark Souls 3: Aldrich, Saint of the Deep Boss Fight (Pyromancy + Profaned Greatsword)",
    "Supreme Inspector - Black Myth: Wukong Bossfight",
    "Elden Ring: Shadow of the Erdtree - Putrescent Knight",
    "Elden Ring: Shadow of the Erdtree - Commander Gaius",
    "Bullying Rellana, Twin Moon Knight in Elden Ring: Shadows of the Erdtree",
    "Tyr - \"Master Thyself\" - God of War Ragnarök Valhalla",
    "God of War Ragnarök Valhalla: Fraekni The Zealous",
    "Rise of the Ronin - Dojo - Genzui Kusaka (Master Rank, Midnight)",
]
PLAYLISTS = ["Phantom Blade Zero", "Onimusha: Way of the Sword", "Elden Ring", "Nightreign", "Lies of P",
             "Sekiro: Shadows Die Twice", "Black Myth - Wukong", "God of War", "Rise of the Ronin"]
CLAIMS = ["No Hit", "No Damage", "Final Boss"]


@pytest.mark.parametrize(("title", "topic", "subject", "angle"), [
    (TITLES[0], "Phantom Blade Zero", "Hua, Deadly Betrothed", "Optional Boss"),
    (TITLES[1], "Onimusha Way of the Sword", "Byakue", "Issen Mastery · No Damage"),
    (TITLES[2], "Onimusha Way of the Sword", "Yoshitsune", "No Damage · Final Boss"),
    (TITLES[3], "Onimusha Way of the Sword", "Greater Nue", "What Lurks in the Shadows"),
    (TITLES[4], "Onimusha Way of the Sword", "Byakue", "Hundred Defilements"),
    (TITLES[6], "Elden Ring Nightreign", "Everdark Caligo, Miasma of Night", ""),
    (TITLES[7], "Lies of P: Overture", "Markiona, Puppeteer of Death", ""),
    (TITLES[9], "Sekiro: Shadows Die Twice", "Inner Owl", "No HUD / No Damage"),
    (TITLES[10], "Dark Souls 3", "Old Demon King", ""),
    (TITLES[11], "Dark Souls 3", "Abyss Watchers", "Katana Parry"),
    (TITLES[12], "Dark Souls 3", "Aldrich, Saint of the Deep", "Pyromancy + Profaned Greatsword"),
    (TITLES[13], "Black Myth: Wukong", "Supreme Inspector", ""),
    (TITLES[14], "Elden Ring: Shadow of the Erdtree", "Putrescent Knight", ""),
    (TITLES[16], "Elden Ring: Shadows of the Erdtree", "Bullying Rellana, Twin Moon Knight", ""),
    (TITLES[18], "God of War Ragnarök Valhalla", "Fraekni The Zealous", ""),
    (TITLES[19], "Rise of the Ronin", "Dojo - Genzui Kusaka", "Master Rank, Midnight"),
])
def test_titles_are_read_from_the_channels_own_evidence(title, topic, subject, angle):
    reading = TitleReader(TITLES, PLAYLISTS, CLAIMS).read(title)
    assert (reading.topic, reading.subject, reading.angle) == (topic, subject, angle)
    assert reading.by in ("playlist", "repeated")


def test_a_title_with_nothing_to_go_on_is_left_for_the_owner():
    reading = TitleReader(TITLES, PLAYLISTS, CLAIMS).read("Avatar Legends: The Fighting Game - This Katara DESTROYED Me Online")
    assert reading.by == "" and reading.topic == ""


def test_iso_durations():
    assert seconds("PT3M24S") == 204 and seconds("PT1M") == 60 and seconds("PT35S") == 35 and seconds("PT1H2M") == 3720


class FakeYouTube:
    def __init__(self, uploads, playlists, shorts, unsure=()):
        self.units = 0
        self._uploads, self._playlists, self._shorts, self._unsure = uploads, playlists, set(shorts), set(unsure)
        self.checked: list[str] = []

    async def channel(self, handle):
        self.units += 1
        return Channel("UC1", "TheLazyRonin", handle, "UU1", 101, len(self._uploads))

    async def uploads(self, channel):
        self.units += 2
        return list(self._uploads)

    async def playlists(self, channel):
        self.units += 1 + len(self._playlists)
        return list(self._playlists)

    async def is_short(self, video_id):
        self.checked.append(video_id)
        return None if video_id in self._unsure else video_id in self._shorts


def up(vid, title, secs, views=10, date="2026-09-01T10:00:00Z"):
    return Upload(id=vid, title=title, published_at=date, duration_s=secs, views=views)


UPLOADS = [
    up("byakue00001", "Onimusha Way of the Sword - Byakue No Damage Boss Fight (Issen Mastery)", 85),
    up("benkei00001", "Onimusha: Way of the Sword - Benkei Boss Fight (1 Hit Taken)", 262),
    up("short000001", "6 Issens in a row on Byakue 😤 #Onimusha", 32, views=968),
    up("unsure00001", "Countered Burai #Onimusha", 50),
    up("pbz00000001", "Phantom Blade Zero - Jagged Steel Boss Fight (Best Early Bleed Weapon)", 92),
]
LISTS = [
    Playlist("PLRXz5KwhnmcA", "Onimusha: Way of the Sword", 2, ["byakue00001", "benkei00001"]),
    Playlist("PLRqBAd29j2jY", "Phantom Blade Zero", 1, ["pbz00000001"]),
]


def run(api, fake) -> dict:
    api.app.state.runner.deps.youtube_client = lambda: fake
    job = api.post("/library/import").json()
    for _ in range(300):
        state = api.get(f"/jobs/{job['id']}").json()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.02)
    raise AssertionError("the import did not finish")


@pytest.fixture
def keyed(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    get_settings.cache_clear()
    return client


def test_import_needs_a_key(client):  # noqa: F811
    assert client.post("/library/import").status_code == 422
    status = client.get("/library/import").json()
    assert status["can_import"] is False and status["key_set"] is False and status["last"] is None


def test_import_merges_uploads_keeps_the_owners_words_and_tells_shorts_apart(keyed):
    # A past upload typed in by hand, linked by its URL; the owner's subject must survive.
    keyed.post("/library", json={"title": "Benkei fight", "subject": "Benkei (owner's words)",
                                 "url": "https://youtu.be/benkei00001"})
    fake = FakeYouTube(UPLOADS, LISTS, shorts={"short000001"}, unsure={"unsure00001"})
    job = run(keyed, fake)
    assert job["status"] == "done", job
    assert "5 uploads read: 3 videos and 2 Shorts" in job["message"]

    items = {i["youtube_id"]: i for i in keyed.get("/library").json()}
    assert len(items) == 5  # the typed entry was linked, not duplicated
    byakue = items["byakue00001"]
    assert (byakue["topic"], byakue["subject"], byakue["angle"]) == ("Onimusha Way of the Sword", "Byakue", "Issen Mastery · No Damage")
    assert byakue["kind"] == "long" and byakue["source"] == "youtube" and byakue["read_by"] == "playlist"
    assert byakue["playlist"] == "Onimusha: Way of the Sword" and byakue["published_at"] == "2026-09-01"
    assert byakue["url"] == "https://www.youtube.com/watch?v=byakue00001"
    benkei = items["benkei00001"]
    assert benkei["subject"] == "Benkei (owner's words)" and benkei["read_by"] == "you" and benkei["source"] == "youtube"
    assert benkei["url"] == "https://youtu.be/benkei00001"  # the owner's link stays
    assert items["short000001"]["kind"] == "short" and items["short000001"]["subject"] == ""
    assert items["unsure00001"]["kind"] == "short"  # the check did not answer; 50 s falls back to a Short
    # Only the uploads short enough to be a Short were checked (the 262 s one was not).
    assert "benkei00001" not in fake.checked and "byakue00001" in fake.checked

    last = keyed.get("/library/import").json()["last"]
    assert (last["new"], last["linked"], last["long"], last["shorts"], last["shorts_unsure"]) == (4, 1, 3, 2, 1)
    by_id = {p["id"]: p for p in last["playlists"]}
    assert by_id["PLRXz5KwhnmcA"]["in_config"]["topic"] == "Onimusha: Way of the Sword"  # the short id is real
    assert by_id["PLRqBAd29j2jY"]["in_config"] is None


def test_reimport_updates_in_place_and_respects_edits(keyed):
    run(keyed, FakeYouTube(UPLOADS, LISTS, shorts={"short000001"}))
    byakue = next(i for i in keyed.get("/library").json() if i["youtube_id"] == "byakue00001")
    keyed.patch(f"/library/{byakue['id']}", json={"angle": "Issen only"})
    again = [up("byakue00001", UPLOADS[0].title, 85, views=500)] + UPLOADS[1:]
    fake = FakeYouTube(again, LISTS, shorts=set())
    assert run(keyed, fake)["status"] == "done"
    items = {i["youtube_id"]: i for i in keyed.get("/library").json()}
    assert len(items) == 5 and items["byakue00001"]["views"] == 500
    assert items["byakue00001"]["angle"] == "Issen only" and items["byakue00001"]["read_by"] == "you"
    assert items["short000001"]["kind"] == "short"  # an imported upload keeps its kind
    assert fake.checked == []  # nothing new to check


def test_adding_playlists_to_channel_yaml_keeps_the_file(keyed):
    run(keyed, FakeYouTube(UPLOADS, LISTS, shorts=set()))
    path = get_settings().config_dir / "channel.yaml"
    before = path.read_text()
    res = keyed.post("/library/playlists", json={"ids": ["PLRqBAd29j2jY"]}).json()
    assert res["added"] == [{"topic": "Phantom Blade Zero", "name": "Phantom Blade Zero",
                             "url": "https://www.youtube.com/playlist?list=PLRqBAd29j2jY"}]
    after = path.read_text()
    new_lines = [line for line in after.splitlines() if line not in before.splitlines()]
    assert new_lines == ['  - {topic: "Phantom Blade Zero", name: "Phantom Blade Zero", url: "https://www.youtube.com/playlist?list=PLRqBAd29j2jY"}']
    assert len(after.splitlines()) == len(before.splitlines()) + 1
    assert all(p["in_config"] for p in res["last"]["playlists"])
    assert keyed.post("/library/playlists", json={"ids": ["PLnope"]}).status_code == 404


def ctx(subject, topic, past, research=None) -> RuleContext:
    from app.services.presets import BUILTIN_GENERAL

    return RuleContext(platform="youtube", preset=BUILTIN_GENERAL, channel=None, topic=topic, subject=subject,
                       facts={}, research=research or {}, past_subjects=past)


def test_repeats_match_names_within_the_same_game():
    past = [
        {"title": "Onimusha Way of the Sword - Byakue No Damage Boss Fight", "subject": "Byakue", "topic": "Onimusha Way of the Sword"},
        {"title": "Sekiro: Shadows Die Twice - Inner Genichiro", "subject": "Inner Genichiro", "topic": "Sekiro: Shadows Die Twice"},
        {"title": "Elden Ring: Shadow of the Erdtree - Commander Gaius", "subject": "Commander Gaius", "topic": "Elden Ring: Shadow of the Erdtree"},
    ]
    assert [p["subject"] for p in repeats(ctx("Byakue", "Onimusha: Way of the Sword", past))] == ["Byakue"]
    assert repeats(ctx("Byakue", "Phantom Blade Zero", past)) == []  # same name, other game
    # A nickname from research finds an upload titled by it; a DLC topic counts as the same game.
    assert [p["subject"] for p in repeats(ctx("Gaius", "Elden Ring", past, {"nicknames": "Commander Gaius"}))] == ["Commander Gaius"]
    assert repeats(ctx("Genichiro Ashina", "Sekiro: Shadows Die Twice", past)) == []


def test_a_short_never_makes_a_subject_a_repeat(client):  # noqa: F811
    video_id = seed(client)  # Zhuo Bi, Phantom Blade Zero
    with session(client.app.state.engine) as s:
        s.add(LibraryItem(title="Zhuo Bi parry #shorts", subject="Zhuo Bi", topic="Phantom Blade Zero", kind="short",
                          url="https://www.youtube.com/shorts/aaaaaaaaaaa"))
        s.commit()
    from tests.test_library import generate

    pkg = generate(client, video_id)
    rule = next(r for r in pkg["rule_results"] if r["rule_id"] == "cannibalization")
    assert rule["severity"] == "pass" and pkg["fields"]["end_screen_target"]["kind"] != "past_upload"
