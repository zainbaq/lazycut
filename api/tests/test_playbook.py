from argparse import Namespace
from pathlib import Path

from app.services.analysis import VideoContext, render_prompt
from app.services.playbook import Playbook, load_playbook, slugify
from app.services.presets import load_presets
from scripts.eval_analysis import config_label, grid, short_label

ROOT = Path(__file__).resolve().parents[2]
PRESETS = load_presets(ROOT / "config")[0]
VIDEO = VideoContext("long", 217, "Phantom Blade Zero", "The Sword Fanatic")


def test_slug_and_missing_playbook(tmp_path):
    assert slugify("Onimusha: Way of the Sword") == "onimusha-way-of-the-sword"
    assert load_playbook(tmp_path, "Phantom Blade Zero") is None
    assert load_playbook(tmp_path, "") is None


def test_saved_playbook_loads_and_reaches_the_prompt():
    playbook = load_playbook(ROOT / "config" / "playbooks", "Phantom Blade Zero")
    assert playbook is not None
    assert [e.event_type for e in playbook.entries_for(PRESETS["boss_fight"])] == PRESETS["boss_fight"].event_type_ids()

    prompt = render_prompt(PRESETS["boss_fight"], VIDEO, playbook=playbook)
    assert "How these events appear in Phantom Blade Zero (from research; coverage: partial)" in prompt
    assert "- counter (in this topic: perfect parry or perfect dodge" in prompt
    assert "Not this type: Blocked attacks" in prompt
    assert "trust the\nfootage" in prompt
    # The generic definitions stay; the playbook is added on top.
    assert "- counter: The player lands a perfect counter or riposte." in prompt


def test_prompt_is_unchanged_without_a_playbook_and_skips_other_presets_types():
    assert "from research" not in render_prompt(PRESETS["boss_fight"], VIDEO)
    playbook = Playbook(topic="Valheim", entries=[
        {"event_type": "counter", "applies": False},
        {"event_type": "parry", "looks_like": "A shield bash."},
    ])
    prompt = render_prompt(PRESETS["boss_fight"], VIDEO, playbook=playbook)
    assert "- counter: does not exist in Valheim. Do not report it." in prompt
    assert "- parry. Looks like: A shield bash." in prompt
    assert "hit_taken (in this topic" not in prompt


def test_playbook_runs_get_their_own_label():
    args = Namespace(fps="1", resolution="default", processing="static", time_format="clock", playbook="off,on")
    off, on = grid(args)
    assert config_label(off) == "static__fps1__default__clock"
    assert config_label(on) == "static__fps1__default__clock__playbook"
    assert short_label(on) == "1 fps + playbook"
    assert config_label({"fps": 1.0, "resolution": None, "processing": "static", "time_format": "clock"}) == config_label(off)
