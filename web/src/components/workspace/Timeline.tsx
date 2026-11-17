"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import { Activity, BarChart3, EyeOff, Film, ListChecks, Minus, ZoomIn, ZoomOut } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ClipBar } from "@/components/clips/ClipBar";
import { ClipBracket } from "@/components/clips/ClipBracket";
import type { ClipActions } from "@/components/clips/useClipActions";
import { apiUrl } from "@/lib/api";
import type { EventEdits } from "@/lib/edits";
import { clock } from "@/lib/format";
import { markIn, PLAYHEAD_SEEK_CSS } from "@/lib/motion";
import { useWorkspace } from "@/lib/store";
import type { Clip, EventType, Frames, Timeline as TimelineData, TimelineEvent } from "@/lib/types";

import { reviewQueue } from "./actions";
import { EventBar, EventMenuItems, eventState, menuContent } from "./EventActions";
import { CHIP_PALETTE, EventGlyph, eventName, isUnverified } from "./glyphs";
import { LANE_GAP, LANE_H, layoutChips, tickStep, type ChipItem } from "./layout";
import { ReviewPanel } from "./ReviewPanel";

const RULER_H = 14;
const FILM_H = 52;
const INTENSITY_H = 36;
const DEAD_H = 18;
const TRACK_GAP = 8;
const MAX_PPS = 200;

/** Event ids that have already played their mark-in animation, per page load. */
const seen = new Set<string>();

function Ruler({ duration, pps }: { duration: number; pps: number }) {
  const step = tickStep(pps);
  const ticks: number[] = [];
  for (let t = 0; t <= duration + 1e-6; t += step) ticks.push(t);
  return (
    <div aria-hidden="true" className="tnum relative text-[10px] text-fg4" style={{ height: RULER_H }}>
      {ticks.map((t) => (
        <span key={t} className="absolute top-0 block h-[14px] border-l border-line3 pl-1 leading-[14px]" style={{ left: t * pps }}>
          {clock(t, step < 1 ? 1 : 0)}
        </span>
      ))}
    </div>
  );
}

type ChipMotion = Pick<React.ComponentProps<typeof motion.button>, "initial" | "animate" | "transition">;

function GroupChip({ item, style, motionProps }: { item: ChipItem; style: React.CSSProperties; motionProps: ChipMotion }) {
  const seek = useWorkspace((s) => s.seek);
  const select = useWorkspace((s) => s.select);
  const palette = CHIP_PALETTE[item.type.color];
  const first = item.events[0];
  const last = item.events[item.events.length - 1];
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <motion.button
          {...motionProps}
          type="button"
          className="ink-chip absolute flex items-center gap-1.5 rounded-[8px] px-2 text-[11px] text-fg"
          style={{
            ...style,
            background: palette.bg,
            border: `1px ${item.events.some(isUnverified) ? "dashed" : "solid"} ${palette.line}`,
          }}
          aria-label={`${item.events.length} ${item.type.label} events from ${clock(first.t_start)} to ${clock(last.t_start)}`}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <EventGlyph glyph={item.type.glyph} color={item.type.color} />
          <span className="tnum">×{item.events.length}</span>
        </motion.button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} onPointerDown={(e) => e.stopPropagation()} className="z-50 max-h-[50vh] w-[240px] overflow-y-auto rounded-[12px] border border-line2 bg-raised p-1.5 text-[12px] text-fg">
          <span className="block px-2 py-1.5 text-[11px] text-fg3">
            {item.events.length} × {item.type.label} · zoom in to spread them out
          </span>
          {item.events.map((e) => (
            <Popover.Close
              key={e.id}
              onClick={() => {
                select(e.id);
                seek(e.t_start);
              }}
              className="flex min-h-11 w-full items-center gap-2 rounded-[8px] px-2 text-left hover:bg-surface2"
            >
              <span className="tnum w-[52px] shrink-0 text-fg3">{clock(e.t_start)}</span>
              <span className="truncate">{eventName(e, item.type)}</span>
              {isUnverified(e) ? <span className="ml-auto shrink-0 text-[10px] text-fg4">unverified</span> : null}
            </Popover.Close>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

interface Drag {
  id: string;
  pointerId: number;
  x0: number;
  t0: number;
  t: number;
  moved: boolean;
}

const snap = (t: number, step: number) => Math.round(t / step) * step;

const Chips = memo(function Chips({
  items,
  delays,
  pps,
  fps,
  duration,
  edits,
  onMenu,
}: {
  items: ChipItem[];
  delays: Map<string, number>;
  pps: number;
  fps: number;
  duration: number;
  edits: EventEdits;
  onMenu: (id: string, x: number, y: number) => void;
}) {
  const selectedId = useWorkspace((s) => s.selectedEventId);
  const seek = useWorkspace((s) => s.seek);
  const select = useWorkspace((s) => s.select);
  const reduced = useReducedMotion();
  const drag = useRef<Drag | null>(null);
  const [dragging, setDragging] = useState<{ id: string; t: number } | null>(null);
  const suppressClick = useRef(false);

  const onDown = (ev: React.PointerEvent<HTMLButtonElement>, e: TimelineEvent) => {
    ev.stopPropagation();
    if (ev.button !== 0) return;
    drag.current = { id: e.id, pointerId: ev.pointerId, x0: ev.clientX, t0: e.t_start, t: e.t_start, moved: false };
    ev.currentTarget.setPointerCapture(ev.pointerId);
  };
  const onMove = (ev: React.PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    if (!d || d.pointerId !== ev.pointerId) return;
    const dx = ev.clientX - d.x0;
    if (!d.moved && Math.abs(dx) < 4) return;
    if (!d.moved) {
      d.moved = true;
      select(d.id);
      useWorkspace.getState().pause();
    }
    // Snap to 0.1 s; with Alt held, to one frame.
    const step = ev.altKey ? 1 / (fps || 30) : 0.1;
    d.t = Math.max(0, Math.min(duration, snap(d.t0 + dx / pps, step)));
    setDragging({ id: d.id, t: d.t });
    seek(d.t, { animate: false });
  };
  const onUp = (ev: React.PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    if (!d || d.pointerId !== ev.pointerId) return;
    drag.current = null;
    if (d.moved) {
      suppressClick.current = true;
      setDragging(null);
      if (Math.abs(d.t - d.t0) >= 0.001) void edits.patch(d.id, { t_start: Math.round(d.t * 1000) / 1000 });
    }
  };

  return (
    <>
      {items.map((item) => {
        const draggedHere = dragging && item.events.length === 1 && item.events[0].id === dragging.id;
        const style: React.CSSProperties = {
          left: draggedHere ? Math.max(0, dragging.t * pps) : item.x,
          top: item.lane * (LANE_H + LANE_GAP),
          width: item.width,
          height: LANE_H,
        };
        const delay = delays.get(item.key);
        const animate = delay !== undefined;
        const motionProps: ChipMotion = animate
          ? {
              initial: reduced ? { opacity: 0 } : markIn.initial,
              animate: reduced ? { opacity: 1 } : markIn.animate,
              transition: { duration: markIn.duration, delay, ease: [0.2, 0.8, 0.2, 1] },
            }
          : { initial: false };

        if (item.events.length > 1) {
          return <GroupChip key={item.key} item={item} style={style} motionProps={motionProps} />;
        }
        const e = item.events[0];
        const on = e.id === selectedId;
        const palette = CHIP_PALETTE[item.type.color];
        const name = eventName(e, item.type);
        return (
          <motion.button
            key={item.key}
            {...motionProps}
            type="button"
            data-event-id={e.id}
            className="ink-chip absolute flex cursor-grab items-center gap-1.5 overflow-visible rounded-[8px] px-2 text-[11px] text-fg active:cursor-grabbing"
            style={{
              ...style,
              justifyContent: item.glyphOnly ? "center" : undefined,
              background: on ? palette.on : palette.bg,
              border: `1px ${isUnverified(e) ? "dashed" : "solid"} ${on ? "var(--accent)" : palette.line}`,
              zIndex: draggedHere ? 3 : on ? 2 : 1,
              opacity: e.hidden ? 0.45 : 1,
              touchAction: "none",
            }}
            aria-label={`${name} at ${clock(e.t_start)}, ${eventState(e)}`}
            aria-pressed={on}
            title={`${name} · ${clock(e.t_start)} · ${eventState(e)} · drag to move, right-click for more`}
            onPointerDown={(ev) => onDown(ev, e)}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={() => {
              drag.current = null;
              setDragging(null);
            }}
            onContextMenu={(ev) => {
              ev.preventDefault();
              select(e.id);
              onMenu(e.id, ev.clientX, ev.clientY);
            }}
            onClick={() => {
              if (suppressClick.current) {
                suppressClick.current = false;
                return;
              }
              select(e.id);
              seek(e.t_start);
            }}
          >
            <EventGlyph glyph={item.type.glyph} color={item.type.color} />
            {item.glyphOnly ? null : <span className={`min-w-0 truncate ${e.hidden ? "line-through" : ""}`}>{name}</span>}
            {draggedHere ? (
              <span className="tnum pointer-events-none absolute -top-6 left-0 whitespace-nowrap rounded-[6px] border border-accent bg-raised px-1.5 py-0.5 text-[10px] text-fg">
                {clock(dragging.t, 2)}
              </span>
            ) : null}
          </motion.button>
        );
      })}
    </>
  );
});

function Filmstrip({ frames, pps }: { frames: Frames | undefined; pps: number }) {
  if (!frames || !frames.frames.length) {
    return <div className="ink-skeleton rounded-[8px]" style={{ height: FILM_H }} aria-hidden="true" />;
  }
  const tile = frames.interval_s * pps;
  const k = Math.max(1, Math.ceil(56 / Math.max(tile, 1)));
  const shown = frames.frames.filter((_, i) => i % k === 0);
  return (
    <div aria-hidden="true" className="relative overflow-hidden rounded-[8px] bg-[#141312]" style={{ height: FILM_H }}>
      {shown.map((f) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={f.url}
          src={apiUrl(f.url)}
          alt=""
          loading="lazy"
          draggable={false}
          className="absolute top-0 h-full object-cover"
          style={{ left: f.t * pps, width: Math.ceil(k * tile) + 1, borderRight: "2px solid #0c0c0b" }}
        />
      ))}
    </div>
  );
}

function Intensity({ data, pps, width, clipStart, clipEnd }: { data: TimelineData; pps: number; width: number; clipStart?: number; clipEnd?: number }) {
  const { normal, dead, inClip } = useMemo(() => {
    const colW = 3;
    const cols = Math.max(1, Math.floor(width / colW));
    const { bucket_s, scores } = data.intensity;
    let n = "";
    let d = "";
    let c2 = "";
    for (let c = 0; c < cols; c++) {
      const t0 = (c * colW) / pps;
      const t1 = ((c + 1) * colW) / pps;
      const tm = (t0 + t1) / 2;
      if (t0 >= data.duration_s) break;
      const isDead = data.dead_time.some((r) => tm >= r.t_start && tm < r.t_end);
      const i0 = Math.floor(t0 / bucket_s);
      const i1 = Math.max(i0 + 1, Math.ceil(t1 / bucket_s));
      let v = 0;
      for (let i = i0; i < i1 && i < scores.length; i++) v = Math.max(v, scores[i] ?? 0);
      const x = c * colW;
      if (isDead || v < 0.02) {
        d += `M${x} ${INTENSITY_H / 2 - 1.5}h2v3h-2z`;
      } else {
        const h = Math.max(3, Math.round(4 + v * 26));
        const bar = `M${x} ${(INTENSITY_H - h) / 2}h2v${h}h-2z`;
        // Bars inside the selected clip are brighter (9.4).
        if (clipStart != null && clipEnd != null && tm >= clipStart && tm < clipEnd) c2 += bar;
        else n += bar;
      }
    }
    return { normal: n, dead: d, inClip: c2 };
  }, [data, pps, width, clipStart, clipEnd]);
  return (
    <svg aria-hidden="true" width={width} height={INTENSITY_H} className="block rounded-[8px] bg-surface">
      <path d={dead} fill="var(--line-2)" />
      <path d={normal} fill="var(--line-strong)" />
      <path d={inClip} fill="var(--text-2)" />
    </svg>
  );
}

function DeadTime({ data, pps }: { data: TimelineData; pps: number }) {
  return (
    <div aria-hidden="true" className="relative" style={{ height: DEAD_H }}>
      {data.dead_time.map((r) => (
        <span
          key={`${r.t_start}`}
          className="absolute top-1 block h-2.5 rounded-[5px] bg-line3"
          style={{ left: r.t_start * pps, width: Math.max(4, (r.t_end - r.t_start) * pps) }}
        />
      ))}
    </div>
  );
}

function Playhead({ pps, scroller }: { pps: number; scroller: React.RefObject<HTMLDivElement | null> }) {
  const playhead = useWorkspace((s) => s.playhead);
  const playing = useWorkspace((s) => s.playing);
  const seeking = useWorkspace((s) => s.seeking);
  const x = playhead * pps;

  // Keep the playhead in view while playing or after a jump.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const left = el.scrollLeft;
    const right = left + el.clientWidth;
    if (x < left + 8 || x > right - 24) {
      el.scrollLeft = Math.max(0, playing ? x - 24 : x - el.clientWidth / 2);
    }
  }, [x, playing, scroller]);

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute bottom-0 z-10 w-0 border-l-2 border-dashed border-fg"
      style={{ top: RULER_H + 4, left: x, transition: seeking && !playing ? PLAYHEAD_SEEK_CSS : undefined }}
    />
  );
}

function TypeFilter({ types, counts, hiddenCount }: { types: EventType[]; counts: Map<string, number>; hiddenCount: number }) {
  const hidden = useWorkspace((s) => s.hiddenTypes);
  const toggle = useWorkspace((s) => s.toggleType);
  const showHidden = useWorkspace((s) => s.showHidden);
  const setShowHidden = useWorkspace((s) => s.setShowHidden);
  const off = types.filter((t) => hidden[t.id]).length;
  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label={`Filter event types${off ? `, ${off} hidden` : ""}`}
        className="ink-btn relative flex w-full items-center justify-center rounded-[8px] bg-surface text-fg3"
        style={{ height: LANE_H }}
      >
        <Activity aria-hidden="true" size={14} />
        {off ? <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-accent" /> : null}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="right" align="start" sideOffset={8} className="z-50 w-[240px] rounded-[12px] border border-line2 bg-raised p-1.5 text-[12px] text-fg">
          <span className="block px-2 py-1.5 text-[11px] text-fg3">Event types on the timeline</span>
          {types.map((t) => {
            const on = !hidden[t.id];
            return (
              <button
                key={t.id}
                type="button"
                role="switch"
                aria-checked={on}
                onClick={() => toggle(t.id)}
                className="flex min-h-11 w-full items-center gap-2 rounded-[8px] px-2 text-left hover:bg-surface2"
              >
                <EventGlyph glyph={t.glyph} color={t.color} />
                <span className={on ? "text-fg" : "text-fg4"}>{t.label}</span>
                <span className="tnum ml-auto text-fg3">{counts.get(t.id) ?? 0}</span>
                <span aria-hidden="true" className="relative block h-5 w-[34px] shrink-0 rounded-[10px] transition-colors duration-200" style={{ background: on ? "var(--accent-fill)" : "var(--line-3)" }}>
                  <span className="absolute top-[3px] block h-3.5 w-3.5 rounded-full bg-fg transition-[left] duration-200" style={{ left: on ? 17 : 3 }} />
                </span>
              </button>
            );
          })}
          <div className="my-1 h-px bg-line2" />
          <button
            type="button"
            role="switch"
            aria-checked={showHidden}
            onClick={() => setShowHidden(!showHidden)}
            className="flex min-h-11 w-full items-center gap-2 rounded-[8px] px-2 text-left hover:bg-surface2"
          >
            <EyeOff aria-hidden="true" size={13} className="text-fg3" />
            <span className={showHidden ? "text-fg" : "text-fg2"}>Show hidden events</span>
            <span className="tnum ml-auto text-fg3">{hiddenCount}</span>
            <span aria-hidden="true" className="relative block h-5 w-[34px] shrink-0 rounded-[10px] transition-colors duration-200" style={{ background: showHidden ? "var(--accent-fill)" : "var(--line-3)" }}>
              <span className="absolute top-[3px] block h-3.5 w-3.5 rounded-full bg-fg transition-[left] duration-200" style={{ left: showHidden ? 17 : 3 }} />
            </span>
          </button>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** Timeline (9.4 region 5): ruler, events, filmstrip, intensity, dead time and the playhead. */
export function Timeline({
  data,
  frames,
  types,
  visible,
  shown,
  emptyNote,
  edits,
  clips,
  clipActions,
  clipTools,
}: {
  /** The video's clips; the selected one is bracketed on the filmstrip. */
  clips: Clip[];
  clipActions: ClipActions;
  /** Extra controls at the end of the clip action bar (export, lift). */
  clipTools?: React.ReactNode;
  data: TimelineData;
  frames: Frames | undefined;
  types: Map<string, EventType>;
  /** Events for navigation and review: not hidden, type not filtered out. */
  visible: TimelineEvent[];
  /** Events drawn as chips: `visible`, plus hidden ones when "Show hidden" is on. */
  shown: TimelineEvent[];
  emptyNote: string | null;
  edits: EventEdits;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const eventsTrack = useRef<HTMLDivElement>(null);
  const [viewW, setViewW] = useState(0);
  const zoom = useWorkspace((s) => s.zoom);
  const setZoom = useWorkspace((s) => s.setZoom);
  const seek = useWorkspace((s) => s.seek);
  const selectedId = useWorkspace((s) => s.selectedEventId);
  const select = useWorkspace((s) => s.select);
  const review = useWorkspace((s) => s.review);
  const startReview = useWorkspace((s) => s.startReview);
  const hiddenTypes = useWorkspace((s) => s.hiddenTypes);
  const dragging = useRef(false);
  const selectedClipId = useWorkspace((s) => s.selectedClipId);
  const clipDraft = useWorkspace((s) => s.clipDraft);
  const clip = selectedClipId ? clips.find((c) => c.id === selectedClipId) : undefined;
  const clipRange = clip ? (clipDraft && clipDraft.id === clip.id ? clipDraft : clip) : undefined;
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [adding, setAdding] = useState<{ t: number } | null>(null);
  const typeList = data.event_types;
  const queue = useMemo(() => reviewQueue(visible), [visible]);
  const selected = selectedId ? data.events.find((e) => e.id === selectedId) : undefined;
  const menuEvent = menu ? data.events.find((e) => e.id === menu.id) : undefined;

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setViewW(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const duration = Math.max(data.duration_s, 0.1);
  const width = Math.max(1, viewW * zoom);
  const pps = width / duration;
  const maxZoom = Math.max(1, (MAX_PPS * duration) / Math.max(viewW, 1));

  const layout = useMemo(() => layoutChips(shown, types, pps, width), [shown, types, pps, width]);
  const eventsH = layout.lanes * LANE_H + (layout.lanes - 1) * LANE_GAP;

  // Chips seen for the first time animate in, 60 ms apart in time order (capped).
  const delays = useMemo(() => {
    const map = new Map<string, number>();
    let n = 0;
    for (const item of layout.items) {
      if (item.events.some((e) => !seen.has(e.id))) {
        map.set(item.key, Math.min(n * markIn.stagger, markIn.maxDelay));
        n++;
      }
    }
    return map;
  }, [layout]);
  useEffect(() => {
    for (const item of layout.items) for (const e of item.events) seen.add(e.id);
  }, [layout]);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of data.events) if (!e.hidden) m.set(e.type, (m.get(e.type) ?? 0) + 1);
    return m;
  }, [data.events]);
  const hiddenCount = useMemo(() => data.events.filter((e) => e.hidden).length, [data.events]);

  const addAt = async (t: number, type: string) => {
    setAdding(null);
    const event = await edits.add(t, type);
    if (event) select(event.id);
  };

  const sliderValue = maxZoom > 1 ? Math.round((Math.log(zoom) / Math.log(maxZoom)) * 100) : 0;
  const applyZoom = (next: number) => {
    const el = scroller.current;
    const clamped = Math.max(1, Math.min(maxZoom, next));
    if (!el) return setZoom(clamped);
    // Keep the playhead where it is on screen.
    const head = useWorkspace.getState().playhead;
    const offset = head * pps - el.scrollLeft;
    setZoom(clamped);
    requestAnimationFrame(() => {
      const newPps = (viewW * clamped) / duration;
      el.scrollLeft = Math.max(0, head * newPps - offset);
    });
  };

  const timeAt = (clientX: number) => {
    const el = scroller.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    return Math.max(0, Math.min(duration, (clientX - r.left + el.scrollLeft) / pps));
  };

  const trackTop = RULER_H + TRACK_GAP;

  return (
    <section aria-label="Timeline" className="flex flex-col gap-2.5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-head text-[16px]">Timeline</h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            aria-pressed={!!review}
            disabled={!review && !queue.length}
            title={queue.length ? "Step through the unverified events (the eye test)" : "Every visible event is verified"}
            onClick={() => (review ? useWorkspace.getState().stopReview() : startReview(queue))}
            className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[22px] border px-3.5 text-[12px] disabled:opacity-50"
            style={{
              borderColor: review ? "var(--accent)" : "var(--line-3)",
              background: review ? "var(--chip-on)" : "transparent",
              color: review ? "var(--text)" : queue.length ? "var(--text)" : "var(--text-3)",
            }}
          >
            <ListChecks aria-hidden="true" size={14} />
            {review ? "Exit review" : "Review events"}
            {!review && queue.length ? <span className="tnum text-fg3">{queue.length}</span> : null}
          </button>
          <span className="flex items-center gap-2 text-fg3">
            <button type="button" aria-label="Zoom out" onClick={() => applyZoom(zoom / 1.6)} className="ink-btn flex h-11 w-8 items-center justify-center rounded-[8px]">
              <ZoomOut aria-hidden="true" size={14} />
            </button>
            <label className="flex items-center">
              <span className="sr-only">Timeline zoom</span>
              <input
                type="range"
                min={0}
                max={100}
                value={sliderValue}
                disabled={maxZoom <= 1}
                onChange={(e) => applyZoom(maxZoom ** (Number(e.target.value) / 100))}
                className="ink-range w-20"
              />
            </label>
            <button type="button" aria-label="Zoom in" onClick={() => applyZoom(zoom * 1.6)} className="ink-btn flex h-11 w-8 items-center justify-center rounded-[8px]">
              <ZoomIn aria-hidden="true" size={14} />
            </button>
          </span>
        </div>
      </div>

      {review ? (
        <ReviewPanel events={data.events} visible={visible} types={types} fps={data.fps} duration={data.duration_s} edits={edits} />
      ) : (
        <EventBar event={selected} types={types} edits={edits} onAdd={() => setAdding({ t: useWorkspace.getState().playhead })} />
      )}

      <div className="flex gap-2.5">
        <div className="flex w-9 shrink-0 flex-col text-fg3" style={{ paddingTop: trackTop, gap: TRACK_GAP }}>
          <div style={{ height: eventsH }}>
            <TypeFilter types={data.event_types} counts={counts} hiddenCount={hiddenCount} />
          </div>
          <span aria-hidden="true" className="flex items-center justify-center rounded-[8px] bg-surface" style={{ height: FILM_H }}>
            <Film size={14} />
          </span>
          <span aria-hidden="true" className="flex items-center justify-center rounded-[8px] bg-surface" style={{ height: INTENSITY_H }}>
            <BarChart3 size={14} />
          </span>
          <span aria-hidden="true" className="flex items-center justify-center rounded-[8px] bg-surface" style={{ height: DEAD_H }}>
            <Minus size={12} />
          </span>
        </div>

        <div ref={scroller} className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden pb-1">
          <div
            className="relative flex touch-none select-none flex-col"
            style={{ width, gap: TRACK_GAP, overflowX: "clip" }}
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              dragging.current = true;
              e.currentTarget.setPointerCapture(e.pointerId);
              useWorkspace.getState().pause();
              seek(timeAt(e.clientX));
            }}
            onPointerMove={(e) => {
              if (dragging.current) seek(timeAt(e.clientX), { animate: false });
            }}
            onPointerUp={() => {
              dragging.current = false;
            }}
            onDoubleClick={(e) => {
              // Double-click on empty space in the events track adds an event there.
              if ((e.target as HTMLElement).closest(".ink-chip")) return;
              const r = eventsTrack.current?.getBoundingClientRect();
              if (!r || e.clientY < r.top || e.clientY > r.bottom) return;
              setAdding({ t: timeAt(e.clientX) });
            }}
          >
            <Ruler duration={data.duration_s} pps={pps} />
            <div ref={eventsTrack} className="relative" style={{ height: eventsH }} title="Double-click to add an event">
              <Chips
                items={layout.items}
                delays={delays}
                pps={pps}
                fps={data.fps}
                duration={data.duration_s}
                edits={edits}
                onMenu={(id, x, y) => setMenu({ id, x, y })}
              />
              {emptyNote && !layout.items.length ? (
                <span className="absolute left-2 top-0 flex h-[30px] items-center text-fg3">{emptyNote}</span>
              ) : null}
              <AddEventPopover
                at={adding}
                pps={pps}
                types={typeList}
                hiddenTypes={hiddenTypes}
                onPick={(type) => adding && void addAt(adding.t, type)}
                onClose={() => setAdding(null)}
              />
            </div>
            <div className="relative" style={{ height: FILM_H }}>
              <Filmstrip frames={frames} pps={pps} />
              <ClipBracket
                clip={clip}
                others={clips.filter((c) => c.id !== selectedClipId)}
                pps={pps}
                duration={data.duration_s}
                height={FILM_H}
                timeAt={timeAt}
                actions={clipActions}
              />
            </div>
            <Intensity data={data} pps={pps} width={width} clipStart={clipRange?.t_start} clipEnd={clipRange?.t_end} />
            <DeadTime data={data} pps={pps} />
            <Playhead pps={pps} scroller={scroller} />
          </div>
        </div>
      </div>

      {clip ? (
        <ClipBar clip={clip} duration={data.duration_s} actions={clipActions}>
          {clipTools}
        </ClipBar>
      ) : null}

      {/* One shared menu for right-click on a chip, anchored where the click was. */}
      <Dropdown.Root open={!!menuEvent} onOpenChange={(o) => (o ? undefined : setMenu(null))}>
        <Dropdown.Trigger asChild>
          <span aria-hidden="true" tabIndex={-1} className="pointer-events-none fixed h-0 w-0" style={{ left: menu?.x ?? 0, top: menu?.y ?? 0 }} />
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content
            align="start"
            sideOffset={4}
            className={menuContent}
            onCloseAutoFocus={(e) => {
              e.preventDefault();
              if (menu) (document.querySelector(`[data-event-id="${menu.id}"]`) as HTMLElement | null)?.focus();
            }}
          >
            {menuEvent ? <EventMenuItems event={menuEvent} types={typeList} edits={edits} /> : null}
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
    </section>
  );
}

/** Type picker for a new event at time `at.t`, shown on the events track. */
function AddEventPopover({
  at,
  pps,
  types,
  hiddenTypes,
  onPick,
  onClose,
}: {
  at: { t: number } | null;
  pps: number;
  types: EventType[];
  hiddenTypes: Record<string, boolean>;
  onPick: (type: string) => void;
  onClose: () => void;
}) {
  // Types shown on the timeline first; the first one is the default (Enter).
  const ordered = [...types.filter((t) => !hiddenTypes[t.id]), ...types.filter((t) => hiddenTypes[t.id])];
  return (
    <Popover.Root open={!!at} onOpenChange={(o) => (o ? undefined : onClose())}>
      <Popover.Anchor asChild>
        <span aria-hidden="true" className="pointer-events-none absolute top-0 h-[30px] w-0" style={{ left: (at?.t ?? 0) * pps }} />
      </Popover.Anchor>
      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="start"
          sideOffset={6}
          // Portalled, but React still bubbles its events to the track; keep them here.
          onPointerDown={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
          className="z-50 w-[220px] rounded-[12px] border border-line2 bg-raised p-1.5 text-[12px] text-fg"
          aria-label="Add an event"
        >
          <span className="tnum block px-2 py-1.5 text-[11px] text-fg3">Add an event at {clock(at?.t ?? 0, 2)}</span>
          {ordered.map((t, i) => (
            <button
              key={t.id}
              type="button"
              autoFocus={i === 0}
              onClick={() => onPick(t.id)}
              className="flex min-h-11 w-full items-center gap-2 rounded-[8px] px-2 text-left outline-none hover:bg-surface2 focus-visible:bg-surface2"
            >
              <EventGlyph glyph={t.glyph} color={t.color} />
              <span className={hiddenTypes[t.id] ? "text-fg3" : "text-fg"}>{t.label}</span>
              {i === 0 ? <span className="ml-auto text-[11px] text-fg4">Enter</span> : null}
            </button>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
