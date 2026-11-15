from argparse import Namespace

from app.services.evaluation import Truth
from scripts.eval_analysis import SUMMARY_HEAD, config_label, detail_table, grid, score, summary_row

ARGS = Namespace(fps="1,5", resolution="default,high", processing="static,agentic", time_format="clock")


def test_grid_skips_fps_in_agentic_mode():
    configs = grid(ARGS)
    assert len(configs) == 2 * 2 + 1 * 2
    assert config_label(configs[0]) == "static__fps1__default__clock"
    assert config_label(configs[-1]) == "agentic__auto__high__clock"
    assert configs[-1]["fps"] is None


def test_score_and_summary_rows_line_up_with_the_header():
    truth = Truth.model_validate({
        "video": "v.mp4", "preset": "boss_fight",
        "events": [{"t": 10.0, "type": "counter"}], "counts": {"hit_taken": 0}, "facts": {"hits_taken": 0},
    })
    analysis = {
        "events": [{"t_start": 10.3, "type": "counter"}, {"t_start": 3.0, "type": "boss_attack"}],
        "fact_proposals": [{"key": "hits_taken", "value": "0"}],
    }
    times = [i / 10 for i in range(200)]
    scores = [0.01] * 200
    scores[100] = 0.9  # a visual spike exactly on the true event
    cfg = grid(ARGS)[0]
    record = {"status": "ok", "analysis": analysis, "usage": {"total_input_tokens": 1900}, "latency_s": 12.3}
    record["score"] = score(truth, analysis, 0.5, (times, scores))

    assert record["score"]["events"]["overall"]["mean_error_s"] == 0.3
    assert record["score"]["events_snapped"]["mean_error_s"] == 0.0
    assert record["score"]["moved_by_snap"] == 1
    assert record["score"]["facts"]["correct"] == 1

    columns = SUMMARY_HEAD.splitlines()[0].count("|")
    ok_row = summary_row("v", cfg, record)
    assert "counter 1/1, hit_taken 0/0" in ok_row
    assert ok_row.count("|") == columns
    assert summary_row("v", cfg, {"status": "error", "error": "boom"}).count("|") == columns
    assert summary_row("v", cfg, {"status": "dry-run", "estimated_input_tokens": 5}).count("|") == columns

    analysis["events"] = [
        {"t_start": 10.3, "type": "counter", "label": "Riposte"},
        {"t_start": 40.0, "type": "counter", "label": "Late riposte"},
        {"t_start": 9.5, "type": "boss_attack", "label": "Lunge"},
    ]
    table = detail_table(truth, [(cfg, record), (cfg, {"status": "error"})])
    assert "| 0:10.0 counter | +0.3 s<br>(boss_attack -0.5 s) |" in table
    assert "- **1 fps**: counter 0:40.0 (Late riposte)" in table
