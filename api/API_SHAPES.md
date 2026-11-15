# API shapes (Phase 1)

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
Job = {id, video_id, kind: "import"|"analysis"|"research"|"package", status: "queued"|"running"|"done"|"error",
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
  Each search run is one Claude call with web search plus one short structuring call.
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
  packages: [Package]              // today at most one: platform "youtube"
}
Package = {
  id, video_id, clip_id: null, platform: "youtube", version: int, created_at,
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
  checklist: [{item, detail}],
  slots: {name: text}, goals: {field: Goal}
}
Goal = "click_through"|"retention"|"session_watch_time"|"engagement"|"funnel"
RuleResult = {key, rule_id, severity: "pass"|"warn"|"block", field, message, evidence, fixed: bool, dismissed: bool}
```
Rule ids: `canonical_spelling`, `hashtag_count`, `banned_tags` (these auto-fix; `fixed: true` says what changed),
`claim_needs_fact.<claim rule id>`, `number_needs_fact`, `search_first_title`, `chapters_valid`, `tags_count`,
`cannibalization`, `length_limits`. `field` is a path such as `title`, `title_alternates[1]`,
`thumbnail.word_options[0]`, `description`, `tags`.

- `POST /videos/{id}/packages` body `{platforms: ["youtube"]}` → 202 `Job` (kind `package`). 409 with no
  Anthropic key, with unconfirmed required facts (the message names them), or while one runs. 422 for
  other platforms (short-form comes with clips in Phase 2). One Claude call per run.
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
  `{Channel}_{Topic}_{Subject}_YouTube_SEO.md` (spaces and `< > : " / \ | ? *` removed). 404 before generation.

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

## Analysis and jobs

- `POST /videos/{id}/analyze` body `{discard_user_work: false}` → 202 `Job`.
  409 when no Gemini key is set, the import is not finished, or an analysis is already running.
  Kept unless `discard_user_work`: user events, verified, hidden or edited (moved, retyped,
  relabelled) events, confirmed facts.
- `GET /jobs/{id}` → `Job`; `POST /jobs/{id}/retry` → 202 `Job` (a new job of the same kind)

## Live updates

`GET /videos/{id}/updates` is a server-sent event stream with no history (load current state first, then subscribe).

| event | data |
| --- | --- |
| `job.progress` | `Job` |
| `job.done` | `Job` |
| `job.error` | `Job` |
| `analysis.event` | `Event`, one per event in time order after an analysis is stored |

A comment line (`: ping`) is sent every 15 s.
