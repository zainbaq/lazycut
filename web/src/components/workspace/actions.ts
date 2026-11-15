// Edit actions shared by the timeline, the review panel and the keyboard shortcuts.

import type { EventEdits } from "@/lib/edits";
import { useWorkspace } from "@/lib/store";
import type { TimelineEvent } from "@/lib/types";

const round = (t: number) => Math.round(t * 1000) / 1000;

/** Move an event to the playhead (`E`). Does nothing when it is already there. */
export function moveToPlayhead(edits: EventEdits, id: string): void {
  const e = edits.find(id);
  const t = round(useWorkspace.getState().playhead);
  if (!e || Math.abs(e.t_start - t) < 0.001) return;
  void edits.patch(id, { t_start: t });
}

export function verify(edits: EventEdits, id: string, on = true): void {
  const e = edits.find(id);
  if (e && e.verified !== on) void edits.patch(id, { verified: on });
}

export function hide(edits: EventEdits, id: string, on = true): void {
  const e = edits.find(id);
  if (e && e.hidden !== on) void edits.patch(id, { hidden: on });
}

// ---- review mode ------------------------------------------------------------------

export function reviewEvent(edits: EventEdits): TimelineEvent | undefined {
  const r = useWorkspace.getState().review;
  if (!r) return undefined;
  const id = r.ids[r.index];
  return id ? edits.find(id) : undefined;
}

export function reviewStep(dir: 1 | -1): void {
  const ws = useWorkspace.getState();
  if (ws.review) ws.reviewGo(ws.review.index + dir);
}

/** Enter in review mode: verify the current event and go to the next. */
export function reviewVerify(edits: EventEdits): void {
  const e = reviewEvent(edits);
  if (e && !e.verified) void edits.patch(e.id, { verified: true }, { quiet: true });
  reviewStep(1);
}

/** Backspace in review mode: hide the current event and go to the next. */
export function reviewHide(edits: EventEdits): void {
  const e = reviewEvent(edits);
  if (e && !e.hidden) void edits.patch(e.id, { hidden: true }, { quiet: true });
  reviewStep(1);
}

/** The events review mode steps through: visible, unverified model events in time order. */
export function reviewQueue(visible: TimelineEvent[]): string[] {
  return visible.filter((e) => e.source === "model" && !e.verified && !e.hidden).map((e) => e.id);
}
