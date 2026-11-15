"use client";

import { AlertTriangle, ChevronRight, Clock3, Search } from "lucide-react";
import Link from "next/link";

import { isActive, jobOf, useResearch, useVideo } from "@/lib/queries";

/** A small card in the workspace that says how far research got and opens the research page. */
export function ResearchLink({ videoId }: { videoId: string }) {
  const research = useResearch(videoId);
  const video = useVideo(videoId);
  const job = jobOf(video.data, "research");
  const r = research.data;
  const running = !!r?.running || isActive(job);
  const unused = r ? r.fields.filter((f) => f.no_credible_source).length : 0;

  let status: string;
  if (research.isLoading) status = "Loading…";
  else if (research.error) status = "Could not load";
  else if (running) status = (isActive(job) && job?.message) || "Researching…";
  else if (job?.status === "error") status = "Research failed";
  else if (!r || r.method === "none") status = "Not researched";
  else status = `${r.fields.filter((f) => f.value !== null).length} of ${r.fields.length} found`;

  return (
    <Link
      href={`/v/${videoId}/research`}
      className="ink-btn flex min-h-11 items-center gap-2 rounded-[12px] bg-surface px-3 py-2 text-fg"
      aria-label={`Research: ${status}${unused ? `, ${unused} without a credible source` : ""}`}
    >
      {running ? (
        <Clock3 aria-hidden="true" size={14} className="shrink-0 text-accentsoft" />
      ) : (
        <Search aria-hidden="true" size={14} className="shrink-0 text-accentsoft" />
      )}
      <span className="text-[13px] font-semibold">Research</span>
      <span className="min-w-0 flex-1 truncate text-right text-[11px] text-fg3">{status}</span>
      {unused && !running ? (
        <span className="flex shrink-0 items-center gap-0.5 text-[11px] text-warn" title={`${unused} without a credible source`}>
          <AlertTriangle aria-hidden="true" size={11} />
          {unused}
        </span>
      ) : null}
      <ChevronRight aria-hidden="true" size={14} className="shrink-0 text-fg3" />
    </Link>
  );
}
