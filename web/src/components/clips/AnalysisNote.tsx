"use client";

import { AnimatePresence, motion } from "motion/react";
import { Lightbulb, MapPin, Wand2 } from "lucide-react";

import { clock } from "@/lib/format";
import { panelRise } from "@/lib/motion";
import { useClips } from "@/lib/queries";
import { useWorkspace } from "@/lib/store";

import type { ClipActions } from "./useClipActions";

/**
 * The analysis note (7.5, 9.4): one suggestion for the selected clip, worked out in code and
 * re-evaluated whenever its edges change. An inverted light card at the bottom of the package panel.
 */
export function AnalysisNote({ videoId, actions }: { videoId: string; actions: ClipActions }) {
  const clips = useClips(videoId, true);
  const selectedId = useWorkspace((s) => s.selectedClipId);
  const seek = useWorkspace((s) => s.seek);
  const clip = selectedId ? clips.data?.clips.find((c) => c.id === selectedId) : undefined;
  const note = clip?.note ?? null;

  return (
    <AnimatePresence mode="wait">
      {clip && note ? (
        <motion.section
          key={`${clip.id}:${note.id}`}
          aria-label="Analysis note"
          aria-live="polite"
          {...panelRise}
          className="sticky bottom-4 mt-auto flex flex-col gap-2 rounded-[12px] bg-note p-3.5 text-notefg"
        >
          <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-accentdeep">
            <Lightbulb aria-hidden="true" size={13} />
            Analysis note
          </h3>
          <p className="text-[12px] leading-[1.5]">{note.message}</p>
          <div className="flex flex-wrap gap-2">
            {note.apply ? (
              <button
                type="button"
                onClick={() =>
                  actions.commit(
                    clip.id,
                    { t_start: note.apply?.t_start ?? clip.t_start, t_end: note.apply?.t_end ?? clip.t_end },
                    note.apply?.t_start != null ? "in" : "out",
                  )
                }
                className="flex min-h-11 items-center gap-1.5 rounded-[10px] bg-notefg px-3 text-[12px] font-semibold text-note transition-transform duration-150 active:scale-[0.96]"
              >
                <Wand2 aria-hidden="true" size={14} />
                Apply recommendation
              </button>
            ) : null}
            {note.at ? (
              <button
                type="button"
                onClick={() => {
                  useWorkspace.getState().pause();
                  seek(note.at![0]);
                }}
                className="flex min-h-11 items-center gap-1.5 rounded-[10px] border border-notefg2 px-3 text-[12px] text-notefg transition-transform duration-150 active:scale-[0.96]"
              >
                <MapPin aria-hidden="true" size={14} />
                Show at {clock(note.at[0])}
              </button>
            ) : null}
          </div>
        </motion.section>
      ) : null}
    </AnimatePresence>
  );
}
