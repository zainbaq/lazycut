import type { EventColor, EventType, Glyph, TimelineEvent } from "@/lib/types";

/** Chip palette per preset colour (9.3). Background, border, active background, glyph colour. */
export const CHIP_PALETTE: Record<EventColor, { bg: string; line: string; on: string; glyph: string }> = {
  accent: { bg: "var(--chip)", line: "var(--chip-line)", on: "var(--chip-on)", glyph: "var(--accent)" },
  gold: { bg: "var(--gold-chip)", line: "var(--gold-line)", on: "#3a2f17", glyph: "var(--gold)" },
  warn: { bg: "var(--warn-chip)", line: "var(--warn-line)", on: "#3a2f1a", glyph: "var(--warn)" },
  paper: { bg: "var(--paper-chip)", line: "var(--line-3)", on: "var(--surface-2)", glyph: "var(--text)" },
};

export function EventGlyph({ glyph, color, size = 1 }: { glyph: Glyph; color: EventColor; size?: number }) {
  const c = CHIP_PALETTE[color].glyph;
  const common = { display: "block", flex: "0 0 auto" } as const;
  switch (glyph) {
    case "slash":
      return <span aria-hidden="true" style={{ ...common, width: 3 * size, height: 12 * size, background: c, transform: "rotate(12deg)", borderRadius: 1 }} />;
    case "diamond":
      return <span aria-hidden="true" style={{ ...common, width: 7 * size, height: 7 * size, background: c, transform: "rotate(45deg)" }} />;
    case "ring":
      return <span aria-hidden="true" style={{ ...common, width: 9 * size, height: 9 * size, border: `2px solid ${c}`, borderRadius: "50%" }} />;
    default:
      return <span aria-hidden="true" style={{ ...common, width: 7 * size, height: 7 * size, background: c, borderRadius: "50%" }} />;
  }
}

const FALLBACK: EventType = { id: "?", label: "Event", glyph: "dot", color: "paper", definition: "", show: true };

export function typeOf(types: Map<string, EventType>, id: string): EventType {
  return types.get(id) ?? { ...FALLBACK, id, label: id.replace(/_/g, " ") };
}

export function eventName(e: TimelineEvent, type: EventType): string {
  return e.label?.trim() || type.label;
}

/** Model events nobody has checked yet get a dashed border. */
export function isUnverified(e: TimelineEvent): boolean {
  return e.source === "model" && !e.verified;
}
