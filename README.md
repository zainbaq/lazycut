# LazyCut

A local, single-user app that turns one video into a complete publishing package.
See [BUILD_SPEC.md](BUILD_SPEC.md) for the full design.

**Status:** Phase 1 in progress. Import, analysis, the workspace timeline, event editing with
review mode, facts confirmation and subject research work; packaging comes next (BUILD_SPEC section 10).

## Setup

1. Install and start Docker Desktop.
2. Copy `.env.example` to `.env` and set `GEMINI_API_KEY`. Without it the app still imports videos,
   but cannot analyze them.
3. Put videos in `inbox/`, or set `IMPORT_DIR` in `.env` to the folder they are already in. The folder is mounted read-only.
4. On Windows, set `WATCH_POLLING=true` in `.env` if code changes do not reload.

## Run

```bash
docker compose up --build
```

- App: http://localhost:3000 (import a video at `/new`)
- API docs: http://localhost:8000/docs
- Config and storage check: http://localhost:8000/config/status

Importing a video starts its analysis automatically when `GEMINI_API_KEY` is set. Each analysis is
one paid Gemini call. With `ANTHROPIC_API_KEY` set, import also researches the subject once (a
Claude call with web search, about $0.40); later videos on the same subject reuse it. Research
sources only count as credible when their site is listed under `credible_domains` in
`config/channel.yaml`.

## How events are found

Event detection is a set of detectors feeding one merge step (BUILD_SPEC 7.3.1). `EVENT_DETECTORS`
in `.env` picks them; only `gemini` exists today. Topic-specific cues live in
`config/playbooks/<topic>.yaml` and are matched to a video by its topic name.

## Measuring accuracy

`eval/` holds reviewed labels for test videos. See [eval/README.md](eval/README.md).

## Tests

```bash
docker compose run --rm api pytest
```

## Back up the database

The database lives in a Docker volume, not in `data/`.

```bash
docker compose cp api:/db/app.db ./backup.db
```
