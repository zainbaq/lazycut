"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type {
  Aspect,
  Fact,
  FactUpdate,
  Job,
  LibraryItem,
  LibraryItemInput,
  NewVideo,
  PackageEdit,
  PackageList,
  PackageRegenerate,
  PublishBody,
  Research,
  ResearchEdit,
  ResearchRun,
  ThumbAdjust,
  ThumbGenerate,
  Thumbnail,
  ThumbnailState,
  ThumbSettings,
  ThumbSettingsInput,
  Video,
} from "./types";

export const keys = {
  configStatus: ["config-status"] as const,
  presets: ["presets"] as const,
  imports: ["imports"] as const,
  videos: ["videos"] as const,
  video: (id: string) => ["video", id] as const,
  timeline: (id: string) => ["timeline", id] as const,
  facts: (id: string) => ["facts", id] as const,
  frames: (id: string) => ["frames", id] as const,
  research: (id: string) => ["research", id] as const,
  packages: (id: string) => ["packages", id] as const,
  allPackages: ["packages"] as const,
  library: ["library"] as const,
  thumbnails: (id: string) => ["thumbnails", id] as const,
  thumbSettings: ["thumb-settings"] as const,
  thumbEstimate: (models: string[], aspects: string[]) => ["thumb-estimate", models.join(","), aspects.join(",")] as const,
};

export const useConfigStatus = () =>
  useQuery({ queryKey: keys.configStatus, queryFn: api.configStatus, staleTime: 30_000 });

export const usePresets = () => useQuery({ queryKey: keys.presets, queryFn: api.presets, staleTime: 60_000 });

export const useImports = () => useQuery({ queryKey: keys.imports, queryFn: api.imports });

export const useVideos = () => useQuery({ queryKey: keys.videos, queryFn: api.videos });

export const useVideo = (id: string) => useQuery({ queryKey: keys.video(id), queryFn: () => api.video(id) });

/** Timeline, frames and facts exist only once the import has finished. */
export const useTimeline = (id: string, ready: boolean) =>
  useQuery({ queryKey: keys.timeline(id), queryFn: () => api.timeline(id), enabled: ready });

export const useFrames = (id: string, ready: boolean) =>
  useQuery({ queryKey: keys.frames(id), queryFn: () => api.frames(id), enabled: ready, staleTime: Infinity });

export const useFacts = (id: string, ready: boolean) =>
  useQuery({ queryKey: keys.facts(id), queryFn: () => api.facts(id), enabled: ready });

export function useCreateVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewVideo) => api.createVideo(body),
    onSuccess: (video) => {
      qc.setQueryData(keys.video(video.id), video);
      void qc.invalidateQueries({ queryKey: keys.videos });
      void qc.invalidateQueries({ queryKey: keys.imports });
    },
  });
}

/** Jobs that set the video's display status. Research runs beside them and does not (API_SHAPES). */
const STATUS_JOBS = new Set(["import", "analysis"]);

/** Put a job into the cached video, replacing the previous job of the same kind. */
export function mergeJob(video: Video | undefined, job: Job): Video | undefined {
  if (!video) return video;
  const jobs = [...video.jobs.filter((j) => j.kind !== job.kind), job];
  let display_status = video.display_status;
  if (STATUS_JOBS.has(job.kind)) {
    if (job.status === "queued" || job.status === "running") {
      display_status = job.kind === "import" ? "importing" : "analyzing";
    } else if (job.status === "error") {
      display_status = "error";
    }
  }
  return { ...video, jobs, display_status };
}

/** The latest job of one kind, if any. */
export function jobOf(video: Video | undefined, kind: string): Job | undefined {
  return video?.jobs.find((j) => j.kind === kind);
}

export const isActive = (job: Job | undefined) => job?.status === "queued" || job?.status === "running";

export const useResearch = (id: string) => useQuery({ queryKey: keys.research(id), queryFn: () => api.research(id) });

/** Start research. Without `pasted_text` this is a paid Claude call with web search. */
export function useRunResearch(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ResearchRun) => api.runResearch(videoId, body),
    onSuccess: (job) => {
      qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job));
      qc.setQueryData<Research>(keys.research(videoId), (r) => (r ? { ...r, running: true } : r));
    },
  });
}

/** Set or restore one research field. The row updates at once and rolls back on error. */
export function useEditResearchField(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ResearchEdit) => api.editResearchField(videoId, body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: keys.research(videoId) });
      const before = qc.getQueryData<Research>(keys.research(videoId));
      qc.setQueryData<Research>(keys.research(videoId), (r) =>
        r
          ? {
              ...r,
              fields: r.fields.map((f) => {
                if (f.key !== body.key) return f;
                if ("restore" in body) {
                  return { ...f, override: null, overridden: false, no_credible_source: f.needs_credible_source && f.value !== null && !f.credible, effective_value: f.needs_credible_source && !f.credible ? null : f.value };
                }
                return { ...f, override: body.value, overridden: true, no_credible_source: false, effective_value: body.value };
              }),
            }
          : r,
      );
      return { before };
    },
    onError: (_err, _vars, context) => {
      if (context?.before) qc.setQueryData(keys.research(videoId), context.before);
    },
    onSuccess: (research) => {
      qc.setQueryData(keys.research(videoId), research);
      invalidatePackages(qc, videoId);
    },
  });
}

/** Put the user's spelling of the subject back (and keep it on later runs). */
export function useRevertSpelling(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.revertSpelling(videoId),
    onSuccess: (research) => {
      qc.setQueryData(keys.research(videoId), research);
      void qc.invalidateQueries({ queryKey: keys.video(videoId) });
      void qc.invalidateQueries({ queryKey: keys.videos });
      invalidatePackages(qc, videoId);
    },
  });
}

/** The package list for one video. Facts, events and research change whether it is stale, so it is
 * refetched whenever they change (see `invalidatePackages`). */
export const usePackages = (id: string, ready: boolean) =>
  useQuery({ queryKey: keys.packages(id), queryFn: () => api.packages(id), enabled: ready });

/** Start writing the package: a paid Claude call. */
export function useGeneratePackage(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.generatePackage(videoId),
    onSuccess: (job) => {
      qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job));
      qc.setQueryData<PackageList>(keys.packages(videoId), (p) => (p ? { ...p, running: true } : p));
    },
  });
}

/** Regenerate one field, or all of them: a paid Claude call. */
export function useRegeneratePackage(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: PackageRegenerate }) => api.regeneratePackage(id, body),
    onSuccess: (job) => {
      qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job));
      qc.setQueryData<PackageList>(keys.packages(videoId), (p) => (p ? { ...p, running: true } : p));
    },
  });
}

/** Edit a field or dismiss a warning; the server re-runs the rules and returns the package. */
export function useEditPackage(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: PackageEdit }) => api.editPackage(id, body),
    onSuccess: (pkg) => {
      qc.setQueryData<PackageList>(keys.packages(videoId), (p) =>
        p ? { ...p, packages: p.packages.map((x) => (x.id === pkg.id ? pkg : x)) } : p,
      );
    },
  });
}

/** Facts, events and research feed the package's stale check (BUILD_SPEC 4). */
export function invalidatePackages(qc: ReturnType<typeof useQueryClient>, videoId: string) {
  void qc.invalidateQueries({ queryKey: keys.packages(videoId) });
}

export function useAnalyze(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (discard: boolean) => api.analyze(videoId, discard),
    onSuccess: (job) => qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job)),
  });
}

export function useRetryJob(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.retryJob(jobId),
    onSuccess: (job) => qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job)),
  });
}

export function useUpdateVideo(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof api.updateVideo>[1]) => api.updateVideo(videoId, body),
    onSuccess: (video) => {
      qc.setQueryData(keys.video(videoId), video);
      void qc.invalidateQueries({ queryKey: keys.timeline(videoId) });
      void qc.invalidateQueries({ queryKey: keys.facts(videoId) });
      void qc.invalidateQueries({ queryKey: keys.videos });
      invalidatePackages(qc, videoId);
    },
  });
}

/** Set a fact's value and/or confirm it. The switch flips at once and rolls back on error. */
export function useUpdateFact(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: FactUpdate }) => api.updateFact(id, body),
    onMutate: async ({ id, body }) => {
      await qc.cancelQueries({ queryKey: keys.facts(videoId) });
      const before = qc.getQueryData<Fact[]>(keys.facts(videoId));
      qc.setQueryData<Fact[]>(keys.facts(videoId), (facts) =>
        facts?.map((f) => {
          if (f.id !== id) return f;
          const next = { ...f };
          if (body.value !== undefined) {
            next.value = body.value;
            next.effective_value = body.value ?? f.proposed_value;
          }
          if (body.confirmed !== undefined) next.confirmed = body.confirmed;
          if (body.confirmed) next.out_of_date = false;
          return next;
        }),
      );
      return { before };
    },
    onError: (_err, _vars, context) => {
      if (context?.before) qc.setQueryData(keys.facts(videoId), context.before);
    },
    onSuccess: (fact) => {
      qc.setQueryData<Fact[]>(keys.facts(videoId), (facts) => facts?.map((f) => (f.id === fact.id ? { ...f, ...fact } : f)));
      void qc.invalidateQueries({ queryKey: keys.video(videoId) });
      void qc.invalidateQueries({ queryKey: keys.videos });
      invalidatePackages(qc, videoId); // missing facts and the stale check
    },
  });
}

// ---- past uploads and publishing ----------------------------------------------------

export const useLibrary = () => useQuery({ queryKey: keys.library, queryFn: api.library });

/** Past uploads feed every package's end-screen target and repeat check, which the server
 * refreshes on the next package GET, so all package lists are refetched. */
function afterLibraryChange(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: keys.library });
  void qc.invalidateQueries({ queryKey: keys.allPackages });
}

export function useAddLibraryItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LibraryItemInput) => api.addLibraryItem(body),
    onSuccess: (item) => {
      qc.setQueryData<LibraryItem[]>(keys.library, (list) => (list ? [item, ...list] : list));
      afterLibraryChange(qc);
    },
  });
}

export function useEditLibraryItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: LibraryItemInput }) => api.editLibraryItem(id, body),
    onSuccess: (item) => {
      qc.setQueryData<LibraryItem[]>(keys.library, (list) => list?.map((x) => (x.id === item.id ? item : x)));
      afterLibraryChange(qc);
    },
  });
}

export function useDeleteLibraryItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteLibraryItem(id),
    onSuccess: (_, id) => {
      qc.setQueryData<LibraryItem[]>(keys.library, (list) => list?.filter((x) => x.id !== id));
      afterLibraryChange(qc);
    },
  });
}

function afterPublishChange(qc: ReturnType<typeof useQueryClient>, video: Video) {
  qc.setQueryData<Video>(keys.video(video.id), (v) => (v ? { ...v, ...video } : video));
  void qc.invalidateQueries({ queryKey: keys.videos });
  afterLibraryChange(qc);
}

/** Mark as published: sets the link and date and writes the past-upload entry (free, no model call). */
export function usePublish(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PublishBody) => api.publish(videoId, body),
    onSuccess: (res) => {
      const video: Video & { library_item?: unknown } = { ...res };
      delete video.library_item;
      afterPublishChange(qc, video);
    },
  });
}

/** Undo "Mark as published": clears the link and removes the past-upload entry it created. */
export function useUnpublish(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.unpublish(videoId),
    onSuccess: (video) => afterPublishChange(qc, video),
  });
}

export function useDeleteVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteVideo(id),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: keys.video(id) });
      void qc.invalidateQueries({ queryKey: keys.videos });
      void qc.invalidateQueries({ queryKey: keys.imports });
    },
  });
}

// ---- thumbnails (7.13) --------------------------------------------------------------

/** Thumbnails, frame finds, word choices and settings for one video. Polls while work runs, as
 * a fallback for the live stream. */
export const useThumbnails = (id: string) =>
  useQuery({
    queryKey: keys.thumbnails(id),
    queryFn: () => api.thumbnails(id),
    refetchInterval: (q) => {
      const d = q.state.data;
      const busy = d && (d.running || d.finding_frames || d.thumbnails.some((t) => t.status === "queued" || t.status === "running"));
      return busy ? 4000 : false;
    },
  });

/** Find frames: free scoring in code, then a small paid Claude call ranks the best few. */
export function useFindFrames(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.findFrames(videoId),
    onSuccess: (job) => {
      qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job));
      qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) => (s ? { ...s, finding_frames: true } : s));
    },
  });
}

export function useUploadThumbSource(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.uploadThumbSource(videoId, file),
    onSuccess: (up) =>
      qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) =>
        s ? { ...s, uploads: [up, ...s.uploads.filter((u) => u.id !== up.id)] } : s,
      ),
  });
}

/** Generate: each image is a paid Higgsfield call. */
export function useGenerateThumbnails(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ThumbGenerate) => api.generateThumbnails(videoId, body),
    onSuccess: (res) => {
      qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, res.job));
      qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) =>
        s ? { ...s, running: true, thumbnails: [...res.thumbnails, ...s.thumbnails] } : s,
      );
    },
  });
}

function putThumb(qc: ReturnType<typeof useQueryClient>, videoId: string, row: Thumbnail) {
  qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) => {
    if (!s) return s;
    const known = s.thumbnails.some((t) => t.id === row.id);
    const rows = known ? s.thumbnails.map((t) => (t.id === row.id ? row : t)) : [row, ...s.thumbnails];
    // Choosing is one per aspect; the server unchose the others.
    return { ...s, thumbnails: row.chosen ? rows.map((t) => (t.id !== row.id && t.aspect === row.aspect ? { ...t, chosen: false } : t)) : rows };
  });
}

/** Choose a thumbnail, or redraw its word, corner or font: free, no model call. */
export function useAdjustThumbnail(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ThumbAdjust }) => api.adjustThumbnail(id, body),
    onSuccess: (row) => putThumb(qc, videoId, row),
  });
}

/** Review again: a small paid Claude call. */
export function useReviewThumbnail(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.reviewThumbnail(id),
    onSuccess: (job) => {
      qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job));
      qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) => (s ? { ...s, running: true } : s));
    },
  });
}

export function useDeleteThumbnail(videoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteThumbnail(id),
    onSuccess: (_, id) =>
      qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) =>
        s ? { ...s, thumbnails: s.thumbnails.filter((t) => t.id !== id) } : s,
      ),
  });
}

/** Higgsfield's price quote for this set of models and aspects (free). Off without a key. */
export const useThumbEstimate = (models: string[], aspects: Aspect[], enabled: boolean) =>
  useQuery({
    queryKey: keys.thumbEstimate(models, aspects),
    queryFn: () => api.estimateThumbnails({ models, aspects }),
    enabled: enabled && models.length > 0 && aspects.length > 0,
    staleTime: 10 * 60_000,
    retry: false,
  });

export const useThumbSettings = () => useQuery({ queryKey: keys.thumbSettings, queryFn: api.thumbSettings });

function afterThumbSettings(qc: ReturnType<typeof useQueryClient>, s: ThumbSettings) {
  qc.setQueryData(keys.thumbSettings, s);
  void qc.invalidateQueries({ queryKey: ["thumbnails"] });
  void qc.invalidateQueries({ queryKey: ["thumb-estimate"] });
}

export function useSaveThumbSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ThumbSettingsInput) => api.saveThumbSettings(body),
    onSuccess: (s) => afterThumbSettings(qc, s),
  });
}

export function useResetThumbSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetThumbSettings(),
    onSuccess: (s) => afterThumbSettings(qc, s),
  });
}
