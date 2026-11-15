from app.services.evaluation import Truth, match_events, score_events, score_facts


def truth(**kwargs) -> Truth:
    return Truth.model_validate({"video": "v.mp4", "preset": "boss_fight"} | kwargs)


def test_match_is_one_to_one_and_prefers_the_closest():
    matches = match_events([2.0, 4.5], [2.1, 2.4, 4.4, 9.0], tolerance_s=0.5)
    assert sorted((i, j) for i, j, _ in matches) == [(0, 0), (1, 2)]


def test_clock_times_in_truth():
    t = truth(events=[{"t": "1:04.5", "type": "counter"}])
    assert t.events[0].t == 64.5


def test_score_events_recall_precision_error():
    t = truth(events=[{"t": 2.0, "type": "counter"}, {"t": 4.5, "type": "counter"}, {"t": 27, "type": "finisher"}])
    found = [(2.2, "counter"), (4.5, "counter"), (11.0, "counter"), (29.0, "finisher"), (5.0, "boss_attack")]
    result = score_events(t, found, tolerance_s=0.5)
    counter = result["per_type"]["counter"]
    assert (counter["true"], counter["found"], counter["matched"]) == (2, 3, 2)
    assert counter["recall"] == 1.0
    assert counter["precision"] == 0.667
    assert counter["mean_error_s"] == 0.1
    assert result["per_type"]["finisher"]["recall"] == 0.0  # 2 s late is outside the window
    assert "boss_attack" not in result["per_type"]  # unlabelled types are not scored
    assert result["overall"]["recall"] == 0.667


def test_count_only_truth_compares_totals_without_timing():
    t = truth(counts={"hit_taken": 0, "counter": 6})
    result = score_events(t, [(1.0, "counter")] * 5, tolerance_s=0.5)
    assert result["per_type"]["counter"] == {"true": 6, "found": 5, "count_diff": -1}
    assert result["per_type"]["hit_taken"]["count_diff"] == 0
    assert "recall" not in result["overall"]


def test_label_contradictions_are_reported_and_timed_events_win():
    t = truth(
        events=[{"t": 59, "type": "hit_taken"}, {"t": 104, "type": "counter"}],
        counts={"hit_taken": 0},
        facts={"hits_taken": 0, "counter_count": 2},
    )
    assert t.true_counts() == {"hit_taken": 1, "counter": 1}
    problems = t.problems({"hits_taken": "hit_taken", "counter_count": "counter"})
    assert problems == [
        "counts.hit_taken is 0, but 1 timed `hit_taken` event(s) are listed",
        "facts.hits_taken is 0, but the labels give 1 `hit_taken` event(s)",
        "facts.counter_count is 2, but the labels give 1 `counter` event(s)",
    ]
    assert truth(counts={"hit_taken": 0}, facts={"hits_taken": 0}).problems({"hits_taken": "hit_taken"}) == []


def test_score_facts():
    t = truth(facts={"hits_taken": 0, "counter_count": 6, "encounter": "Second"})
    result = score_facts(t, {"hits_taken": "0", "counter_count": "5", "encounter": "second"})
    assert (result["correct"], result["total"]) == (2, 3)
    assert result["facts"]["counter_count"]["ok"] is False
