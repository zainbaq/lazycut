"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, Loader2, RotateCcw, X } from "lucide-react";
import { useMemo, useState } from "react";

import { plural } from "@/lib/format";
import { replaceable } from "@/lib/sse";
import type { Fact, Timeline } from "@/lib/types";

export interface ReanalyzeCounts {
  replace: { events: number; segments: number; facts: number };
  keep: { events: number; facts: number };
}

/** What a re-analysis replaces and keeps (7.12), from the data already on screen. */
export function countReanalysis(timeline: Timeline | undefined, facts: Fact[] | undefined, discard: boolean): ReanalyzeCounts {
  const events = timeline?.events ?? [];
  const untouched = events.filter(replaceable).length;
  const confirmed = (facts ?? []).filter((f) => f.confirmed).length;
  const segments = (timeline?.segments ?? []).length;
  if (discard) {
    return {
      replace: { events: events.length, segments, facts: (facts ?? []).length },
      keep: { events: 0, facts: 0 },
    };
  }
  return {
    replace: { events: untouched, segments, facts: (facts ?? []).length - confirmed },
    keep: { events: events.length - untouched, facts: confirmed },
  };
}

/**
 * The warning dialog that always comes before a re-analysis (D21, 7.12). `title` and
 * `confirmLabel` change when the trigger is a preset switch.
 */
export function ReanalyzeDialog({
  open,
  onOpenChange,
  timeline,
  facts,
  title = "Re-analyze this video?",
  intro,
  confirmLabel = "Re-analyze",
  canAnalyze,
  onConfirm,
  pending,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  timeline: Timeline | undefined;
  facts: Fact[] | undefined;
  title?: string;
  intro?: React.ReactNode;
  confirmLabel?: string;
  canAnalyze: boolean;
  onConfirm: (discard: boolean) => void;
  pending: boolean;
  error: string | null;
}) {
  const [discard, setDiscard] = useState(false);
  const counts = useMemo(() => countReanalysis(timeline, facts, discard), [timeline, facts, discard]);

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        if (!o) setDiscard(false);
        onOpenChange(o);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex w-[min(440px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4 text-[12px] text-fg shadow-none">
          <div className="flex items-start justify-between gap-2">
            <Dialog.Title className="flex items-center gap-2 font-head text-[16px]">
              <AlertTriangle aria-hidden="true" size={16} className="text-warn" />
              {title}
            </Dialog.Title>
            <Dialog.Close className="ink-btn -m-2 flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3" aria-label="Close">
              <X aria-hidden="true" size={16} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="text-fg2">
            {intro ?? "Gemini watches the video again and the timeline is rebuilt."}
          </Dialog.Description>

          {canAnalyze ? (
            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1 rounded-[10px] bg-surface p-3">
                <span className="text-[11px] font-semibold text-fg3">Replaced</span>
                <span className="tnum">{plural(counts.replace.events, "model event")}</span>
                <span className="tnum">{plural(counts.replace.segments, "section")}</span>
                <span className="tnum">{plural(counts.replace.facts, "unconfirmed fact")}</span>
              </div>
              <div className="flex flex-col gap-1 rounded-[10px] bg-surface p-3">
                <span className="text-[11px] font-semibold text-fg3">Kept</span>
                <span className="tnum">{plural(counts.keep.events, "event")} you added, edited, verified or hid</span>
                <span className="tnum">{plural(counts.keep.facts, "confirmed fact")}</span>
              </div>
            </div>
          ) : null}

          {canAnalyze ? (
            <label className="flex min-h-11 items-center gap-2 text-fg2">
              <input
                type="checkbox"
                checked={discard}
                onChange={(e) => setDiscard(e.target.checked)}
                className="h-4 w-4 accent-[var(--accent-fill)]"
              />
              Also discard my edits and confirmations
            </label>
          ) : null}

          {error ? (
            <span role="alert" className="rounded-[10px] border border-accent bg-surface p-2.5 text-fg">
              {error}
            </span>
          ) : null}

          <div className="flex justify-end gap-2">
            <Dialog.Close className="ink-btn min-h-11 rounded-[10px] border border-line3 px-3.5 text-[12px]">Cancel</Dialog.Close>
            <button
              type="button"
              disabled={pending}
              onClick={() => onConfirm(discard)}
              className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:opacity-60"
            >
              {pending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <RotateCcw aria-hidden="true" size={14} />}
              {confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
