import { AlertTriangle, Check, CircleSlash, Clock3, Send, Upload } from "lucide-react";

import type { DisplayStatus, Job } from "@/lib/types";

const LABELS: Record<DisplayStatus, string> = {
  importing: "Importing",
  analyzing: "Analyzing",
  needs_confirmation: "Needs confirmation",
  ready: "Ready",
  packaged: "Packaged",
  published: "Published",
  error: "Error",
};

/**
 * Status pill. Never colour alone: busy has the bar, done a check, warning a triangle,
 * error a slashed circle.
 */
export function StatusPill({
  status,
  job,
  analyzed,
  compact,
}: {
  status: DisplayStatus;
  job?: Job | null;
  analyzed?: boolean;
  compact?: boolean;
}) {
  const busy = status === "importing" || status === "analyzing";
  if (busy) {
    const pct = job && job.progress > 0 ? ` ${Math.round(job.progress * 100)}%` : "";
    const message = job?.message || (job?.status === "queued" ? "Queued" : LABELS[status]);
    return (
      <span
        role="status"
        className="relative flex max-w-[280px] items-center gap-1.5 overflow-hidden rounded-[14px] bg-surface px-3 py-1.5 text-fg2"
      >
        <Clock3 aria-hidden="true" size={12} strokeWidth={2.5} className="shrink-0 text-accentsoft" />
        <span className="truncate">
          {compact ? LABELS[status] : message}
          <span className="tnum text-fg3">{pct}</span>
        </span>
        <span aria-hidden="true" className="absolute bottom-0 left-0 h-[2px] w-full bg-line2">
          {job && job.progress > 0 && status === "importing" ? (
            <span className="block h-full bg-accent transition-[width] duration-300" style={{ width: `${Math.round(job.progress * 100)}%` }} />
          ) : (
            <span className="ink-busy-bar block h-full bg-accent" />
          )}
        </span>
      </span>
    );
  }
  if (status === "error") {
    return (
      <span role="status" className="flex items-center gap-1.5 rounded-[14px] border border-accent px-3 py-1.5 text-fg">
        <CircleSlash aria-hidden="true" size={12} strokeWidth={2.5} className="text-accentsoft" />
        Error
      </span>
    );
  }
  if (status === "needs_confirmation") {
    return (
      <span role="status" className="flex items-center gap-1.5 rounded-[14px] border border-warnline px-3 py-1.5 text-warn">
        <AlertTriangle aria-hidden="true" size={12} strokeWidth={2.5} />
        {LABELS[status]}
      </span>
    );
  }
  if (status === "published") {
    return (
      <span role="status" className="flex items-center gap-1.5 rounded-[14px] bg-okbg px-3 py-1.5 text-oktext">
        <Send aria-hidden="true" size={12} strokeWidth={2.5} />
        Published
      </span>
    );
  }
  if (!analyzed) {
    return (
      <span role="status" className="flex items-center gap-1.5 rounded-[14px] border border-line3 px-3 py-1.5 text-fg3">
        <Upload aria-hidden="true" size={12} strokeWidth={2.5} />
        Imported · not analyzed
      </span>
    );
  }
  return (
    <span role="status" className="flex items-center gap-1.5 rounded-[14px] bg-okbg px-3 py-1.5 text-oktext">
      <Check aria-hidden="true" size={12} strokeWidth={2.5} />
      {status === "packaged" ? "Packaged" : "Analyzed"}
    </span>
  );
}
