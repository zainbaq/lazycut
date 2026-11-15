from ruamel.yaml import YAML

from app.services.evaluation import Truth
from scripts.review_sheet import (
    collect,
    events_from_answers,
    group_repeats,
    red_flashes,
    red_share,
    render_truth,
    reviewed_truth,
)


def test_group_repeats_merges_runs_that_agree_and_keeps_separate_moments_apart():
    reports = [
        {"t": 10.5, "label": "first", "run": 0},
        {"t": 11.0, "label": "same moment", "run": 1},
        {"t": 12.5, "label": "still the same", "run": 2},
        {"t": 20.0, "label": "another", "run": 0},
        {"t": 20.5, "label": "another, same run", "run": 0},
    ]
    assert group_repeats(reports) == [
        {"t": 11.0, "label": "first", "runs": 3},
        {"t": 20.25, "label": "another", "runs": 1},
    ]


def test_red_flash_detection():
    red, grey = bytes([200, 30, 30]), bytes([120, 120, 120])
    assert red_share(red * 3 + grey * 7) == 0.3
    assert red_share(bytes([200, 170, 160]) * 10) == 0.0  # pale, not red
    series = [0.0] * 20 + [0.2, 0.3, 0.1] + [0.0] * 3 + [0.15] + [0.0] * 30 + [0.4] + [0.0] * 5
    # The flicker 0.6 s after the first flash belongs to it; the one 3 s later is new.
    assert red_flashes(series, fps=10) == [2.0, 5.7]


def test_collect_merges_sources_into_one_candidate_per_moment():
    runs = [
        [
            {"t_start": 23.0, "type": "counter", "label": "Red glint counter"},
            {"t_start": 36.0, "type": "hit_taken", "label": "Shockwave hits the player"},
            {"t_start": 59.0, "type": "hit_taken", "label": "Boss grabs the player"},
            {"t_start": 70.0, "type": "parry", "label": "not reviewed"},
        ],
        [{"t_start": 23.5, "type": "counter", "label": "Counter"}],
    ]
    drops = [{"t": 36.7, "t_end": 36.9, "from": 0.49, "to": 0.12}]
    flashes = [24.6, 36.4, 90.0]
    labels = [{"t": 24.0, "type": "counter"}, {"t": 210.0, "type": "finisher"}]

    found = collect(runs, drops, flashes, labels)

    assert [(c["id"], c["type"]) for c in found] == [
        ("counter-00232", "counter"),
        ("hit_taken-00367", "hit_taken"),
        ("hit_taken-00590", "hit_taken"),
        ("counter-00900", "counter"),
        ("finisher-02100", "finisher"),
    ]
    counter, hit, grab, flash, finisher = found
    assert counter["sources"] == [
        "Gemini reported it in 2 of 2 runs.",
        "The screen flashed red at 0:24.6.",
        "You labelled this at 0:24.0.",
    ]
    # The measured drop keeps its own time; Gemini's report and the damage flash fold into it.
    assert hit["t"] == 36.7
    assert hit["sources"] == ["The health bar fell from 49% to 12%.", "Gemini reported it in 1 of 2 runs."]
    assert hit["label"] == "Shockwave hits the player"
    assert "drop" in hit and "drop" not in grab
    assert flash["sources"][-1] == "No run reported a counter here."
    assert finisher["sources"] == ["You labelled this at 3:30.0."]
    assert counter["strip_start"] == 21.75


OLD = {
    "video": "fight.mp4", "preset": "boss_fight", "kind": "long", "topic": "Some Game", "subject": 'The "Boss"',
    "topic_terms": "",
    "events": [{"t": "0:24.0", "type": "counter"}, {"t": "1:10", "type": "parry"}],
    "counts": {"hit_taken": 0, "boss_attack": 7},
    "facts": {"hits_taken": 0, "counter_count": 2, "no_damage": True},
}

ANSWERS = {
    "candidates": {
        "counter-00232": {"verdict": "yes", "type": "counter", "t": 23.75},
        "counter-00900": {"verdict": "no", "type": "counter", "t": 90.0},
        "hit_taken-00367": {"verdict": "yes", "type": "hit_taken", "t": 36.7},
        "hit_taken-00590": {"verdict": "yes", "type": "hit_taken", "t": 59.0},
        "counter-00762": {"verdict": "yes", "type": "parry", "t": 76.25},  # proposed as a counter, was a parry
    },
    "added": [{"t": 10.5, "type": "counter"}],
}


def test_answers_become_the_truth_file():
    assert events_from_answers(ANSWERS) == [
        {"t": 10.5, "type": "counter"},
        {"t": 23.75, "type": "counter"},
        {"t": 36.7, "type": "hit_taken"},
        {"t": 59.0, "type": "hit_taken"},
        {"t": 76.25, "type": "parry"},
    ]
    truth = reviewed_truth(OLD, ANSWERS)
    # Parries were never reviewed in full: the old label stays and the re-typed one is not scored.
    # The old counter label is replaced.
    assert [(e["t"], e["type"]) for e in truth["events"]] == [
        (10.5, "counter"), (23.75, "counter"), (36.7, "hit_taken"), (59.0, "hit_taken"), (70.0, "parry"),
    ]
    assert truth["unscored"] == [{"t": 76.25, "type": "parry"}]
    assert "#   1:16.25 parry" in render_truth(truth)
    # Reviewed types with nothing confirmed are scored as zero; unreviewed counts are kept.
    assert truth["counts"] == {"boss_attack": 7, "finisher": 0, "phase_change": 0}
    assert truth["facts"] == {"hits_taken": 2, "counter_count": 2, "no_damage": True}

    text = render_truth(truth)
    assert '  - {t: "0:23.75", type: counter}' in text
    loaded = Truth.model_validate(YAML(typ="safe").load(text))
    assert loaded.subject == 'The "Boss"'
    assert loaded.true_counts() == {"boss_attack": 7, "finisher": 0, "phase_change": 0, "counter": 2, "hit_taken": 2, "parry": 1}
    assert loaded.problems({"hits_taken": "hit_taken", "counter_count": "counter"}) == []


def test_review_with_nothing_confirmed_still_loads():
    truth = reviewed_truth({"video": "v.mp4"}, {"candidates": {}, "added": []})
    loaded = Truth.model_validate(YAML(typ="safe").load(render_truth(truth)))
    assert loaded.events == []
    assert loaded.true_counts() == {"counter": 0, "hit_taken": 0, "finisher": 0, "phase_change": 0}
