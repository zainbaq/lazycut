"use client";

import { AlertTriangle, Scissors } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo } from "react";

import { ConfigErrorCard, ErrorCard, SetupCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { ApiError } from "@/lib/api";
import { useConfigStatus, useFacts, useFrames, usePresets, useRetryJob, useTimeline, useVideo } from "@/lib/queries";
import { type EventEdits, useEventEdits } from "@/lib/edits";
import { useVideoUpdates } from "@/lib/sse";
import { useWorkspace } from "@/lib/store";
import type { EventType, Job, TimelineEvent } from "@/lib/types";

import { hide, moveToPlayhead, reviewHide, reviewStep, reviewVerify, verify } from "./actions";
import { RenameDialog, UndoToast } from "./EventActions";
import { Header } from "./Header";
import { stepEvent } from "./nav";
import { PackagePanel } from "./PackagePanel";
import { Preview } from "./Preview";
import { Timeline } from "./Timeline";

const BLOCKING = 'input, textarea, select, [contenteditable="true"], [role="slider"], [role="menu"], [role="menuitem"], [role="dialog"], [role="listbox"]';

/** Keyboard shortcuts (9.6) for what exists in this step. Inactive in inputs, sliders, menus and dialogs. */
function useShortcuts(events: TimelineEvent[], fps: number, edits: EventEdits) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest(BLOCKING)) return;
      if (document.querySelector('[role="dialog"][data-state="open"], [role="menu"][data-state="open"]')) return;
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        void edits.undo();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const ws = useWorkspace.getState();
      const el = ws.videoEl;
      if (!el) return;
      const frame = 1 / (fps || 30);
      const review = ws.review;
      const chipId = (target?.closest("[data-event-id]") as HTMLElement | null)?.dataset.eventId;
      switch (e.key) {
        case "Escape":
          if (review) ws.stopReview();
          else if (ws.selectedEventId) ws.select(null);
          else return;
          break;
        case "Enter": {
          // A focused button or link keeps Enter for itself; a focused chip means "verify this one".
          if (target?.closest("button, a") && !chipId) return;
          if (review) {
            reviewVerify(edits);
            break;
          }
          const id = chipId ?? ws.selectedEventId;
          if (!id) return;
          ws.select(id);
          verify(edits, id);
          break;
        }
        case "Backspace":
        case "Delete": {
          if (review) {
            reviewHide(edits);
            break;
          }
          const id = chipId ?? ws.selectedEventId;
          if (!id) return;
          hide(edits, id);
          break;
        }
        case "e":
        case "E": {
          const id = review ? review.ids[review.index] : ws.selectedEventId;
          if (!id) return;
          moveToPlayhead(edits, id);
          break;
        }
        case " ":
          if (target?.closest("button, a")) return; // the focused control handles Space itself
          ws.togglePlay();
          break;
        case "k":
        case "K":
          ws.pause();
          break;
        case "j":
        case "J":
          ws.seek(el.currentTime - 0.5, { animate: false });
          break;
        case "l":
        case "L":
          ws.seek(el.currentTime + 0.5, { animate: false });
          break;
        case ",":
          ws.pause();
          ws.seek(el.currentTime - frame, { animate: false });
          break;
        case ".":
          ws.pause();
          ws.seek(el.currentTime + frame, { animate: false });
          break;
        case "ArrowLeft":
        case "ArrowRight": {
          if (review) {
            reviewStep(e.key === "ArrowRight" ? 1 : -1);
            break;
          }
          const next = stepEvent(events, ws.playhead, e.key === "ArrowRight" ? 1 : -1);
          if (!next) return;
          ws.pause();
          ws.select(next.id);
          ws.seek(next.t_start);
          break;
        }
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [events, fps, edits]);
}

function ClipsStrip() {
  return (
    <div
      aria-label="Clips (arrive in Phase 2)"
      className="hidden w-11 shrink-0 flex-col items-center gap-3 border-r border-line py-4 text-fg4 min-[720px]:flex"
      title="Clips arrive in Phase 2"
    >
      <Scissors aria-hidden="true" size={16} />
      <span className="text-[11px] [writing-mode:vertical-rl]">Clips</span>
    </div>
  );
}

function jobTitle(job: Job): string {
  if (job.kind === "import") return "Import failed";
  if (job.kind === "analysis") return "Analysis failed";
  if (job.kind === "research") return "Research failed";
  if (job.kind === "package") return "Writing the package failed";
  return `${job.kind} failed`;
}

export function Workspace({ id }: { id: string }) {
  const video = useVideo(id);
  const presets = usePresets();
  const status = useConfigStatus();
  const ready = video.data?.status === "ready";
  const timeline = useTimeline(id, ready);
  const frames = useFrames(id, ready);
  const facts = useFacts(id, ready);
  const retry = useRetryJob(id);
  useVideoUpdates(id, video.isSuccess);

  const reset = useWorkspace((s) => s.reset);
  const filterReady = useWorkspace((s) => s.filterReady);
  const initFilter = useWorkspace((s) => s.initFilter);
  const hiddenTypes = useWorkspace((s) => s.hiddenTypes);
  const showHidden = useWorkspace((s) => s.showHidden);
  const edits = useEventEdits(id);

  useEffect(() => {
    reset(id);
  }, [id, reset]);

  useEffect(() => {
    if (!timeline.data || filterReady) return;
    initFilter(Object.fromEntries(timeline.data.event_types.map((t) => [t.id, !t.show])));
  }, [timeline.data, filterReady, initFilter]);

  const types = useMemo(() => new Map<string, EventType>((timeline.data?.event_types ?? []).map((t) => [t.id, t])), [timeline.data?.event_types]);
  const visible = useMemo(
    () => (timeline.data?.events ?? []).filter((e) => !e.hidden && !hiddenTypes[e.type]).sort((a, b) => a.t_start - b.t_start),
    [timeline.data?.events, hiddenTypes],
  );
  const shown = useMemo(
    () => (showHidden ? (timeline.data?.events ?? []).filter((e) => !hiddenTypes[e.type]) : visible),
    [showHidden, timeline.data?.events, hiddenTypes, visible],
  );

  useShortcuts(visible, timeline.data?.fps ?? video.data?.fps ?? 30, edits);

  if (video.error) {
    const missing = video.error instanceof ApiError && video.error.status === 404;
    return (
      <div className="flex min-h-screen">
        <Rail section="workspace" />
        <main className="flex max-w-xl flex-1 flex-col gap-3 p-6">
          <ErrorCard
            title={missing ? "Video not found" : "Could not load the video"}
            message={missing ? "It may have been deleted." : video.error.message}
            onRetry={missing ? undefined : () => void video.refetch()}
          />
          <Link href="/" className="text-accentsoft underline">
            Back to the library
          </Link>
        </main>
      </div>
    );
  }

  if (!video.data) {
    return (
      <div className="flex min-h-screen">
        <Rail section="workspace" videoId={id} />
        <main className="flex flex-1 flex-col gap-3 p-4" aria-busy="true">
          <span className="ink-skeleton block h-14 rounded-[12px]" />
          <span className="ink-skeleton block h-[300px] rounded-[12px]" />
          <span className="ink-skeleton block h-[180px] rounded-[12px]" />
        </main>
      </div>
    );
  }

  const v = video.data;
  const failed = v.jobs.filter((j) => j.status === "error");
  const analysisJob = v.jobs.find((j) => j.kind === "analysis");
  const analyzing = analysisJob?.status === "running" || analysisJob?.status === "queued";
  const geminiReady = status.data ? status.data.keys.gemini : true;
  const preset = (presets.data ?? []).find((p) => p.id === v.preset_id);

  let emptyNote: string | null = null;
  if (analyzing) emptyNote = "Watching the video…";
  else if (!v.analysis) emptyNote = geminiReady ? "Not analyzed yet." : "Not analyzed: no Gemini key.";
  else if (!visible.length) emptyNote = (timeline.data?.events.length ?? 0) ? "All event types are filtered out." : "No events found.";

  return (
    <div className="flex min-h-screen">
      <Rail section="workspace" videoId={id} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          video={v}
          presets={presets.data ?? []}
          timeline={timeline.data}
          facts={facts.data}
          geminiReady={geminiReady}
        />
        <div className="flex flex-1 flex-col min-[1100px]:flex-row">
          <main className="flex min-w-0 flex-1 flex-col">
            {(failed.length || (status.data && (!status.data.keys.gemini || status.data.errors.length)) || v.is_hdr) ? (
              <div className="flex flex-col gap-2.5 px-4 pt-4">
                {failed.map((job) => (
                  <ErrorCard
                    key={job.id}
                    title={jobTitle(job)}
                    message={job.error || job.message || "The job stopped without a message."}
                    onRetry={() => retry.mutate(job.id)}
                    retrying={retry.isPending}
                  />
                ))}
                {retry.error ? <ErrorCard title="Retry did not start" message={retry.error.message} /> : null}
                {status.data && !status.data.keys.gemini ? <SetupCard /> : null}
                {status.data ? <ConfigErrorCard errors={status.data.errors} /> : null}
                {v.is_hdr ? (
                  <div className="flex items-start gap-2 rounded-[12px] border border-warnline bg-surface p-3 text-fg2">
                    <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-warn" />
                    This source is HDR. LazyCut does not tone-map, so exports may look washed out.
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="flex border-b border-line">
              <ClipsStrip />
              {ready ? (
                <Preview video={v} events={visible} types={types} />
              ) : (
                <section aria-label="Preview" className="flex flex-1 flex-col gap-2.5 p-4">
                  <span className="truncate text-[13px] font-semibold">{v.title}</span>
                  <div className="ink-skeleton flex aspect-video max-h-[46vh] w-full items-center justify-center rounded-[12px] text-fg3">
                    {v.status === "error" ? "The import did not finish." : "Copying and preparing the video…"}
                  </div>
                </section>
              )}
            </div>

            {ready && timeline.data ? (
              <Timeline
                data={timeline.data}
                frames={frames.data}
                types={types}
                visible={visible}
                shown={shown}
                emptyNote={emptyNote}
                edits={edits}
              />
            ) : timeline.error ? (
              <div className="p-4">
                <ErrorCard title="Could not load the timeline" message={timeline.error.message} onRetry={() => void timeline.refetch()} />
              </div>
            ) : (
              <section aria-label="Timeline" className="flex flex-col gap-2.5 p-4">
                <h2 className="font-head text-[16px]">Timeline</h2>
                <div className="ink-skeleton flex h-[170px] items-center justify-center rounded-[12px] text-fg3">
                  {ready ? "Loading the timeline…" : "The timeline appears when the proxy and intensity are ready."}
                </div>
              </section>
            )}
          </main>
          <PackagePanel
            video={v}
            preset={preset}
            facts={facts.data}
            factsLoading={ready && facts.isLoading}
            factsError={facts.error?.message ?? null}
            analyzed={!!v.analysis}
          />
        </div>
      </div>
      <RenameDialog edits={edits} types={types} />
      <UndoToast edits={edits} />
    </div>
  );
}
