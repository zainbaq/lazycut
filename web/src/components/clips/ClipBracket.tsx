"use client";

import { useRef, useState } from "react";

import { clock } from "@/lib/format";
import { EASE_OUT_INK_CSS } from "@/lib/motion";
import { useWorkspace } from "@/lib/store";
import type { Clip } from "@/lib/types";

import { type Edge, FINE_S, moveEdge, SNAP_S, snapTo } from "./trim";
import type { ClipActions } from "./useClipActions";

const HANDLE_W = 14;

/**
 * The selected clip on the filmstrip (9.4): a 3 px accent bracket whose edges drag
 * (0.5 s snap, Alt for 0.1 s). The rest of the strip is dimmed; other clips show as thin marks.
 */
export function ClipBracket({
  clip,
  others,
  pps,
  duration,
  height,
  timeAt,
  actions,
}: {
  clip: Clip | undefined;
  others: Clip[];
  pps: number;
  duration: number;
  height: number;
  timeAt: (clientX: number) => number;
  actions: ClipActions;
}) {
  const draft = useWorkspace((s) => s.clipDraft);
  const dragging = useRef<Edge | null>(null);
  const [active, setActive] = useState(false);

  const marks = others.map((c) => (
    <span
      key={c.id}
      aria-hidden="true"
      className="pointer-events-none absolute top-0 block h-[3px] rounded-b-[2px] bg-accent opacity-55"
      style={{ left: c.t_start * pps, width: Math.max(3, (c.t_end - c.t_start) * pps) }}
    />
  ));
  if (!clip) return <>{marks}</>;

  const range = draft && draft.id === clip.id ? draft : clip;
  const left = range.t_start * pps;
  const width = Math.max(HANDLE_W * 2, (range.t_end - range.t_start) * pps);
  const move = active ? undefined : `left 320ms ${EASE_OUT_INK_CSS}, width 320ms ${EASE_OUT_INK_CSS}`;

  const dragTo = (edge: Edge, clientX: number, fine: boolean) => {
    const ws = useWorkspace.getState();
    const now = ws.clipDraft && ws.clipDraft.id === clip.id ? ws.clipDraft : clip;
    const next = moveEdge(now, edge, snapTo(timeAt(clientX), fine ? FINE_S : SNAP_S), duration);
    ws.setClipDraft({ id: clip.id, ...next });
    // The preview shows the frame the edge is on while it moves.
    ws.seek(edge === "in" ? next.t_start : Math.max(next.t_start, next.t_end - 0.04), { animate: false });
  };

  const handle = (edge: Edge) => {
    const t = edge === "in" ? range.t_start : range.t_end;
    return (
      <span
        role="slider"
        tabIndex={0}
        aria-label={edge === "in" ? "Clip start" : "Clip end"}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration * 10) / 10}
        aria-valuenow={Math.round(t * 10) / 10}
        aria-valuetext={clock(t)}
        title={`${edge === "in" ? "Clip start" : "Clip end"} ${clock(t)} · drag to trim (Alt: 0.1 s)`}
        className="pointer-events-auto absolute inset-y-[-3px] z-[2] flex cursor-ew-resize touch-none items-center justify-center bg-accent"
        style={{ width: HANDLE_W, [edge === "in" ? "left" : "right"]: 0, borderRadius: edge === "in" ? "6px 0 0 6px" : "0 6px 6px 0" }}
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          e.stopPropagation();
          e.currentTarget.setPointerCapture(e.pointerId);
          dragging.current = edge;
          setActive(true);
          useWorkspace.getState().pause();
        }}
        onPointerMove={(e) => {
          if (dragging.current === edge) dragTo(edge, e.clientX, e.altKey);
        }}
        onPointerUp={(e) => {
          e.stopPropagation();
          if (dragging.current !== edge) return;
          dragging.current = null;
          setActive(false);
          const d = useWorkspace.getState().clipDraft;
          if (d && d.id === clip.id) actions.commit(clip.id, { t_start: d.t_start, t_end: d.t_end });
        }}
        onPointerCancel={() => {
          dragging.current = null;
          setActive(false);
          useWorkspace.getState().setClipDraft(null);
        }}
        onDoubleClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();
          e.stopPropagation();
          actions.nudge(edge, (e.key === "ArrowLeft" ? -1 : 1) * (e.altKey ? FINE_S : SNAP_S));
        }}
      >
        <span aria-hidden="true" className="block h-4 w-[2px] rounded-[1px] bg-onaccent opacity-80" />
      </span>
    );
  };

  return (
    <>
      {marks}
      {/* Dim what is outside the clip. */}
      <span aria-hidden="true" className="pointer-events-none absolute left-0 top-0 block rounded-l-[8px] bg-[rgba(12,12,11,0.6)]" style={{ width: Math.max(0, left), height, transition: active ? undefined : `width 320ms ${EASE_OUT_INK_CSS}` }} />
      <span aria-hidden="true" className="pointer-events-none absolute right-0 top-0 block rounded-r-[8px] bg-[rgba(12,12,11,0.6)]" style={{ left: left + width, height, transition: active ? undefined : `left 320ms ${EASE_OUT_INK_CSS}` }} />
      <div
        className="pointer-events-none absolute top-0 rounded-[8px] border-y-[3px] border-accent"
        style={{ left, width, height, transition: move }}
      >
        {handle("in")}
        {handle("out")}
      </div>
    </>
  );
}
