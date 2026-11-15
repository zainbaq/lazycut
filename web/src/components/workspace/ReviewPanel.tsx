"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { motion, useReducedMotion } from "motion/react";
import { Check, ChevronLeft, ChevronRight, Crosshair, EyeOff, Pause, Play, Shapes, StepBack, StepForward, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

import { Switch } from "@/components/ui/Switch";
import type { EventEdits } from "@/lib/edits";
import { clock, plural } from "@/lib/format";
import { stamp } from "@/lib/motion";
import { useWorkspace } from "@/lib/store";
import type { EventType, TimelineEvent } from "@/lib/types";

import { moveToPlayhead, reviewHide, reviewQueue, reviewStep, reviewVerify } from "./actions";
import { foundBy, menuContent, menuItem } from "./EventActions";
import { EventGlyph, eventName, typeOf } from "./glyphs";

const PAD_S = 1; // the loop runs from 1 s before to 1 s after the event

/**
 * Review mode, the eye test (9.4, D19). Steps through the unverified events fixed when it
 * started. The preview loops around the current one; Enter verifies and moves on.
 */
export function ReviewPanel({
  events,
  visible,
  types,
  fps,
  duration,
  edits,
}: {
  events: TimelineEvent[];
  visible: TimelineEvent[];
  types: Map<string, EventType>;
  fps: number;
  duration: number;
  edits: EventEdits;
}) {
  const review = useWorkspace((s) => s.review)!;
  const playing = useWorkspace((s) => s.playing);
  const playhead = useWorkspace((s) => s.playhead);
  const panel = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  const byId = useMemo(() => new Map(events.map((e) => [e.id, e])), [events]);
  const total = review.ids.length;
  const done = review.index >= total;
  const id = review.ids[review.index];
  const current = id ? byId.get(id) : undefined;
  const verified = review.ids.filter((x) => byId.get(x)?.verified).length;
  const hidden = review.ids.filter((x) => byId.get(x)?.hidden).length;
  const type = current ? typeOf(types, current.type) : undefined;

  // Each new event: select it, jump to the loop start and play.
  useEffect(() => {
    if (!id) return;
    const ws = useWorkspace.getState();
    const e = edits.find(id);
    if (!e) return;
    ws.select(id);
    ws.seek(Math.max(0, e.t_start - PAD_S));
    const el = ws.videoEl;
    if (el) void el.play().catch(() => undefined);
  }, [id, edits]);

  useEffect(() => {
    const el = useWorkspace.getState().videoEl;
    if (el) el.playbackRate = review.halfSpeed ? 0.5 : 1;
  }, [review.halfSpeed]);

  // Loop the window around the event while it plays (follows the event if it is moved).
  const start = current ? Math.max(0, current.t_start - PAD_S) : 0;
  const end = current ? Math.min(duration, current.t_start + PAD_S) : 0;
  useEffect(() => {
    if (!current) return;
    let raf = 0;
    const tick = () => {
      const el = useWorkspace.getState().videoEl;
      if (el && !el.paused && (el.currentTime >= end || el.currentTime < start - 0.25)) el.currentTime = start;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [current, start, end]);

  // Pause when review mode ends.
  useEffect(() => () => useWorkspace.getState().pause(), []);

  /** Keep focus on the panel after a click, so Enter keeps meaning "verify". */
  const act = (fn: () => void) => () => {
    fn();
    panel.current?.focus();
  };
  const frame = 1 / (fps || 30);
  const stepFrame = (dir: 1 | -1) => {
    const ws = useWorkspace.getState();
    ws.pause();
    ws.seek(ws.playhead + dir * frame, { animate: false });
  };
  const offset = current ? playhead - current.t_start : 0;

  const btn = "ink-btn flex min-h-11 items-center justify-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px] text-fg disabled:opacity-40";

  return (
    <div
      ref={panel}
      tabIndex={-1}
      role="region"
      aria-label="Review events"
      className="flex flex-col gap-2.5 rounded-[12px] border border-line2 bg-surface p-3 outline-none"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-accentsoft">Review</span>
        <span className="tnum text-fg2" aria-live="polite">
          {verified} of {total} verified{hidden ? ` · ${hidden} hidden` : ""}
        </span>
        <span className="relative h-1.5 min-w-[80px] flex-1 overflow-hidden rounded-[3px] bg-line2" aria-hidden="true">
          <span className="absolute inset-y-0 left-0 bg-ok transition-[width] duration-300" style={{ width: `${total ? ((verified + hidden) / total) * 100 : 0}%` }} />
        </span>
        <span className="tnum text-[11px] text-fg3">{done ? "done" : `${review.index + 1} / ${total}`}</span>
        <button type="button" onClick={() => useWorkspace.getState().stopReview()} className="ink-btn flex min-h-9 items-center gap-1 rounded-[8px] px-2 text-fg3">
          <X aria-hidden="true" size={14} />
          Exit <span className="text-[11px] text-fg4">Esc</span>
        </button>
      </div>

      {done ? (
        <div className="flex flex-wrap items-center gap-3 py-2">
          <motion.span {...(reduced ? {} : stamp)} className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-ok text-ok">
            <Check aria-hidden="true" size={20} />
          </motion.span>
          <span className="text-[13px] text-fg">
            Reviewed {plural(total, "event")}: {verified} verified{hidden ? `, ${hidden} hidden` : ""}.
          </span>
          <span className="ml-auto flex gap-2">
            {reviewQueue(visible).length ? (
              <button type="button" onClick={() => useWorkspace.getState().startReview(reviewQueue(visible))} className={btn}>
                Review the {reviewQueue(visible).length} still unverified
              </button>
            ) : null}
            <button type="button" onClick={() => useWorkspace.getState().stopReview()} className={`${btn} border-accentfill bg-accentfill font-semibold text-onaccent`}>
              Finish
            </button>
          </span>
        </div>
      ) : !current || !type ? (
        <div className="flex items-center gap-3 py-2 text-fg3">
          This event was deleted.
          <button type="button" onClick={act(() => reviewStep(1))} className={btn}>
            Next
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="flex min-w-0 items-center gap-2.5">
              <EventGlyph glyph={type.glyph} color={type.color} size={1.6} />
              <span className="truncate font-head text-[18px] text-fg">{eventName(current, type)}</span>
            </span>
            <span className="tnum text-[13px] text-fg2">{clock(current.t_start)}</span>
            <span className="text-[11px] text-fg3">
              {type.label !== eventName(current, type) ? `${type.label} · ` : ""}
              {foundBy(current)}
              {current.confidence === "uncertain" ? " · model was unsure" : ""}
              {current.verified ? " · verified" : current.hidden ? " · hidden" : ""}
            </span>
            {current.detected_by.some((d) => d.label && d.label !== current.label) ? (
              <span className="w-full truncate text-[11px] text-fg4" title={current.detected_by.map((d) => d.label).join(" / ")}>
                “{current.detected_by.find((d) => d.label && d.label !== current.label)?.label}”
              </span>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" aria-label="Previous event in review" disabled={review.index === 0} onClick={act(() => reviewStep(-1))} className={btn}>
              <ChevronLeft aria-hidden="true" size={16} />
            </button>
            <button type="button" aria-label="Step back one frame" onClick={act(() => stepFrame(-1))} className={btn}>
              <StepBack aria-hidden="true" size={14} />
            </button>
            <button type="button" aria-label={playing ? "Pause the loop" : "Play the loop"} onClick={act(() => useWorkspace.getState().togglePlay())} className={btn}>
              {playing ? <Pause aria-hidden="true" size={14} /> : <Play aria-hidden="true" size={14} />}
            </button>
            <button type="button" aria-label="Step forward one frame" onClick={act(() => stepFrame(1))} className={btn}>
              <StepForward aria-hidden="true" size={14} />
            </button>
            <Switch checked={review.halfSpeed} onChange={(on) => act(() => useWorkspace.getState().setHalfSpeed(on))()}>
              Half speed
            </Switch>

            <span className="mx-1 hidden h-6 w-px bg-line2 sm:block" aria-hidden="true" />

            <button
              type="button"
              onClick={act(() => moveToPlayhead(edits, current.id))}
              disabled={Math.abs(offset) < 0.001}
              className={btn}
              title="Move the event to the playhead (E)"
            >
              <Crosshair aria-hidden="true" size={14} />
              Set to playhead
              <span className="tnum text-[11px] text-fg3">{Math.abs(offset) < 0.001 ? "E" : `${offset > 0 ? "+" : "−"}${Math.abs(offset).toFixed(2)} s`}</span>
            </button>
            <Dropdown.Root>
              <Dropdown.Trigger className={btn}>
                <Shapes aria-hidden="true" size={14} />
                Retype
              </Dropdown.Trigger>
              <Dropdown.Portal>
                <Dropdown.Content sideOffset={6} className={menuContent} onCloseAutoFocus={(e) => (e.preventDefault(), panel.current?.focus())}>
                  {[...types.values()].map((t) => (
                    <Dropdown.Item key={t.id} className={menuItem} disabled={t.id === current.type} onSelect={() => void edits.patch(current.id, { type: t.id })}>
                      <EventGlyph glyph={t.glyph} color={t.color} />
                      {t.label}
                    </Dropdown.Item>
                  ))}
                </Dropdown.Content>
              </Dropdown.Portal>
            </Dropdown.Root>

            <span className="ml-auto flex gap-2">
              <button type="button" onClick={act(() => reviewHide(edits))} className={`${btn} min-w-[104px]`}>
                <EyeOff aria-hidden="true" size={14} />
                Not it · hide
                <span className="text-[11px] text-fg4">⌫</span>
              </button>
              <button type="button" onClick={act(() => reviewStep(1))} className={btn} aria-label="Skip to the next event">
                Skip
                <ChevronRight aria-hidden="true" size={14} />
              </button>
              <button
                type="button"
                onClick={act(() => reviewVerify(edits))}
                className={`${btn} min-w-[148px] border-okline bg-okbg font-semibold text-oktext`}
              >
                <Check aria-hidden="true" size={16} />
                Verify &amp; next
                <span className="text-[11px] font-normal opacity-70">Enter</span>
              </button>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
