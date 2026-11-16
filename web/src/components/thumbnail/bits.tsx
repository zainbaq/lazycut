"use client";

// Small shared pieces for the thumbnail creator and its settings (BUILD_SPEC 7.13).

import type { Corner, CornerChoice, ThumbFont, ThumbSettings } from "@/lib/types";

export const CORNER_LABELS: Record<CornerChoice, string> = {
  auto: "Auto",
  top_left: "Top left",
  top_right: "Top right",
  bottom_left: "Bottom left",
  bottom_right: "Bottom right",
};
export const CORNERS: Corner[] = ["top_left", "top_right", "bottom_left", "bottom_right"];

export const FONT_LABELS: Record<ThumbFont, string> = {
  bebas: "Bebas Neue",
  montserrat: "Montserrat Black",
  league_spartan: "League Spartan",
  dejavu: "DejaVu Sans Bold",
};

export const HUD_LABELS = { none: "no HUD", light: "light HUD", heavy: "heavy HUD" } as const;

export const CHECK_LABELS: Record<string, string> = {
  faces: "Faces",
  hands: "Hands",
  hud: "HUD removed",
  text: "Text",
  likeness: "Likeness",
  artifacts: "Artifacts",
  placement: "Word placement",
  file: "File",
  backdrop: "Behind the word",
};

export function modelLabel(settings: ThumbSettings | undefined, id: string): string {
  return settings?.models.find((m) => m.id === id)?.label ?? id;
}

export function money(usd: number | null | undefined): string {
  if (usd == null) return "–";
  return usd < 0.1 ? `$${usd.toFixed(3).replace(/0$/, "")}` : `$${usd.toFixed(2)}`;
}

/** A tiny corner diagram: which corner of the frame the word goes in. */
export function CornerGlyph({ corner, size = 14 }: { corner: CornerChoice; size?: number }) {
  const w = size * 1.6;
  const h = size;
  const dot = { top_left: [3, 3], top_right: [w - 8, 3], bottom_left: [3, h - 6], bottom_right: [w - 8, h - 6] } as const;
  return (
    <svg aria-hidden="true" width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0">
      <rect x="0.5" y="0.5" width={w - 1} height={h - 1} rx="2" fill="none" stroke="currentColor" strokeOpacity="0.55" />
      {corner === "auto" ? (
        <text x={w / 2} y={h / 2 + 3} textAnchor="middle" fontSize={h * 0.6} fill="currentColor">
          A
        </text>
      ) : (
        <rect x={dot[corner][0]} y={dot[corner][1]} width="5" height="3" rx="1" fill="currentColor" />
      )}
    </svg>
  );
}

/** A segmented control: one choice of a few, each a 44 px target. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  render,
}: {
  label: string;
  value: T;
  options: readonly T[];
  onChange: (v: T) => void;
  render?: (v: T) => React.ReactNode;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = o === value;
        return (
          <button
            key={o}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o)}
            className={
              "ink-chip flex min-h-11 items-center gap-1.5 rounded-[8px] border px-3 text-[12px] " +
              (on ? "border-accent bg-chipon text-fg" : "border-line3 text-fg2")
            }
          >
            {render ? render(o) : o}
          </button>
        );
      })}
    </div>
  );
}

/** A labelled native select, styled like the app's inputs. */
export function SelectField({
  id,
  label,
  value,
  onChange,
  children,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1">
      <span className="text-[12px] font-semibold text-fg2">{label}</span>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-11 w-full rounded-[10px] border border-line3 bg-bg px-3 text-[13px] text-fg outline-none focus:border-accent"
      >
        {children}
      </select>
      {hint ? <span className="text-[11px] text-fg4">{hint}</span> : null}
    </label>
  );
}

export function SectionTitle({ id, children, aside }: { id?: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-2">
      <h2 id={id} className="font-head text-[16px]">
        {children}
      </h2>
      {aside ? <span className="text-[12px] text-fg3">{aside}</span> : null}
    </div>
  );
}
