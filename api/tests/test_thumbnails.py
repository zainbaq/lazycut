"""Thumbnail creator (7.13): settings, prompts, frame scoring, the word overlay, the Higgsfield client and the API."""

import asyncio
import io
import itertools
import json
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter

from app.db import session
from app.models import Event, Package, Research, Segment, Video
from app.services import thumbnails as tn
from app.services.higgsfield import Higgsfield, HiggsfieldError
from app.services.llm.base import LLMResult
from app.services.research import name_key

CONFIG = Path(__file__).resolve().parents[2] / "config"
CFG = tn.load_config(CONFIG)[0]


def picture(size=(1280, 720), seed=0, blur=0) -> Image.Image:
    img = Image.new("RGB", size, (30, 40, 60))
    d = ImageDraw.Draw(img)
    for i in range(0, size[0], 40):
        d.rectangle((i, (i * 7 + seed * 50) % size[1], i + 20, size[1]), fill=((i * 3 + seed * 40) % 255, 120, 200))
    return img.filter(ImageFilter.GaussianBlur(blur)) if blur else img


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_the_backdrop_check_measures_the_picture_not_the_word(tmp_path):
    from types import SimpleNamespace

    from app.services.thumbnail_jobs import code_checks

    def backdrop(raw: Image.Image) -> bool:
        raw.save(tmp_path / "raw.png")
        row = SimpleNamespace(aspect="16:9", text_mode="app", word="2 V 1", text_corner="top_right",
                              raw_path=str(tmp_path / "raw.png"))
        final = tn.render_final(raw, aspect="16:9", word="2 V 1", text_style="white, heavy black outline",
                                corner="top_right", font="bebas", text_mode="app")
        return next(c for c in code_checks(row, final) if c["id"] == "backdrop")["ok"]

    assert backdrop(Image.new("RGB", (1280, 720), (90, 110, 140)))  # flat sky: the drawn word must not count as busy
    stripes = Image.new("RGB", (1280, 720), (0, 0, 0))
    for x in range(0, 1280, 16):
        ImageDraw.Draw(stripes).rectangle((x, 0, x + 7, 720), fill=(255, 255, 255))
    assert not backdrop(stripes)


# ---- settings and prompts -----------------------------------------------------------


def test_the_shipped_config_loads_and_overrides_are_checked():
    assert CFG is not None and CFG.default_model in CFG.models
    eff = tn.effective(CFG, tn.Overrides(model="ideogram_4", params={"ideogram_4": {"image_weight": 85}}))
    assert eff.model == "ideogram_4" and eff.model_params("ideogram_4")["image_weight"] == 85
    assert eff.model_params("ideogram_4")["rendering_speed"] == "QUALITY"  # untouched defaults stay
    problems = tn.validate_overrides(CFG, tn.Overrides(model="nope", params={"grok_image_2": {"quality": "ultra"},
                                                                             "qwen_image_3_edit": {"seed": 1}}))
    assert any("nope" in p for p in problems) and any("quality must be one of" in p for p in problems)
    assert any("no option `seed`" in p for p in problems)
    echoed = tn.Overrides(params={"qwen_image_3_edit": eff.model_params("qwen_image_3_edit")})
    assert tn.validate_overrides(CFG, echoed) == []  # params sent back as GET shows them are fine


def test_prompts_fill_variables_and_follow_the_text_mode():
    eff = tn.effective(CFG, None)
    app = tn.build_prompt(eff, template=None, topic="Phantom Blade Zero", subject="Zhuo Bi", word="2 HITS",
                          text_style="white", corner="top_left", aspect="16:9")
    assert "Zhuo Bi" in app and "Phantom Blade Zero" in app and "top left corner" in app
    assert "Do not add any text" in app and "2 HITS" not in app and "{" not in app
    model = tn.build_prompt(eff, template=None, topic="PB0", subject="Zhuo Bi", word="2 HITS",
                            text_style="gold, black outline", corner="top_right", aspect="9:16", text_mode="model")
    assert '"2 HITS"' in model and "gold, black outline" in model and "top 12%" in model
    own = tn.build_prompt(eff, template="My style for {subject}, keep {json: braces}", topic="", subject="Zhuo Bi",
                          word="", text_style="", corner="top_right", aspect="16:9")
    assert own == "My style for Zhuo Bi, keep {json: braces}"


def test_request_bodies_match_each_models_fields():
    grok = tn.request_body(CFG.models["grok_image_2"], {"quality": "medium"}, "p", "https://x/s.jpg", "16:9", "app")
    assert grok["image_urls"] == ["https://x/s.jpg"] and grok["aspect_ratio"] == "16:9"
    ideo = tn.request_body(CFG.models["ideogram_4"], {}, "p", "https://x/s.jpg", "9:16", "app")
    assert ideo["image_url"] == "https://x/s.jpg" and "image_urls" not in ideo
    qwen = tn.request_body(CFG.models["qwen_image_3_edit"], {}, "p", "https://x/s.jpg", "16:9", "app")
    assert "text" in qwen["negative_prompt"]
    assert "text" not in tn.request_body(CFG.models["qwen_image_3_edit"], {}, "p", "u", "16:9", "model")["negative_prompt"]


def test_text_styles_read_colours_and_outlines():
    s = tn.parse_style("gold, heavy black outline")
    assert s.fill == tn.COLORS["gold"] and s.stroke == tn.COLORS["black"] and not s.glow
    s = tn.parse_style("white text with a red outline and glow")
    assert s.fill == tn.COLORS["white"] and s.stroke == tn.COLORS["red"] and s.glow


# ---- frame finder -------------------------------------------------------------------


def test_candidate_times_keep_reasons_drop_neighbours_and_fill_evenly():
    times = tn.candidate_times(100.0, writer_ts=[12.0, 12.4], peaks=[(40.0, 44.0)],
                               events=[(41.5, 42.5, "parry")], intensity=[(70.0, 1.0), (70.5, 0.9)])
    ts = [t for t, _ in times]
    assert (12.0, "picked by the writer") in times and 12.4 not in ts
    assert 42.0 in ts and all(b - a >= 1.0 for a, b in itertools.pairwise(ts))
    assert any(why == "evenly spaced" for _, why in times) and len(times) <= 24


def test_sharp_frames_win_and_duplicates_collapse():
    frames = [{"t": float(i), "why": "x", "drama": 0.0, "stats": tn.frame_stats(img)}
              for i, img in enumerate([picture(seed=1), picture(seed=1), picture(seed=2, blur=6), picture(seed=3)])]
    kept = tn.score_frames(frames)
    assert len(kept) == 3  # the exact duplicate is gone
    assert kept[-1]["t"] == 2.0  # the blurred one ranks last
    for f in frames:
        f["moment"] = 0.0 if f["t"] < 2 else 5.0
    assert [f["t"] for f in tn.score_frames(frames)] in ([0.0, 3.0], [1.0, 3.0], [3.0, 0.0], [3.0, 1.0])


# ---- overlay ------------------------------------------------------------------------


def test_the_word_lands_in_its_corner_and_the_file_fits_youtube():
    base = Image.new("RGB", (1600, 900), (40, 40, 40))
    out = tn.render_final(base, aspect="16:9", word="2 HITS", text_style="gold, black outline",
                          corner="top_right", font="bebas", text_mode="app")
    img = Image.open(io.BytesIO(out))
    assert img.size == (1280, 720) and len(out) <= tn.MAX_BYTES
    tr = img.crop((800, 30, 1250, 250)).convert("L").getextrema()
    bl = img.crop((30, 470, 480, 690)).convert("L").getextrema()
    assert tr[1] - tr[0] > 100 and bl[1] - bl[0] < 20  # text top right, nothing bottom left
    tall = Image.open(io.BytesIO(tn.render_final(base, aspect="9:16", word="NO HIT", text_style="white",
                                                 corner="top_left", font="bebas", text_mode="app",
                                                 safe={"top_pct": 12, "bottom_pct": 15})))
    assert tall.size == (1080, 1920)
    top_band = tall.crop((0, 0, 1080, int(1920 * 0.11))).convert("L").getextrema()
    assert top_band[1] - top_band[0] < 30  # the safe margin stays clear
    model_drawn = Image.open(io.BytesIO(tn.render_final(base, aspect="16:9", word="2 HITS", text_style="gold",
                                                        corner="top_right", font="bebas", text_mode="model")))
    assert model_drawn.convert("L").getextrema()[1] < 60  # the app draws nothing when the model wrote the text


# ---- Higgsfield client --------------------------------------------------------------


def test_client_uploads_submits_polls_and_maps_errors():
    calls: list[tuple[str, str, dict]] = []
    states = iter(["queued", "in_progress", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), dict(request.headers)))
        url = str(request.url)
        if url.endswith("/files/generate-upload-url"):
            return httpx.Response(200, json={"upload_url": "https://store.test/put", "public_url": "https://cdn.test/s.jpg",
                                             "upload_headers": {"Content-Type": "image/jpeg"}})
        if url == "https://store.test/put":
            return httpx.Response(200)
        if url.endswith("/estimate/xai/grok-imagine-image-2.0"):
            return httpx.Response(200, json={"usd": "0.06"})
        if url.endswith("/xai/grok-imagine-image-2.0"):
            return httpx.Response(200, json={"status": "queued", "request_id": "r1",
                                             "status_url": "https://api.test/requests/r1/status"})
        if url.endswith("/requests/r1/status"):
            st = next(states)
            body = {"status": st, "request_id": "r1"}
            if st == "completed":
                body["images"] = [{"url": "https://cdn.test/out.png"}]
            return httpx.Response(200, json=body)
        if url.endswith("/broke"):
            return httpx.Response(403, json={"detail": "Insufficient balance"})
        return httpx.Response(404)

    async def no_sleep(_s):
        return None

    hf = Higgsfield("kid:ksecret", "https://api.test", transport=httpx.MockTransport(handler), sleep=no_sleep)

    async def go():
        url = await hf.upload(b"jpeg", "image/jpeg")
        usd = await hf.estimate("xai/grok-imagine-image-2.0", {"prompt": "p"})
        gen = await hf.generate("xai/grok-imagine-image-2.0", {"prompt": "p"})
        return url, usd, gen

    url, usd, gen = asyncio.run(go())
    assert url == "https://cdn.test/s.jpg" and usd == 0.06
    assert gen.status == "completed" and gen.images == ["https://cdn.test/out.png"]
    put = next(c for c in calls if c[1] == "https://store.test/put")
    assert "authorization" not in put[2]  # credentials never go to the presigned URL
    submit = next(c for c in calls if c[1] == "https://api.test/xai/grok-imagine-image-2.0")
    assert submit[2]["authorization"] == "Key kid:ksecret" and submit[2].get("idempotency-key")
    with pytest.raises(HiggsfieldError) as err:
        asyncio.run(hf.generate("broke", {}))
    assert err.value.status == 403 and "balance" in str(err.value)


# ---- API ----------------------------------------------------------------------------


class FakeImages:
    def __init__(self) -> None:
        self.bodies: list[tuple[str, dict]] = []
        self.uploads = 0
        self.status = "completed"

    async def upload(self, data, content_type):
        self.uploads += 1
        assert Image.open(io.BytesIO(data)).width >= 320
        return f"https://cdn.test/src{self.uploads}.jpg"

    async def estimate(self, path, body):
        return 0.05

    async def generate(self, path, body, on_status=None):
        from app.services.higgsfield import Generation

        self.bodies.append((path, body))
        if on_status:
            on_status("in_progress")
        if self.status != "completed":
            return Generation(request_id="r", status=self.status, error="nope")
        return Generation(request_id=f"r{len(self.bodies)}", status="completed",
                          images=[f"https://cdn.test/out.png?a={body['aspect_ratio']}"])

    async def download(self, url):
        size = (1344, 768) if "16:9" in url else (768, 1344)
        return png(picture(size, seed=len(self.bodies)))


class FakeClaude:
    model = "fake-claude"

    def __init__(self) -> None:
        self.looks: list[tuple[str, int]] = []

    async def look_json(self, prompt, images, schema, effort="low"):
        self.looks.append((schema.__name__, len(images)))
        if schema is tn.FrameRanking:
            parsed = tn.FrameRanking(frames=[tn.FrameJudgement(
                index=i, score=10 - i, subject_visible=True, hud="light", text_corner="top_left", reason="clear")
                for i in range(len(images))])
        else:
            parsed = tn.ReviewOut(checks=[tn.Check(id=c, ok=c != "hands", note="fine" if c != "hands" else "six fingers")
                                          for c in tn.REVIEW_IDS], summary="One hand looks wrong.")
        return LLMResult(parsed=parsed, raw_text="{}", model=self.model, usage={"input_tokens": 900}, latency_s=1.0)

    async def generate_json(self, prompt, schema, search=False, effort="low"):
        raise AssertionError("no writing in these tests")


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = tmp_path / "config"
    shutil.copytree(CONFIG, config)
    for name in ("inbox", "data"):
        (tmp_path / name).mkdir()
    for key, value in {
        "INBOX_DIR": tmp_path / "inbox", "DATA_DIR": tmp_path / "data", "CONFIG_DIR": config,
        "DB_PATH": tmp_path / "db" / "app.db", "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": "",
        "HIGGSFIELD_API_KEY": "", "HIGGSFIELD_KEY_ID": "", "HIGGSFIELD_KEY_SECRET": "",
    }.items():
        monkeypatch.setenv(key, str(value))
    from app import main
    from app.settings import get_settings

    get_settings.cache_clear()
    claude, images = FakeClaude(), FakeImages()
    monkeypatch.setattr(main, "claude_factory", lambda _settings: lambda: claude)
    with TestClient(main.app) as test_client:
        test_client.app.state.runner.deps.image_client = lambda: images
        test_client.claude, test_client.images, test_client.tmp = claude, images, tmp_path
        yield test_client
    get_settings.cache_clear()


def seed(client: TestClient) -> str:
    clip = client.tmp / "inbox" / "fight.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=1280x720:rate=30:duration=12", "-pix_fmt", "yuv420p", str(clip)], check=True)
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", subject="Zhuo Bi", topic="Phantom Blade Zero", preset_id="boss_fight",
                      status="ready", duration_s=12.0, width=1280, height=720, source_path=str(clip),
                      proxy_path=str(clip))
        s.add(video)
        s.flush()
        s.add_all([
            Event(video_id=video.id, t_start=3.0, t_end=4.0, type="counter", intensity="high", source="model"),
            Segment(video_id=video.id, kind="peak", t_start=7.0, t_end=9.0),
            Research(subject_key=name_key("Zhuo Bi"), topic_key=name_key("Phantom Blade Zero"),
                     payload={"method": "search", "canonical_name": "Zhuo Bi", "fields": {}}),
            Package(video_id=video.id, platform="youtube", fields={"thumbnail": {
                "frame_ts": [5.0], "word_options": ["2 HITS", "SHIELD"], "text_style": "white, heavy black outline"}}),
        ])
        s.commit()
        return video.id


def wait(client: TestClient, job: dict) -> dict:
    for _ in range(1500):
        state = client.get(f"/jobs/{job['id']}").json()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_find_frames_generate_compare_adjust_and_choose(client):
    video_id = seed(client)
    state = client.get(f"/videos/{video_id}/thumbnails").json()
    assert state["can_generate"] and state["frames"] is None and [w["word"] for w in state["words"]] == ["2 HITS", "SHIELD"]

    job = client.post(f"/videos/{video_id}/thumbnails/frames").json()
    assert wait(client, job)["status"] == "done"
    frames = client.get(f"/videos/{video_id}/thumbnails").json()["frames"]
    assert frames["ranked_by"] == "claude" and len(frames["frames"]) >= 2
    assert ("FrameRanking", len(frames["frames"])) in client.claude.looks or client.claude.looks[0][0] == "FrameRanking"
    best = frames["frames"][0]
    assert best["claude"]["score"] == 10 and best["text_corner"] == "top_left"

    r = client.post(f"/videos/{video_id}/thumbnails", json={
        "source": {"kind": "frame", "t": best["t"]}, "models": ["grok_image_2", "ideogram_4"],
        "aspects": ["16:9", "9:16"]})
    assert r.status_code == 202, r.text
    out = r.json()
    assert len(out["thumbnails"]) == 4 and {t["text_corner"] for t in out["thumbnails"]} == {"top_left"}
    assert wait(client, out["job"])["status"] == "done"
    rows = client.get(f"/videos/{video_id}/thumbnails").json()["thumbnails"]
    assert [t["error"] for t in rows] == [None] * 4
    assert client.images.uploads == 1  # one source upload shared by the batch
    paths = sorted(p for p, _ in client.images.bodies)
    assert paths == ["ideogram/v4.0", "ideogram/v4.0", "xai/grok-imagine-image-2.0", "xai/grok-imagine-image-2.0"]
    rows = client.get(f"/videos/{video_id}/thumbnails").json()["thumbnails"]
    assert all(t["status"] == "done" and t["cost_usd"] == 0.05 for t in rows)
    wide = next(t for t in rows if t["aspect"] == "16:9" and t["model"] == "grok_image_2")
    assert wide["word"] == "2 HITS" and wide["review"]["verdict"] == "check" and wide["review"]["problems"] == 1
    assert {c["id"] for c in wide["review"]["code"]} == {"file", "backdrop"}
    img = Image.open(io.BytesIO(client.get(wide["urls"]["final"]).content))
    assert img.size == (1280, 720)
    tall = next(t for t in rows if t["aspect"] == "9:16")
    assert Image.open(io.BytesIO(client.get(tall["urls"]["final"]).content)).size == (1080, 1920)

    # Redraw the word for free, then choose; choosing is one per aspect.
    before = client.get(wide["urls"]["final"]).content
    r = client.patch(f"/thumbnails/{wide['id']}", json={"word": "SHIELD", "text_corner": "bottom_right"})
    assert r.status_code == 200 and r.json()["review"]["stale"] is True
    assert client.get(r.json()["urls"]["final"]).content != before
    other = next(t for t in rows if t["aspect"] == "16:9" and t["model"] == "ideogram_4")
    client.patch(f"/thumbnails/{wide['id']}", json={"chosen": True})
    client.patch(f"/thumbnails/{other['id']}", json={"chosen": True})
    chosen = [t["id"] for t in client.get(f"/videos/{video_id}/thumbnails").json()["thumbnails"]
              if t["chosen"] and t["aspect"] == "16:9"]
    assert chosen == [other["id"]]

    # An unbacked claim as the word is refused before any paid call.
    r = client.post(f"/videos/{video_id}/thumbnails", json={"source": {"kind": "frame", "t": 2.0}, "word": "NO HIT"})
    assert r.status_code == 422 and "hit" in r.json()["detail"].lower()

    dl = client.get(f"/thumbnails/{wide['id']}/image?download=true")
    assert dl.headers["content-disposition"].endswith('_thumbnail_16x9.jpg"')


def test_uploads_failures_review_again_and_settings(client):
    video_id = seed(client)
    r = client.post(f"/videos/{video_id}/thumbnails/uploads", content=b"not an image",
                    headers={"Content-Type": "image/png"})
    assert r.status_code == 422
    up = client.post(f"/videos/{video_id}/thumbnails/uploads", content=png(picture()),
                     headers={"Content-Type": "image/png"}).json()
    assert client.get(up["url"]).status_code == 200

    client.images.status = "nsfw"
    out = client.post(f"/videos/{video_id}/thumbnails",
                      json={"source": {"kind": "upload", "upload_id": up["id"]}, "word": ""}).json()
    assert wait(client, out["job"])["status"] == "error"
    row = client.get(f"/videos/{video_id}/thumbnails").json()["thumbnails"][0]
    assert row["status"] == "nsfw" and "not charged" in row["error"] and row["cost_usd"] is None

    client.images.status = "completed"
    out = client.post(f"/videos/{video_id}/thumbnails", json={
        "source": {"kind": "upload", "upload_id": up["id"]}, "prompt": "Make {subject} look heroic.",
        "text_mode": "model"}).json()
    assert wait(client, out["job"])["status"] == "done"
    path, body = client.images.bodies[-1]
    assert body["prompt"] == "Make Zhuo Bi look heroic." and path == "xai/grok-imagine-image-2.0"
    row = next(t for t in client.get(f"/videos/{video_id}/thumbnails").json()["thumbnails"] if t["id"] == out["thumbnails"][0]["id"])
    assert row["custom_prompt"] and row["text_mode"] == "model"
    assert client.patch(f"/thumbnails/{row['id']}", json={"word": "X"}).status_code == 422  # the model drew the text
    looks = len(client.claude.looks)
    assert wait(client, client.post(f"/thumbnails/{row['id']}/review").json())["status"] == "done"
    assert len(client.claude.looks) == looks + 1

    s = client.get("/settings/thumbnails").json()
    assert s["model"] == "grok_image_2" and s["keys"]["higgsfield"] and {m["id"] for m in s["models"]} >= {"ideogram_4"}
    bad = client.put("/settings/thumbnails", json={"params": {"grok_image_2": {"quality": "ultra"}}})
    assert bad.status_code == 422
    good = client.put("/settings/thumbnails", json={"model": "qwen_image_3_edit", "aspects": ["16:9", "9:16"],
                                                     "prompt": "Mine: {subject}", "review": False}).json()
    assert good["model"] == "qwen_image_3_edit" and good["custom_prompt"] and good["aspects"] == ["16:9", "9:16"]
    out = client.post(f"/videos/{video_id}/thumbnails", json={"source": {"kind": "frame", "t": 4.0}}).json()
    assert len(out["thumbnails"]) == 2 and {t["model"] for t in out["thumbnails"]} == {"qwen_image_3_edit"}
    assert wait(client, out["job"])["status"] == "done"
    rows = client.get(f"/videos/{video_id}/thumbnails").json()["thumbnails"]
    assert all(t["review"]["verdict"] is None for t in rows if t["batch_id"] == out["batch_id"])  # review off
    reset = client.delete("/settings/thumbnails").json()
    assert reset["model"] == "grok_image_2" and not reset["custom_prompt"]
    assert json.dumps(reset).count("Mine:") == 0


def test_the_key_is_read_from_one_value_or_two(monkeypatch):
    from app.settings import Settings

    for name in ("HIGGSFIELD_API_KEY", "HIGGSFIELD_KEY_ID", "HIGGSFIELD_KEY_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert Settings(_env_file=None).higgsfield_credential == ""
    assert Settings(_env_file=None, higgsfield_api_key="a:b").higgsfield_credential == "a:b"
    assert Settings(_env_file=None, higgsfield_key_id="a", higgsfield_key_secret="b").higgsfield_credential == "a:b"
    assert Settings(_env_file=None, higgsfield_key_secret="a:b").higgsfield_credential == "a:b"  # the console key, pasted as the secret
    assert Settings(_env_file=None, higgsfield_key_secret="half").higgsfield_credential == ""
