"use client";

// Event editing with optimistic updates and a per-video undo stack (Phase 1 step 4).
//
// Every edit updates the cached timeline at once, then calls the API. The undo stack keeps the
// event as it was before each edit; undo sends it back (PATCH, POST with its id after a delete,
// DELETE after an add). Facts and the video are refetched after each saved edit, because derived
// facts and the display status follow the events (7.4).

import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { create } from "zustand";

import { api } from "./api";
import { keys } from "./queries";
import type { EventPatch, Timeline, TimelineEvent } from "./types";

export type UndoEntry =
  | { kind: "patch"; seq: number; before: TimelineEvent; fields: (keyof EventPatch)[]; text: string }
  | { kind: "delete"; seq: number; before: TimelineEvent; text: string }
  | { kind: "add"; seq: number; id: string; text: string };

export interface Toast {
  id: number;
  text: string;
  /** The undo entry this toast offers to undo, if any. */
  undoSeq?: number;
  error?: boolean;
}

interface EditState {
  stacks: Record<string, UndoEntry[]>;
  toast: Toast | null;
  push: (videoId: string, entry: UndoEntry) => void;
  drop: (videoId: string, seq: number) => void;
  pop: (videoId: string) => UndoEntry | undefined;
  showToast: (toast: Omit<Toast, "id">) => void;
  clearToast: () => void;
}

const UNDO_LIMIT = 100;
let seq = 0;
let toastSeq = 0;

export const useEdits = create<EditState>((set, get) => ({
  stacks: {},
  toast: null,
  push: (videoId, entry) =>
    set((s) => ({ stacks: { ...s.stacks, [videoId]: [...(s.stacks[videoId] ?? []), entry].slice(-UNDO_LIMIT) } })),
  drop: (videoId, n) =>
    set((s) => ({ stacks: { ...s.stacks, [videoId]: (s.stacks[videoId] ?? []).filter((e) => e.seq !== n) } })),
  pop: (videoId) => {
    const stack = get().stacks[videoId] ?? [];
    const entry = stack[stack.length - 1];
    if (entry) set((s) => ({ stacks: { ...s.stacks, [videoId]: stack.slice(0, -1) } }));
    return entry;
  },
  showToast: (toast) => set({ toast: { ...toast, id: ++toastSeq } }),
  clearToast: () => set({ toast: null }),
}));

const byTime = (a: TimelineEvent, b: TimelineEvent) => a.t_start - b.t_start || a.type.localeCompare(b.type);

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The cached event after a patch, matching what the server does (a move keeps the length). */
export function applyPatch(e: TimelineEvent, patch: EventPatch): TimelineEvent {
  const next = { ...e, ...patch };
  if (patch.t_start !== undefined && patch.t_end === undefined) next.t_end = e.t_end + (patch.t_start - e.t_start);
  if (e.source === "model" && (patch.t_start !== undefined || patch.t_end !== undefined || patch.type !== undefined || patch.label !== undefined)) {
    next.edited = true;
  }
  return next;
}

function makeEdits(qc: QueryClient, videoId: string) {
  const tlKey = keys.timeline(videoId);
  const store = useEdits.getState;

  const timeline = () => qc.getQueryData<Timeline>(tlKey);
  const find = (id: string) => timeline()?.events.find((e) => e.id === id);
  const setEvents = (fn: (events: TimelineEvent[]) => TimelineEvent[]) =>
    qc.setQueryData<Timeline>(tlKey, (tl) => (tl ? { ...tl, events: fn(tl.events).sort(byTime) } : tl));
  const replace = (id: string, event: TimelineEvent | null) =>
    setEvents((events) => (event ? events.map((e) => (e.id === id ? event : e)) : events.filter((e) => e.id !== id)));

  const typeLabel = (type: string) => timeline()?.event_types.find((t) => t.id === type)?.label ?? type.replace(/_/g, " ");
  const nameOf = (e: TimelineEvent) => e.label?.trim() || typeLabel(e.type);

  const saved = () => {
    void qc.invalidateQueries({ queryKey: keys.facts(videoId) });
    void qc.invalidateQueries({ queryKey: keys.video(videoId) });
    void qc.invalidateQueries({ queryKey: keys.videos });
    void qc.invalidateQueries({ queryKey: keys.packages(videoId) }); // events feed the stale check
  };
  const failed = (what: string, err: unknown) => {
    store().showToast({ text: `${what} failed: ${message(err)}`, error: true });
    void qc.invalidateQueries({ queryKey: tlKey });
  };

  function describe(before: TimelineEvent, patch: EventPatch): string {
    const name = nameOf(before);
    if (patch.type !== undefined && patch.type !== before.type) return `Retyped ${name} to ${typeLabel(patch.type)}`;
    if (patch.label !== undefined) return patch.label.trim() ? `Renamed to ${patch.label.trim()}` : `Cleared the label of ${name}`;
    if (patch.t_start !== undefined) return `Moved ${name}`;
    if (patch.verified !== undefined) return `${patch.verified ? "Verified" : "Unverified"} ${name}`;
    if (patch.hidden !== undefined) return `${patch.hidden ? "Hid" : "Unhid"} ${name}`;
    return `Edited ${name}`;
  }

  /** Change one event. Returns false when the event is not in the cache. */
  async function patch(id: string, fields: EventPatch, opts: { record?: boolean; quiet?: boolean } = {}): Promise<boolean> {
    const before = find(id);
    if (!before) return false;
    const text = describe(before, fields);
    replace(id, applyPatch(before, fields));
    const n = ++seq;
    if (opts.record !== false) {
      const changed = Object.keys(fields) as (keyof EventPatch)[];
      // A move changes the end too, so undo puts both back.
      if (changed.includes("t_start") && !changed.includes("t_end")) changed.push("t_end");
      store().push(videoId, { kind: "patch", seq: n, before, fields: changed, text });
      if (!opts.quiet) store().showToast({ text, undoSeq: n });
    }
    try {
      replace(id, await api.updateEvent(id, fields));
      saved();
      return true;
    } catch (err) {
      replace(id, before);
      store().drop(videoId, n);
      failed(text, err);
      return false;
    }
  }

  async function remove(id: string): Promise<void> {
    const before = find(id);
    if (!before) return;
    const text = `Deleted ${nameOf(before)}`;
    replace(id, null);
    const n = ++seq;
    store().push(videoId, { kind: "delete", seq: n, before, text });
    store().showToast({ text, undoSeq: n });
    try {
      await api.deleteEvent(id);
      saved();
    } catch (err) {
      setEvents((events) => [...events, before]);
      store().drop(videoId, n);
      failed(text, err);
    }
  }

  /** Add a user event at `t`. Resolves with the saved event (or null on failure). */
  async function add(t: number, type: string): Promise<TimelineEvent | null> {
    const tl = timeline();
    const duration = tl?.duration_s ?? t + 0.5;
    const tempId = `tmp-${++seq}`;
    const temp: TimelineEvent = {
      id: tempId, video_id: videoId, t_start: t, t_end: Math.min(duration, t + 0.5), t_model_start: null, t_model_end: null,
      type, label: "", intensity: "medium", crop_safe_9x16: true, confidence: "certain", source: "user",
      detected_by: [], verified: false, hidden: false, edited: false,
    };
    const text = `Added ${typeLabel(type)}`;
    setEvents((events) => [...events, temp]);
    try {
      const event = await api.createEvent(videoId, { t_start: Math.round(t * 1000) / 1000, type });
      replace(tempId, event);
      const n = ++seq;
      store().push(videoId, { kind: "add", seq: n, id: event.id, text });
      store().showToast({ text, undoSeq: n });
      saved();
      return event;
    } catch (err) {
      replace(tempId, null);
      failed(text, err);
      return null;
    }
  }

  async function revert(entry: UndoEntry): Promise<void> {
    const label = `Undo ${entry.text.charAt(0).toLowerCase()}${entry.text.slice(1)}`;
    try {
      if (entry.kind === "patch") {
        const back: EventPatch = {};
        for (const f of entry.fields) (back as Record<string, unknown>)[f] = entry.before[f];
        const current = find(entry.before.id);
        if (current) replace(current.id, { ...current, ...back });
        replace(entry.before.id, await api.updateEvent(entry.before.id, back));
      } else if (entry.kind === "delete") {
        setEvents((events) => [...events.filter((e) => e.id !== entry.before.id), entry.before]);
        replace(entry.before.id, await api.createEvent(videoId, entry.before));
      } else {
        replace(entry.id, null);
        await api.deleteEvent(entry.id);
      }
      store().showToast({ text: `Undid: ${entry.text}` });
      saved();
    } catch (err) {
      failed(label, err);
    }
  }

  /** Undo the last edit of this video, or one entry by its number (the toast's Undo button). */
  async function undo(n?: number): Promise<void> {
    let entry: UndoEntry | undefined;
    if (n === undefined) entry = store().pop(videoId);
    else {
      entry = (store().stacks[videoId] ?? []).find((e) => e.seq === n);
      if (entry) store().drop(videoId, n);
    }
    if (entry) await revert(entry);
  }

  return { patch, remove, add, undo, find, nameOf, typeLabel };
}

export type EventEdits = ReturnType<typeof makeEdits>;

export function useEventEdits(videoId: string): EventEdits {
  const qc = useQueryClient();
  return useMemo(() => makeEdits(qc, videoId), [qc, videoId]);
}
