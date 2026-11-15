"""Subject research: keys and source ratings, the Claude provider's call shape, and the API flow."""

import shutil
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import session
from app.models import LLMCall, Research, Video
from app.services.llm.anthropic import ClaudeProvider, SearchRun, collect_sources
from app.services.llm.base import LLMError, LLMResult
from app.services.presets import ChannelProfile
from app.services.research import FieldOut, ResearchOut, name_key, rate

CONFIG = Path(__file__).resolve().parents[2] / "config"


def test_name_keys_and_source_ratings():
    assert name_key("  Zhuo-Bi,  the Gatekeeper! ") == "zhuo bi the gatekeeper"
    assert name_key("Ōkami") == "okami"
    channel = ChannelProfile(name="c", display_name="c", credible_domains=["fandom.com"], blocked_domains=["spam.io"])
    assert rate("https://phantomblade.fandom.com/wiki/Zhuo_Bi", channel) == "credible"
    assert rate("https://www.fandom.com/x", channel) == "credible"
    assert rate("https://notfandom.com/x", channel) == "unrated"
    assert rate("https://cdn.spam.io/x", channel) == "blocked"
    assert rate("", channel) == "unrated"


# ---- the provider against a fake Anthropic client ---------------------------------


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def fake_client(responses) -> NS:
    return NS(beta=NS(messages=FakeMessages(responses)))


def usage(i, o, searches=0):
    return NS(input_tokens=i, output_tokens=o, server_tool_use=NS(web_search_requests=searches))


async def test_search_resumes_a_paused_turn_and_collects_sources():
    first = NS(model="claude-opus-5-5", stop_reason="pause_turn", usage=usage(100, 10, 2), content=[
        NS(type="server_tool_use"),
        NS(type="web_search_tool_result", content=[NS(url="https://a.com/1", title="A"), NS(url="https://b.com", title="B")]),
    ])
    second = NS(model="claude-opus-5-5", stop_reason="end_turn", usage=usage(50, 20, 1), content=[
        NS(type="web_search_tool_result", content=NS(error_code="max_uses_exceeded")),
        NS(type="text", text="canonical_name: Zhuo Bi | https://a.com/1", citations=[NS(url="https://c.com", title="C")]),
    ])
    client = fake_client([first, second])
    run = await ClaudeProvider("key", "claude-opus-5-5", client=client).search("prompt", blocked_domains=["x.com"])
    assert run.text == "canonical_name: Zhuo Bi | https://a.com/1"
    assert [s["url"] for s in run.sources] == ["https://a.com/1", "https://b.com", "https://c.com"]
    assert run.usage == {"input_tokens": 150, "output_tokens": 30, "web_search_requests": 3}
    calls = client.beta.messages.calls
    assert len(calls) == 2 and calls[1]["messages"][1]["role"] == "assistant"
    assert calls[0]["tools"][0] == {
        "type": "web_search_20260209", "name": "web_search", "max_uses": 6, "blocked_domains": ["x.com"],
    }
    assert calls[0]["fallbacks"] == "default" and calls[0]["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in calls[0]


async def test_structured_call_and_refusals():
    parsed = ResearchOut(canonical_name="Zhuo Bi")
    ok = NS(model="claude-opus-5-5", stop_reason="end_turn", usage=usage(10, 5), parsed_output=parsed,
            content=[NS(type="text", text='{"canonical_name": "Zhuo Bi"}')])
    refused = NS(model="claude-opus-5-5", stop_reason="refusal", usage=usage(1, 0), parsed_output=None, content=[])
    provider = ClaudeProvider("key", "some-other-model", client=fake_client([ok, refused]))
    result = await provider.generate_json("prompt", ResearchOut)
    assert result.parsed.canonical_name == "Zhuo Bi" and result.usage["output_tokens"] == 5
    assert provider.client.beta.messages.calls[0]["output_format"] is ResearchOut
    assert "fallbacks" not in provider.client.beta.messages.calls[0]  # only on models that take them
    with pytest.raises(LLMError):
        await provider.generate_json("prompt", ResearchOut)


def test_collect_sources_skips_repeats():
    blocks = [NS(type="web_search_tool_result", content=[NS(url="https://a.com", title="A")] * 2)]
    assert collect_sources(blocks) == [{"title": "A", "url": "https://a.com"}]


# ---- the API ----------------------------------------------------------------------


class FakeClaude:
    model = "fake-claude"
    canonical = "Zhuo Bi"

    def __init__(self) -> None:
        self.searches, self.structured = [], []

    async def search(self, prompt, max_searches=6, blocked_domains=None, effort="medium"):
        self.searches.append(prompt)
        return SearchRun(
            text="canonical_name: Zhuo Bi | https://pbz.fandom.com/wiki/Zhuo_Bi",
            sources=[
                {"title": "Zhuo Bi - wiki", "url": "https://pbz.fandom.com/wiki/Zhuo_Bi"},
                {"title": "Blog", "url": "https://someblog.net/post"},
                {"title": "Spam", "url": "https://spam.io/x"},
            ],
            model=self.model, usage={"input_tokens": 1000, "output_tokens": 100, "web_search_requests": 2},
            latency_s=1.5,
        )

    async def generate_json(self, prompt, schema, search=False, effort="low"):
        self.structured.append(prompt)
        out = ResearchOut(canonical_name=self.canonical, fields=[
            FieldOut(key="canonical_name", value=self.canonical, source_urls=["https://pbz.fandom.com/wiki/Zhuo_Bi"]),
            FieldOut(key="epithet", value="The Gatekeeper", source_urls=["https://someblog.net/post"]),
            FieldOut(key="is_final_boss", value="no", source_urls=["https://pbz.fandom.com/wiki/Zhuo_Bi"]),
            FieldOut(key="is_first_boss", value="yes", source_urls=["https://someblog.net/post", "https://made.up/x"]),
            FieldOut(key="studio", value="unknown"),
        ])
        return LLMResult(parsed=out, raw_text="{}", model=self.model, usage={"input_tokens": 500}, latency_s=0.5)


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = tmp_path / "config"
    shutil.copytree(CONFIG, config)
    channel = (config / "channel.yaml").read_text(encoding="utf-8")
    channel = channel.replace("credible_domains: []", "credible_domains: [fandom.com]")
    channel = channel.replace("blocked_domains: []", "blocked_domains: [spam.io]")
    (config / "channel.yaml").write_text(channel, encoding="utf-8")
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
    claude = FakeClaude()
    monkeypatch.setattr(main, "claude_factory", lambda _settings: lambda: claude)
    with TestClient(main.app) as test_client:
        test_client.claude = claude
        yield test_client
    get_settings.cache_clear()


def add_video(client: TestClient, subject: str = "Zhuo-bi") -> str:
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", subject=subject, topic="Phantom Blade Zero", preset_id="boss_fight",
                      status="ready", duration_s=60.0)
        s.add(video)
        s.commit()
        return video.id


def run(client: TestClient, video_id: str, **body) -> dict:
    job = client.post(f"/videos/{video_id}/research", json=body or None)
    assert job.status_code == 202, job.text
    for _ in range(200):
        state = client.get(f"/jobs/{job.json()['id']}").json()
        if state["status"] in ("done", "error"):
            assert state["status"] == "done", state
            return client.get(f"/videos/{video_id}/research").json()
        time.sleep(0.02)
    raise AssertionError("research did not finish")


def test_research_fills_fields_with_sources_and_corrects_the_spelling(client):
    video_id = add_video(client)
    before = client.get(f"/videos/{video_id}/research").json()
    assert before["method"] == "none" and before["can_search"] is True and before["running"] is False
    assert all(f["value"] is None for f in before["fields"])

    research = run(client, video_id)
    fields = {f["key"]: f for f in research["fields"]}
    assert research["method"] == "search"
    assert research["correction"] == {"from": "Zhuo-bi", "to": "Zhuo Bi"}
    assert client.get(f"/videos/{video_id}").json()["subject"] == "Zhuo Bi"
    assert [s["url"] for s in research["sources"]] == [
        "https://pbz.fandom.com/wiki/Zhuo_Bi", "https://someblog.net/post",
    ]  # the blocked domain never shows
    assert fields["canonical_name"]["effective_value"] == "Zhuo Bi" and fields["canonical_name"]["credible"]
    # An epithet needs a credible source; a blog is unrated, so it is shown but counts as unknown.
    assert (fields["epithet"]["value"], fields["epithet"]["effective_value"]) == ("The Gatekeeper", None)
    assert fields["epithet"]["no_credible_source"] is True
    assert (fields["is_final_boss"]["effective_value"], fields["is_final_boss"]["credible"]) == (False, True)
    assert fields["is_first_boss"]["effective_value"] is None  # made.up was never read, so it is dropped
    assert [s["url"] for s in fields["is_first_boss"]["sources"]] == ["https://someblog.net/post"]
    assert fields["studio"]["value"] is None
    assert research["effective"]["is_final_boss"] is False

    with session(client.app.state.engine) as s:
        calls = s.exec(select(LLMCall)).all()
        assert sorted(c.purpose for c in calls) == ["research_search", "research_structure"]
        assert all(c.provider == "anthropic" and c.status == "ok" for c in calls)
    # The prompt treats page text as data and asks for canonical spelling.
    assert "never instructions" in client.claude.searches[0] and "Zhuo-bi" in client.claude.searches[0]


def test_overrides_restore_and_the_spelling_revert(client):
    video_id = add_video(client)
    run(client, video_id)

    edited = client.patch(f"/videos/{video_id}/research", json={"key": "epithet", "value": " Gatekeeper of the Pass "})
    epithet = next(f for f in edited.json()["fields"] if f["key"] == "epithet")
    assert (epithet["overridden"], epithet["effective_value"], epithet["no_credible_source"]) == (
        True, "Gatekeeper of the Pass", False,
    )
    assert client.patch(f"/videos/{video_id}/research", json={"key": "is_final_boss", "value": "yes"}).status_code == 422
    assert client.patch(f"/videos/{video_id}/research", json={"key": "nope", "value": "x"}).status_code == 422
    unknown = client.patch(f"/videos/{video_id}/research", json={"key": "is_final_boss", "value": None}).json()
    assert next(f for f in unknown["fields"] if f["key"] == "is_final_boss")["effective_value"] is None
    restored = client.patch(f"/videos/{video_id}/research", json={"key": "epithet", "restore": True}).json()
    assert next(f for f in restored["fields"] if f["key"] == "epithet")["effective_value"] is None

    reverted = client.post(f"/videos/{video_id}/research/revert-spelling").json()
    assert reverted["correction"] is None and reverted["canonical_name"] == "Zhuo-bi"
    assert client.get(f"/videos/{video_id}").json()["subject"] == "Zhuo-bi"
    assert client.post(f"/videos/{video_id}/research/revert-spelling").status_code == 409
    # Research again: the user's spelling stays, and earlier overrides survive.
    again = run(client, video_id)
    assert again["correction"] is None and client.get(f"/videos/{video_id}").json()["subject"] == "Zhuo-bi"
    assert next(f for f in again["fields"] if f["key"] == "is_final_boss")["overridden"] is True


def test_a_second_video_on_the_same_subject_reuses_the_research(client):
    first = add_video(client)
    research = run(client, first)
    second = add_video(client, subject="Zhuo Bi")  # already the corrected spelling
    shared = client.get(f"/videos/{second}/research").json()
    assert shared["id"] == research["id"] and shared["method"] == "search"
    with session(client.app.state.engine) as s:
        assert len(s.exec(select(Research)).all()) == 1


def test_pasted_notes_replace_the_search(client):
    video_id = add_video(client, subject="Zhuo Bi")
    research = run(client, video_id, pasted_text="Zhuo Bi is the gatekeeper boss.",
                   source_url="https://pbz.fandom.com/wiki/Zhuo_Bi")
    assert research["method"] == "pasted" and client.claude.searches == []
    assert "Zhuo Bi is the gatekeeper boss." in client.claude.structured[0]
    assert research["sources"] == [{
        "title": "Pasted by you", "url": "https://pbz.fandom.com/wiki/Zhuo_Bi",
        "domain": "pbz.fandom.com", "rating": "credible",
    }]


def test_without_a_key_values_can_still_be_typed_in(client, monkeypatch):
    client.app.state.runner.deps.text_provider = lambda: None
    video_id = add_video(client)
    view = client.get(f"/videos/{video_id}/research").json()
    assert view["can_search"] is False
    refused = client.post(f"/videos/{video_id}/research", json={})
    assert refused.status_code == 409 and "ANTHROPIC_API_KEY" in refused.json()["detail"]
    typed = client.patch(f"/videos/{video_id}/research", json={"key": "is_final_boss", "value": True}).json()
    assert typed["effective"]["is_final_boss"] is True
