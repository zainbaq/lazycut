from scripts.gauge_probe import FPS, fill_fraction, steps

WHITE, DARK, RED = bytes([230, 230, 225]), bytes([30, 30, 34]), bytes([200, 20, 20])


def test_fill_counts_white_from_the_left_and_ignores_glare_further_right():
    assert fill_fraction(WHITE * 60 + DARK * 40) == 0.6
    assert fill_fraction(WHITE * 50 + RED * 10 + DARK * 40) == 0.5  # red = damage just taken
    assert fill_fraction(WHITE * 30 + DARK * 50 + WHITE * 20) == 0.3
    assert fill_fraction(DARK * 100) == 0.0


def test_steps_finds_drops_and_heals_and_skips_flicker_and_hidden_hud():
    series = (
        [1.0] * 30            # full
        + [0.8] * 30          # hit at 3.0 s
        + [0.0] * 20          # HUD hidden: no reading, not a hit
        + [0.8] * 20
        + [0.5] * 3 + [0.8] * 30  # a glow for 0.3 s, undone: not a hit
        + [0.95] * 30         # heal
    )
    found = steps(series, 0.03)
    assert [(e["kind"], round(e["t"], 1)) for e in found] == [("drop", 3.0), ("rise", 13.3)]
    assert found[0]["from"] == 1.0 and found[0]["to"] == 0.8
    assert FPS == 10
