// Typed client for the LazyCut API (api/API_SHAPES.md). The browser calls the API directly (D18).

import type {
  Aspect,
  ConfigStatus,
  EventPatch,
  Fact,
  FactUpdate,
  Frames,
  ImportList,
  Job,
  LibraryItem,
  LibraryItemInput,
  NewEvent,
  NewVideo,
  Package,
  PackageEdit,
  PackageList,
  PackageRegenerate,
  Preset,
  PublishBody,
  PublishedVideo,
  Research,
  ResearchEdit,
  ResearchRun,
  ThumbAdjust,
  ThumbEstimate,
  ThumbGenerate,
  ThumbGenerateResult,
  Thumbnail,
  ThumbnailState,
  ThumbSettings,
  ThumbSettingsInput,
  ThumbUpload,
  Timeline,
  TimelineEvent,
  Video,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Turn a path from an API payload (`/videos/x/media`) into a full URL. */
export function apiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${API_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_URL}. Is the api container running?`, 0);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) {
        // Pydantic prefixes validator messages with "Value error, "; the rest is written for the user.
        detail = body.detail
          .map((d: { msg?: string }) => (d.msg ? d.msg.replace(/^Value error, /, "") : JSON.stringify(d)))
          .join("; ");
      }
    } catch {
      // keep the status text
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  configStatus: () => request<ConfigStatus>("/config/status"),
  presets: () => request<Preset[]>("/presets"),
  imports: () => request<ImportList>("/imports"),
  videos: () => request<Video[]>("/videos"),
  video: (id: string) => request<Video>(`/videos/${id}`),
  createVideo: (body: NewVideo) => request<Video>("/videos", { method: "POST", ...json(body) }),
  updateVideo: (id: string, body: Partial<Pick<Video, "title" | "subject" | "topic" | "topic_terms" | "preset_id">>) =>
    request<Video>(`/videos/${id}`, { method: "PATCH", ...json(body) }),
  deleteVideo: (id: string) => request<void>(`/videos/${id}`, { method: "DELETE" }),
  frames: (id: string) => request<Frames>(`/videos/${id}/frames`),
  timeline: (id: string) => request<Timeline>(`/videos/${id}/timeline`),
  facts: (id: string) => request<Fact[]>(`/videos/${id}/facts`),
  createEvent: (videoId: string, body: NewEvent) =>
    request<TimelineEvent>(`/videos/${videoId}/events`, { method: "POST", ...json(body) }),
  updateEvent: (id: string, body: EventPatch) => request<TimelineEvent>(`/events/${id}`, { method: "PATCH", ...json(body) }),
  deleteEvent: (id: string) => request<void>(`/events/${id}`, { method: "DELETE" }),
  updateFact: (id: string, body: FactUpdate) => request<Fact>(`/facts/${id}`, { method: "PUT", ...json(body) }),
  analyze: (id: string, discardUserWork: boolean) =>
    request<Job>(`/videos/${id}/analyze`, { method: "POST", ...json({ discard_user_work: discardUserWork }) }),
  retryJob: (id: string) => request<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  research: (id: string) => request<Research>(`/videos/${id}/research`),
  /** A paid Claude call (web search) unless `pasted_text` is given. */
  runResearch: (id: string, body: ResearchRun = {}) =>
    request<Job>(`/videos/${id}/research`, { method: "POST", ...json(body) }),
  editResearchField: (id: string, body: ResearchEdit) =>
    request<Research>(`/videos/${id}/research`, { method: "PATCH", ...json(body) }),
  revertSpelling: (id: string) => request<Research>(`/videos/${id}/research/revert-spelling`, { method: "POST" }),
  packages: (id: string) => request<PackageList>(`/videos/${id}/packages`),
  /** A paid Claude call. */
  generatePackage: (id: string) =>
    request<Job>(`/videos/${id}/packages`, { method: "POST", ...json({ platforms: ["youtube"] }) }),
  editPackage: (id: string, body: PackageEdit) => request<Package>(`/packages/${id}`, { method: "PATCH", ...json(body) }),
  /** A paid Claude call. */
  regeneratePackage: (id: string, body: PackageRegenerate) =>
    request<Job>(`/packages/${id}/regenerate`, { method: "POST", ...json(body) }),
  library: () => request<LibraryItem[]>("/library"),
  addLibraryItem: (body: LibraryItemInput) => request<LibraryItem>("/library", { method: "POST", ...json(body) }),
  editLibraryItem: (id: string, body: LibraryItemInput) =>
    request<LibraryItem>(`/library/${id}`, { method: "PATCH", ...json(body) }),
  deleteLibraryItem: (id: string) => request<void>(`/library/${id}`, { method: "DELETE" }),
  publish: (id: string, body: PublishBody) =>
    request<PublishedVideo>(`/videos/${id}/publish`, { method: "POST", ...json(body) }),
  unpublish: (id: string) => request<Video>(`/videos/${id}/publish`, { method: "DELETE" }),
  // ---- thumbnails (7.13) ----
  thumbnails: (id: string) => request<ThumbnailState>(`/videos/${id}/thumbnails`),
  /** Scores frames in code, then a small paid Claude call ranks the best few. */
  findFrames: (id: string) => request<Job>(`/videos/${id}/thumbnails/frames`, { method: "POST" }),
  /** The raw file is the request body; its type is the Content-Type. */
  uploadThumbSource: (id: string, file: File) =>
    request<ThumbUpload>(`/videos/${id}/thumbnails/uploads`, {
      method: "POST",
      body: file,
      headers: { "Content-Type": file.type },
    }),
  /** Each image is a paid Higgsfield call. */
  generateThumbnails: (id: string, body: ThumbGenerate) =>
    request<ThumbGenerateResult>(`/videos/${id}/thumbnails`, { method: "POST", ...json(body) }),
  /** Choose, or redraw the word: free, no model call. */
  adjustThumbnail: (id: string, body: ThumbAdjust) =>
    request<Thumbnail>(`/thumbnails/${id}`, { method: "PATCH", ...json(body) }),
  /** A small paid Claude call. */
  reviewThumbnail: (id: string) => request<Job>(`/thumbnails/${id}/review`, { method: "POST" }),
  deleteThumbnail: (id: string) => request<void>(`/thumbnails/${id}`, { method: "DELETE" }),
  thumbSettings: () => request<ThumbSettings>("/settings/thumbnails"),
  saveThumbSettings: (body: ThumbSettingsInput) =>
    request<ThumbSettings>("/settings/thumbnails", { method: "PUT", ...json(body) }),
  resetThumbSettings: () => request<ThumbSettings>("/settings/thumbnails", { method: "DELETE" }),
  /** Higgsfield's price quote; no charge. */
  estimateThumbnails: (body: { models?: string[]; aspects?: Aspect[] }) =>
    request<{ estimates: ThumbEstimate[] }>("/settings/thumbnails/estimate", { method: "POST", ...json(body) }),
};

/** A thumbnail image as a download (`?download=true` names the file after the video). */
export function thumbDownloadUrl(thumbId: string, v: "final" | "raw" = "final"): string {
  return apiUrl(`/thumbnails/${thumbId}/image?v=${v}&download=true`);
}

/** The package as Markdown, served as a download. */
export function exportUrl(videoId: string): string {
  return apiUrl(`/videos/${videoId}/export.md`);
}

export function frameUrl(videoId: string, t: number, w = 480): string {
  return apiUrl(`/videos/${videoId}/frame?t=${t.toFixed(2)}&w=${w}`);
}
