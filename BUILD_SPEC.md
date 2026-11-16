# LazyCut — Build Spec for Claude Code

Date: 2026-11-14 (rev 2, after the spec review) · Owner: Zain · Status: Phase 0 closed on 2026-11-15; Phase 1 in progress (see section 10)

Read this whole file before writing code. It is the single source of truth for scope, architecture, backend behaviour and frontend design. Where it says "verify", check the current vendor docs before relying on the detail.

Companion files:

- `workspace-reference.dc.html` is the approved interactive mockup of the main screen. It is a design reference only (it needs a design-tool runtime to render and is not app code). Read its inline styles and its `renderVals()` logic for exact colours, sizes, motion timings and interaction behaviour. Do not copy its code structure. Its sample content (titles, fact rows, a 32-second video) is illustrative; where the mockup and this spec disagree, this spec wins.
- `LazyCut — Product Spec.md` gives background and rationale. It is kept in line with this file but is not the implementation reference.

---

## 1. What this is

LazyCut is a local, single-user web app that turns one video into a complete publishing package. It replaces a manual workflow spread across a chat assistant (titles, descriptions, SEO), Gemini (watching the video) and an image tool (thumbnails).

The user imports a video from a local folder. The app:

1. Watches it and builds a timestamped event timeline.
2. Lets the user check event timing by eye and confirm key facts.
3. Finds clips from a plain-language prompt and proposes trim points.
4. Researches the subject and competing videos.
5. Writes titles, descriptions, tags, chapters and per-platform packages.
6. Checks every output against rules before the user copies it.

### Non-goals

- Not a video editor. No timeline editing, effects, overlays, captions or music. The only video operations are trimming one continuous range and an optional 9:16 centre crop.
- No auto-publishing in v1. Output is copy-paste blocks and a Markdown export.
- No accounts, auth, billing or multi-tenant features.
- No speech-based highlight detection. The target footage is silent gameplay.
- No browser upload in v1. Videos come from a local import folder (D16). Google Drive import is planned for Phase 3.
- No AI upscaling or frame interpolation. Exports preserve the source's quality and frame rate; they cannot add detail the source does not have.

### Primary user and footage

A faceless YouTube gaming channel (TheLazyRonin) posting skilled boss-fight runs, plus Shorts and Instagram Reels cut from them.

- Typical footage: 1440p, 60 fps, usually under 5 minutes, sometimes 5 to 10 minutes.
- The app must also work on any other video with no niche configuration (see Presets). The second real use case is a non-combat video such as a Valheim base build, run in General mode.

---

## 2. Decisions already made

| # | Decision | Reason |
| --- | --- | --- |
| D1 | Personal tool, one user, no auth | Not a product for now |
| D2 | Runs locally in Docker (Docker Desktop), via `docker compose up` | User's requirement |
| D3 | Backend: Python + FastAPI. Frontend: Next.js (App Router, TypeScript) | User's requirement and existing stack |
| D4 | Low running cost. Video analysis uses Gemini on the paid tier (the owner enabled billing on 2026-11-15, after the free tier's 20 requests a day ran out in Phase 0); one full pass per video keeps it cheap. Text reasoning uses Claude (D24), which is paid per call, so those calls stay few and text-only | Owner wants running cost kept low |
| D5 | LLM access goes through two provider interfaces, one for video and one for text, so either model can be swapped | Models change; the app should not depend on one |
| D6 | SQLite + local disk. No Postgres, no object storage | Single user, local |
| D7 | The core is niche-agnostic. Niche behaviour lives in optional presets. Default mode is General | App must handle generic requests |
| D8 | The creator is the source of truth about the video. Model output about claimable facts (counts, hits) is a draft until confirmed. Research facts about the world (names, spelling, whether a boss is the final one) are accepted by default with their sources, and the user can override any of them | Gemini has miscounted before; online research is often better than memory for names |
| D9 | Clips are always one continuous range ("uncut"): trim start and end only, never remove a piece from the middle. This is built into the data model, not a rule or a preset option | Uncut footage is the proof of skill |
| D10 | Claims in titles are blocked (not warned) when no confirmed fact supports them. Claim wording enters titles through preset hook templates filled from confirmed facts; phrase rules are a backstop for free text and manual edits | Channel credibility |
| D11 | Thumbnails: v1 suggests frames, a result word and a ready-to-paste image prompt. No image generation API in v1. **Superseded by D26** | Existing tool had no confirmed API route |
| D12 | Visual direction: dark "ink" style in an editor-like workspace layout (mockup artboard 5). No Japanese characters or glyphs anywhere | User feedback through five mockup rounds |
| D13 | UI must feel alive: motion, interactivity and icons throughout; small text | User feedback |
| D14 | Rules, templates and vocabulary are data (YAML), not hard-coded prompts | So conventions can change without code |
| D15 | The product is named **LazyCut**. Use `lazycut` for the repo, compose project, package names and the page title | Chosen by the owner; sibling to the channel name TheLazyRonin |
| D16 | Videos enter through an import folder on the host, mounted read-only; the app copies the chosen file into its own storage. Import sources sit behind one interface so Google Drive can be added | The files are already on the machine; a browser upload of several GB is wasted work |
| D17 | Nothing niche-specific is hard-coded or stored in the channel profile. Claims such as "No Hit", their wording, the facts behind them and the short-form templates are all user-defined in presets | The owner wants the app generic; hit counts matter only to one preset |
| D18 | The browser calls the API directly on `localhost:8000`, with CORS limited to the web origin. No Next.js proxy | Video range requests and SSE do not survive a dev proxy reliably |
| D19 | Timestamp accuracy is handled three ways: a higher sampling rate on the full pass, an on-demand refine pass, and an eye-test review mode where the user corrects and verifies events | Browser tests of Gemini were decent but not exact |
| D20 | Exports keep the source frame rate and use a near-lossless encode. A 9:16 export is scaled to 1080×1920 | Owner wants the best quality and frame rate the source allows |
| D21 | Re-analysis keeps the user's own events, verified events and confirmed facts unless the user chooses to discard them. A warning dialog always shows first | User work must not be lost silently |
| D22 | Past uploads are typed in by hand in v1. Import from the YouTube channel comes in Phase 3 | Simplest start |
| D23 | No per-game record in v1. A video carries its topic name and optional extra terms; research is shared between videos by matching names | Not needed yet |
| D24 | Gemini is used only to watch video. All other reasoning (research, clip finding, writing) runs on Claude through the Anthropic API | Owner's decision, 2026-11-14: Gemini is the only API that reads video; Claude does everything else |
| D26 | Thumbnails are generated in the app through Higgsfield's API (7.13). The image model only paints: LazyCut picks the source, writes the prompt, draws the result word itself by default, sizes the file and has Claude review the result. The model and its options are a setting | Owner's decision, 2026-11-15: keep the usual Higgsfield flow (frame in, 16:9 out, check faces, hands and HUD) but inside the app; Higgsfield's public API (key pair) makes it possible |
| D25 | Event understanding is a modular engine: separate detectors feed one merge step, and the eye test has the last word (7.3.1). Each part can be replaced or added without touching the others, and a change becomes the default only after it is scored on the reviewed labels | Owner's decision, 2026-11-15: Phase 0 accuracy is good enough to build on, and the engine must stay easy to improve later |

---

## 3. Architecture

```
            Browser ──HTTP──▶ web (Next.js, :3000)      pages and assets only
               │
               └──HTTP/SSE──▶ api (FastAPI, :8000)
                                │
┌───────────── Docker Compose ──┼──────────────────────────────────────────┐
│                               ├─ SQLite  (/db/app.db, named volume)      │
│                               ├─ Media   (/data/media/...)               │
│                               ├─ Inbox   (/inbox, read-only)             │
│                               ├─ Config  (/config/*.yaml)                │
│                               ├─ ffmpeg / ffprobe (in image)             │
│                               └─ Job runner (in-process)                 │
└───────────────────────────────┼──────────────────────────────────────────┘
                                ▼
       Gemini API (video) · Anthropic API (text, web search) · YouTube Data API
```

- Two services: `web` and `api`. No separate worker container; `api` runs a small in-process job runner (7.11).
- Media and config live in bind-mounted host folders (`./data`, `./config`) so they survive container rebuilds. The SQLite file lives in a named volume, because SQLite locking is unreliable on Windows bind mounts under Docker Desktop. Verify in Phase 0; if the bind mount proves reliable, `DB_PATH` can point into `/data`.
- The browser loads pages from `web` and calls `api` directly at `NEXT_PUBLIC_API_URL` (D18). The API allows CORS from `WEB_ORIGIN` only. API routes sit at the root (no `/api` prefix).
- Both ports are published on `127.0.0.1` only. The app has no auth, so it must not be reachable from the network.
- Video playback goes through the API with HTTP range support.

### 3.1 Repository layout

```
lazycut/
  docker-compose.yml
  .env.example
  README.md
  config/
    channel.yaml              # channel profile (section 6)
    presets/
      general.yaml
      boss_fight.yaml
  inbox/                      # default import folder; gitignored
  data/                       # gitignored; created at runtime
    media/<video_id>/source.<ext>, proxy.mp4, scene_scores.bin, frames/, clips/, exports/
  eval/                       # Phase 0: ground-truth labels and results
  api/
    Dockerfile
    pyproject.toml
    app/
      main.py                 # FastAPI app, routers, lifespan
      settings.py             # pydantic-settings, env vars
      db.py                   # engine, session, migrations-lite
      models.py               # SQLModel tables
      schemas.py              # request/response + LLM output schemas
      routers/                # imports, videos, analysis, facts, clips, packages, research, config, jobs, library
      services/
        importers/base.py     # import source interface
        importers/local.py
        media.py              # ffprobe, proxy, frames, trim, crop, intensity
        llm/base.py           # provider interface
        llm/gemini.py
        llm/anthropic.py      # all text reasoning (D24)
        events/               # the event engine (7.3.1, D25)
          base.py             # Detection, Detector, DetectionContext
          detectors/gemini.py # full pass (7.3); the only detector on by default
          detectors/gauge.py  # reads an on-screen bar from pixels; needs a playbook region
          detectors/flash.py  # full-screen colour burst; needs a playbook entry
          merge.py            # detections -> events
        playbook.py           # optional per-topic cues and screen regions
        analysis.py
        clipfinder.py
        research.py
        packaging.py
        templates.py          # template variables and slots (7.8)
        rules.py
        presets.py            # load/validate YAML
        jobs.py               # runner, progress events
      prompts/                # .md templates, Jinja2
    scripts/
      eval_analysis.py        # scores analyses against the reviewed labels
      review_sheet.py         # builds the label review page and applies its answers
      gauge_probe.py          # Phase 0 probe; becomes detectors/gauge.py
    tests/
  web/
    Dockerfile
    package.json
    next.config.ts
    src/
      app/                    # routes (section 9.2)
      components/
      lib/                    # api client, types, hooks, motion presets
      styles/tokens.css
```

### 3.2 Docker

`docker-compose.yml` (shape, adjust versions):

```yaml
name: lazycut
services:
  api:
    build: ./api
    env_file: .env
    ports: ["127.0.0.1:8000:8000"]
    volumes:
      - ./data:/data
      - ./config:/config
      - ${IMPORT_DIR:-./inbox}:/inbox:ro
      - db:/db
      - ./api/app:/srv/app          # dev hot reload
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 3s
      retries: 5
  web:
    build: ./web
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    ports: ["127.0.0.1:3000:3000"]
    volumes:
      - ./web/src:/app/src          # dev hot reload
    depends_on:
      api:
        condition: service_healthy
volumes:
  db:
```

Requirements:

- `api` image: `python:3.12-slim` plus `ffmpeg` and `curl` from apt. Use `uv` or pip with a lockfile.
- `web` image: current Node LTS. Dev target runs `next dev`; add a `prod` target that runs `next build` and `next start`.
- Docker Desktop on Windows: bind-mounted file watching can be slow. Enable polling for uvicorn reload and Next dev (`WATCHPACK_POLLING=true`) behind an env flag. Keep `data/` on the host so large videos never enter an image layer.
- `IMPORT_DIR` can point at any host folder, for example the capture folder. It is mounted read-only; the app never changes or deletes files there.
- Never read a whole video into memory. Copy and transcode with streams or ffmpeg.
- One command to run: `docker compose up --build`. App at `http://localhost:3000`, API docs at `http://localhost:8000/docs`.
- Back up the database with `docker compose cp api:/db/app.db ./backup.db`. Document this in the README.

### 3.3 Environment variables (`.env.example`)

```
GEMINI_API_KEY=                         # video analysis only (D24)
GEMINI_VIDEO_MODEL=gemini-3.8-flash     # verify current free-tier Flash model id
ANTHROPIC_API_KEY=                      # research, clip finding and writing (D24)
ANTHROPIC_MODEL=                        # Claude model id for those calls
YOUTUBE_API_KEY=                        # optional; research degrades gracefully without it
HIGGSFIELD_API_KEY=                     # thumbnails (7.13): the console's API key ("id:secret" in one value); each image is a paid call
IMPORT_DIR=./inbox                      # host folder to import videos from (read-only)
DATA_DIR=/data
DB_PATH=/db/app.db
CONFIG_DIR=/config
WEB_ORIGIN=http://localhost:3000        # the only origin allowed by CORS
ANALYSIS_FPS=1                          # full-pass sampling rate; the only rate measured in Phase 0
ANALYSIS_MEDIA_RESOLUTION=              # empty = the model's default, the only setting measured in Phase 0
EVENT_DETECTORS=gemini                  # comma-separated detector ids, in merge priority order (7.3.1)
EVENT_SNAP=off                          # off | visual (7.3)
SEARCH_DEMAND=youtube_suggest           # youtube_suggest | off (7.7.1; free, unofficial)
EXPORT_VERTICAL_SIZE=1080x1920
WATCH_POLLING=false
```

Model ids change often. Never hard-code them; read from settings and surface the active model in the UI footer.

---

## 4. Data model (SQLite via SQLModel)

Use string UUIDs for ids, UTC ISO timestamps, JSON columns for nested data. Open SQLite in WAL mode with a busy timeout of 5 s.

| Table | Fields |
| --- | --- |
| `video` | id, title, subject, topic (game or series; may be empty), topic_terms (free text, optional), kind (`long` \| `clip`), preset_id (default `general`), status (`importing` \| `ready` \| `error`), import_source, import_ref, source_path, proxy_path, duration_s, width, height, fps, size_bytes, published_url, published_at, created_at |
| `analysis` | id, video_id, model, fps, summary, basics (JSON), raw (JSON), created_at |
| `event` | id, video_id, t_start, t_end, t_model_start, t_model_end (the model's original times; null for user events), type, label, intensity (`low`\|`medium`\|`high`), crop_safe_9x16 (bool), confidence (`certain`\|`uncertain`), source (`model`\|`user`), detected_by (JSON list of {detector, t_start, label, evidence}: every detection merged into this event, 7.3.1; empty for user events), verified (bool), hidden (bool), edited (bool: the user moved, retyped or relabelled a model event) |
| `segment` | id, video_id, kind (`dead_time`\|`peak`\|`section`), t_start, t_end, label |
| `intensity_sample` | video_id, t, score (0–1). One row per 0.5 s |
| `fact` | id, video_id, key, label, value (JSON), proposed_value (JSON), confirmed (bool), evidence_ts (JSON), evidence_event_ids (JSON), confirmed_at |
| `clip` | id, video_id, name, t_start, t_end, prompt, reason, payoff_t, dead_time_s, crop_warning, status (`candidate`\|`selected`\|`exported`) |
| `clip_export` | id, clip_id, crop (`none`\|`9x16`), mode (`accurate`\|`lossless`), path, width, height, fps, created_at |
| `research` | id, subject_key, topic_key, kind (`subject`\|`competitors`), payload (JSON), overrides (JSON: fields the user changed), sources (JSON list of {title,url,credible}), created_at. Keys are the lower-cased, punctuation-stripped names, so a second video on the same subject reuses the row |
| `package` | id, video_id, clip_id (nullable), platform (`youtube`\|`shorts`\|`reels`\|`tiktok`), fields (JSON), alternates (JSON), edited_fields (JSON list), rule_results (JSON), inputs_hash, version, created_at |
| `job` | id, video_id, kind, status (`queued`\|`running`\|`done`\|`error`), progress (0–1), message, error, created_at, updated_at |
| `library_item` | id, video_id (nullable), title, subject, topic, angle, hook, url, playlist, published_at. Past uploads, used for end-screen targets and cannibalization checks |
| `llm_call` | id, job_id, provider, model, purpose, prompt, tokens_in, tokens_out, latency_ms, status, created_at |

Notes:

- The status shown in the UI is derived, not stored: Importing, Analyzing, Needs confirmation (a required fact is unconfirmed), Ready, Packaged, Published, Error.
- `package.inputs_hash` covers the confirmed facts, effective research values, visible events, clip range, preset and channel profile. A package is stale when the hash no longer matches (9.7).
- A video with `kind = clip` is a pre-trimmed clip. On import it gets one `clip` row spanning the whole video; short-form packages apply and the long-form package is off by default.

Create tables at startup if missing. No Alembic in v1; keep a `schema_version` row and simple forward-only migration functions.

---

## 5. Presets (the niche layer)

A preset adapts the generic engine to one kind of content. Presets are optional. With none chosen the video uses `general`. Everything niche-specific lives here and is user-defined (D17): event vocabulary, facts, hooks, claim rules, title patterns and short-form templates. The core never mentions hits, bosses or damage.

The user can switch preset per video from the workspace header and view what a preset defines. Editing: Phase 1 ships a raw YAML editor with validation; the form editor comes in Phase 3.

Switching preset re-labels the UI immediately. It marks analysis as stale only if the event vocabulary changed, and offers "Re-analyze with this preset" (7.12). Events whose type the new preset does not define stay visible with a neutral chip until re-analysis.

Loading and validation:

- A preset that fails validation is not loaded. The app still starts, shows a config error card naming the file and the problem, and keeps a built-in copy of `general` available.
- Deleting a preset that videos still use switches those videos to `general` and says so.
- The API writes YAML with a round-trip writer so hand-written comments survive.

### 5.1 Preset schema

```yaml
id: boss_fight
name: Boss fight
description: Skilled boss-fight runs in hard action games.

event_types:
  - {id: counter,      label: Counter,      glyph: slash,   color: accent, definition: "The player lands a perfect counter or riposte."}
  - {id: parry,        label: Parry,        glyph: slash,   color: paper,  definition: "The player deflects an attack without a follow-up."}
  - {id: hit_taken,    label: Hit taken,    glyph: dot,     color: warn,   definition: "The player's health bar drops."}
  - {id: boss_attack,  label: Boss move,    glyph: dot,     color: paper,  definition: "A named or distinctive boss attack.", show: false}
  - {id: phase_change, label: Phase change, glyph: ring,    color: paper,  definition: "The boss enters a new phase or transforms."}
  - {id: finisher,     label: Finisher,     glyph: diamond, color: gold,   definition: "The killing blow or finishing animation."}

facts:
  - key: hits_taken
    label: Hits taken
    type: int                 # int | text | bool | enum (with options)
    derive_from: hit_taken    # count of visible events of this type
    required: true
    instructions: >
      List each timestamp where the player's health drops, or state clearly
      that it never drops. If the health bar is not visible, say so.
  - {key: counter_count, label: Counters landed, type: int, derive_from: counter}
  - {key: encounter,     label: Encounter,       type: text}

research_fields:
  - {key: canonical_name}
  - {key: real_name}
  - {key: epithet,       needs_credible_source: true}
  - {key: questline}
  - {key: phases}
  - {key: signature_mechanics}
  - {key: is_final_boss, type: bool, needs_credible_source: true}
  - {key: is_first_boss, type: bool, needs_credible_source: true}
  - {key: studio}
  - {key: platforms}
  - {key: protagonist}
  - {key: nicknames,     label: Nicknames,      hint: "names players and guides use for the boss besides the official one"}
  - {key: genre,                                hint: "the game's genre as its makers and major reviewers describe it"}
  - {key: is_soulslike,  label: Is a soulslike, type: bool, needs_credible_source: true}
  - {key: related_games, label: Related games}
credit_fields: [real_name, epithet, questline, platforms, studio]
credit_lines: ["Boss: {real_name} ({epithet})", "Game: {topic} ({platforms}, {studio})"]

hooks:
  - {id: no_hit,   text: "No Hit",                       thumbnail_word: "NO HIT",             thumbnail_text_style: "gold, heavy black outline", when: {fact: hits_taken, op: eq, value: 0}}
  - {id: one_hit,  text: "Only 1 Hit Taken",             thumbnail_word: "1 HIT TAKEN",        when: {fact: hits_taken, op: eq, value: 1}}
  - {id: few_hits, text: "Only {hits_taken} Hits Taken", thumbnail_word: "{hits_taken} HITS",  when: {fact: hits_taken, op: between, value: [2, 3]}}
  - {id: counters, text: "{counter_count} Counters",     when: {fact: counter_count, op: gte, value: 3}}
  - {id: final_boss, text: "Final Boss", thumbnail_word: "FINAL BOSS", when: {research: is_final_boss, op: eq, value: true}}
thumbnail_words: ["2 V 1"]    # extra words with no claim attached

title_patterns:               # the owner's playbook: recommended, search-max, on-brand, short
  recommended: "{topic} - {subject} Boss Fight ({hook})"
  alternates:
    - "{topic} {subject} Boss Fight | {search_tail}"
    - "{topic} - How to Beat {subject} | Boss Made Easy"
    - "{topic} - {subject} ({hook})"

claim_rules:
  - id: no_hit_claim
    phrases: ["No Hit", "No Damage", "Hitless", "Flawless", "Untouched", "Zero Hits", "Without Getting Hit", "Perfect Run"]
    requires: {fact: hits_taken, op: eq, value: 0}
    severity: block
  - {id: final_boss_claim, phrases: ["Final Boss"], requires: {research: is_final_boss, op: eq, value: true}, severity: block, suggest: "Final Fight"}
  - {id: first_boss_claim, phrases: ["First Boss"], requires: {research: is_first_boss, op: eq, value: true}, severity: block}

clip_rules:
  lead_in_s: 0.5              # start this long before the first event in range
  tail_s: 0.5                 # end this long after the closing event
  end_on: [finisher]          # event types that close a clip; falls back to the last event in range
  start_cue: "a beat before the first clash"
  end_cue: "on the result flash, before any dissolve"

saved_prompts: ["Longest counter chain", "Finisher", "Phase change"]
tag_recipe: [topic_variants, subject_names, difficulty_terms, questline_area, mechanics, protagonist, platforms, studio, related_games, channel]
banned_tags:                  # removed automatically unless research says the label is accurate
  - {tag: soulslike, unless: {research: is_soulslike, op: eq, value: true}}
search_seeds: ["{topic} boss", "{topic} bosses", "{topic} {name} boss fight", "how to beat {name}"]   # 7.7.1
search_fit: "This video is one boss fight ... 'boss fight' and 'how to beat' fit; 'walkthrough' does not."
fallback_hashtags: ["#BossFight", "#Gameplay"]
playlist_name: "{topic} — All Boss Fights"

slots:                        # text the writer model fills (7.8)
  hook_line: "1 to 2 sentences that open the description and restate the title's promise in plain words."
  search_tail: "2 to 4 words players search with this boss (questline, area or nickname); not Boss or Fight."
  body_paragraph: "3 to 5 sentences on the tactics that worked, in first person."
  tip: "One specific tip that pays off during the clip, 2 sentences."
  plain_hook: "On-screen text in plain language with a number, no niche jargon."
  what_happens: "One sentence on what happens in the clip."
  term_explained: "The game's term for the mechanic, explained in one line."
  question: "A question that invites a reply."
  emoji: "One fitting emoji."

templates:
  shorts_description: |
    {hook}. That's all {subject} got. {emoji}

    {tip}

    Full fight + every boss: {playlist_url}

    {hashtags}
  reel: |
    ON-SCREEN: {plain_hook}. No cuts.
    CAPTION: {what_happens} {term_explained}

    {question}

    Full boss fights on YouTube: {channel_name}

    {hashtags}
  reel_end_text: "Full fight on YouTube {handle}"
```

Schema rules:

- `requires` and `when` share one condition shape: `{fact|research: key, op: eq|ne|gt|gte|lt|lte|between|in, value}`.
- A `fact` condition is only true when that fact is confirmed. A `research` condition uses the effective value (7.7).
- A hook is eligible when its `when` holds. Only eligible hooks, and their thumbnail words, are offered to the writer and the user.
- Every `{name}` in a pattern or template must be a built-in variable, a fact key, a research key or a declared slot (7.8). Unknown names fail validation.

### 5.2 General preset (default)

```yaml
id: general
name: General
description: Works on any video. No niche vocabulary, no claim rules.
event_types:
  - {id: highlight,    label: Highlight,      glyph: slash,   color: accent, definition: "A moment a viewer would want to see again."}
  - {id: scene_change, label: Scene change,   glyph: ring,    color: paper,  definition: "The location, activity or subject changes."}
  - {id: screen_text,  label: On-screen text, glyph: dot,     color: paper,  definition: "New text appears on screen."}
  - {id: peak,         label: Peak moment,    glyph: diamond, color: gold,   definition: "The most striking moment of a section."}
facts: []
research_fields:
  - {key: canonical_name}
  - {key: summary}
  - {key: nicknames, label: Nicknames}   # names searched besides the official one (7.7.1)
credit_fields: []
hooks: []
thumbnail_words: []
title_patterns:
  recommended: "{topic} - {subject}: {hook}"
  alternates: ["{subject}: {title_angle}"]   # title_angle: a 3-6 word slot; what_happens is too long for a title
claim_rules: []
clip_rules: {lead_in_s: 0.5, tail_s: 0.5}
saved_prompts: ["Best 30 seconds", "Opening", "Ending"]
tag_recipe: [subject_names, topic_variants, channel]
banned_tags: []
slots:
  hook_line: "1 to 2 sentences that open the description and say what the video shows."
  body_paragraph: "3 to 5 sentences on what happens and what is worth noticing."
  plain_hook: "On-screen text in plain language, one short line."
  what_happens: "One sentence on what happens in the clip."
  question: "A question that invites a reply."
  emoji: "One fitting emoji."
templates:
  shorts_description: |
    {plain_hook} {emoji}

    {what_happens}

    {full_video_ref}

    {hashtags}
  reel: |
    ON-SCREEN: {plain_hook}
    CAPTION: {what_happens}

    {question}

    {full_video_ref}

    {hashtags}
  reel_end_text: "Full video on YouTube {handle}"
```

In General mode the Facts panel is titled "Detected", shows counts without confirm switches, and only universal rules run. With no eligible hook, the writer fills `{hook}` with a claim-free phrase drawn from the timeline.

---

## 6. Channel profile (`config/channel.yaml`)

Holds everything that is about the channel and true for every preset: identity, links, counts and the long-form description layout. Niche wording belongs in presets (D17). Seed it with this content.

```yaml
name: TheLazyRonin
display_name: The Lazy Ronin
handle: "@thelazyronin"
tagline: "I make difficult games look easy."
subscribe_url: "https://www.youtube.com/@thelazyronin?sub_confirmation=1"
format: faceless
default_preset: general
strategy_mode: search_first        # search_first | hook_first
playlists:
  - {topic: "Onimusha: Way of the Sword", name: "Onimusha — All Boss Fights", url: "https://www.youtube.com/playlist?list=PLRXz5KwhnmcA"}  # id unverified by owner
description_template: |
  {hook_line}

  {body_paragraph}

  {display_name} - {tagline}

  Full playlist: {playlist_url}
  Subscribe: {subscribe_url}

  CHAPTERS
  {chapters}

  {credit_block}

  {hashtags}
hashtags: {youtube: 3, shorts: 5, reels: 5, tiktok: 5}
shorts_required_hashtag: "#Shorts"
tags_target: 20
thumbnail_style:
  text_default: "white, heavy black outline"
  avoid: "red text in fire-heavy scenes; text over faces or weapons"
  words: "2-4 words, never repeats the title"
vertical_safe_margins: {top_pct: 12, bottom_pct: 15}
credible_domains: []               # research sources treated as credible; owner to fill (section 13)
blocked_domains: []                # research sources never used
baselines:
  reel_skip_rate_pct: 23
  reel_share_rate_pct: 0.7
```

A preset may override `description_template` by defining `templates.description`.

---

## 7. Backend pipelines

All long work runs as a job (7.11). Each job writes progress to the `job` row and pushes events to an SSE stream so the UI can show results as they arrive.

### 7.1 Import

Import sources implement one interface:

```python
class ImportSource(Protocol):
    id: str
    async def list(self) -> list[ImportItem]: ...          # name, ref, size_bytes, modified_at
    async def fetch(self, ref: str, dest: Path, on_progress) -> None: ...
```

- v1 ships `local`: it lists video files under `/inbox` (recursive, by extension) and copies the chosen one. Resolve `ref` against `/inbox` and reject anything that escapes it.
- Planned, Phase 3: `google_drive`. It needs a Google OAuth client for a local app and read access to the files the user picks; it downloads into the same destination and then follows the same pipeline. Verify the current Drive scopes and consent rules before building.
- Interim route with no code: Google Drive for desktop can mirror a Drive folder to local disk, and `IMPORT_DIR` can point at it. Verify that Docker can read the mirrored folder; streamed (online-only) files may not be readable.

Steps:

1. `GET /imports` lists the files, marking any already imported (same ref and size).
2. `POST /videos` with `{source, ref, title, subject, topic, topic_terms, kind, preset_id}` creates the row (`importing`) and starts the import job.
3. Copy to `data/media/<id>/source.<ext>` with progress.
4. `ffprobe` for duration, resolution, fps, codecs. Reject non-video.
5. Transcode a proxy: 720p H.264, source frame rate, constant frame rate, a keyframe every 0.5 s, AAC audio, `+faststart`. The proxy is used for playback, the Gemini upload and intensity. The source is used only for export and on-demand frames. The proxy must keep the source's timeline (same start and duration within one frame); test this.
6. Extract a filmstrip from the proxy: one JPEG per second, 320 px wide, to `frames/`. For videos over 10 minutes, cap at 600 evenly spaced frames.
7. Compute intensity (7.2).
8. Queue `analysis` and `research` jobs in parallel.

If ffprobe reports an HDR transfer on the source, show a notice: v1 does not tone-map, so exports of HDR footage may look washed out.

### 7.2 Intensity track (no LLM)

Purpose: the waveform row, dead-time detection and optional event snapping.

- Run ffmpeg scene scoring on the proxy, for example `ffmpeg -i proxy -vf "select='gte(scene,0)',metadata=print:file=-" -an -f null -`, and parse `lavfi.scene_score` per frame.
- Save the per-frame scores to `scene_scores.bin`. Bucket into 0.5 s samples (mean), normalise 0–1 with a robust max (95th percentile), and store those as `intensity_sample` rows.
- Dead time = runs of at least 1.0 s below a threshold (start at 0.08, make it a setting).
- If scene scoring proves poor on gameplay, fall back to mean absolute frame difference on downscaled grayscale frames. Keep this behind one function so it can change.

### 7.3 Video analysis (Gemini)

- SDK: Google GenAI Python SDK 3.x (`from google import genai`; `client = genai.Client()`), using the Interactions API: `client.interactions.create(model=..., input=[...], response_format=...)`. Checked against the SDK source and the docs on 2026-11-14:
  - A video part is `{"type": "video", "uri", "mime_type", "processing", "resolution"}`. Put the text prompt after it.
  - `processing` is `{"type": "static", "fps": n}` or `"agentic"`. A sampling rate only applies in static mode; agentic mode lets the model choose what to load and is cheaper on long videos. Phase 0 compares both.
  - `resolution` is `low`, `medium` or `high`, set per part.
  - Structured output: `response_format={"type": "text", "mime_type": "application/json", "schema": Model.model_json_schema()}`.
  - Token usage: `interaction.usage.total_input_tokens` and `total_output_tokens`.
- Upload the proxy with the Files API and poll until the file state is `ACTIVE` before prompting. Delete the remote file after each call.
- Limits, from the docs on 2026-11-14: Files API 2 GB per file, kept 48 hours; default sampling 1 frame per second; for Gemini 3 and 4 models, 70 tokens per frame at low, medium or default resolution and 280 at high, plus 25 tokens per second of audio. Other doc pages give different per-frame figures, so trust the usage returned by each call. A 10-minute video at 5 fps is about 225,000 input tokens at default resolution.
- Free-tier rate limits are not published in the docs; they are shown per project in AI Studio. The tokens-per-minute limit decides how high the sampling rate can go, and Phase 0 finds it by running.
- Timestamps: the docs use `MM:SS`, so the LLM-facing schema asks for clock strings (`M:SS.s`) and the server parses them to seconds. Phase 0 can compare this with plain seconds.
- Ask for JSON only, validated with a Pydantic schema built from the preset (event type enum, fact keys). Verify whether response-schema structured output is supported with video input for the chosen model; if not, request fenced JSON and validate with one repair retry.
- The call returns the whole timeline at once. The server validates and stores it, then emits one `analysis.event` per event in time order so the UI can animate the marks in.

**Timestamp accuracy (D19).** At 1 frame per second the model cannot see most sub-second events, so timing and counts suffer. The footage is short, which makes better sampling affordable.

1. **Full pass.** Sample at `ANALYSIS_FPS`, lowered when needed so the request fits the token limits. Phase 0 only measured 1 fps at the default resolution, so that is the default. Higher rates and `high` resolution are untested; score them with `eval_analysis.py` before changing the default.
2. **Refine pass (on demand).** For a clip edge or a single event: cut a window of about 6 s around the time from the source with ffmpeg, upload that small file, sample it at a high rate, and ask only for the exact moment of the cue. Add the window offset back to the answer. Triggered by "Refine edges" on a clip and "Refine" on an event.
3. **Visual snap (experimental, `EVENT_SNAP=visual`).** Move each model event to the largest spike in the per-frame scene scores within ±0.75 s, if one stands out. Keep the model's original time in `t_model_start`. Off by default; enable only if Phase 0 shows it helps.
4. **Eye test.** The user reviews events in the timeline (9.4): move, retype, hide or verify each one. This is the final authority.

If a video exceeds the limits even at 1 fps, split it into chunks with 5 s overlap and merge events (dedupe by type within 0.75 s).

**Analysis output schema**

```json
{
  "basics": {
    "subject_name_on_screen": "string|null",
    "on_screen_text": [{"text": "", "position": "top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right", "persistent": true}],
    "audio_notes": "string"
  },
  "events": [{
    "t_start": 0.0, "t_end": 0.0,
    "type": "<one of preset.event_types ids>",
    "label": "short human label",
    "intensity": "low|medium|high",
    "crop_safe_9x16": true,
    "confidence": "certain|uncertain"
  }],
  "segments": [{"kind": "peak|section", "t_start": 0.0, "t_end": 0.0, "label": ""}],
  "fact_proposals": [{"key": "<preset fact key>", "value": "string, parsed to the fact's type", "evidence_ts": [0.0], "confidence": "certain|uncertain"}],
  "first_seconds": [{"t": 0, "description": "", "intensity": "low|medium|high"}],
  "first_frame": "one sentence",
  "last_frame": "one sentence"
}
```

Duration comes from ffprobe, not the model.

**Analysis prompt (template, `prompts/analysis.md`)** — keep these instructions, fill the braces. Nothing niche-specific is written here; it arrives through the preset's event definitions and fact instructions.

```
You are analyzing a video for a publishing assistant. Report only what you can
see and hear. If unsure, mark confidence "uncertain" instead of guessing.
Do not give opinions on whether it will perform well.

Context: {kind} of about {duration} from {topic_or_unknown}. Subject: {subject_or_unknown}.
Event types to use, with definitions: {event_types_with_definitions}
Extra terms for this topic: {topic_terms}

Return JSON matching the schema. Requirements:
1. BASICS: on-screen text and where it sits (HUD, subtitles, prompts, overlays, watermarks).
2. FIRST 7 SECONDS: one entry per second.
3. EVENTS: every notable event to the end. Give the moment each one starts as
   precisely as the footage allows.
4. SECTIONS: the main parts of the video in order, with start and end times.
5. FACT PROPOSALS: for each fact below, propose a value with evidence timestamps,
   following that fact's instructions: {facts_with_instructions}
6. PEAK: the single most striking 2 to 3 seconds.
7. FRAMING: for each event, would a centered 9:16 crop cut off the key action?
8. AUDIO: what is audible and what is most prominent at key moments.
9. FIRST AND LAST FRAME: one sentence each.
```

The shipped template (`prompts/analysis.md`) adds two things measured in Phase 0: a rule that the same event type can happen many times and every occurrence is its own event, and an optional playbook block (7.3.1).

### 7.3.1 Event engine (D25)

Event understanding is the part of the app most likely to change. It is built as separate stages with fixed contracts between them, so one stage can be improved or replaced without touching the others.

```
preset definitions + optional playbook
              │
   detectors (one or more)  ──>  merge  ──>  event rows  ──>  eye test (9.4)
```

**Contract** (`services/events/base.py`):

```python
class Detection(BaseModel):
    t_start: float
    t_end: float | None = None
    type: str                      # a preset event type id
    label: str = ""
    confidence: Literal["certain", "uncertain"] = "certain"
    intensity: Literal["low", "medium", "high"] | None = None   # filled by detectors that judge it
    crop_safe_9x16: bool | None = None
    detector: str                  # id of the detector that produced it
    evidence: dict = {}            # detector-specific, e.g. {"from": 0.68, "to": 0.31}

class Detector(Protocol):
    id: str
    def enabled_for(self, ctx: DetectionContext) -> bool: ...   # e.g. gauge needs a playbook region
    async def detect(self, ctx: DetectionContext) -> list[Detection]: ...
```

`DetectionContext` carries the proxy path, the duration, the preset, the video's topic, subject and terms, the playbook if one exists, and the providers.

**Stages**

- **Detectors** (`services/events/detectors/`). Registered by id and chosen with `EVENT_DETECTORS`. A detector only returns detections; it never writes to the database and never imports another detector.
  - `gemini`: the full pass of 7.3. On by default and the only one required. Its basics, segments and fact proposals pass through unchanged.
  - `gauge`: reads how full an on-screen bar is from the pixels, with no model (Phase 0 probe: `scripts/gauge_probe.py`). Runs only when the playbook gives the bar's region. In Phase 0 it found 18 of the 24 hits the owner confirmed and the other 6 show no change in the health bar; Gemini found at most 3 of 11 and 3 of 13.
  - `flash`: a full-screen colour burst (Phase 0 probe in `scripts/review_sheet.py`). It proposes moments and is not reliable enough to decide on its own: 2 of the 5 moments only it proposed were real.
  - Later candidates, each a new file and a registry entry: the refine pass (7.3), an audio-cue detector, a second model.
- **Merge** (`services/events/merge.py`). A pure function from detections to events. Same-type detections from different detectors within 3 s become one event. Detections from one detector are never merged with each other, because a fight can hold many counters a second apart. The time comes from the first detector in `EVENT_DETECTORS` order that reported it, with pixel detectors listed before the model when both run. Every contributing detection is kept in `event.detected_by`. Detections of different types at the same moment are both kept; the eye test decides.
- **Guidance**. Detectors get event definitions from the preset (5.1). A playbook (`config/playbooks/<topic>.yaml`) can add what each event looks like in that topic and where on-screen gauges sit. It is optional and is data, not code (D14, D17). Phase 0 result: cues taken from web research alone made Gemini report no counters at all, while cues written from the footage gave the best counter results (10 of 11 and 3 of 6 found, one run each, on the two videos the cues were written from). So a playbook is written from footage by the owner, never from web text alone, and v1 does not generate one automatically.
- **Review**. The eye test is the authority (D8, D19). It shows which detectors proposed each event.
- **Measurement**. `eval/` holds the owner-reviewed labels, made with `scripts/review_sheet.py`. `eval_analysis.py` scores one detector or the merged output against them. A change to a detector, the merge rules, the prompt, the sampling rate or a playbook becomes the default only after it scores better there.

**Rules that keep it modular**

- Nothing outside `services/events/` knows which detectors ran. Clip finding, facts and packaging read `event` rows only.
- Topic-specific knowledge (bar positions, cue descriptions) lives in playbooks, never in code.
- A detector that is not configured for a video is skipped without an error.
- Adding a detector needs no schema change: its details go in `evidence` and `detected_by`.

### 7.4 Facts and confirmation

- After analysis, create a `fact` row per preset fact with `proposed_value` from the model and `confirmed=false`. Map each `evidence_ts` to the nearest event of the fact's `derive_from` type and store both.
- The UI shows each fact as a row with its value and a confirm switch. The value is editable before confirming (number stepper, text input or select, by type). Confirming sets `value`, `confirmed=true`, `confirmed_at`.
- Derived facts (`derive_from`) recompute from visible events when the user adds, hides or retypes events, until confirmed. After confirmation they are locked; editing events shows a "fact may be out of date" warning. Unconfirming a derived fact clears the locked value so it follows the events again.
- Fact rows exist for every preset fact even before an analysis (created on first read), so a video without a Gemini key can still be counted by hand.
- Undo of event edits lives in the web app: it keeps each event as it was before an edit and sends it back; a deleted event is restored whole with its id, so fact evidence keeps pointing at it.
- Precondition for packaging: every `required` fact of the preset is confirmed. Until then the generate action is disabled and says which fact is missing. General mode has no required facts.

### 7.5 Clip finder

Input: free-text prompt, target platform, target length (optional).

- Runs on the stored timeline, not by re-watching the video: send events, segments, dead time and intensity summary as JSON to the text model with the preset's `clip_rules`.
- Output: 3 to 5 candidates: `{name, t_start, t_end, reason, payoff_t}`.
- Server-side post-processing (deterministic, not LLM):
  - Clamp to video bounds; enforce minimum 3 s and the platform's maximum length.
  - Snap start to `lead_in_s` before the first event in range. Snap end to `tail_s` after the last `end_on` event in range, or after the last event if there is none.
  - Compute `dead_time_s` inside the range, the count of each event type in range, and `crop_warning` if any event in range has `crop_safe_9x16=false`.
- Optional refine pass (7.3) tightens start and end when the user clicks "Refine edges".
- The user nudges either edge in 0.5 s steps. Every change persists.
- "Analysis note": one deterministic suggestion per selected clip, generated in code and re-evaluated whenever the edges change. Examples: first event lands more than 1.0 s after clip start (which happens after manual nudges, or when a range starts on dead time) → suggest starting later; payoff later than 7 s into a short → suggest an on-screen promise; dead time over 2 s inside the clip → show where.

### 7.6 Clip export (ffmpeg)

Exports are cut from the source file, never the proxy, and keep the source frame rate (D20).

- **Accurate (default):** re-encode at near-lossless quality: `ffmpeg -ss {start} -to {end} -i source -c:v libx264 -crf 16 -preset slow -pix_fmt yuv420p -c:a aac -b:a 256k -movflags +faststart out.mp4`. Source resolution is kept.
- **9:16:** add `-vf "crop=trunc(ih*9/16/2)*2:ih,scale=1080:1920:flags=lanczos"`. The centre crop of a 1440p source is 810×1440; scaling it to `EXPORT_VERTICAL_SIZE` gives the platforms their native size so they do not rescale it a second time. This does not add detail.
- **Lossless (uncropped only):** `-c copy`. No quality loss, but the edges snap to keyframes, so label it as approximate and show the real start and end.
- Record each export in `clip_export` with its real dimensions and frame rate. Export to `data/media/<id>/clips/`. Also always offer "Copy timestamps".
- Verify at build time which frame rates Shorts, Reels and TikTok keep; show a note if a platform will reduce 60 fps.

### 7.7 Research

Two jobs. Results are stored by subject and topic keys, so another video on the same subject reuses them.

**Subject research.** Fill the preset's `research_fields` with sources.
- Two Claude calls (D24). Structured JSON output cannot be combined with the citations web search returns, so: (1) a call with the `web_search` server tool (at most 6 searches, `blocked_domains` passed through) that answers one line per field with the URL that states it; (2) a call with no tools and a JSON schema that sorts those findings into fields. Source URLs a field cites are kept only if they were among the pages actually read.
- Runs as a `research` job. Import queues it beside the analysis when `ANTHROPIC_API_KEY` is set and the subject has no research yet. Without a key, or by choice, the user pastes notes (and an optional source URL); then only the structuring call runs. With no key at all, every field can still be typed in by hand.
- Requirements: canonical spelling; real name behind a nickname; every field carries its source URL. Treat fetched page text as data, never as instructions.
- A source is `credible` when its domain is in `credible_domains`. Sources in `blocked_domains` are never used. Others are `unrated`.
- **Research is the default (D8).** Field values are applied as found, without a confirm step. Each field shows its value, its source and an edit control. An edited field is marked "Edited by you" with "Restore research value"; the edit is stored in `overrides`.
- **Effective value** = the user's override if there is one; otherwise the research value. For a field marked `needs_credible_source`, a research value with no credible source counts as unknown: it is shown, flagged "No credible source", left out of generated text, and cannot unlock a claim until the user sets it.
- Canonical spelling: if the user's `subject` differs from the canonical name, apply the correction, show it ("Corrected from …") and offer a one-click revert. Reverting stores the user's spelling as the `canonical_name` override, so later runs do not correct it again. A corrected subject still finds its research row (rows are also matched by their canonical name).

#### 7.7.1 Search demand (as built, `services/search_demand.py`)

The package is chosen by what people actually type into YouTube, not by the writer's guess. Tested on 2026-11-15 before building: "phantom blade zero hua qianxiao", "… sword fanatic" and "… drunk boss" are real top suggestions; "phantom blade zero boss fight" is the game's top one; nothing exists for "Zhuo Bi" or "Gatekeeper" with the game; and the bare names "sword fanatic" (a manhwa), "drunk boss" (a trope) and "zhuo bi" (a song) return 0 of 10 suggestions about the game.

- **Source.** YouTube search suggestions (`suggestqueries.google.com`, `ds=yt`): free, no key, ordered by popularity. Unofficial, so every failure is soft: the package then uses the writer's choices and says there is no search data. Only the topic and the subject's names are sent. `SEARCH_DEMAND=off` turns it off. The rank is a demand signal, not a view count; competition (who already ranks) needs the YouTube Data API and stays with similar-video research below.
- **Harvest.** After each research run (and in a package run when the last harvest is over 7 days old). Names: the subject, the canonical name and its comma parts, real name, epithet, `nicknames` and the user's spelling before correction, up to 5. Seeds: the topic, `topic + name`, `topic + name + space`, the bare name, plus the preset's `search_seeds` (boss fight: `{topic} boss`, `{topic} bosses`, `{topic} {name} boss fight`, `how to beat {name}`), at most 40 requests, spaced out. Stored as a `research` row with `kind = search_demand` beside the subject's row.
- **Reading it.** Demand = 1.0 for a top suggestion down to 0.1 for the tenth, +0.05 for each extra seed that found it. A bare name is **ambiguous** when it has 3+ suggestions and under 30% mention the topic. Candidate phrases must name the topic, or a subject name that is not ambiguous (so "drunk boss manga" and "sekiro how to beat drunk boss" are out). A phrase carrying a claim that is not backed (for example "no hit") is excluded with the reason.
- **Fit (the writer).** The writer call gets the phrases with their rank and marks each `fits` only if someone typing it would want this exact video; the preset's `search_fit` says which generic phrases describe its kind of video (boss fight: "boss fight", "how to beat" fit; "walkthrough", "all bosses" do not). Code uses only fitting phrases.
- **Title (code).** Every candidate is scored: the sum of demand over the fitting phrases it covers (1.0 if their words appear in order, 0.6 in any order), a match ending past 60 characters counts 70%, each repeated word costs 15%, every character past 70 costs 2% (down to half), a title the claim and number rules would block scores 0, and each warning it would draw costs 20%. On a `search_first` channel the best-scoring candidate becomes the title; a tie keeps the writer's pick. `seo.picked_by` says which happened. On `hook_first` the writer's pick stands.
- **Tags (code).** Up to 8 fitting phrases first, most popular first, then the writer's tags; tags that differ only by small words are one tag; bare ambiguous names are dropped (the topic-anchored form stays); then the 500-character fit.
- **Hashtags (rule).** A hashtag of an ambiguous bare name sends viewers to the wrong page (#SwordFanatic is a manhwa): it is swapped for the preset's `fallback_hashtags` (boss fight: `#BossFight`, `#Gameplay`) or dropped.
- **Shown.** `fields.seo` keeps the phrases (fit, in title, in tags), every candidate's score, the current title's score against the best, and the ambiguous names; the Markdown export has a "Search demand" section. Measured live: Gate Keeper's title moved from the writer's 84-character "…Boss Fight (Ghoststep Counters and Parries)" to "Phantom Blade Zero Zhuo Bi, the Gatekeeper Boss Fight | Village of Lu" (covers "phantom blade zero boss fight"); Sword Fanatic's carries "hua qianxiao", "sword fanatic" and "drunk boss" with the game name.

**Similar-video research.** Requires `YOUTUBE_API_KEY`; without it, show a manual-entry state.
- Query: preset-built search phrase (General: `{topic} {subject}`; boss fight: `{topic} {subject} boss fight`).
- YouTube Data API: `search.list` (expensive in quota; cache hard, one call per subject per day) then `videos.list` and `channels.list` for stats.
- Output per video: title, channel, subscribers, views, age, duration, thumbnail URL. Analysis (text model): shared title patterns, common thumbnail words, the unclaimed angle, and a demand-versus-competition read.
- Cannibalization: fuzzy match the subject against `library_item`. If found, warn and list existing angles.

### 7.8 Packaging

One generation call per platform, text model, JSON output, built from: channel profile, preset, confirmed facts, effective research values, event timeline summary, selected clip (for short platforms), past uploads (for the end-screen target).

**Template variables.** Every `{name}` in a title pattern or template resolves in this order:

| Kind | Names | Filled by |
| --- | --- | --- |
| Built-in | `{topic}`, `{subject}`, `{channel_name}`, `{display_name}`, `{handle}`, `{tagline}`, `{playlist_url}`, `{subscribe_url}`, `{full_video_ref}`, `{chapters}`, `{credit_block}`, `{hashtags}` | Code |
| Hook | `{hook}` | Code renders the eligible hooks; the writer picks one per title. With none eligible, the writer writes a claim-free phrase |
| Fact | `{<fact key>}` | Code, from the confirmed value. Empty if unconfirmed |
| Research | `{<research key>}` | Code, from the effective value |
| Slot | Any name under the preset's `slots` | Writer model, following the slot's instruction |

- `{full_video_ref}` is the source video's published URL if set, else the topic's playlist URL, else a line naming the channel.
- `{credit_block}` is built from the preset's `credit_lines` (boss fight: "Boss: {real_name} ({epithet})", "Game: {topic} ({platforms}, {studio})"; a line whose first variable is empty is left out, and an empty variable takes its comma or brackets with it), or from `credit_fields` as "Label: value" lines when there are none.
- A line whose built-in variable is empty is dropped, along with a heading that would be left alone (for example `CHAPTERS`). An empty variable inside a title is removed with its adjoining separator.
- The writer model returns slot values and a hook choice, never the assembled template. Code assembles the text. This keeps claims out of free text as far as possible (D10).
- As built (Phase 1 step 6, `services/packaging.py`): code first builds every title candidate (each pattern, once per eligible hook where it uses `{hook}`) and sends them to the writer with the confirmed facts, effective research, a timeline summary, the eligible hooks and the claim phrases that may not be used. One Claude call (structured output, `WriterOut`) returns the slot values, a claim-free phrase for `{hook}` when no hook is eligible, the recommended candidate id, a why and goal per candidate, tags, hashtags, `opening_5s`, `pinned_comment`, `community_post` and thumbnail frames and prompt. Code renders titles, the description, chapters and the credit block; thumbnail words come only from eligible hooks and the preset (the writer's words are used only when there are none). Measured on Gate Keeper: 3.8k tokens in, 2k out, 22 s, about $0.05.
- Fields are stored on one `package` row per video and platform; each run bumps `version`. Rule dismissals and `edited_fields` survive regeneration.

**YouTube long-form fields**

| Field | Notes |
| --- | --- |
| `title` | Recommended; follows preset pattern and strategy mode |
| `title_alternates` | 3–4, each with `why` (one line) and `goal`. Offer one alternate per eligible hook where the pattern uses `{hook}` |
| `description` | Rendered from `description_template` |
| `hook_line` | First 1–2 sentences |
| `chapters` | From `section` segment boundaries. First at 0:00, at least 3, each 10+ s apart, and the last one 10+ s before the end (a section closer to the end joins the chapter before it). If the video cannot give three valid chapters, leave them out |
| `tags` | About 20, ordered by the preset's `tag_recipe`; `banned_tags` removed; tags past the 500-character total dropped from the end |
| `hashtags` | Exactly 3 |
| `credit_block` | From `credit_fields` |
| `opening_5s` | What moment to open on or cut |
| `pinned_comment` | A question that splits opinion or invites stories |
| `end_screen_target` | A specific past upload, never the channel page. With no past uploads recorded, the topic's playlist, with a note to add past uploads |
| `community_post` | Poll or teaser for the day before or after |
| `thumbnail` | `{frame_ts: [..], word_options: [..], text_style, prompt}` (D11). Word options come from eligible hooks' `thumbnail_word` plus the preset's `thumbnail_words` |
| `checklist` | Category, captions, end screen, pinned comment, Short cut (the first peak widened to 20–60 s inside the video) |

**Shorts:** `title` (short, first-person, one emoji, topic hashtag), `description` from the preset's `templates.shorts_description` (a tip must pay off during the clip), 5 hashtags including `#Shorts`.

**Reels:** rendered from the preset's `templates.reel`: `on_screen_text` (plain language, no niche jargon), `caption`, `question`, `end_text`, about 5 hashtags, `pinned_comment` pointing to the full video.

**TikTok:** starts from the Reel package, shortened. Conventions not yet established; keep fields the same as Reels.

Every recommendation carries a `goal` tag, one of: `click_through`, `retention`, `session_watch_time`, `engagement`, `funnel`. Show it as a small chip.

Regeneration and edits:

- Regenerating a single field must be possible (`POST /packages/{id}/regenerate` with `field`).
- A manual edit adds the field to `edited_fields`. "Regenerate all" keeps edited fields unless the user ticks "Replace my edits".

**Mark as published.** The overflow menu has "Mark as published": paste the URL, which sets `published_url` and `published_at` and creates a `library_item` from the package (title, subject, topic, hook, playlist). This is how the app's own videos reach the past-uploads list. As built: publishing again updates the same entry; "Unpublish" (`DELETE /videos/{id}/publish`) clears the link and removes that entry. A video's own entry never counts against it in the cannibalization check, and publishing does not make its package stale (`published_url` is not part of the inputs hash).

**Past uploads and the package.** Past uploads change only code-built parts of a package (the end-screen target, the checklist's end-screen line and the cannibalization check). Reading a package refreshes those parts for free when the past-uploads list has changed, instead of marking the package stale and asking for a paid regeneration.

### 7.9 Rules engine (`services/rules.py`)

Pure Python, deterministic, no LLM. Runs after every generation and every manual edit. Returns `[{rule_id, severity: pass|warn|block, field, message, evidence}]`. A `block` disables Copy for that field and shows the reason; the user can fix the text or the underlying fact. A `warn` can be dismissed per package; the dismissal is stored in `rule_results`.

**Universal rules (always on)**

| Rule | Check | Severity |
| --- | --- | --- |
| `claim_needs_fact` | Any preset claim phrase in a title, hook, thumbnail word or on-screen text must satisfy its `requires` | block |
| `number_needs_fact` | Any number in a title, hook, thumbnail word or on-screen text equals a confirmed fact value, or is part of the topic or subject name | warn |
| `canonical_spelling` | Subject spelling matches the effective research value | auto-fix, shown, revertible |
| `search_first_title` | In `search_first` mode, topic and subject lead the title. Compared after normalising case and punctuation; skipped when the topic is empty | warn |
| `chapters_valid` | If chapters are present: first 0:00, at least 3, each 10+ s apart, the last 10+ s long. No chapters passes with a note | block |
| `hashtag_count` | Matches channel profile per platform; Shorts includes `#Shorts` | auto-fix |
| `tags_count` | Within ±5 of `tags_target` | warn |
| `banned_tags` | No tag containing a banned tag in force (any spelling: "Souls-like"). A ban with `unless` lifts when research backs the label (boss fight: `soulslike` unless `is_soulslike`) | auto-fix, shown |
| `tags_fit` | Tags fit the platform's total length; the last ones are dropped until they do | auto-fix, shown |
| `ambiguous_names` | No bare tag or hashtag of a name mostly searched for something else (7.7.1); hashtags get the preset's fallback | auto-fix, shown |
| `search_demand` | The title and the description's first 150 characters carry at least one of the top 3 fitting search phrases (7.7.1). No search data passes with a note | warn |
| `playlist` | The topic has a playlist in `channel.yaml`; otherwise suggest the preset's `playlist_name` | warn |
| `cannibalization` | Subject already in past uploads without a distinct angle. Passes with "No past uploads recorded" when the list is empty | warn |
| `link_back` | Short-form packages include the full-video, playlist or channel reference | block (TikTok: warn, until its conventions exist) |
| `length_limits` | Per-platform character limits from a config table (verify limits at build time) | block |

Preset `claim_rules` are evaluated by `claim_needs_fact`. Match phrases case-insensitively on word boundaries. As built, `claim_needs_fact` also checks the description (written from slots), since a slot could carry a claim. `canonical_spelling` rewrites any spelling of the researched name (case, spaces, hyphens) to the canonical one. Auto-fixes report `fixed: true` with what changed; `length_limits` uses title 100, description 5,000 and tags 500 characters (tags counted with separators, a tag with a space as if quoted); an alternate title over 100 characters gets a warn, since it cannot be picked as the title.

Not rules:

- Required facts are a precondition for generation (7.4), not a check on output.
- Uncut clips need no rule; a clip is one range by construction (D9).
- Vertical safe margins are drawn as guides on the phone-frame preview (9.4); the app renders no text into video, so there is nothing to check.

### 7.10 LLM provider interface

```python
class VideoProvider(Protocol):      # Gemini
    async def analyze_video[T: BaseModel](self, path: Path, prompt: str, schema: type[T],
                            fps: float | None = None,
                            media_resolution: MediaResolution | None = None,
                            processing: Processing = "static") -> LLMResult[T]: ...

class TextProvider(Protocol):       # Claude (services/llm/anthropic.py)
    async def search(self, prompt: str, max_searches: int = 6,
                     blocked_domains: list[str] | None = None) -> SearchRun: ...   # text + pages read
    async def generate_json[T: BaseModel](self, prompt: str, schema: type[T]) -> LLMResult[T]: ...
```

- Claude calls use the beta Messages endpoint with server-side refusal fallbacks (`fallbacks: "default"`) on models that accept them, resume a paused server-side search loop at most 3 times, and send no sampling parameters. `ANTHROPIC_MODEL` empty means `claude-opus-5-5`.

- `LLMResult` carries the parsed model plus the raw text, model id, token usage and latency, so every call can be logged and measured.

- Gemini implements `VideoProvider` only. Claude implements `TextProvider`; `search` uses Claude's web search tool (D24).
- Every Gemini call has a hard timeout enforced outside the SDK. In Phase 0 one call hung for 84 minutes without an error despite the SDK's own timeout.
- `analyze_video` always receives a local file that is already the right window (the proxy, or a short cut for the refine pass), so it takes no clipping offsets.
- Retries with exponential backoff on 429 and 5xx. On free-tier rate limits, surface "waiting for rate limit" in the job message instead of failing.
- Log prompt, model, token counts and latency per call to the `llm_call` table for debugging. Never log the API key.

### 7.11 Job runner

- Jobs are asyncio tasks tracked in the `job` table. Run ffmpeg and ffprobe with `asyncio.create_subprocess_exec`; never block the event loop.
- A restart kills running tasks. At startup, mark every `queued` or `running` job as `error` with the message "Interrupted by a restart" and offer Retry in the UI.
- Make each pipeline step idempotent: skip a copy, proxy or filmstrip that already exists and is complete.
- In development, `--reload` restarts the process on every code save and interrupts running jobs. This is expected.

### 7.12 Re-analysis

Re-analysis runs when the user asks for it or accepts "Re-analyze with this preset". A warning dialog always shows first (D21). It states what will be replaced and what will be kept, with counts.

- **Kept by default:** events the user added, events the user edited (`edited`: moved, retyped or relabelled) or verified, hidden flags, and confirmed facts.
- **Replaced:** model events that were never touched, segments, unconfirmed fact proposals.
- New model events that land within 0.75 s of a kept event of the same type are dropped as duplicates.
- The dialog has one checkbox, off by default: "Also discard my edits and confirmations".
- After re-analysis, a confirmed derived fact whose event count no longer matches shows the "fact may be out of date" warning.

### 7.13 Thumbnail creator (D26; as built: `services/thumbnails.py`, `services/thumbnail_jobs.py`, `services/higgsfield.py`)

The owner's flow before the app: upload a gameplay frame to Higgsfield, generate at 16:9, check faces, hands and leftover HUD, and rebuild at 9:16 for Stories. The app runs the same flow with fewer chances to go wrong.

**Source.** One of three:
1. A frame the **frame finder** suggests (7.13.1).
2. Any moment picked on the filmstrip. The frame is cut from the original file at up to 1920 px wide, not from the 720p proxy.
3. An image the user uploads (JPEG, PNG or WebP, at least 640×360, up to 20 MB).

**Generation** (`thumbnail` job). One Generate click makes a batch: one image per chosen model × aspect (up to four models, to compare them on the same source). For each image:
1. Cut or read the source. Upload it once per batch to Higgsfield (`/files/generate-upload-url`, then a PUT to the presigned URL without our credentials).
2. Ask `/estimate/<model>` for the price, then submit with an `Idempotency-Key`. Poll the status (2 s, ×1.5, capped at 10 s, with jitter; 10-minute limit, then cancel).
3. Download the result straight away; Higgsfield deletes outputs after seven days.
4. A result identical to the source counts as a failure. `nsfw`, `failed` and cancelled requests are not charged and show their reason.
5. Fit the result to 1280×720 (16:9) or 1080×1920 (9:16), draw the word, and save as JPEG under YouTube's 2 MB limit.
6. Review it (below).

**The word.**
- The choices come from the package's `thumbnail.word_options`. Blocked ones are left out, and each hook's word keeps its `thumbnail_text_style`.
- A word the user types runs through the claim and number rules first. A block refuses it before any paid call.
- `text_mode: app` (default): the prompt tells the model to leave the chosen corner clear and add no text, and LazyCut draws the word in Bebas Neue (or Montserrat, League Spartan, DejaVu), with a heavy outline and a soft shadow.
  - Why: exact spelling, the same template on every video (the playbook's "consistent template"), and a free redraw. Changing the word, corner, font or style re-renders from the stored raw image with no model call; the review is marked stale.
  - On 9:16 the word is centred and kept inside `vertical_safe_margins`.
- `text_mode: model`: the model draws the word itself, and the prompt spells it out.

**The corner.** `auto` uses the free corner the frame finder found for that moment (Claude's pick, else the calmest corner by edge density); without one, top right.

**Review.**
- Claude compares the source and the result, with seven checks, each ok or not with a short note: faces, hands, hud (anything left), text (exact spelling and readable at phone size), likeness (boss and player still match), artifacts, and placement (the word does not cover a face, the subject or a weapon; the channel's `thumbnail_style.avoid` is included).
- Code adds two checks: file size and dimensions, and how busy the area behind the word is.
- The review is advice, not a block. "Review again" re-runs it after a redraw.

**Choosing.** One chosen thumbnail per aspect. Download names follow the export: `{Channel}_{Topic}_{Subject}_thumbnail_16x9.jpg`.

**Settings** (`config/thumbnails.yaml`, plus the Advanced settings page).
- The YAML lists the models that edit from a source image, each with its endpoint path, its image field, default params and the allowed options. As of 2026-11-15: Grok Image 2.0, Qwen Image 3 Edit, Ideogram 4.0, Marketing Studio Image.
- It also holds the prompt template and its text and framing lines.
- The page saves overrides in the `app_setting` table: model, per-model options (checked against the YAML's `options`), text mode, review on or off, corner, font, default aspects, and a custom prompt template. Delete resets to the YAML.
- A custom prompt can also be given for one run.
- Template variables: `{topic} {subject} {word} {text_style} {text_corner} {aspect} {avoid}`. Unknown braces are left as typed.
- In 9:16 the word is drawn centred across a band, so `{text_corner}` reads "top 40% of the picture" or "bottom 40% of the picture", and the framing line asks for a wider shot with only open background in that band. It asks for more room than the word needs because models leave less than they are asked for: asked for a third, Grok Image 2.0 left 17%; asked for 40%, it left 30% (tested live on 2026-11-16).
- 9:16 placement is measured, not assumed. After the image is painted, code measures how far the open background runs from the safe line, in the columns the word will cover (a row is busy when detail fills more than a third of them). The word keeps its full size when it fits, shrinks to fit when the subject is close (never below 65% of full size) and sits slightly lower when there is room to spare. This costs nothing and also applies to a free redraw. Limit: a dark character on dark ground reads as open space, so the bottom band is less reliable than the top.
- Known gap: a small blue lock-on marker in the Gate Keeper frame survived all four Grok attempts, even with markers named in the prompt. Claude's review flags it each time. Other models were not tried on it.

**Cost.** Each image is a paid Higgsfield call. The page shows the estimate before Generate, and each thumbnail stores the quoted price. Calls are logged in `llm_call` with `provider = higgsfield`. Claude's frame ranking and each review are small vision calls.

#### 7.13.1 Frame finder (`thumbnail_frames` job)

1. **Candidate moments** (up to 24, at least 1 s apart), each with its reason. In order:
   - the writer's `thumbnail.frame_ts`
   - peak segments
   - high-intensity events
   - the busiest intensity samples
   - evenly spaced fill
2. **Code scores** three frames around each candidate (−0.4, 0, +0.4 s; 480 px, from the proxy). Each metric is compared against the video's own 90th percentile:
   - sharpness (Laplacian variance) 45%
   - contrast 25%
   - colourfulness 15%
   - drama (intensity nearby) 15%
   - Very dark or blown-out frames lose half.
   - Only the best of the three frames around each moment is kept.
   - Near-duplicates keep only the best: frames under 3 s apart that look alike (dHash within 6 bits), or frames anywhere that look the same (within 2 bits). A fixed-camera arena looks alike all fight long, so time apart keeps those.
3. **Claude ranks** the top 8 as stills (640 px). For each frame it gives:
   - a 0–10 score
   - whether the subject is visible
   - HUD level
   - the calmest corner
   - a short reason

   Final score = 60% Claude + 40% code. Without a Claude key the code ranking stands. Claude reads stills only; Gemini still does all video watching (D24).
4. The result is saved as `thumbs/frames.json` in the video's media folder.

---

## 8. API

Served at the root of `http://localhost:8000`. JSON unless noted. All list endpoints are small; no pagination needed in v1. The payload of each endpoint built so far is fixed in `api/API_SHAPES.md`; extend that file when an endpoint is added.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| GET | `/config/channel` · PUT | Read / update channel profile |
| GET | `/config/status` | Config validation errors, active models, which API keys are set |
| GET | `/presets` · POST | List / create presets |
| GET | `/presets/{id}` · PUT · DELETE | Read / update / delete (cannot delete `general`) |
| GET | `/imports` | Files available in the import sources, with an already-imported flag |
| POST | `/videos` | `{source, ref, title, subject, topic, topic_terms, kind, preset_id}` → video + import job |
| GET | `/videos` | Video list with derived status |
| GET | `/videos/{id}` | Video + latest analysis summary + job states |
| PATCH | `/videos/{id}` | Edit title, subject, topic, topic_terms, preset |
| DELETE | `/videos/{id}` | Remove rows and media folder. Never touches the import folder |
| POST | `/videos/{id}/publish` · DELETE | `{url, published_at?}` → mark as published and create the past-upload entry; DELETE undoes it |
| GET | `/videos/{id}/media` | Video bytes with HTTP Range support. `?quality=proxy` (default) or `source` |
| GET | `/videos/{id}/frames` | Filmstrip frame URLs + timestamps |
| GET | `/videos/{id}/frame` | `?t=&w=` → one JPEG cut from the source on demand, cached. For clip thumbnails and the frame picker |
| GET | `/videos/{id}/timeline` | Events, segments, intensity samples, dead time |
| POST | `/videos/{id}/analyze` | (Re)run analysis job. Body: `{discard_user_work: false}` |
| POST | `/videos/{id}/events` · PATCH/DELETE `/events/{id}` | User adds, moves, retypes, verifies, hides or deletes an event |
| POST | `/events/{id}/refine` | Refine one event's time with a narrow high-rate pass |
| GET | `/videos/{id}/facts` | Facts with proposals |
| PUT | `/facts/{id}` | Set value and confirm / unconfirm |
| POST | `/videos/{id}/clips/find` | `{prompt, platform, target_len_s}` → candidates |
| GET | `/videos/{id}/clips` | All clips |
| PATCH | `/clips/{id}` | Nudge edges, rename, select |
| POST | `/clips/{id}/refine` | Refine edges with a narrow high-rate pass |
| POST | `/clips/{id}/export` | `{crop: none\|9x16, mode: accurate\|lossless}` → job |
| GET | `/exports/{id}/download` | Exported file |
| POST | `/videos/{id}/research` | Run subject research (`{}` searches; `{pasted_text, source_url?}` sorts the user's notes). Competitor research joins in Phase 3 |
| GET | `/videos/{id}/research` | Latest results with sources and effective values |
| PATCH | `/videos/{id}/research` | `{key, value}` sets a field override; `{key, restore: true}` clears it |
| POST | `/videos/{id}/research/revert-spelling` | Undo the subject spelling correction |
| POST | `/videos/{id}/packages` | `{platforms: [...], clip_id?}` → generate (Phase 1: `youtube` only) |
| GET | `/videos/{id}/packages` | Latest package per platform (and per clip), with stale state, plus whether generation is possible and which required facts are missing |
| PATCH | `/packages/{id}` | Manual field edit → re-run rules; or dismiss / undismiss a warning |
| POST | `/packages/{id}/regenerate` | `{field}` or `{all: true, replace_edits: false}` |
| GET | `/videos/{id}/export.md` | Markdown export of all packages |
| GET | `/library` · POST · PATCH · DELETE | Past uploads |
| GET | `/videos/{id}/thumbnails` | Thumbnails (newest first), word choices, found frames, uploads, settings, whether generation is possible |
| POST | `/videos/{id}/thumbnails/frames` | Run the frame finder (7.13.1) → job |
| POST | `/videos/{id}/thumbnails/uploads` | Raw image body (`Content-Type` image/jpeg, png or webp) → `{id, url}`; GET `/videos/{id}/thumbnails/uploads/{name}` serves it |
| POST | `/videos/{id}/thumbnails` | `{source: {kind: frame, t} \| {kind: upload, upload_id}, models?, aspects?, word?, text_style?, text_corner?, text_mode?, prompt?}` → batch + job |
| PATCH | `/thumbnails/{id}` | `{chosen?, word?, text_style?, text_corner?, font?}`; changing the text redraws for free |
| POST | `/thumbnails/{id}/review` | Review again → job |
| GET | `/thumbnails/{id}/image` | `?v=final\|raw\|source&download=` |
| DELETE | `/thumbnails/{id}` | Remove one |
| GET | `/settings/thumbnails` · PUT · DELETE | Advanced settings for thumbnails; DELETE resets to `config/thumbnails.yaml` |
| POST | `/settings/thumbnails/estimate` | `{models?, aspects?}` → Higgsfield's price quote per image (no charge) |
| GET | `/jobs/{id}` · POST `/jobs/{id}/retry` | Job status / retry |
| GET | `/videos/{id}/updates` | SSE: job progress and incremental results |

SSE event types: `job.progress`, `job.done`, `job.error`, `analysis.event` (one per timeline event, sent in time order after the analysis call returns), `clip.candidate`, `package.field`, `thumbnail.updated` (one thumbnail row), `thumbnail.frames` (the frame finder's result). On page load the client fetches current state first and then subscribes; the stream carries no history.

Markdown export filename: `{Channel}_{Topic}_{Subject}_YouTube_SEO.md`, with spaces and the characters `< > : " / \ | ? *` removed so the name is valid on Windows.

---

## 9. Frontend

### 9.1 Stack

- Next.js App Router, TypeScript, React Server Components only where trivial; the workspace is a client component.
- Tailwind CSS with the tokens below as CSS variables. No component library that fights the look; small headless primitives (Radix) are fine for switch, collapsible, dialog, tooltip, popover.
- Motion (the `motion` package, formerly Framer Motion) for animation and layout transitions.
- TanStack Query for server state; a small Zustand store for workspace UI state (playhead, selected clip, panel open states).
- `lucide-react` for icons. Stroke icons only, 1.75–2 px stroke. No emoji as icons.
- Native `<video>` element for playback, fed by the proxy.

### 9.2 Routes

| Route | Screen |
| --- | --- |
| `/` | Library: video cards by topic, status, search |
| `/new` | Import: file list from the import folder (name, size, date, already-imported mark), then title, subject, topic, extra terms, kind, preset |
| `/v/[id]` | Workspace (main screen, below) |
| `/v/[id]/research` | Subject facts with sources and edit controls; competitor grid; gap analysis |
| `/v/[id]/thumbnail` | Frame picker, result-word options, prompt to copy |
| `/past-uploads` | Past uploads: a table with add, edit and delete |
| `/settings/channel` | Channel profile form |
| `/settings/presets` | Preset list, viewer, YAML editor |

Build `/new` and `/v/[id]` first. The other routes can ship as simple functional pages in the same style.

### 9.3 Design language: "Ink"

A dark, quiet, editor-like workspace. Near-black surfaces, paper-white text, one vermilion accent, gold reserved for peak moments and top results. Serif headings over a sans body. Motion shows what the app is doing; it is never decoration.

Hard constraints:

- No Japanese characters, kanji or cultural glyphs anywhere (D12).
- Small text: 12 px body, 11 px labels, 10 px ruler; headings 16 px, section titles 13–14 px.
- Icons on every action and section header.
- No gradients as decoration, no drop-shadow cards, no left-border accent cards.

**Colour tokens (`styles/tokens.css`)**

| Token | Hex | Use |
| --- | --- | --- |
| `--bg` | `#0C0C0B` | App background |
| `--bg-raised` | `#111110` | Rail, header, right panel |
| `--surface` | `#181715` | Cards, inputs, track backgrounds |
| `--surface-2` | `#211F1C` | Hover, selected rows |
| `--stage` | `#070707` | Video area |
| `--line` | `#23211E` | Panel dividers |
| `--line-2` | `#2B2925` | Card borders |
| `--line-3` | `#3A3731` | Control borders, switch off |
| `--line-strong` | `#5A554B` | Input borders, emphasised controls |
| `--text` | `#F2EEE6` | Primary text ("paper") |
| `--text-2` | `#D9D3C6` | Secondary text |
| `--text-3` | `#B5AEA0` | Muted text (min for 11 px on dark) |
| `--text-4` | `#8F897C` | Ruler labels |
| `--accent` | `#E2452D` | Vermilion: selection, playhead range, counters |
| `--accent-fill` | `#C8381F` | Filled buttons, switch on |
| `--accent-soft` | `#F06A50` | Accent used as small icon/text on dark |
| `--accent-deep` | `#A82C17` | Accent on the light note card |
| `--chip` | `#2A1A16` / on `#4A2219` | Event chip background / active |
| `--chip-line` | `#5A2A20` | Event chip border |
| `--gold` | `#D9A93F` | Peak, finisher, top result |
| `--gold-text` | `#E9C56A` | Gold as text |
| `--ok` | `#8FD19E` / text `#A9DDB5` / line `#3F6B49` / bg `#17231A` | Pass, success |
| `--warn` | `#F7C97A` / line `#8A6A2A` | Warning |
| `--note-bg` | `#F2EEE6` with text `#1A1917` / `#3A3731` | Inverted "Analysis note" card |

Status must never rely on colour alone: pass has a check icon, warn a triangle, block a strike-through plus slash icon.

**Typography**

- Headings: a serif with character. The mockup uses "Shippori Mincho" 700 for Latin headings; an equivalent Latin serif (for example "Cormorant Garamond" 700 or "Fraunces") is acceptable. Make it one token, `--font-head`.
- Body: Inter 400/500/600. Tabular numerals for all timestamps and durations.

**Shape and space**

- Radius: panels and cards 12 px; inputs, tracks and buttons 10 px; pills 22 px; chips 8 px; thumbnails 10 px.
- 4 px base grid. Panel padding 16 px; card padding 12–14 px; gaps 8–12 px.
- Standalone controls have a target of at least 44×44 px even when the visible glyph is smaller. Timeline chips are the exception: they are 30 px tall to fit the track, and every chip action is also reachable by keyboard.

### 9.4 Workspace layout (`/v/[id]`)

```
┌────┬──────────────────────────────────────────────────────────────┬───────────────┐
│    │ Library / {subject · topic}            [Preset: General|…] ✓ ⋮│               │
│ R  ├──────────────┬───────────────────────────────────────────────┤  PACKAGE      │
│ A  │ CLIPS    🔍  │ {subject · clip name} ⌄            9:16 crop ◯ │               │
│ I  │ [prompt…   ] │ ┌───────────────────────────────────────────┐ │ ▸ Facts       │
│ L  │ ┌────┬────┐  │ │                                           │ │   switches    │
│    │ │clip│clip│  │ │               VIDEO                       │ │ ▸ Platforms   │
│ 60 │ ├────┼────┤  │ │        (crop guide, event label)          │ │   switches    │
│ px │ │clip│clip│  │ └───────────────────────────────────────────┘ │ ▸ Title deck  │
│    │ └────┴────┘  │ 0:13.5        ⏮  ▶  ⏭                 0:32.0 │   next / copy │
│    │              │ ━━━━━━━━━━━●──────────────────────────────── │ rule badges   │
│    ├──────────────┴───────────────────────────────────────────────┤               │
│    │ TIMELINE                          [Review events]  zoom ─●──  │               │
│    │ ⌁  |0:00   |0:04   |0:08   |0:12  …            (ruler)        │ ┌───────────┐ │
│    │ ⌁  [chip][chip][chip]      [chip]   [chip][chip][◆][◆]        │ │ Analysis  │ │
│    │ ▦  ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮  filmstrip with ┌ selected range ┐        │ │ note      │ │
│    │ ⫴  ▂▅▇▃▆▂▁▁▅▇▆▃  intensity waveform                           │ │ [Apply]   │ │
│    │ ─  ▬        ▬▬      dead time                    ┊ playhead   │ └───────────┘ │
│    │ [↺ Reset]   [In earlier][In later][Out earlier][Out later]  [↑ Lift clip 28s] │
└────┴──────────────────────────────────────────────────────────────┴───────────────┘
```

Widths at 1440: rail 60, clips panel ~260, right panel ~300, centre flexible. Below 1100 px the right panel wraps under the main column; below 720 px the clips panel wraps above the preview. The timeline scrolls horizontally when zoomed.

**Regions and behaviour**

1. **Icon rail.** Logo mark (two diagonal brush slashes, white on a vermilion rounded square), then Library, Workspace (active: `--surface-2` fill, accent border), Research, Thumbnail, Past uploads; Settings at the bottom. Performance appears in Phase 4. Tooltips on hover.
2. **Header.** Breadcrumb (`Library / {subject · topic}`); preset control (a segmented control of pills for up to three presets, a dropdown beyond that; active filled accent) with a settings button that opens a popover listing what the preset defines (event types, facts, hooks, rules, title pattern) and links to the editor; status pill (Analyzing with animated bar → Analyzed with check); overflow menu (re-analyze, mark as published, export Markdown, delete).
3. **Clips panel.** Title + search toggle that reveals the prompt input (saved prompts as chips under it). Two-column grid of clip thumbnails: real frame at `payoff_t`, name, duration, and a thin accent bar along the bottom edge showing the clip's position and extent within the video. Selected clip has a 2 px accent outline with 2 px offset. Loading: skeleton cards that shimmer subtly. Empty: "Describe the clip you want" with the saved prompts.
4. **Preview.** Clip name with dropdown to switch clips; 9:16 crop switch that animates the stage narrowing to a 9:16 frame and dims what is cut; dashed centre guide; a label chip naming the event under the playhead (or "Clip start" / "Clip end"). Transport: previous event, play/pause (loops the selected clip), next event. Current time left, total right. Scrubber below with a draggable handle.
5. **Timeline.** Left gutter of track icons; ruler; four tracks sharing one time scale:
   - **Events:** clickable chips with glyph + label (per preset `glyph`/`color`). Active chip is highlighted. Unverified model events have a dashed border; verified and user events a solid one. Drag a chip sideways to move it (snap 0.1 s; hold Alt for one frame). Right-click or a small menu: retype, verify, refine, hide, delete; double-click empty space adds an event. The gutter icon opens a filter of event types; types marked `show: false` in the preset start hidden.
   - **Filmstrip:** frames; the selected clip is a 3 px accent bracket with draggable left and right edges (snap 0.5 s; hold Alt for 0.1 s).
   - **Intensity:** bars from `intensity_sample`; bars inside the clip brighter; dead time flat and dim.
   - **Dead time:** rounded grey blocks.
   - **Playhead:** dashed vertical line across all tracks. Click anywhere to seek; drag to scrub.
   - **Density:** the default zoom fits the whole video. A chip narrower than 44 px shows its glyph only. Overlapping chips of one type collapse into a count chip ("×4") that expands on zoom or click. A 10-minute video with 150 events must stay readable.
   - **Review events (the eye test, D19).** A button in the timeline header starts review mode. It steps through unverified events in time order. For each one the preview loops from 1 s before to 1 s after, with a half-speed toggle. The user steps by frame, sets the event to the playhead, retypes, hides, or verifies and moves on. A counter shows progress ("7 of 23 verified"). Verification is optional; facts can be confirmed without it, and a fact row shows how many of its events are verified.
6. **Action bar.** Reset; four nudge buttons; primary "Lift clip · {duration}" (creates/exports the clip and generates short packages; turns green "Clip lifted" on success).
7. **Package panel.** Collapsible sections with chevrons:
   - **Facts to confirm** (General: "Detected"): one row per fact with its value, state text and a switch. Clicking the value opens a small editor (stepper, text or select). Confirming plays the stamp animation on the row's check seal.
   - **Platforms:** switches for YouTube long-form, Shorts, Instagram Reels, TikTok.
   - **Title:** recommended title, its one-line reason, deck position ("1 of 3"), Next and Copy. Any claim phrase in the title shows a small round check seal linking to the supporting fact.
   - **Rule badges:** pills with icons; clicking one opens its message and evidence.
   - **Analysis note:** inverted light card pinned to the bottom with one suggestion and "Apply recommendation".
   - A "Open full package" button opens a wide drawer with every field for the selected platform as copyable blocks with character counts and rule badges, and a platform preview (YouTube search-result row, or a phone frame for vertical with the safe-margin guides drawn on it). The drawer has no mockup; build it from this spec in the same visual language.

**Phase 1 workspace.** There are no clips yet. The clips panel is collapsed to a narrow strip, the action bar is hidden and the filmstrip has no range bracket. The package panel and the full-package drawer carry the long-form flow.

### 9.5 Motion spec

Use these as shared presets in `lib/motion.ts`.

| Name | Where | Spec |
| --- | --- | --- |
| `ease-out-ink` | Default | `cubic-bezier(.2,.8,.2,1)` |
| Mark-in | Event chips as analysis results arrive | scale 0.9→1 + fade, 260 ms, 60 ms stagger in time order |
| Range move | Clip bracket, scrubber, thumbnail bar | left/width, 320 ms, `ease-out-ink` |
| Playhead seek | Click or event jump | left, 240 ms, `ease-out-ink` |
| Playhead loop | While playing | linear, driven by `video.currentTime` (requestAnimationFrame) |
| Panel rise | Section open, drawers, popovers | translateY 8→0 + fade, 200–260 ms |
| Stamp | Fact confirmed, event verified | scale 2.2→0.92→1, rotate −18°→−6°, 420 ms, slight overshoot |
| Slash | Claim blocked | strike-through draws left→right 220 ms + 4 px shake once |
| Switch | All toggles | knob left 3→17 px, 200 ms; track colour cross-fade |
| Press | Buttons | scale 0.96 on active, 160 ms |
| Lift | Clip lifted | thumbnail rises 6 px and settles; button cross-fades to success |
| Crop | 9:16 switch | stage width animates 320 ms |
| Copy | Copy buttons | background sweeps to `--ok`, icon morphs to check, reverts after 1.6 s |
| Busy | Running job pill | thin bar oscillating 8%↔78% width, 2.2 s loop |

Rules: interaction feedback 150–320 ms; nothing blocks input; honour `prefers-reduced-motion` by replacing movement with fades.

### 9.6 Keyboard

`Space` play/pause · `J` / `L` step back/forward 0.5 s · `K` pause · `,` / `.` step one frame · `←` / `→` previous/next event · `E` move the selected event to the playhead · `Enter` verify the selected event (and go to the next in review mode) · `Backspace` hide the selected event · `I` / `O` set clip in/out at playhead · `[` / `]` nudge the clip edge nearest the playhead · `1–9` select clip · `C` copy focused field · `Cmd/Ctrl+K` command palette (jump to video, switch preset, run actions).

Shortcuts are inactive while focus is in a text input, a slider, a menu or a dialog.

### 9.7 States

Every panel needs loading, empty, error and partial states in the same visual language:

- **Importing:** the header pill shows copy and proxy progress; the timeline appears as soon as the proxy and intensity are ready.
- **Analyzing:** timeline tracks render as soon as intensity is ready; chips animate in when the analysis result arrives; header pill shows the busy bar and a message ("Watching video", "Waiting for rate limit").
- **No API key:** a setup card with the exact env var to set; the rest of the UI works on intensity and manual events.
- **Config error:** a card naming the YAML file and the problem; the app runs on the built-in General preset until it is fixed.
- **Error:** inline card with the message, a Retry button and "Copy error". An interrupted job reads "Interrupted by a restart".
- **Stale:** when facts, events or research change after generation, the package shows "Out of date · Regenerate".
- **Re-analysis warning:** the dialog from 7.12, shown before every re-analysis.

### 9.8 Accessibility

Real `button`, `a`, `input` + `label` elements; `role="switch"` with `aria-checked`; `aria-pressed` on toggle buttons; `aria-expanded` on collapsibles; visible focus ring (2 px `--text` outline, 2 px offset). Text contrast at least 4.5:1, including 11 px labels. The timeline is keyboard-operable through the shortcuts above and each chip is focusable with an accessible name ("Highlight 5 at 0:20.5, unverified").

---

## 10. Build order

Ship each phase working end to end before starting the next.

**Phase 0 — Analysis accuracy spike (do first, a day or two)**

Status: closed by the owner on 2026-11-15. The accuracy is accepted as good enough to build on, and further gains go through the event engine (7.3.1, D25).

What was measured, on two boss fights of about 3.5 minutes each, at 1 fps and default resolution, one run per configuration, against labels the owner confirmed on the review sheet:

| | Gate Keeper | Sword Fanatic |
| --- | --- | --- |
| Counters found within 1 s, no playbook | 8 of 11 (9 reported) | 2 of 6 (7 reported) |
| Counters found within 1 s, playbook written from the footage | 10 of 11 (10 reported) | 3 of 6 (5 reported) |
| Hits found by Gemini within 3 s, best run | 3 of 11 | 3 of 13 |
| Hits found by the health-bar reader | 9 of 11 | 9 of 13 |

- The labels came from moments that Gemini, the health bar or a red flash proposed; the owner added none, so recall is an upper bound.
- Gemini limits are in section 12. The SQLite volume and the read-only import mount are confirmed on the owner's machine.
- Not measured: 2 and 5 fps, `high` resolution, agentic processing, a General video, a 10-minute video. The visual snap was not scored against the reviewed labels and stays off.

The original plan for this phase, kept for reference:

- Compose stack with the `api` service only, settings, the import folder mount, proxy transcode.
- `scripts/eval_analysis.py`: run the analysis prompt through the API on two or three real fights and one General video, across a small grid of sampling rates and media resolutions. Save each result to `eval/`.
- The owner supplies ground truth for each video in `eval/<name>.truth.yaml`: event type and time for every counter, hit and phase change (a hand count is enough to start).
- Report per run: events found versus true events (within ±0.5 s), mean timing error, fact proposals versus truth, token counts, and any rate-limit or size errors. Also try the visual snap and report whether it reduces timing error.
- Check that SQLite in the named volume and the read-only import mount work on the owner's machine.
- *Done when:* `ANALYSIS_FPS` and `ANALYSIS_MEDIA_RESOLUTION` have measured defaults, the free-tier limits for a 10-minute video are known, and the owner has seen the accuracy numbers.

**Phase 1 — Understand and package**

Status on 2026-11-15: steps 1 to 7 are built (step 7: past uploads typed in by hand, "Mark as published" and "Unpublish"; step 4: event editing with undo, review mode, facts confirmation; schema version 3 adds `event.edited`. Step 5: subject research with sources, overrides, spelling correction and the paste fallback. Step 6: the YouTube long-form package, template variables, the rules engine, the package panel and drawer, Markdown export). Not yet built from those steps: `PUT /config/channel` and the preset write endpoints (the preset editor is Phase 3). Since then: search demand (7.7.1) picks titles and tags from measured YouTube search suggestions, with the owner's SEO playbook in the boss-fight preset. Also built: the thumbnail creator (7.13, from Phase 3). The API payloads are in `api/API_SHAPES.md`.

Build in this order; each step is usable on its own.

1. Compose stack, health check, settings, DB, config loading with validation; General and Boss fight presets; channel profile.
2. Import from the local folder, ffprobe, proxy, filmstrip, intensity, media endpoint with Range.
3. Analysis job with SSE, built on the event engine (7.3.1) with the `gemini` detector and the merge step in place from the start; timeline API; workspace UI with header, preview and timeline.
4. Event editing and review mode; facts confirm flow; re-analysis with its warning dialog.
5. Subject research with overrides (with graceful no-search fallback: user pastes facts).
6. YouTube long-form package, template variables, rules engine, package panel, package drawer, Markdown export.
7. Past uploads page (typed in by hand) and "Mark as published".

- *Done when:* one boss fight and one General video each go from import to a copied, rule-checked long-form package with real chapter timestamps, without leaving the app.

**Phase 2 — Clips**
- Clip finder, candidates grid, selection, nudge, draggable edges, analysis note, refine pass.
- ffmpeg export (accurate and lossless, 9:16 at 1080×1920, source frame rate).
- Shorts, Reels and TikTok packages; platform previews.
- *Done when:* a Reel is chosen, trimmed, exported and captioned from a full video in one sitting.

**Phase 3 — Research, thumbnails and imports**
- Competitor research with YouTube Data API and caching; gap analysis; cannibalization.
- Past uploads imported from the YouTube channel.
- Google Drive import source.
- Thumbnail page: frame picker, result words, prompt builder. **Built early (2026-11-15) as the thumbnail creator (7.13, D26)**, with Higgsfield generation, the frame finder, uploads, the word overlay, Claude review and an Advanced settings page.
- Preset form editor.

**Phase 4 — Loop and plan (later)**
- Performance logging against baselines; profile suggestions; next-video planner; posting plan.

---

## 11. Testing and quality

- **Rules engine:** unit tests for every rule, including: "No Hit" title with `hits_taken=1` blocks; with `hits_taken=0` unconfirmed blocks; confirmed passes; "Untouched" is caught by the phrase list; "Final Boss" with no credible source blocks and suggests "Final Fight"; the same with a user override passes; a number in a title that matches no confirmed fact warns; chapters closer than 10 s block; a video with no chapters passes; Shorts without `#Shorts` auto-fixes; a banned tag is removed.
- **Templates:** unit tests for variable resolution, dropped empty lines, hook eligibility, and preset validation failing on an unknown variable.
- **Clip post-processing:** unit tests for snapping, clamping, dead-time and crop-warning computation.
- **Media:** tests against a short generated sample (ffmpeg `testsrc`) for probe, proxy timeline match, frames, trim accuracy (±1 frame in accurate mode), crop and scale dimensions (1080×1920), and kept frame rate.
- **Import:** a ref that escapes the import folder is rejected; the import folder is never written to.
- **Re-analysis:** user events, verified events and confirmed facts survive by default and are removed only with `discard_user_work`.
- **LLM calls:** mocked in tests via the provider interface with recorded JSON fixtures. Add one opt-in live smoke test.
- **Analysis quality:** keep the Phase 0 ground-truth set and re-run `eval_analysis.py` whenever the prompt, model, sampling rate, a detector, the merge rules or a playbook changes. Add a video to the set with `scripts/review_sheet.py` (confirm proposed moments on a page) instead of hand-labelling.
- **Event engine:** unit tests for the merge step (grouping, time priority, `detected_by`), and one test per detector against a recorded or generated input. A fake detector proves that adding one needs no change elsewhere.
- **Frontend:** component tests for timeline maths (time↔pixel, snap), and a Playwright smoke test: import fixture → mocked analysis → verify an event → confirm fact → copy title.
- Lint and type-check in both services (`ruff`, `mypy` or pyright; `eslint`, `tsc --noEmit`).

---

## 12. Cost and limits

- Claude (Anthropic API) is paid per token. Check current prices and the web search tool's cost before Phase 1, and show the spend per video from the `llm_call` table.
- Gemini free tier: lower rate limits, and free-tier content may be used to improve Google's products. Show this once in settings. Read actual limits from AI Studio; do not hard-code them.
- Measured in Phase 0 (2026-11-14, `gemini-3.8-flash`): the free tier allowed 20 requests per day per model, and every retry counts as a request. A call that is out of quota can hang on an open connection; started in the background and polled, it reports the quota error within seconds. So: retry at most once, never retry a daily-quota error, and prefer background-and-poll for video calls. The owner enabled billing on 2026-11-15; paid calls for a 3.5-minute video at 1 fps answered in 44 to 65 s.
- Budget calls: one full analysis per video; refine passes only on demand; clip finding and packaging are text-only and cheap. A higher sampling rate costs more tokens per analysis; Phase 0 confirms what the free tier allows.
- YouTube Data API: free daily quota; `search.list` is the expensive call. Cache per subject for 24 h and show remaining-quota errors clearly.
- Everything else (ffmpeg, SQLite, local disk) is free.

---

## 13. Assumptions to confirm with the owner

1. Artboard 5 of the design canvas ("Ink style, editor-like workspace") is the approved direction. The companion mockup file is that artboard.
2. Heading font: keep the mockup's serif or swap for a Latin-only serif.
3. TikTok conventions are undefined; v1 mirrors the Reel package.
4. ~~Thumbnail generation stays outside the app in v1.~~ Replaced by D26 on 2026-11-15: thumbnails are generated through Higgsfield's API. Higgsfield's API balance is pay-as-you-go and may be separate from the web plan. Models that are on the web app but not on the API are not available, including Nano Banana and GPT Image (as of 2026-11-15).
5. Research uses Claude's web search tool (D24). Measured on 2026-11-15 (Gate Keeper, `claude-opus-5-5`): the search call read 57k tokens in and wrote 2.9k out in 41 s, the structuring call 4.3k in and 1.1k out in 9 s; about $0.35–0.40 per run including searches ($10 per 1,000, at most 6 per run). Research runs once per subject and is reused.
6. The Onimusha playlist id in `channel.yaml` is flagged by the owner as possibly clipped; verify before relying on it.
7. Hook wording in the boss-fight preset is "No Hit" (the owner's current usage), with "NO HIT" as the thumbnail word. Earlier drafts used "No Damage". The owner can change it in the YAML.
8. `credible_domains` holds the owner's starter list, `fextralife.com` and `wikipedia.org` (2026-11-15; subdomains count). Fields that need a credible source stay locked until one of those sites backs them or the owner sets the field by hand.
9. A video imported as `kind = clip` is treated as one ready-made clip with short-form packages only.
10. The SQLite file lives in a Docker named volume rather than `./data`.
11. "Mark as published" adds the video to past uploads automatically.
12. Vertical exports default to 1080×1920.
13. The app copies an imported file rather than moving it; the original stays in the import folder.
14. A hit means the player's health dropped, as the boss-fight preset says. On the Phase 0 review the owner also confirmed six hits where the health bar did not move and rejected one measured drop. Until the owner says otherwise, the `hits_taken` fact counts health drops only.
15. The 1 fps default is what was measured, not what was found best. Higher sampling rates and `high` resolution are untested.
16. Search demand comes from YouTube's unofficial suggestion endpoint (7.7.1). It can change or stop without notice; the app then falls back to the writer's choices. A suggestion's rank is a popularity signal, not search volume.
17. On a search-first channel, code overrides the writer's title pick with the best search score. The owner can always pick another title; the `search_demand` rule warns when an edit drops every top phrase.
18. The default thumbnail model is Grok Image 2.0, picked from one comparison on 2026-11-16: the same Gate Keeper frame (0:10), the same preset prompt, 16:9, all four models. Grok ($0.09) kept the boss and player most faithful and removed all HUD. Qwen Image 3 Edit ($0.075) also passed and added moodier light; it is the cheaper alternative. Marketing Studio ($0.265) gave the most cinematic golden-hour look at three times the price. Ideogram 4.0 ($0.10) failed: it repainted the HUD and boss name and recoloured the bronze mask gold. One frame is a small sample, so recompare on a different game. Prices come from Higgsfield's estimate endpoint, and no per-image price is published.

---

## Appendix A — Lessons from the manual workflow (design inputs)

- Model timestamps are approximate; every trim point needs a preview and a nudge, and every event needs a way to be corrected by eye.
- The model has miscounted mechanics and once could not hear audio. Counts and hits come from the creator.
- Plain words on screen, niche terms in the caption and hashtags.
- Each clip in a set needs its own angle; similar clips posted together read as repeats.
- If the payoff lands after about second 7 of a short, the on-screen text must promise it from the first frame.
- Starting a beat before the first clash and ending on the result flash (before any dissolve) makes a clip loop cleanly.
- A true small hit count ("Only 2 Hits Taken") is a hook, not a weakness.
- Recurring subjects need a distinct angle or a compilation, or they compete with each other in search.

## Appendix B — Reference

- Product spec (background and rationale): `LazyCut — Product Spec.md` in this repo; original at https://claude.ai/artifact/AFi2nGLsQ2ijC8kkLGHfpv
- Design canvas (all five artboards): https://claude.ai/artifact/9zapDnqw5rFkJAaDFUBZPD
- Gemini video understanding docs: https://ai.google.dev/gemini-api/docs/video-understanding
- Gemini pricing and free tier: https://ai.google.dev/pricing
