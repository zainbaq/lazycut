"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { Fact, FactUpdate, Job, NewVideo, Research, ResearchEdit, ResearchRun, Video } from "./types";

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
    onSuccess: (research) => qc.setQueryData(keys.research(videoId), research),
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
    },
  });
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
    },
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
