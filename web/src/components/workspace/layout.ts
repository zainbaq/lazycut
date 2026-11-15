// Pure layout for the events track: grouping, chip widths and lanes. No React here.

import type { EventType, TimelineEvent } from "@/lib/types";

import { eventName, typeOf } from "./glyphs";

export const LANE_H = 30;
export const LANE_GAP = 4;
export const MAX_LANES = 3;
/** Same-type events closer than this many pixels collapse into a count chip. */
export const GROUP_PX = 28;
const GLYPH_W = 26;
const LABEL_MIN = 44;
const LABEL_MAX = 150;
const CHAR_W = 6.1;

export interface ChipItem {
  key: string;
  type: EventType;
  t: number;
  x: number;
  width: number;
  glyphOnly: boolean;
  lane: number;
  events: TimelineEvent[];
}

export interface ChipLayout {
  items: ChipItem[];
  lanes: number;
}

function labelWidth(text: string): number {
  return Math.min(LABEL_MAX, Math.ceil(16 + 7 + 6 + text.length * CHAR_W));
}

/**
 * Lay out the visible events at `pps` pixels per second across `width` pixels.
 *
 * 1. Same-type events closer than GROUP_PX become one "×n" chip; zooming in splits them.
 * 2. A chip takes its label's width when there is room before the next chip, else shows
 *    its glyph only (anything under 44 px is glyph-only).
 * 3. Chips that still overlap go to the first free lane, up to MAX_LANES.
 */
export function layoutChips(events: TimelineEvent[], types: Map<string, EventType>, pps: number, width: number): ChipLayout {
  const byType = new Map<string, TimelineEvent[]>();
  for (const e of events) byType.set(e.type, [...(byType.get(e.type) ?? []), e]);

  const raw: { type: EventType; events: TimelineEvent[] }[] = [];
  for (const [typeId, list] of byType) {
    const type = typeOf(types, typeId);
    const sorted = [...list].sort((a, b) => a.t_start - b.t_start);
    let group: TimelineEvent[] = [];
    for (const e of sorted) {
      const prev = group[group.length - 1];
      if (prev && (e.t_start - prev.t_start) * pps < GROUP_PX) group.push(e);
      else {
        if (group.length) raw.push({ type, events: group });
        group = [e];
      }
    }
    if (group.length) raw.push({ type, events: group });
  }
  raw.sort((a, b) => a.events[0].t_start - b.events[0].t_start);

  const items: ChipItem[] = raw.map((r, i) => {
    const t = r.events[0].t_start;
    const x = t * pps;
    const nextX = i + 1 < raw.length ? raw[i + 1].events[0].t_start * pps : width;
    const room = nextX - x - LANE_GAP;
    let w: number;
    let glyphOnly: boolean;
    if (r.events.length > 1) {
      w = Math.ceil(GLYPH_W + 8 + String(r.events.length).length * 7);
      glyphOnly = false;
    } else {
      const wanted = labelWidth(eventName(r.events[0], r.type));
      w = Math.min(wanted, room);
      glyphOnly = w < LABEL_MIN;
      if (glyphOnly) w = GLYPH_W;
    }
    const clampedX = Math.max(0, Math.min(x, width - w));
    return {
      key: r.events.map((e) => e.id).join("+"),
      type: r.type,
      t,
      x: clampedX,
      width: w,
      glyphOnly,
      lane: 0,
      events: r.events,
    };
  });

  const laneEnd: number[] = [];
  for (const item of items) {
    let lane = laneEnd.findIndex((end) => end <= item.x - 2);
    if (lane === -1) {
      if (laneEnd.length < MAX_LANES) lane = laneEnd.length;
      else lane = laneEnd.indexOf(Math.min(...laneEnd));
    }
    laneEnd[lane] = item.x + item.width;
    item.lane = lane;
  }
  return { items, lanes: Math.max(1, laneEnd.length) };
}

/** Ruler step: the smallest round step that leaves at least `minPx` between ticks. */
export function tickStep(pps: number, minPx = 64): number {
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
  return steps.find((s) => s * pps >= minPx) ?? 3600;
}
