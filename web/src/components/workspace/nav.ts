import type { TimelineEvent } from "@/lib/types";

/** The event to jump to from time `t` in direction `dir`, skipping ones within 50 ms of `t`. */
export function stepEvent(events: TimelineEvent[], t: number, dir: 1 | -1): TimelineEvent | undefined {
  if (dir > 0) return events.find((e) => e.t_start > t + 0.05);
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].t_start < t - 0.05) return events[i];
  }
  return undefined;
}

/** The event under the playhead: from its start until its end, or at least 0.6 s. */
export function eventAt(events: TimelineEvent[], t: number): TimelineEvent | undefined {
  let found: TimelineEvent | undefined;
  for (const e of events) {
    if (e.t_start > t + 0.05) break;
    const end = Math.max(e.t_end, e.t_start + 0.6);
    if (t <= end) found = e;
  }
  return found;
}
