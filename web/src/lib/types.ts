// JSON shapes from api/API_SHAPES.md. Keep in step with that file.

export type Glyph = "slash" | "dot" | "ring" | "diamond";
export type EventColor = "accent" | "paper" | "warn" | "gold";

export interface EventType {
  id: string;
  label: string;
  glyph: Glyph;
  color: EventColor;
  definition: string;
  show: boolean;
}

export interface FactDef {
  key: string;
  label: string;
  type: "int" | "text" | "bool" | "enum";
  options: string[];
  derive_from: string | null;
  required: boolean;
  instructions: string | null;
}

export interface Preset {
  id: string;
  name: string;
  description?: string;
  event_types: EventType[];
  facts: FactDef[];
  hooks?: { id: string; text: string }[];
  claim_rules?: { id: string; phrases: string[]; severity: string }[];
  title_patterns?: { recommended?: string; alternates?: string[] } | null;
  [key: string]: unknown;
}

// ---- Preset editor (5): the whole preset as the API reads and writes it ----

export type ConditionOp = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "between" | "in";
export type ConditionValue = string | number | boolean | null | (string | number)[];

export interface Condition {
  fact: string | null;
  research: string | null;
  op: ConditionOp;
  value: ConditionValue;
}

export interface ResearchFieldDef {
  key: string;
  label: string | null;
  type: "text" | "bool";
  needs_credible_source: boolean;
  hint: string | null;
}

export interface HookDef {
  id: string;
  text: string;
  thumbnail_word: string | null;
  thumbnail_text_style: string | null;
  when: Condition;
}

export interface ClaimRuleDef {
  id: string;
  phrases: string[];
  requires: Condition;
  severity: "block" | "warn";
  suggest: string | null;
}

export interface BannedTagDef {
  tag: string;
  unless: Condition | null;
}

export interface PresetDoc {
  id: string;
  name: string;
  description: string;
  event_types: EventType[];
  facts: FactDef[];
  research_fields: ResearchFieldDef[];
  credit_fields: string[];
  credit_lines: string[];
  hooks: HookDef[];
  thumbnail_words: string[];
  title_patterns: { recommended: string; alternates: string[] };
  claim_rules: ClaimRuleDef[];
  clip_rules: { lead_in_s: number; tail_s: number; end_on: string[]; start_cue: string | null; end_cue: string | null };
  saved_prompts: string[];
  tag_recipe: string[];
  banned_tags: (string | BannedTagDef)[];
  slots: Record<string, string>;
  templates: { description: string | null; shorts_description: string | null; reel: string | null; reel_end_text: string | null };
  search_seeds: string[];
  search_fit: string;
  fallback_hashtags: string[];
  playlist_name: string;
  competitor_query: string;
  /** Read-only, added by the API. */
  file?: string | null;
  video_count?: number;
}

export interface PresetProblem {
  path: string;
  message: string;
}

export interface PresetCheck {
  ok: boolean;
  problems: PresetProblem[];
}

export interface NewPreset {
  id: string;
  name: string;
  copy_from: string | null;
}

export interface ConfigError {
  file: string;
  problem: string;
}

export interface ConfigStatus {
  errors: ConfigError[];
  channel: string | null;
  presets: string[];
  models: { video: string | null; text: string | null };
  keys: { gemini: boolean; anthropic: boolean; youtube: boolean; higgsfield?: boolean };
  event_detectors?: string[];
  storage?: Record<string, unknown>;
  tools?: Record<string, boolean>;
}

export interface ImportItem {
  source: "local";
  ref: string;
  name: string;
  size_bytes: number;
  modified_at: number;
  imported_video_id: string | null;
}

export interface ImportList {
  folder: string;
  items: ImportItem[];
}

export type JobKind = "import" | "analysis" | "research" | "package" | string;
export type JobStatus = "queued" | "running" | "done" | "error";

export interface Job {
  id: string;
  video_id: string;
  kind: JobKind;
  status: JobStatus;
  progress: number;
  message: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export type DisplayStatus =
  | "importing"
  | "analyzing"
  | "needs_confirmation"
  | "ready"
  | "packaged"
  | "published"
  | "error";

export interface Video {
  id: string;
  title: string;
  subject: string;
  topic: string;
  topic_terms: string;
  kind: "long" | "clip";
  preset_id: string;
  status: "importing" | "ready" | "error";
  display_status: DisplayStatus;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  size_bytes: number | null;
  is_hdr: boolean;
  import_source: string;
  import_ref: string;
  published_url: string | null;
  published_at: string | null;
  created_at: string;
  analysis: null | {
    id: string;
    model: string;
    fps: number | null;
    created_at: string;
    event_count: number;
  };
  jobs: Job[];
  media_url: string;
}

export interface NewVideo {
  source: "local";
  ref: string;
  title: string;
  subject?: string;
  topic?: string;
  topic_terms?: string;
  kind: "long" | "clip";
  preset_id: string;
}

export interface Detection {
  detector: string;
  t_start: number;
  label: string;
  evidence: Record<string, unknown>;
}

export interface TimelineEvent {
  id: string;
  video_id: string;
  t_start: number;
  t_end: number;
  t_model_start: number | null;
  t_model_end: number | null;
  type: string;
  label: string;
  intensity: "low" | "medium" | "high";
  crop_safe_9x16: boolean;
  confidence: "certain" | "uncertain";
  source: "model" | "user";
  detected_by: Detection[];
  verified: boolean;
  hidden: boolean;
  /** The user moved, retyped or relabelled this model event; re-analysis keeps it (7.12). */
  edited: boolean;
}

/** `POST /videos/{id}/events`. A restore (undo of a delete) sends the whole old event, id included. */
export type NewEvent = { t_start: number; type: string; t_end?: number; label?: string } | TimelineEvent;

/** `PATCH /events/{id}`. `t_start` without `t_end` moves the event and keeps its length. */
export type EventPatch = Partial<Pick<TimelineEvent, "t_start" | "t_end" | "type" | "label" | "verified" | "hidden">>;

export interface Segment {
  id: string;
  kind: "peak" | "section";
  t_start: number;
  t_end: number;
  label: string;
}

export interface Timeline {
  duration_s: number;
  fps: number;
  preset_id: string;
  event_types: EventType[];
  events: TimelineEvent[];
  segments: Segment[];
  intensity: { bucket_s: number; scores: number[] };
  dead_time: { t_start: number; t_end: number }[];
}

export interface Frames {
  interval_s: number;
  width: number;
  frames: { t: number; url: string }[];
}

export type FactValue = number | string | boolean | null;

export interface Fact {
  id: string;
  video_id: string;
  key: string;
  label: string;
  type: FactDef["type"];
  options: string[];
  required: boolean;
  derive_from: string | null;
  /** From the model, or the visible-event count for derived facts. */
  proposed_value: FactValue;
  /** The user's value; null means "use the proposal". */
  value: FactValue;
  /** value ?? proposed_value: what the UI shows and packaging uses. */
  effective_value: FactValue;
  confirmed: boolean;
  confirmed_at: string | null;
  evidence_ts: number[];
  evidence_event_ids: string[];
  /** Derived facts: visible events of that type now. */
  event_count: number | null;
  /** Derived facts: how many of those are verified. */
  verified_count: number | null;
  /** A confirmed derived fact whose value no longer equals event_count. */
  out_of_date: boolean;
}

/** `PUT /facts/{id}`. */
export interface FactUpdate {
  value?: FactValue;
  confirmed?: boolean;
}

// ---- Subject research (Phase 1 step 5, BUILD_SPEC 7.7) -------------------------------

export type ResearchValue = string | boolean | null;

export interface ResearchSource {
  url: string;
  title: string;
  domain: string;
  rating: "credible" | "unrated";
}

export interface ResearchField {
  key: string;
  label: string;
  type: "text" | "bool";
  needs_credible_source: boolean;
  /** What research found; null = not found. */
  value: ResearchValue;
  sources: ResearchSource[];
  /** At least one source is on the channel's credible list. */
  credible: boolean;
  /** The user's value ("Edited by you"); null with overridden=true means "unknown". */
  override: ResearchValue;
  overridden: boolean;
  /** Found, but it needs a credible source and has none: shown, not used. */
  no_credible_source: boolean;
  /** Override if set; else value, or null when no_credible_source. */
  effective_value: ResearchValue;
}

export interface Research {
  id: string;
  video_id: string;
  subject_key: string;
  topic_key: string;
  method: "none" | "search" | "pasted";
  updated_at: string | null;
  /** An Anthropic key is set. */
  can_search: boolean;
  /** A research job for this video is running. */
  running: boolean;
  canonical_name: string | null;
  /** The subject's spelling was corrected; offer a revert. */
  correction: null | { from: string; to: string };
  fields: ResearchField[];
  sources: ResearchSource[];
  effective: Record<string, ResearchValue>;
}

/** `POST /videos/{id}/research`: `{}` searches the web; `pasted_text` sorts the user's own notes. */
export interface ResearchRun {
  pasted_text?: string;
  source_url?: string;
}

/** `PATCH /videos/{id}/research`. */
export type ResearchEdit = { key: string; value: ResearchValue } | { key: string; restore: true };

// ---- Packages (Phase 1 step 6: YouTube long-form, BUILD_SPEC 7.8, 7.9) -----------------

export type Goal = "click_through" | "retention" | "session_watch_time" | "engagement" | "funnel";
export type Severity = "pass" | "warn" | "block";

export interface RuleResult {
  /** `rule_id:field`; used to dismiss a warning. */
  key: string;
  rule_id: string;
  severity: Severity;
  /** A path such as `title`, `title_alternates[1]`, `thumbnail.word_options[0]`, `description`, `tags`. */
  field: string;
  message: string;
  evidence: unknown;
  /** An auto-fix changed the field (canonical_spelling, hashtag_count, banned_tags, tags_fit). */
  fixed: boolean;
  dismissed: boolean;
}

export interface TitleAlternate {
  text: string;
  why: string;
  goal: Goal;
  hook_id: string | null;
}

export interface PackageFields {
  title: string;
  title_why: string;
  title_goal: Goal;
  title_hook_id: string | null;
  title_alternates: TitleAlternate[];
  hook_line: string;
  description: string;
  /** "0:00 Label" lines; "" when the video has fewer than 3 valid sections. */
  chapters: string;
  chapter_list: { t: number; label: string }[];
  tags: string[];
  hashtags: string[];
  credit_block: string;
  opening_5s: string;
  pinned_comment: string;
  community_post: string;
  end_screen_target: { kind: "past_upload" | "playlist" | "none"; title: string | null; url: string | null; label: string };
  thumbnail: { frame_ts: number[]; word_options: string[]; text_style: string | null; prompt: string };
  checklist: { item: string; detail: string }[];
  slots: Record<string, string>;
  goals: Record<string, Goal>;
  /** Search demand behind the title and tags (BUILD_SPEC 7.7.1). Older packages lack it. */
  seo?: Seo;
}

export interface SeoCover {
  text: string;
  demand: number;
  match: "exact" | "words";
  /** The match ends within the first 60 characters. */
  front: boolean;
}

export interface SeoPhrase {
  id: string;
  text: string;
  rank: number;
  seen: number;
  /** 1.0 = a top suggestion; suggestion rank, not views. */
  demand: number;
  about_subject: boolean;
  /** The writer judged someone typing it would want this video. */
  fits: boolean;
  in_title?: boolean;
  in_tags?: boolean;
}

export interface SeoTitleScore {
  id: string;
  text: string;
  /** Includes rule penalties (0 when a rule would block it). */
  score: number;
  demand_score?: number;
  covers: SeoCover[];
  writer_pick: boolean;
  issues?: string[];
}

export interface Seo {
  /** null: no search data; the writer's choices stand. */
  source: "youtube_suggest" | null;
  harvested_at: string | null;
  picked_by: "search_score" | "search_score_agrees" | "writer";
  phrases: SeoPhrase[];
  excluded: { text: string; demand: number; reason: string }[];
  title_scores: SeoTitleScore[];
  /** The current title (after edits) against the best candidate. */
  title_score?: { score: number; covers: SeoCover[]; best_candidate: number };
  /** Bare names mostly searched for something else; never a tag or hashtag alone. */
  ambiguous_names: string[];
}

export interface Package {
  id: string;
  video_id: string;
  clip_id: string | null;
  platform: "youtube" | ShortPlatform;
  version: number;
  created_at: string;
  fields: PackageFields;
  edited_fields: string[];
  rule_results: RuleResult[];
  inputs_hash: string;
  /** Facts, research, events, preset or channel changed since generation. */
  stale: boolean;
  /** Field paths with a block: Copy is disabled for them. */
  blocked_fields: string[];
  /** Open (not dismissed) checks. */
  counts: { block: number; warn: number };
}

export interface PackageList {
  /** An Anthropic key is set. */
  can_write: boolean;
  /** Required facts not confirmed yet; generation is blocked until empty. */
  missing_facts: string[];
  can_generate: boolean;
  /** A package job is queued or running. */
  running: boolean;
  /** A short-form (clip) package is being written. */
  running_short: boolean;
  packages: Package[];
}

/** The fields a PATCH may edit. */
export type EditableField =
  | "title"
  | "description"
  | "hook_line"
  | "tags"
  | "hashtags"
  | "pinned_comment"
  | "community_post"
  | "opening_5s"
  | "chapters"
  | "on_screen_text"
  | "caption"
  | "end_text";

/** `PATCH /packages/{id}`. */
export type PackageEdit =
  | { field: EditableField; value: string | string[] }
  | { dismiss: string }
  | { undismiss: string };

/** `POST /packages/{id}/regenerate`. */
export type PackageRegenerate = { field: EditableField } | { all: true; replace_edits: boolean };

/** A past upload (`GET /library`), typed in by hand or created by "Mark as published". */
export interface LibraryItem {
  id: string;
  video_id: string | null;
  title: string;
  subject: string;
  topic: string;
  angle: string;
  hook: string;
  url: string;
  playlist: string;
  /** A date "YYYY-MM-DD" or an ISO timestamp. */
  published_at: string | null;
  /** Created by "Mark as published" (video_id is set). */
  from_app: boolean;
  /** Phase 3: imported from the channel. */
  youtube_id: string | null;
  kind: "long" | "short";
  duration_s: number | null;
  views: number | null;
  /** How topic and subject were filled: read from the title ("playlist" | "repeated"), by you ("you"), or "" (not read). */
  read_by: "" | "playlist" | "repeated" | "you";
  source: "you" | "app" | "youtube";
}

export interface ChannelPlaylistRow {
  id: string;
  title: string;
  count: number;
  url: string;
  in_config: { topic: string; name: string } | null;
}

export interface ChannelSync {
  at: string;
  channel: { id: string; title: string; handle: string; subscribers: number | null; video_count: number };
  uploads: number;
  new: number;
  updated: number;
  linked: number;
  long: number;
  shorts: number;
  unread: number;
  shorts_unsure: number;
  units: number;
  playlists: ChannelPlaylistRow[];
}

export interface ImportStatus {
  can_import: boolean;
  key_set: boolean;
  handle: string;
  running: Job | null;
  last_job: Job | null;
  last: ChannelSync | null;
}

/** `POST /library` (title required) and `PATCH /library/{id}` (any field). */
export type LibraryItemInput = Partial<
  Pick<LibraryItem, "title" | "subject" | "topic" | "angle" | "hook" | "url" | "playlist" | "published_at">
>;

/** `POST /videos/{id}/publish`. */
export interface PublishBody {
  url: string;
  published_at?: string | null;
}

/** `POST /videos/{id}/publish` returns the video plus the past-upload entry it wrote. */
export type PublishedVideo = Video & { library_item: LibraryItem };

// ---- thumbnails (BUILD_SPEC 7.13) --------------------------------------------------

export type Aspect = "16:9" | "9:16";
export type Corner = "top_left" | "top_right" | "bottom_left" | "bottom_right";
export type CornerChoice = Corner | "auto";
export type ThumbFont = "bebas" | "montserrat" | "league_spartan" | "dejavu";
export type TextMode = "app" | "model";
export type ParamValue = string | number | boolean;

export interface ThumbModel {
  id: string;
  label: string;
  path: string;
  /** Current values: the YAML defaults with the saved overrides on top. */
  params: Record<string, ParamValue>;
  /** Allowed values per option. */
  options: Record<string, ParamValue[]>;
}

/** The effective thumbnail settings (`GET /settings/thumbnails` adds `keys`). */
export interface ThumbSettings {
  model: string;
  text_mode: TextMode;
  review: boolean;
  text_corner: CornerChoice;
  font: ThumbFont;
  aspects: Aspect[];
  prompt: string;
  custom_prompt: boolean;
  default_prompt: string;
  models: ThumbModel[];
  keys?: { higgsfield: boolean; anthropic: boolean };
}

/** `PUT /settings/thumbnails`: every field optional; unset keeps the YAML default. */
export interface ThumbSettingsInput {
  model?: string;
  params?: Record<string, Record<string, ParamValue>>;
  text_mode?: TextMode;
  review?: boolean;
  text_corner?: CornerChoice;
  font?: ThumbFont;
  aspects?: Aspect[];
  prompt?: string | null;
}

export interface FrameCandidate {
  t: number;
  why: string;
  score: number;
  code_score: number;
  text_corner: Corner;
  claude: null | {
    score: number;
    subject_visible: boolean;
    hud: "none" | "light" | "heavy";
    text_corner: Corner;
    reason: string;
  };
  sharpness: number;
  brightness: number;
}

export interface FrameFinds {
  created_at: string;
  ranked_by: "claude" | "code";
  looked_at: number;
  frames: FrameCandidate[];
}

export interface WordChoice {
  word: string;
  text_style: string;
  from: "hook" | "package";
}

export interface ReviewCheck {
  id: string;
  ok: boolean;
  note: string;
}

export interface ThumbReview {
  verdict: "ok" | "check" | null;
  checks: ReviewCheck[];
  summary?: string;
  problems?: number;
  model?: string;
  /** Checks done in code: file size and dimensions, and the area behind the word. */
  code?: ReviewCheck[];
  /** The word changed after the review. */
  stale?: boolean;
}

export interface Thumbnail {
  id: string;
  video_id: string;
  batch_id: string;
  source_kind: "frame" | "upload";
  source_t: number | null;
  aspect: Aspect;
  model: string;
  params: Record<string, ParamValue>;
  prompt: string;
  custom_prompt: boolean;
  text_mode: TextMode;
  word: string;
  text_style: string;
  text_corner: Corner;
  font: ThumbFont;
  status: "queued" | "running" | "done" | "failed" | "nsfw";
  request_id: string | null;
  review: ThumbReview | null;
  cost_usd: number | null;
  chosen: boolean;
  error: string | null;
  created_at: string;
  urls: { source: string | null; raw: string | null; final: string | null };
}

export interface ThumbUpload {
  id: string;
  url: string;
  width?: number;
  height?: number;
}

/** `GET /videos/{id}/thumbnails`. */
export interface ThumbnailState {
  can_generate: boolean;
  missing: string[];
  can_review: boolean;
  settings: ThumbSettings;
  words: WordChoice[];
  default_text_style: string;
  frames: FrameFinds | null;
  finding_frames: boolean;
  running: boolean;
  uploads: ThumbUpload[];
  thumbnails: Thumbnail[];
}

export interface ThumbSource {
  kind: "frame" | "upload";
  t?: number;
  upload_id?: string;
}

/** `POST /videos/{id}/thumbnails`. Each image is a paid Higgsfield call. */
export interface ThumbGenerate {
  source: ThumbSource;
  models?: string[];
  aspects?: Aspect[];
  word?: string;
  text_style?: string;
  text_corner?: CornerChoice;
  text_mode?: TextMode;
  prompt?: string;
}

export interface ThumbGenerateResult {
  batch_id: string;
  job: Job;
  thumbnails: Thumbnail[];
  word_issues: { message: string; severity: string }[];
}

/** `PATCH /thumbnails/{id}`: choose, or redraw the word for free. */
export interface ThumbAdjust {
  chosen?: boolean;
  word?: string;
  text_style?: string;
  text_corner?: Corner;
  font?: ThumbFont;
}

export interface ThumbEstimate {
  model: string;
  aspect: Aspect;
  usd: number | null;
  error?: string;
}

// ---- clips (BUILD_SPEC 7.5, 7.6) ----

export type ShortPlatform = "shorts" | "reels" | "tiktok";
export type ClipStatus = "candidate" | "selected" | "exported";

/** One suggestion for a clip. `apply` holds the edges that carry it out; null when it is advice only. */
export interface ClipNote {
  id: "too_long" | "late_start" | "dead_time" | "late_payoff" | "long_tail" | "crop" | "no_events";
  message: string;
  apply: { t_start?: number; t_end?: number } | null;
  /** The stretch of the video the note is about, when it has one. */
  at: [number, number] | null;
}

export interface ClipExport {
  id: string;
  clip_id: string;
  crop: "none" | "9x16";
  mode: "accurate" | "lossless";
  width: number | null;
  height: number | null;
  fps: number | null;
  t_start: number | null;
  t_end: number | null;
  /** What the file really holds: a lossless cut starts on a keyframe. */
  real_start: number | null;
  real_end: number | null;
  duration_s: number | null;
  size_bytes: number | null;
  created_at: string;
  url: string;
}

export interface Clip {
  id: string;
  video_id: string;
  name: string;
  t_start: number;
  t_end: number;
  duration_s: number;
  prompt: string | null;
  reason: string | null;
  payoff_t: number | null;
  /** The frame shown on the card: the payoff, or the middle. */
  frame_t: number;
  status: ClipStatus;
  platform: ShortPlatform | null;
  source: "finder" | "user" | "import";
  orig_start: number | null;
  orig_end: number | null;
  /** The range differs from the one it was created with (Reset brings that back). */
  edited: boolean;
  dead_time_s: number;
  dead_runs: { t_start: number; t_end: number }[];
  event_counts: Record<string, number>;
  crop_warning: boolean;
  over_limit_s: number;
  note: ClipNote | null;
  exports: ClipExport[];
  created_at: string;
}

export interface ClipList {
  can_find: boolean;
  /** A Gemini key is set, so edges can be refined. */
  can_refine: boolean;
  finding: boolean;
  limits: { min_s: number; max_s: Record<ShortPlatform, number> };
  clips: Clip[];
}

export interface NewClip {
  t_start: number;
  t_end: number;
  name?: string;
  platform?: ShortPlatform | null;
}

export type ClipPatch = Partial<Pick<Clip, "t_start" | "t_end" | "name" | "platform" | "payoff_t">> & {
  status?: "candidate" | "selected";
  reset?: boolean;
};

export interface ClipFind {
  prompt: string;
  platform: ShortPlatform;
  target_len_s?: number | null;
}

/** A short-form package's fields (Shorts: title and description; Reels and TikTok: on-screen text and caption). */
export interface ShortFields {
  clip: { id: string; name: string; t_start: number; t_end: number };
  title?: string;
  description?: string;
  on_screen_text?: string;
  caption?: string;
  question?: string;
  end_text?: string;
  hashtags: string[];
  pinned_comment: string;
  link_back: string;
  hook_id: string | null;
  slots: Record<string, string>;
  goals: Record<string, Goal>;
  safe_margins: { top_pct: number; bottom_pct: number };
}

export type ShortPackage = Omit<Package, "fields" | "platform" | "clip_id"> & {
  platform: ShortPlatform;
  clip_id: string;
  fields: ShortFields;
};

// ---- Competitor research (BUILD_SPEC 7.7, Phase 3) ----

export interface CompetitorVideo {
  id: string;
  title: string;
  channel: string;
  channel_id: string;
  published_at: string;
  views: number;
  duration_s: number;
  subs: number | null;
  url: string;
  thumbnail: string;
  age_days: number;
  views_per_day: number;
  /** Views against the channel's average per video. */
  outlier: number | null;
  own: boolean;
}

export interface CompetitorMetrics {
  videos: number;
  views: number;
  /** Herfindahl index of view shares over the first page (0..1). */
  hhi: number | null;
  concentration: "spread" | "moderate" | "concentrated" | null;
  small_share: number | null;
  small_videos?: number;
  recent_30d: number;
  median_per_day: number | null;
  leader: { id: string; channel: string; share: number } | null;
  breakouts: string[];
}

export interface CompetitorReadOut {
  patterns: { pattern: string; count: number; examples: string[] }[];
  angles_taken: { angle: string; count: number }[];
  thumbnail_words: { word: string; count: number }[];
  thumbnail_look: string;
  unclaimed: { angle: string; why: string; backed_by: string; blocked_by: string[] }[];
  read: string;
}

export interface CompetitorResult {
  query: string;
  searched_at: string;
  units: number;
  rows: CompetitorVideo[];
  metrics: CompetitorMetrics;
  read?: CompetitorReadOut | null;
  read_for?: string;
  read_at?: string;
}

export interface CompetitorsView {
  video_id: string;
  query: string;
  can_search: boolean;
  can_read: boolean;
  running: boolean;
  fresh: boolean;
  result: CompetitorResult | null;
}
