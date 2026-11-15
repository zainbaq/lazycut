"""Past uploads and "Mark as published", and how they feed the package without a new writer call."""

import time

from tests.test_packaging import client, confirm, seed  # noqa: F401 - the fixture is shared


def generate(api, video_id: str) -> dict:
    confirm(api, video_id, "hits_taken", 2)
    job = api.post(f"/videos/{video_id}/packages", json={}).json()
    for _ in range(300):
        if api.get(f"/jobs/{job['id']}").json()["status"] in ("done", "error"):
            break
        time.sleep(0.02)
    return api.get(f"/videos/{video_id}/packages").json()["packages"][0]


def test_past_uploads_crud_and_validation(client):  # noqa: F811
    assert client.get("/library").json() == []
    assert client.post("/library", json={"title": ""}).status_code == 422
    assert client.post("/library", json={"title": "x", "url": "youtube.com/watch"}).status_code == 422
    old = client.post("/library", json={"title": " Older ", "subject": "Byakue", "published_at": "2026-01-01"}).json()
    new = client.post("/library", json={"title": "Newer", "url": "https://youtu.be/abc", "published_at": "2026-06-01"})
    assert new.status_code == 201 and old["title"] == "Older" and old["from_app"] is False
    assert [i["title"] for i in client.get("/library").json()] == ["Newer", "Older"]
    edited = client.patch(f"/library/{old['id']}", json={"angle": "No-hit run", "url": ""}).json()
    assert edited["angle"] == "No-hit run" and edited["url"] == ""
    assert client.patch(f"/library/{old['id']}", json={"title": None}).status_code == 422
    assert client.patch(f"/library/{old['id']}", json={"url": "ftp://x"}).status_code == 422
    assert client.delete(f"/library/{old['id']}").status_code == 204
    assert client.delete(f"/library/{old['id']}").status_code == 404


def test_publishing_adds_the_video_to_past_uploads_and_can_be_undone(client):  # noqa: F811
    video_id = seed(client)
    pkg = generate(client, video_id)
    assert pkg["fields"]["end_screen_target"]["kind"] == "none"

    assert client.post(f"/videos/{video_id}/publish", json={"url": "not a link"}).status_code == 422
    published = client.post(f"/videos/{video_id}/publish", json={"url": "https://youtu.be/gate"}).json()
    item = published["library_item"]
    assert published["display_status"] == "published" and published["published_url"] == "https://youtu.be/gate"
    assert item["from_app"] and item["title"] == pkg["fields"]["title"] and item["subject"] == "Zhuo Bi"
    assert item["hook"] and item["angle"] == item["hook"]  # the recommended title's hook
    # Publishing again updates the same entry instead of adding a second one.
    again = client.post(f"/videos/{video_id}/publish", json={"url": "https://youtu.be/gate2", "published_at": "2026-11-16"})
    assert again.json()["library_item"]["id"] == item["id"]
    assert [i["url"] for i in client.get("/library").json()] == ["https://youtu.be/gate2"]

    # The video's own entry never counts as a repeat, and publishing does not make its package stale.
    after = client.get(f"/videos/{video_id}/packages").json()["packages"][0]
    assert after["stale"] is False
    assert next(r for r in after["rule_results"] if r["rule_id"] == "cannibalization")["severity"] == "pass"

    restored = client.delete(f"/videos/{video_id}/publish").json()
    assert restored["published_url"] is None and restored["display_status"] == "packaged"
    assert client.get("/library").json() == []


def test_past_uploads_refresh_the_end_screen_and_repeat_check_for_free(client):  # noqa: F811
    video_id = seed(client)
    pkg = generate(client, video_id)
    calls = len(client.writer.prompts)
    client.post("/library", json={"title": "Phantom Blade Zero - Zhuo Bi First Try", "subject": "Zhuo Bi",
                                  "topic": "Phantom Blade Zero", "url": "https://youtu.be/first",
                                  "published_at": "2026-10-01"})
    after = client.get(f"/videos/{video_id}/packages").json()["packages"][0]
    assert len(client.writer.prompts) == calls  # no new writer call
    assert after["version"] == pkg["version"] and after["stale"] is False
    assert after["fields"]["end_screen_target"]["url"] == "https://youtu.be/first"
    end_line = next(c for c in after["fields"]["checklist"] if c["item"] == "End screen")
    assert "First Try" in end_line["detail"]
    assert next(r for r in after["rule_results"] if r["rule_id"] == "cannibalization")["severity"] == "warn"
