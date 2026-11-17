// Trimming maths for clips (BUILD_SPEC 7.5, 9.4). Pure: no React, no store.

import { clock } from "@/lib/format";

export const MIN_CLIP_S = 3;
/** Edges snap to half a second; hold Alt for a tenth. */
export const SNAP_S = 0.5;
export const FINE_S = 0.1;
/** A clip marked with one key press gets this length until the other edge is set. */
export const NEW_CLIP_S = 15;

export type Edge = "in" | "out";
export interface Range {
  t_start: number;
  t_end: number;
}

const round = (t: number) => Math.round(t * 1000) / 1000;

export function snapTo(t: number, step: number): number {
  return round(Math.round(t / step) * step);
}

/** Put one edge at `t`, keeping the clip inside the video and at least 3 s long. */
export function moveEdge(range: Range, edge: Edge, t: number, duration: number, min = MIN_CLIP_S): Range {
  if (edge === "in") {
    return { t_start: round(Math.max(0, Math.min(t, range.t_end - min))), t_end: range.t_end };
  }
  return { t_start: range.t_start, t_end: round(Math.min(duration, Math.max(t, range.t_start + min))) };
}

export function nudgeEdge(range: Range, edge: Edge, delta: number, duration: number): Range {
  return moveEdge(range, edge, (edge === "in" ? range.t_start : range.t_end) + delta, duration);
}

/** The edge `[` and `]` move: the one nearest the playhead. */
export function nearestEdge(range: Range, playhead: number): Edge {
  return Math.abs(playhead - range.t_start) <= Math.abs(playhead - range.t_end) ? "in" : "out";
}

/** A new clip from one key press: `I` starts it at the playhead, `O` ends it there. */
export function newRange(playhead: number, duration: number, anchor: Edge): Range {
  const length = Math.min(NEW_CLIP_S, duration);
  let start = anchor === "in" ? playhead : playhead - length;
  start = Math.max(0, Math.min(start, duration - length));
  let end = anchor === "in" ? start + length : Math.max(playhead, start + MIN_CLIP_S);
  end = Math.min(duration, Math.max(end, start + MIN_CLIP_S));
  return { t_start: round(start), t_end: round(end) };
}

export function sameRange(a: Range, b: Range): boolean {
  return Math.abs(a.t_start - b.t_start) < 1e-6 && Math.abs(a.t_end - b.t_end) < 1e-6;
}

export function length(range: Range): number {
  return Math.max(0, range.t_end - range.t_start);
}

/** "27.5 s", or "1:12.5" from a minute up. */
export function lengthText(seconds: number): string {
  return seconds < 60 ? `${seconds.toFixed(1)} s` : clock(seconds);
}

/** What "Copy timestamps" puts on the clipboard. */
export function timestamps(range: Range): string {
  return `${clock(range.t_start)} - ${clock(range.t_end)} (${lengthText(length(range))})`;
}
