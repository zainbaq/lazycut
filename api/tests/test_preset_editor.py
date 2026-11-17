"""The preset editor's API (5): saves keep the owner's comments and layout, bad edits never reach the file."""

from pathlib import Path

from app.db import session
from app.models import Video
from app.settings import get_settings
from tests.test_packaging import client, seed  # noqa: F401 - the fixture is shared


def preset_file(name: str) -> Path:
    return get_settings().config_dir / "presets" / f"{name}.yaml"


def changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    a, b = before.splitlines(), after.splitlines()
    assert len(a) == len(b)
    return [(x, y) for x, y in zip(a, b, strict=True) if x != y]


def test_saving_unchanged_presets_keeps_the_files_byte_for_byte(client):  # noqa: F811
    for preset_id in ("boss_fight", "general"):
        before = preset_file(preset_id).read_text()
        body = client.get(f"/presets/{preset_id}").json()
        assert client.put(f"/presets/{preset_id}", json=body).status_code == 200
        assert preset_file(preset_id).read_text() == before


def test_a_form_edit_changes_only_its_own_lines(client):  # noqa: F811
    before = preset_file("boss_fight").read_text()
    body = client.get("/presets/boss_fight").json()
    body["slots"]["plain_hook"] = "On-screen text in plain language, no niche jargon."
    body["saved_prompts"][1] = "Finishers"
    body["clip_rules"]["tail_s"] = 0.8
    saved = client.put("/presets/boss_fight", json=body).json()
    assert saved["slots"]["plain_hook"].startswith("On-screen text in plain language, no")
    assert saved["file"] == "presets/boss_fight.yaml"

    after = preset_file("boss_fight").read_text()
    assert changed_lines(before, after) == [
        ("  tail_s: 0.5                 # end this long after the closing event",
         "  tail_s: 0.8                 # end this long after the closing event"),
        ('saved_prompts: ["Longest counter chain", "Finisher", "Phase change"]',
         'saved_prompts: ["Longest counter chain", "Finishers", "Phase change"]'),
        ('  plain_hook: "On-screen text in plain language with a number, no niche jargon."',
         '  plain_hook: "On-screen text in plain language, no niche jargon."'),
    ]
    assert client.get("/presets/boss_fight").json()["clip_rules"]["tail_s"] == 0.8


def test_adding_and_removing_list_items_keeps_the_neighbours(client):  # noqa: F811
    before = preset_file("boss_fight").read_text()
    body = client.get("/presets/boss_fight").json()
    body["event_types"].insert(2, {"id": "dodge", "label": "Dodge", "definition": "The player dodges."})
    body["hooks"] = [h for h in body["hooks"] if h["id"] != "counters"]
    body["thumbnail_words"] = []
    assert client.put("/presets/boss_fight", json=body).status_code == 200
    after = preset_file("boss_fight").read_text()
    assert '  - {id: dodge, label: Dodge, definition: "The player dodges."}' in after
    assert "counter_count} Counters" not in after
    # Emptied, the field keeps its line and its comment.
    assert "thumbnail_words: []           # extra words with no claim attached" in after
    # Untouched entries keep their column alignment.
    assert "  - {id: finisher,     label: Finisher,     glyph: diamond, color: gold," in after
    assert len(after.splitlines()) == len(before.splitlines())  # +1 event type, -1 hook


def test_an_invalid_edit_is_refused_and_the_file_is_untouched(client):  # noqa: F811
    before = preset_file("boss_fight").read_text()
    body = client.get("/presets/boss_fight").json()
    body["hooks"][0]["when"]["fact"] = "nope"
    res = client.put("/presets/boss_fight", json=body)
    assert res.status_code == 422
    assert any("unknown fact `nope`" in d["msg"] for d in res.json()["detail"])
    assert preset_file("boss_fight").read_text() == before

    body = client.get("/presets/boss_fight").json()
    assert client.put("/presets/boss_fight", json=body | {"id": "other"}).status_code == 422


def test_check_reports_problems_with_their_place(client):  # noqa: F811
    body = client.get("/presets/boss_fight").json()
    assert client.post("/presets/boss_fight/check", json={"preset": body}).json() == {"ok": True, "problems": []}
    body["event_types"][0]["glyph"] = "star"
    problems = client.post("/presets/boss_fight/check", json={"preset": body}).json()["problems"]
    assert [p["path"] for p in problems] == ["event_types.0.glyph"]
    # Cross-check problems (reported at the root) are placed by what they name.
    body = client.get("/presets/boss_fight").json()
    body["templates"]["reel"] = "{nope}"
    problems = client.post("/presets/boss_fight/check", json={"preset": body}).json()["problems"]
    assert [p["path"] for p in problems] == ["templates.reel"]
    body = client.get("/presets/boss_fight").json()
    body["hooks"][0]["when"]["fact"] = "nope"
    problems = client.post("/presets/boss_fight/check", json={"preset": body}).json()["problems"]
    assert problems == [{"path": "hooks", "message": "hook `no_hit` refers to unknown fact `nope`"}]
    assert client.post("/presets/boss_fight/check", json={"yaml": "id: [unclosed"}).json()["ok"] is False


def test_copy_keeps_comments_and_ids_must_be_new_and_well_formed(client):  # noqa: F811
    made = client.post("/presets", json={"id": "souls_boss", "name": "Souls boss", "copy_from": "boss_fight"})
    assert made.status_code == 201 and made.json()["name"] == "Souls boss"
    text = preset_file("souls_boss").read_text()
    assert text.startswith("id: souls_boss\nname: Souls boss\n")
    # Everything but the id and name is the original, comments and alignment included.
    assert text.splitlines()[2:] == preset_file("boss_fight").read_text().splitlines()[2:]
    assert client.post("/presets", json={"id": "souls_boss", "name": "Again"}).status_code == 409
    assert client.post("/presets", json={"id": "Bad Id", "name": "X"}).status_code == 422
    assert client.post("/presets", json={"id": "x", "name": "X", "copy_from": "nope"}).status_code == 404
    fresh = client.post("/presets", json={"id": "talk", "name": "Talk"}).json()
    assert fresh["event_types"] == client.get("/presets/general").json()["event_types"]
    assert next(p["id"] for p in client.get("/presets").json()) == "general"


def test_the_yaml_tab_saves_text_as_typed_once_it_validates(client):  # noqa: F811
    text = client.get("/presets/general/yaml").json()["text"]
    edited = text.replace('"Best 30 seconds"', '"Best 20 seconds"') + "# owner's note\n"
    assert client.put("/presets/general/yaml", json={"text": edited}).status_code == 200
    assert preset_file("general").read_text() == edited
    assert "Best 20 seconds" in client.get("/presets/general").json()["saved_prompts"]
    assert client.put("/presets/general/yaml", json={"text": "id: [oops"}).status_code == 422
    assert client.put("/presets/general/yaml", json={"text": text.replace("id: general", "id: other")}).status_code == 422
    assert preset_file("general").read_text() == edited


def test_deleting_a_preset_moves_its_videos_to_general(client):  # noqa: F811
    video_id = seed(client)  # a boss_fight video
    client.post("/presets", json={"id": "spare", "name": "Spare", "copy_from": "boss_fight"})
    with session(client.app.state.engine) as s:
        video = s.get(Video, video_id)
        video.preset_id = "spare"
        s.add(video)
        s.commit()
    assert client.get("/presets/spare").json()["video_count"] == 1
    res = client.delete("/presets/spare")
    assert res.json() == {"deleted": "spare", "videos_switched": 1}
    assert not preset_file("spare").exists()
    assert client.get(f"/videos/{video_id}").json()["preset_id"] == "general"
    assert client.delete("/presets/general").status_code == 409
    assert client.delete("/presets/nope").status_code == 404
