# Analysis accuracy test

This folder holds reviewed labels for test videos and the results of running the analysis against
them. Phase 0 used it to choose the defaults; keep using it whenever the prompt, the model, the
sampling rate, a detector, the merge rules or a playbook changes (BUILD_SPEC 7.3.1).

## Labels

Each test video has `<name>.truth.yaml`. The quickest way to make one is the review sheet: it lists
moments that Gemini, the health bar or a red flash proposed, with frame strips and clips, and you
answer yes or no.

```bash
docker compose run --rm api python -m scripts.review_sheet build --hud 420:80:40:590
docker compose run --rm api python -m scripts.review_sheet apply /data/review/answers.json
```

`build` writes the page to `data/review/`; `apply` writes the truth files from the saved answers
and keeps the old ones as `<name>.truth.before-review.yaml`. You can also copy
`example.truth.yaml.sample` and label by hand.

## Run it

Check everything except Gemini (proxy, timeline match, token estimates):

```bash
docker compose run --rm api python -m scripts.eval_analysis --dry-run
```

Run the analysis (each run is one paid Gemini call):

```bash
docker compose run --rm api python -m scripts.eval_analysis --background --fps 1 --playbook off,on
```

Results land in `eval/results/`: one JSON per run and `summary.md` with the comparison table.
A run that already has a result is reused; add `--force` to repeat it, or `--retry-errors` to
repeat only the failed ones. Playbooks are read from `config/playbooks/`.

Other options: `--only <name>`, `--resolution default,high`, `--processing static,agentic`,
`--time-format clock,seconds`, `--tolerance 0.5`, `--report-only`.

## Reading the table

- **Recall**: share of your labelled events that Gemini found within the match window (±0.5 s by default).
- **Precision**: share of Gemini's events that match one of yours.
- **Mean error**: average timing gap on the matched events.
- **Snapped**: the same, after moving each event to the nearest visual spike. If this is not clearly better, the snap stays off.
- **Tokens in**: the input size of the call, which sets its cost.
