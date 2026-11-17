"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiUrl } from "./api";
import { keys, mergeJob } from "./queries";
import type { Clip, ClipList, FrameFinds, Job, PackageList, Research, Thumbnail, ThumbnailState, Timeline, TimelineEvent, Video } from "./types";

/** Model events the server replaces on re-analysis (7.12), unless the user chose to discard everything. */
export function replaceable(e: TimelineEvent): boolean {
  return (
    e.source === "model" &&
    !e.verified &&
    !e.hidden &&
    !e.edited &&
    (e.t_model_start == null || Math.abs(e.t_start - e.t_model_start) < 1e-6)
  );
}

/**
 * Live updates for one video (`GET /videos/{id}/updates`).
 *
 * The stream carries no history, so the caller loads current state first and passes
 * `ready` once it has. Job events update the pill; a finished job refetches what it changed;
 * `analysis.event` adds a chip as it arrives.
 */
export function useVideoUpdates(videoId: string, ready: boolean) {
  const qc = useQueryClient();
  const batchOpen = useRef(false);
  const clipBatchOpen = useRef(false);

  useEffect(() => {
    if (!ready) return;
    const source = new EventSource(apiUrl(`/videos/${videoId}/updates`));
    let hadError = false;

    const onJob = (e: MessageEvent<string>) => {
      const job = JSON.parse(e.data) as Job;
      qc.setQueryData<Video>(keys.video(videoId), (v) => mergeJob(v, job));
      if (job.kind === "analysis" && (job.status === "queued" || job.status === "running")) {
        batchOpen.current = false;
      }
      if (job.kind === "clip_find" && (job.status === "queued" || job.status === "running")) {
        clipBatchOpen.current = false;
        qc.setQueryData<ClipList>(keys.clips(videoId), (c) => (c && !c.finding ? { ...c, finding: true } : c));
      }
      if (job.kind === "research" && (job.status === "queued" || job.status === "running")) {
        qc.setQueryData<Research>(keys.research(videoId), (r) => (r && !r.running ? { ...r, running: true } : r));
      }
      if (job.kind === "clip_package" && (job.status === "queued" || job.status === "running")) {
        qc.setQueryData<PackageList>(keys.packages(videoId), (p) => (p && !p.running_short ? { ...p, running_short: true } : p));
      }
      if (job.kind === "package" && (job.status === "queued" || job.status === "running")) {
        qc.setQueryData<PackageList>(keys.packages(videoId), (p) => (p && !p.running ? { ...p, running: true } : p));
      }
      if ((job.kind === "thumbnail" || job.kind === "thumbnail_frames") && (job.status === "queued" || job.status === "running")) {
        const flag = job.kind === "thumbnail" ? "running" : "finding_frames";
        qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) => (s && !s[flag] ? { ...s, [flag]: true } : s));
      }
    };
    const onFinished = (e: MessageEvent<string>) => {
      onJob(e);
      const job = JSON.parse(e.data) as Job;
      void qc.invalidateQueries({ queryKey: keys.video(videoId) });
      void qc.invalidateQueries({ queryKey: keys.timeline(videoId) });
      void qc.invalidateQueries({ queryKey: keys.facts(videoId) });
      void qc.invalidateQueries({ queryKey: keys.videos });
      if (job.kind === "import") void qc.invalidateQueries({ queryKey: keys.frames(videoId) });
      // Research results, and the subject if its spelling was corrected (7.7). Import may queue research.
      if (job.kind === "research" || job.kind === "import") void qc.invalidateQueries({ queryKey: keys.research(videoId) });
      // A new package, or new facts, events or research that make the current one stale.
      void qc.invalidateQueries({ queryKey: keys.packages(videoId) });
      // Clips are measured against the events, and clip jobs add or change them.
      if (job.kind === "analysis" || job.kind === "import" || job.kind.startsWith("clip")) {
        void qc.invalidateQueries({ queryKey: keys.clips(videoId) });
      }
      if (job.kind === "thumbnail"|| job.kind === "thumbnail_frames" || job.kind === "package") {
        void qc.invalidateQueries({ queryKey: keys.thumbnails(videoId) });
      }
    };
    const onClip = (e: MessageEvent<string>) => {
      const clip = JSON.parse(e.data) as Clip;
      qc.setQueryData<ClipList>(keys.clips(videoId), (list) => {
        if (!list) return list;
        let clips = list.clips;
        if (!clipBatchOpen.current) {
          // The server has just replaced the proposals nobody touched; drop ours so they do not linger.
          clipBatchOpen.current = true;
          clips = clips.filter((c) => !(c.status === "candidate" && c.source === "finder"));
        }
        clips = [...clips.filter((c) => c.id !== clip.id), clip].sort((a, b) => a.t_start - b.t_start);
        return { ...list, clips };
      });
    };
    const onThumb = (e: MessageEvent<string>) => {
      const row = JSON.parse(e.data) as Thumbnail;
      qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) => {
        if (!s) return s;
        const known = s.thumbnails.some((t) => t.id === row.id);
        return { ...s, thumbnails: known ? s.thumbnails.map((t) => (t.id === row.id ? row : t)) : [row, ...s.thumbnails] };
      });
    };
    const onFrames = (e: MessageEvent<string>) => {
      const frames = JSON.parse(e.data) as FrameFinds;
      qc.setQueryData<ThumbnailState>(keys.thumbnails(videoId), (s) => (s ? { ...s, frames } : s));
    };
    const onEvent = (e: MessageEvent<string>) => {
      const event = JSON.parse(e.data) as TimelineEvent;
      qc.setQueryData<Timeline>(keys.timeline(videoId), (tl) => {
        if (!tl) return tl;
        let events = tl.events;
        if (!batchOpen.current) {
          // The server has just replaced the untouched model events; drop ours so they do not linger.
          batchOpen.current = true;
          events = events.filter((x) => !replaceable(x));
        }
        events = [...events.filter((x) => x.id !== event.id), event].sort((a, b) => a.t_start - b.t_start);
        return { ...tl, events };
      });
    };

    source.addEventListener("job.progress", onJob as EventListener);
    source.addEventListener("job.done", onFinished as EventListener);
    source.addEventListener("job.error", onFinished as EventListener);
    source.addEventListener("analysis.event", onEvent as EventListener);
    source.addEventListener("clip.candidate", onClip as EventListener);
    source.addEventListener("thumbnail.updated", onThumb as EventListener);
    source.addEventListener("thumbnail.frames", onFrames as EventListener);
    source.onerror = () => {
      hadError = true;
    };
    source.onopen = () => {
      // After a dropped connection, catch up on anything missed while it was down.
      if (hadError) {
        hadError = false;
        void qc.invalidateQueries({ queryKey: keys.video(videoId) });
        void qc.invalidateQueries({ queryKey: keys.timeline(videoId) });
        void qc.invalidateQueries({ queryKey: keys.research(videoId) });
        void qc.invalidateQueries({ queryKey: keys.packages(videoId) });
        void qc.invalidateQueries({ queryKey: keys.thumbnails(videoId) });
        void qc.invalidateQueries({ queryKey: keys.clips(videoId) });
      }
    };
    return () => source.close();
  }, [videoId, ready, qc]);
}
