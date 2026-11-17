# LazyCut

A local, single-user app that turns one video into a complete publishing package.
See [BUILD_SPEC.md](BUILD_SPEC.md) for the full design.

**Status:** Phases 1 and 2 are built. Import, analysis, the workspace timeline, event editing with
review mode, facts confirmation, subject research, the YouTube long-form package (rule-checked,
exportable as Markdown), past uploads and "Mark as published" work. So do clips: finding them from
a prompt, trimming, exporting with ffmpeg, and the Shorts, Reels and TikTok packages (BUILD_SPEC
section 10). Phase 3 (competitor research, imports, the preset editor) comes next.

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
`config/channel.yaml`. Writing the YouTube package is one Claude call (about $0.05) and needs the
preset's required facts confirmed first.

Titles and tags are chosen by measured search demand: after research the app collects YouTube's
search suggestions for the topic and the subject's names (free, no key; only those names are sent),
the writer marks which phrases fit the video, and code picks the title that covers the most popular
fitting phrases. `SEARCH_DEMAND=off` in `.env` turns this off.

Thumbnails are made on the video's Thumbnail page with Higgsfield (set `HIGGSFIELD_API_KEY` to the API key from
console.higgsfield.ai, exactly as the console shows it; each image is a paid call, priced before you click).
"Find frames" suggests the best source moments (Claude ranks them, a few cents), or pick any moment or upload
your own image. LazyCut draws the result word itself, so it is always spelled right and a new word costs
nothing, then Claude checks faces, hands, leftover HUD and the text. The model, its options and the prompt are
on the Settings page; `config/thumbnails.yaml` holds the defaults.

## Clips

In a video's workspace, describe the clip you want in the Clips panel (or click a saved prompt). The
finder reads the event timeline, not the video: one Claude call, about 1 to 2 cents, gives 3 to 5
proposals. Without `ANTHROPIC_API_KEY` it proposes the ending, the busiest stretch and the peak from
the timeline alone. You can also mark a clip by hand: `I` starts one at the playhead, `O` ends it.

Select a clip to loop it. Drag its edges on the filmstrip (0.5 s steps, hold Alt for 0.1 s), use the
nudge buttons or `[` and `]`, and follow the analysis note, which points at a late first event, dead
time or a late payoff. "Refine edges" asks Gemini to look closely at the clip's first and last event
(two small calls, under a cent); it is experimental. A clip is always one uncut range.

"Export" cuts the clip from the source file at the source frame rate: vertical 9:16 at 1080×1920,
or the original frame, frame-exact (re-encoded near-lossless) or lossless (no re-encode, so it starts
on the keyframe before the in-point and says where). A 30 s vertical export of 1440p60 footage takes
about a minute. Files are kept in `data/media/<video>/clips/` and download with a readable name.
`EXPORT_VERTICAL_SIZE` in `.env` changes the vertical size.

Switch on Shorts, Reels or TikTok in the package panel and press "Write": one Claude call (about 2
cents) fills the preset's short-form templates for every platform switched on, and the rules check
claims, hashtags, the length limits and that the text points back to the full video. "Open" shows
each field with Copy and a phone preview with the safe-area guides. "Lift clip" does the vertical
export and the packages in one press. The app never draws text into the video.

To compare ways of asking the finder, or to measure the refine pass, run the probes (paid calls):

```bash
docker compose exec api python -m scripts.clip_finder_probe --dry
```

```bash
docker compose exec api python -m scripts.refine_probe --truth pb0-the-gate-keeper --type counter --limit 5
```

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
