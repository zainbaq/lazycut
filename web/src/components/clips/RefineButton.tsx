"use client";

import { Loader2, ScanSearch } from "lucide-react";

import { isActive, jobOf, useRefineClip } from "@/lib/queries";
import type { Clip, Video } from "@/lib/types";

/**
 * "Refine edges" (7.3, 7.5): the video model looks closely at the clip's first and closing event
 * and the edges are placed around what it sees. Reset brings the original range back.
 */
export function RefineButton({ video, clip, canRefine }: { video: Video; clip: Clip; canRefine: boolean }) {
  const refine = useRefineClip(video.id);
  const job = jobOf(video, "clip_refine");
  const busy = isActive(job) || refine.isPending;
  const empty = !Object.keys(clip.event_counts).length;
  let title = "Look closely at the first and the closing event of this clip and tighten its edges (two small Gemini calls)";
  if (!canRefine) title = "Needs GEMINI_API_KEY in .env";
  else if (empty) title = "There are no events in this clip to refine its edges against";
  else if (refine.error) title = refine.error.message;
  else if (job?.status === "error") title = `The last refine stopped: ${job.error ?? "no message"}`;
  else if (job?.status === "done" && job.message) title = `${job.message}. Click to refine again`;
  return (
    <button
      type="button"
      disabled={busy || !canRefine || empty}
      onClick={() => refine.mutate(clip.id)}
      title={title}
      className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px] text-fg disabled:opacity-50"
    >
      {busy ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <ScanSearch aria-hidden="true" size={14} />}
      {busy ? (job?.message ?? "Refining…") : "Refine edges"}
    </button>
  );
}
