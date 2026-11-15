from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.presets import Preset, load_channel, load_presets

# Repo root locally (api/tests -> repo), `/` in the container where ./config is mounted at /config.
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

MINIMAL = {
    "id": "t",
    "name": "T",
    "event_types": [{"id": "hit", "label": "Hit", "definition": "A hit."}],
    "title_patterns": {"recommended": "{subject} - {hook}"},
}


def test_shipped_config_is_valid():
    presets, errors = load_presets(CONFIG_DIR)
    assert errors == []
    assert {"general", "boss_fight"} <= set(presets)
    channel, channel_errors = load_channel(CONFIG_DIR)
    assert channel_errors == []
    assert channel.name == "TheLazyRonin"


def test_boss_fight_keeps_claims_in_config():
    boss = load_presets(CONFIG_DIR)[0]["boss_fight"]
    assert [f.key for f in boss.facts if f.required] == ["hits_taken"]
    no_hit = next(h for h in boss.hooks if h.id == "no_hit")
    assert (no_hit.when.fact, no_hit.when.op, no_hit.when.value) == ("hits_taken", "eq", 0)
    assert "Untouched" in boss.claim_rules[0].phrases


def test_unknown_template_variable_fails():
    with pytest.raises(ValidationError, match="unknown variable `{nope}`"):
        Preset.model_validate(MINIMAL | {"templates": {"reel": "{nope}"}})


def test_slot_and_fact_variables_are_allowed():
    preset = Preset.model_validate(
        MINIMAL
        | {
            "facts": [{"key": "hits", "label": "Hits", "type": "int", "derive_from": "hit"}],
            "slots": {"tip": "A tip."},
            "templates": {"reel": "{tip} {hits} {playlist_url}"},
        }
    )
    assert preset.slots == {"tip": "A tip."}


def test_hook_may_only_use_facts():
    hook = {"id": "h", "text": "{tip} run", "when": {"fact": "hits", "op": "eq", "value": 0}}
    with pytest.raises(ValidationError, match="not a fact"):
        Preset.model_validate(
            MINIMAL
            | {
                "facts": [{"key": "hits", "label": "Hits", "type": "int"}],
                "slots": {"tip": "A tip."},
                "hooks": [hook],
            }
        )


def test_condition_must_name_a_known_fact():
    rule = {"id": "r", "phrases": ["No Hit"], "requires": {"fact": "missing", "op": "eq", "value": 0}}
    with pytest.raises(ValidationError, match="unknown fact `missing`"):
        Preset.model_validate(MINIMAL | {"claim_rules": [rule]})


def test_broken_preset_is_reported_and_general_survives(tmp_path):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "bad.yaml").write_text("id: bad\nname: Bad\n", encoding="utf-8")
    presets, errors = load_presets(tmp_path)
    assert list(presets) == ["general"]
    assert errors[0].file == "presets/bad.yaml"
    assert "event_types" in errors[0].problem
