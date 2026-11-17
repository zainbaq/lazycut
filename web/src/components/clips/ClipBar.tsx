"use client";

import { Check, ChevronLeft, ChevronRight, Copy, RotateCcw, Scissors } from "lucide-react";
import { useState } from "react";

import { clock } from "@/lib/format";
import { COPY_RESET_MS } from "@/lib/motion";
import { useWorkspace } from "@/lib/store";
import type { Clip } from "@/lib/types";

import { type Edge, length, lengthText, SNAP_S, timestamps } from "./trim";
import type { ClipActions } from "./useClipActions";

const btn = "ink-btn flex min-h-11 items-center gap-1 rounded-[10px] border border-line3 px-2.5 text-[12px] text-fg disabled:opacity-40";

/** Action bar under the timeline (9.4 region 6): reset, the four nudges and the clip's timestamps. */
export function ClipBar({ clip, duration, actions, children }: { clip: Clip; duration: number; actions: ClipActions; children?: React.ReactNode }) {
  const draft = useWorkspace((s) => s.clipDraft);
  const [copied, setCopied] = useState(false);
  const range = draft && draft.id === clip.id ? draft : clip;

  const nudge = (edge: Edge, dir: -1 | 1) => {
    const label = `${edge === "in" ? "In" : "Out"} ${dir < 0 ? "earlier" : "later"}`;
    const stuck =
      edge === "in"
        ? dir < 0 ? range.t_start <= 0 : length(range) <= 3
        : dir < 0 ? length(range) <= 3 : range.t_end >= duration - 1e-3;
    return (
      <button key={label} type="button" disabled={stuck} onClick={() => actions.nudge(edge, dir * SNAP_S)} title={`${label} by ${SNAP_S} s`} className={btn}>
        {dir < 0 ? <ChevronLeft aria-hidden="true" size={14} /> : null}
        {label}
        {dir > 0 ? <ChevronRight aria-hidden="true" size={14} /> : null}
      </button>
    );
  };

  return (
    <div aria-label="Clip actions" role="group" className="flex flex-wrap items-center gap-2 rounded-[10px] bg-surface px-3 py-1.5">
      <span className="flex min-w-0 items-center gap-2">
        <Scissors aria-hidden="true" size={14} className="shrink-0 text-accentsoft" />
        <span className="truncate font-semibold text-fg">{clip.name}</span>
        <span className="tnum whitespace-nowrap text-fg3">
          {clock(range.t_start)} to {clock(range.t_end)}
        </span>
      </span>
      <button type="button" onClick={() => actions.patch(clip.id, { reset: true })} disabled={!clip.edited} title="Back to the range this clip was created with" className={btn}>
        <RotateCcw aria-hidden="true" size={14} />
        Reset
      </button>
      <span className="flex flex-wrap items-center gap-1.5">
        {nudge("in", -1)}
        {nudge("in", 1)}
        {nudge("out", -1)}
        {nudge("out", 1)}
      </span>
      <button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(timestamps(range));
            setCopied(true);
            setTimeout(() => setCopied(false), COPY_RESET_MS);
          } catch {
            // Clipboard refused; nothing else to do.
          }
        }}
        className={`${btn} transition-colors duration-200`}
        style={copied ? { background: "var(--ok)", borderColor: "var(--ok)", color: "var(--on-ok)" } : undefined}
      >
        {copied ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
        {copied ? "Copied" : "Copy timestamps"}
      </button>
      <span className="ml-auto flex items-center gap-2">
        <span className="tnum whitespace-nowrap text-fg2">{lengthText(length(range))}</span>
        {children}
      </span>
    </div>
  );
}
