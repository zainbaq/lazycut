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

export interface ConfigError {
  file: string;
  problem: string;
}

export interface ConfigStatus {
  errors: ConfigError[];
  channel: string | null;
  presets: string[];
  models: { video: string | null; text: string | null };
  keys: { gemini: boolean; anthropic: boolean; youtube: boolean };
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
  /** An auto-fix changed the field (canonical_spelling, hashtag_count, banned_tags). */
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
}

export interface Package {
  id: string;
  video_id: string;
  clip_id: string | null;
  platform: "youtube";
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
  | "chapters";

/** `PATCH /packages/{id}`. */
export type PackageEdit =
  | { field: EditableField; value: string | string[] }
  | { dismiss: string }
  | { undismiss: string };

/** `POST /packages/{id}/regenerate`. */
export type PackageRegenerate = { field: EditableField } | { all: true; replace_edits: boolean };
