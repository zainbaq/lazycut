# API shapes (Phases 1 and 2)

The JSON the web app relies on. `BUILD_SPEC.md` section 8 lists the endpoints; this file fixes
their payloads. All times are float seconds. Errors are `{"detail": "message"}` with a 4xx/5xx code.
Media URLs in payloads are paths relative to the API origin (`NEXT_PUBLIC_API_URL`).

## Config

- `GET /health` → `{"status": "ok"}`
- `GET /config/status` → `{errors: [{file, problem}], channel: str|null, presets: [id], models: {video, text}, keys: {gemini, anthropic, youtube}: bool, event_detectors: [id], storage: {...}, tools: {...}}`
- `GET /config/channel` → the channel profile as in `config/channel.yaml`, or 404
- `GET /presets` → `[Preset]`; `GET /presets/{id}` → `Preset`
  - `Preset = {id, name, description, event_types: [EventType], facts: [FactDef], ...rest of the YAML}`
  - `EventType = {id, label, glyph: "slash"|"dot"|"ring"|"diamond", color: "accent"|"paper"|"warn"|"gold", definition, show: bool}`
  - `FactDef = {key, label, type: "int"|"text"|"bool"|"enum", options: [str], derive_from: str|null, required: bool, instructions: str|null}`

## Imports and videos

- `GET /imports` → `{folder: str, items: [{source: "local", ref, name, size_bytes, modified_at, imported_video_id: str|null}]}` (newest first; `modified_at` is epoch seconds)
- `POST /videos` body `{source: "local", ref, title, subject?, topic?, topic_terms?, kind: "long"|"clip", preset_id}` → 201 `Video` (the import job starts at once)
- `GET /videos` → `[Video]`, newest first
- `GET /videos/{id}` → `Video`
- `PATCH /videos/{id}` body any of `{title, subject, topic, topic_terms, preset_id}` → `Video`
- `DELETE /videos/{id}` → 204 (stops its jobs, removes rows and `data/media/<id>/`; never touches the import folder)

```
Video = {
  id, title, subject, topic, topic_terms, kind: "long"|"clip", preset_id,
  status: "importing"|"ready"|"error",                       // stored import status
  display_status: "importing"|"analyzing"|"needs_confirmation"|"ready"|"packaged"|"published"|"error",
  duration_s: float|null, width: int|null, height: int|null, fps: float|null, size_bytes: int|null,
  is_hdr: bool, import_source, import_ref, published_url: str|null, published_at: str|null, created_at,
  analysis: null | {id, model, fps: float|null, created_at, event_count: int},
  jobs: [Job],                                               // latest job of each kind
  media_url: "/videos/{id}/media"
}
Job = {id, video_id, kind: "import"|"analysis"|"research"|"package"|"clip_find"|"clip_export"|"clip_package"|"clip_refine"|"thumbnail"|"thumbnail_frames", status: "queued"|"running"|"done"|"error",
       progress: 0..1, message: str|null, error: str|null, created_at, updated_at}
```

Timestamps such as `created_at` are UTC ISO 8601 strings.

## Media

- `GET /videos/{id}/media?quality=proxy|source` → the video, with HTTP Range support (proxy by default)
- `GET /videos/{id}/frames` → `{interval_s: float, width: 320, frames: [{t, url}]}`; `url` is `/videos/{id}/frames/<n>.jpg`
- `GET /videos/{id}/frame?t=&w=` → one JPEG cut from the source at `t`, `w` px wide (default 640), cached

## Timeline

`GET /videos/{id}/timeline` →

```
{
  duration_s, fps, preset_id,
  event_types: [EventType],          // from the video's preset, in preset order
  events: [Event],                   // time order, hidden ones included (hidden: true)
  segments: [{id, kind: "peak"|"section", t_start, t_end, label}],
  intensity: {bucket_s: 0.5, scores: [float 0..1]},   // sample i covers t = i * bucket_s
  dead_time: [{t_start, t_end}]
}
Event = {
  id, video_id, t_start, t_end, t_model_start: float|null, t_model_end: float|null,
  type, label, intensity: "low"|"medium"|"high", crop_safe_9x16: bool,
  confidence: "certain"|"uncertain", source: "model"|"user",
  detected_by: [{detector, t_start, label, evidence: {}}],
  verified: bool, hidden: bool,
  edited: bool                       // the user moved, retyped or relabelled it (model events only)
}
```

## Editing events (Phase 1 step 4)

- `POST /videos/{id}/events` body `{t_start, type, t_end?, label?}` → 201 `Event` with `source: "user"`.
  `t_end` defaults to `t_start + 0.5` (clamped to the duration). `type` must be one of the preset's
  event types; times must lie in `[0, duration_s]`, else 422.
  For undo of a delete, the body may also carry the deleted event's full fields including `id`;
  the event is then restored exactly (409 if that id exists).
- `PATCH /events/{id}` body any of `{t_start, t_end, type, label, verified, hidden}` → `Event`.
  Sending `t_start` without `t_end` moves the event and keeps its length. Changing `t_start`,
  `t_end`, `type` or `label` of a model event sets `edited: true`. Sending the model's own
  times back clears nothing: `edited` only resets on a re-analysis that discards user work.
- `DELETE /events/{id}` → 204.

Every edit recomputes the derived facts that are not confirmed (7.4). Undo is done by the web
app: it keeps the event as it was before each edit and sends it back (PATCH, or POST with `id`
after a delete).

## Facts

`GET /videos/{id}/facts` → `[Fact]`, one per fact of the video's preset, in preset order (rows are
created on first read when missing, e.g. before any analysis).

```
Fact = {
  id, video_id, key, label, type: "int"|"text"|"bool"|"enum", options: [str], required: bool,
  derive_from: str|null,
  proposed_value,                    // from the model, or the visible-event count for derived facts
  value,                             // the user's value: set by editing or confirming; null = use the proposal
  effective_value,                   // value ?? proposed_value: what the UI shows and packaging uses
  confirmed: bool, confirmed_at: str|null,
  evidence_ts: [float], evidence_event_ids: [str],
  event_count: int|null,             // derived facts: visible events of that type now
  verified_count: int|null,          // derived facts: how many of those are verified
  out_of_date: bool                  // confirmed derived fact whose value no longer equals event_count
}
```

- `PUT /facts/{id}` body `{value?, confirmed?}` → `Fact`.
  - `value` is checked against `type` (int: whole number ≥ 0; bool; enum: one of `options`; text:
    trimmed, empty = null), else 422. `"value": null` clears the user's value.
  - `confirmed: true` locks `effective_value` into `value` and sets `confirmed_at`; 422 if there is
    no value to confirm. `confirmed: false` unlocks it (`confirmed_at` null) and the fact follows
    the events again if derived.

## Subject research (Phase 1 step 5)

Research is shared by subject and topic: two videos with the same names see the same results.
It is accepted by default (D8); the user can override any field.

`GET /videos/{id}/research` → `Research` (an empty one, `method: "none"`, before any run)

```
Research = {
  id, video_id, subject_key, topic_key,
  method: "none"|"search"|"pasted",  updated_at: str|null,
  can_search: bool,                    // an Anthropic key is set
  running: bool,                       // a research job for this video is running
  canonical_name: str|null,            // the user's override if set, else the research value
  correction: null | {from: str, to: str},   // the subject's spelling was corrected; offer a revert
  fields: [ResearchField],             // preset order
  sources: [Source],                   // every page read (blocked domains removed)
  effective: {<key>: value}            // what titles and claims may use
}
ResearchField = {
  key, label, type: "text"|"bool", needs_credible_source: bool,
  value: str|bool|null,                // what research found (null = not found)
  sources: [Source],                   // pages backing this field
  credible: bool,                      // at least one source is on the channel's credible list
  override: str|bool|null, overridden: bool,      // the user's value ("Edited by you")
  no_credible_source: bool,            // found, but needs a credible source and has none: shown, not used
  effective_value: str|bool|null       // override if set; else value, or null when no_credible_source
}
Source = {url, title, domain, rating: "credible"|"unrated"}
```

- `POST /videos/{id}/research` body `{}` (search the web) or `{pasted_text, source_url?}` (sort the
  user's own notes, no search) → 202 `Job` (kind `research`). 409 with no Anthropic key or when one
  is running. Import queues it automatically when the key is set and the subject has no research yet.
  Each search run is one Claude call with web search plus one short structuring call, then a free
  harvest of YouTube search suggestions for the topic and subject names (stored with the research;
  a package run refreshes it when it is older than 7 days).
- `PATCH /videos/{id}/research` body `{key, value}` sets the user's value (`null` = "unknown"),
  `{key, restore: true}` goes back to the research value → `Research`. 422 for an unknown key or a
  wrong type (bool fields take true/false). Works without a key, so values can be typed in by hand.
- `POST /videos/{id}/research/revert-spelling` → `Research`: puts the user's spelling back and keeps
  it on later runs. 409 when there is no correction.

## Packages (Phase 1 step 6: YouTube long-form)

`GET /videos/{id}/packages` →
```
{
  can_write: bool,                 // an Anthropic key is set
  missing_facts: [label],          // required facts not confirmed yet; generation is blocked until empty
  can_generate: bool,
  running: bool,                   // a package job is queued or running
  packages: [Package]              // the long-form one (platform "youtube"), then each clip's short-form ones
}
Package = {
  id, video_id, clip_id: null, platform: "youtube", version: int, created_at,   // short-form: see "Short-form packages"
  fields: PackageFields, edited_fields: [field name], rule_results: [RuleResult],
  inputs_hash, stale: bool,        // facts, research, events, preset or channel changed since generation
  blocked_fields: [field path],    // fields with a block: disable Copy for them
  counts: {block: int, warn: int}  // open (not dismissed) checks
}
PackageFields = {
  title, title_why, title_goal: Goal, title_hook_id: str|null,
  title_alternates: [{text, why, goal: Goal, hook_id: str|null}],   // up to 4
  hook_line, description,          // description is the rendered template, ready to paste
  chapters: str,                   // "0:00 Label" lines, "" when the video has fewer than 3 valid sections
  chapter_list: [{t, label}],
  tags: [str], hashtags: [str],    // hashtags already trimmed to the channel's count, each "#Word"
  credit_block: str,
  opening_5s: str, pinned_comment: str, community_post: str,
  end_screen_target: {kind: "past_upload"|"playlist"|"none", title: str|null, url: str|null, label: str},
  thumbnail: {frame_ts: [float], word_options: [str], text_style: str|null, prompt: str},
  checklist: [{item, detail}],     // includes "Playlist" when the topic has no playlist yet
  slots: {name: text}, goals: {field: Goal},
  seo: Seo                         // search demand behind the title and tags (BUILD_SPEC 7.7.1)
}
Seo = {
  source: "youtube_suggest"|null,  // null: no search data; the writer's choices stand
  harvested_at: str|null,
  picked_by: "search_score"|"search_score_agrees"|"writer",   // who chose the title
  phrases: [{id, text, rank: int, seen: int, demand: float, about_subject: bool,
             fits: bool,             // the writer judged someone typing it would want this video
             in_title: bool, in_tags: bool}],                 // what the current title and tags carry
  excluded: [{text, demand, reason}],   // left out before judging (e.g. an unbacked claim like "no hit")
  title_scores: [{id, text, score, demand_score, covers: [{text, demand, match: "exact"|"words", front: bool}],
                  writer_pick: bool, issues: [str]}],         // every candidate; score includes rule penalties
  title_score: {score, covers, best_candidate},               // the current title (after edits) vs the best
  ambiguous_names: [str]           // bare names mostly searched for something else; never a tag or hashtag alone
}
Goal = "click_through"|"retention"|"session_watch_time"|"engagement"|"funnel"
RuleResult = {key, rule_id, severity: "pass"|"warn"|"block", field, message, evidence, fixed: bool, dismissed: bool}
```
Rule ids: `canonical_spelling`, `hashtag_count`, `banned_tags`, `tags_fit`, `ambiguous_names` (these auto-fix;
`fixed: true` says what changed; `tags_fit` and `ambiguous_names` only appear when they changed something),
`claim_needs_fact.<claim rule id>`, `number_needs_fact`, `search_first_title`, `chapters_valid`, `tags_count`,
`cannibalization`, `search_demand` (title and description: warn when they miss every top fitting search phrase),
`playlist` (warn on description: the topic has no playlist), `length_limits` (block on a field, warn on
`title_alternates[i]`). `field` is a path such as `title`, `title_alternates[1]`,
`thumbnail.word_options[0]`, `description`, `tags`.

- `POST /videos/{id}/packages` body `{platforms: ["youtube"]}` → 202 `Job` (kind `package`). 409 with no
  Anthropic key, with unconfirmed required facts (the message names them), or while one runs. Short-form
  platforms need a `clip_id` (see "Short-form packages"). One Claude call per run.
- `PATCH /packages/{id}` body `{field, value}` edits one of `title, description, hook_line, tags, hashtags,
  pinned_comment, community_post, opening_5s, chapters` (tags/hashtags take a list, or a comma/space-separated
  string; chapters take "m:ss Label" lines) → `Package`; the field joins `edited_fields` and the rules re-run.
  Body `{dismiss: key}` / `{undismiss: key}` dismisses a current warning (blocks cannot be dismissed).
  To use an alternate title, PATCH `title` with its text: the title takes that alternate's why, goal and
  hook. Sending a field's generated text back (kept in `fields.generated`) removes it from
  `edited_fields`, and for the title restores its why, goal and hook. Any other title gets the why "Your own title".
  A passing `claim_needs_fact` result carries `evidence: {phrase, requires}` (the phrase it backed).
- `POST /packages/{id}/regenerate` body `{field}` (that field only, its edit is replaced) or
  `{all: true, replace_edits: false}` (edited fields kept unless `replace_edits`) → 202 `Job`.
- `GET /videos/{id}/export.md` → the package as Markdown, as a download named
  `{Channel}_{Topic}_{Subject}_YouTube_SEO.md` (letters, digits, `_` and `-` only). It includes a
  "Search demand" section. 404 before generation.

## Clips (Phase 2; BUILD_SPEC 7.5, 7.6)

A clip is one continuous range of a video. `GET /videos/{id}/clips` →

```
{
  can_find: bool,                    // an Anthropic key is set; without one the finder reads the timeline alone
  can_refine: bool,                  // a Gemini key is set
  finding: bool,                     // a clip_find job is queued or running
  limits: {min_s: 3.0, max_s: {shorts: 180, reels: 180, tiktok: 600}},
  clips: [Clip]                      // in time order
}
Clip = {
  id, video_id, name, t_start, t_end, duration_s,
  status: "candidate"|"selected"|"exported",     // candidate = a finder proposal nobody touched
  source: "finder"|"user"|"import", platform: "shorts"|"reels"|"tiktok"|null,
  prompt: str|null, reason: str|null,              // what was asked, and the finder's one-line reason
  payoff_t: float|null,              // the finder's or the user's; else the default for the current range
  frame_t: float,                    // the frame for the card: the payoff, or the middle
  orig_start, orig_end,              // the range it was created with; `edited` says whether it differs
  edited: bool,
  event_counts: {type: int},         // visible events that start inside the range, measured on every read
  dead_time_s: float, dead_runs: [{t_start, t_end}],
  crop_warning: bool,                // an event inside is marked unsafe for a 9:16 crop
  over_limit_s: float,               // how far over its platform's maximum (0 when it fits)
  note: null | {id: "too_long"|"late_start"|"dead_time"|"late_payoff"|"long_tail"|"crop"|"no_events",
                message, apply: null | {t_start?: float, t_end?: float}, at: null | [float, float]},
  exports: [ClipExport],             // newest first
  created_at
}
ClipExport = {id, clip_id, crop: "none"|"9x16", mode: "accurate"|"lossless", width, height, fps,
              t_start, t_end,        // the range asked for (compare with the clip to see whether it was trimmed since)
              real_start, real_end,  // what the file holds: a lossless cut starts on a keyframe
              duration_s, size_bytes, created_at, url: "/exports/{id}/download"}
```

- `POST /videos/{id}/clips` body `{t_start, t_end, name?, platform?}` → 201 `Clip` (`source: "user"`, `status:
  "selected"`). 422 outside the video or under 3 s; 409 before the import has finished.
- `PATCH /clips/{id}` body any of `{t_start, t_end, name, status: "candidate"|"selected", platform, payoff_t}`, or
  `{reset: true}` (back to `orig_start`, `orig_end`) → `Clip`. Moving an edge or renaming makes a candidate
  `selected`. To apply the analysis note, send its `apply` object. 422 for a range outside the video or under 3 s,
  an empty name, a payoff outside the clip.
- `DELETE /clips/{id}` → 204. Its exports (rows and files) and its packages go with it.
- `POST /videos/{id}/clips/find` body `{prompt?, platform: "shorts"|"reels"|"tiktok" (default "reels"),
  target_len_s?: 3..600}` → 202 `Job` (kind `clip_find`). One Claude text call on the stored timeline; with no
  Anthropic key, three proposals from the timeline alone. Candidates of earlier runs are replaced; kept clips stay.
  The finished job's `message` reads like "4 clips found. <the model's note>". 409 while importing, while one
  runs, or when the video has no visible events.
- `POST /clips/{id}/export` body `{crop: "none"|"9x16", mode: "accurate"|"lossless"}` → 202 `Job` (kind
  `clip_export`, with progress). 422 for lossless with a crop; 409 when the source file is missing or an export is
  running. The clip becomes `exported`; an export of the same crop and mode replaces the earlier file.
- `GET /exports/{id}/download` → the MP4, named `{Channel}_{Topic}_{Subject}_{Clip}_9x16.mp4` (or `_full`,
  `_full_lossless`). 404 once it was replaced or its clip deleted.
- `POST /clips/{id}/refine` → 202 `Job` (kind `clip_refine`): two small Gemini calls look at the clip's first and
  closing event and move the edges by at most 2 s. The `message` says what happened to each edge. 409 with no
  Gemini key, no source file, no events in the clip, or while one runs.

## Short-form packages (Phase 2; BUILD_SPEC 7.8)

`GET /videos/{id}/packages` also lists each clip's packages and adds `running_short: bool` (a `clip_package` job
is queued or running). A short-form `Package` has `clip_id` set, `platform: "shorts"|"reels"|"tiktok"`, and is
`stale` when its clip was trimmed or the long-form inputs changed. Its fields:

```
ShortFields = {
  clip: {id, name, t_start, t_end},
  title, description,                  // Shorts only
  on_screen_text, caption, question, end_text,   // Reels and TikTok only; caption is ready to paste, hashtags included
  hashtags: [str], pinned_comment, link_back: str, hook_id: str|null,
  slots: {name: text}, goals: {field: Goal}, safe_margins: {top_pct, bottom_pct}
}
```
Rule ids: `canonical_spelling`, `hashtag_count`, `ambiguous_names`, `claim_needs_fact.<id>`, `number_needs_fact`,
`link_back` (block; warn on TikTok; field `description` or `caption`), `length_limits`, `clip_length` (field `clip`).

- `POST /videos/{id}/packages` body `{platforms: ["shorts", "reels", "tiktok"], clip_id}` → 202 `Job` (kind
  `clip_package`): one Claude call writes every platform listed. 422 without `clip_id`, 404 for a clip of another
  video, 409 with no Anthropic key, unconfirmed required facts, or while one runs. Without `clip_id` the endpoint
  writes the YouTube long-form package as before.
- `PATCH /packages/{id}` edits `title, description, hashtags, pinned_comment` (Shorts) or `on_screen_text, caption,
  end_text, hashtags, pinned_comment` (Reels, TikTok); editing the hashtags rewrites their line inside the
  description or caption. Dismissals work as for long-form.
- `POST /packages/{id}/regenerate` body `{field}` or `{all: true, replace_edits}` rewrites that platform of that clip.
- `GET /videos/{id}/export.md` appends each clip's short-form packages after the long-form package.

## Past uploads and publishing (Phase 1 step 7)

```
LibraryItem = {id, video_id: str|null, title, subject, topic, angle, hook, url, playlist,
               published_at: str|null,            // a date "YYYY-MM-DD" or an ISO timestamp
               from_app: bool}                    // created by "Mark as published" (video_id set)
```

- `GET /library` → `[LibraryItem]`, newest `published_at` first.
- `POST /library` body `{title, subject?, topic?, angle?, hook?, url?, playlist?, published_at?}` → 201
  `LibraryItem`. `title` is required; `url`, when given, must be a full `http(s)://` link (422 otherwise).
- `PATCH /library/{id}` body any of those fields → `LibraryItem`. `DELETE /library/{id}` → 204.
- `POST /videos/{id}/publish` body `{url, published_at?}` → `Video` plus `library_item: LibraryItem`. Sets
  `published_url` and `published_at` (now when not given) and creates or updates this video's past-upload
  entry from its package (title, subject, topic, the title's hook as `hook` and, if empty, `angle`, the
  topic's playlist). The video's `display_status` becomes `published`. 422 for a missing or bad link.
- `DELETE /videos/{id}/publish` → `Video`: clears the link and date and removes the entry publishing created.

Past uploads feed the package's end-screen target and the `cannibalization` check (a video's own entry is
never counted against it). They only change code-built parts, so `GET /videos/{id}/packages` refreshes
`end_screen_target`, the checklist's end-screen line and the rules for free when past uploads change; the
package is not marked stale. Publishing does not make a package stale either.

## Thumbnails (BUILD_SPEC 7.13)

```
Thumbnail = {id, video_id, batch_id, source_kind: "frame"|"upload", source_t: float|null, aspect: "16:9"|"9:16",
             model, params: {}, prompt, custom_prompt: bool, text_mode: "app"|"model", word, text_style,
             text_corner: "top_left"|"top_right"|"bottom_left"|"bottom_right", font,
             status: "queued"|"running"|"done"|"failed"|"nsfw", request_id: str|null, error: str|null,
             cost_usd: float|null,                  // Higgsfield's quote; null when none or not charged
             chosen: bool, created_at,
             review: null | {verdict: "ok"|"check"|null, problems: int, summary, model, stale?: bool,
                             checks: [{id: "faces"|"hands"|"hud"|"text"|"likeness"|"artifacts"|"placement", ok, note}],
                             code: [{id: "file"|"backdrop", ok, note}]},
             urls: {source: str|null, raw: str|null, final: str|null}}    // relative to the API
FoundFrame = {t, why, score, code_score, text_corner, sharpness, brightness,
              claude: null | {score: 0-10, subject_visible, hud: "none"|"light"|"heavy", text_corner, reason}}
ThumbSettings = {model, text_mode, review, text_corner: "auto"|corner, font, aspects: [..], prompt,
                 custom_prompt: bool, default_prompt,
                 models: [{id, label, path, params: {}, options: {name: [values]}}],
                 keys: {higgsfield: bool, anthropic: bool}}      // keys only on /settings/thumbnails
```

- `GET /videos/{id}/thumbnails` → `{can_generate, missing: [str], can_review, settings: ThumbSettings,
  words: [{word, text_style, from: "hook"|"package"}], default_text_style,
  frames: null | {created_at, ranked_by: "claude"|"code", looked_at, frames: [FoundFrame]},
  finding_frames: bool, running: bool, uploads: [{id, url}], thumbnails: [Thumbnail]}`.
- `POST /videos/{id}/thumbnails/frames` → 202 `Job` (`thumbnail_frames`). 409 while importing or already running.
- `POST /videos/{id}/thumbnails/uploads` with the image as the raw body and `Content-Type` image/jpeg, png or
  webp → 201 `{id, url, width, height}`. 415 other types, 413 over 20 MB, 422 unreadable or under 640×360.
- `POST /videos/{id}/thumbnails` body `{source: {kind: "frame", t} | {kind: "upload", upload_id}, models?: [id]
  (≤ 4; default the settings' model), aspects?, word? (default the first word choice; "" for none),
  text_style?, text_corner? ("auto" default), text_mode?, prompt? (a template for this run)}` → 202
  `{batch_id, job: Job, thumbnails: [Thumbnail], word_issues: [RuleResult]}`. 409 without Higgsfield keys or while
  a batch runs; 422 for an unknown model, a bad source or a word the claim rules block.
- `PATCH /thumbnails/{id}` body any of `{chosen, word, text_style, text_corner, font}` → `Thumbnail`. Text changes
  redraw from the raw image (no model call) and set `review.stale`; 422 when the model drew the text.
  Choosing one clears the other chosen thumbnail of the same aspect.
- `POST /thumbnails/{id}/review` → 202 `Job` (Claude only).
- `GET /thumbnails/{id}/image?v=final|raw|source&download=true` → the image; with `download`, named
  `{Channel}_{Topic}_{Subject}_thumbnail_16x9.jpg`. `DELETE /thumbnails/{id}` → 204 (409 while running).
- `GET /settings/thumbnails` → `ThumbSettings`. `PUT` body any of `{model, params: {model_id: {option: value}},
  text_mode, review, text_corner, font, aspects, prompt}` → `ThumbSettings` (422 for values the YAML does not allow).
  `DELETE` resets to `config/thumbnails.yaml`.
- `POST /settings/thumbnails/estimate` body `{models?, aspects?}` → `{estimates: [{model, aspect, usd: float|null,
  error?}]}`; a quote is free.

## Analysis and jobs

- `POST /videos/{id}/analyze` body `{discard_user_work: false}` → 202 `Job`.
  409 when no Gemini key is set, the import is not finished, or an analysis is already running.
  Kept unless `discard_user_work`: user events, verified, hidden or edited (moved, retyped,
  relabelled) events, confirmed facts.
- `GET /jobs/{id}` → `Job`; `POST /jobs/{id}/retry` → 202 `Job` (a new job of the same kind). 409 for the clip
  jobs (`clip_find`, `clip_export`, `clip_package`, `clip_refine`): they need what they were started with, so
  start them again from the clip.

## Live updates

`GET /videos/{id}/updates` is a server-sent event stream with no history (load current state first, then subscribe).

| event | data |
| --- | --- |
| `job.progress` | `Job` |
| `job.done` | `Job` |
| `job.error` | `Job` |
| `analysis.event` | `Event`, one per event in time order after an analysis is stored |
| `clip.candidate` | `Clip`, one per finder proposal as it is stored (the untouched proposals of earlier runs are gone by then) |
| `thumbnail.updated` | `Thumbnail`, whenever one changes |
| `thumbnail.frames` | the frame finder's result, as in `GET /videos/{id}/thumbnails` `frames` |

A comment line (`: ping`) is sent every 15 s.
