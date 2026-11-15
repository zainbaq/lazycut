"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronRight, Crosshair, Eye, EyeOff, MoreHorizontal, Pencil, Shapes, Trash2, Undo2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { type EventEdits, useEdits } from "@/lib/edits";
import { clock } from "@/lib/format";
import { panelRise } from "@/lib/motion";
import { useWorkspace } from "@/lib/store";
import type { EventType, TimelineEvent } from "@/lib/types";

import { hide, moveToPlayhead, verify } from "./actions";
import { EventGlyph, eventName, typeOf } from "./glyphs";

export const menuItem =
  "flex min-h-11 cursor-pointer items-center gap-2 rounded-[8px] px-3 text-[12px] text-fg outline-none data-[disabled]:cursor-not-allowed data-[disabled]:text-fg4 data-[highlighted]:bg-surface2";
export const menuContent = "z-50 min-w-[220px] rounded-[12px] border border-line2 bg-raised p-1.5";

function Key({ children }: { children: React.ReactNode }) {
  return <span className="ml-auto pl-3 text-[11px] text-fg4">{children}</span>;
}

/** Who proposed an event: "gemini", "you", or several detectors. */
export function foundBy(e: TimelineEvent): string {
  if (e.source === "user") return "added by you";
  const ids = [...new Set(e.detected_by.map((d) => d.detector))];
  return ids.length ? `found by ${ids.join(" + ")}` : "found by the model";
}

export function eventState(e: TimelineEvent): string {
  if (e.hidden) return "hidden";
  if (e.verified) return "verified";
  if (e.source === "user") return "added by you";
  return "unverified";
}

/** The items of an event's menu (right-click on a chip, or the ⋯ button). */
export function EventMenuItems({ event, types, edits }: { event: TimelineEvent; types: EventType[]; edits: EventEdits }) {
  const setRenaming = useWorkspace((s) => s.setRenaming);
  return (
    <>
      <Dropdown.Item className={menuItem} onSelect={() => verify(edits, event.id, !event.verified)}>
        <Check aria-hidden="true" size={14} className={event.verified ? "text-fg3" : "text-ok"} />
        {event.verified ? "Unverify" : "Verify"}
        {event.verified ? null : <Key>Enter</Key>}
      </Dropdown.Item>
      <Dropdown.Item className={menuItem} onSelect={() => moveToPlayhead(edits, event.id)}>
        <Crosshair aria-hidden="true" size={14} />
        Move to playhead
        <Key>E</Key>
      </Dropdown.Item>
      <Dropdown.Sub>
        <Dropdown.SubTrigger className={menuItem}>
          <Shapes aria-hidden="true" size={14} />
          Retype
          <ChevronRight aria-hidden="true" size={14} className="ml-auto text-fg3" />
        </Dropdown.SubTrigger>
        <Dropdown.Portal>
          <Dropdown.SubContent sideOffset={4} className={menuContent}>
            {types.map((t) => (
              <Dropdown.Item
                key={t.id}
                className={menuItem}
                disabled={t.id === event.type}
                onSelect={() => void edits.patch(event.id, { type: t.id })}
              >
                <EventGlyph glyph={t.glyph} color={t.color} />
                {t.label}
                {t.id === event.type ? <Key>current</Key> : null}
              </Dropdown.Item>
            ))}
          </Dropdown.SubContent>
        </Dropdown.Portal>
      </Dropdown.Sub>
      <Dropdown.Item className={menuItem} onSelect={() => setRenaming(event.id)}>
        <Pencil aria-hidden="true" size={14} />
        Rename label…
      </Dropdown.Item>
      <Dropdown.Item className={menuItem} onSelect={() => hide(edits, event.id, !event.hidden)}>
        {event.hidden ? <Eye aria-hidden="true" size={14} /> : <EyeOff aria-hidden="true" size={14} />}
        {event.hidden ? "Unhide" : "Hide"}
        {event.hidden ? null : <Key>Backspace</Key>}
      </Dropdown.Item>
      <Dropdown.Separator className="my-1 h-px bg-line2" />
      <Dropdown.Item className={menuItem} onSelect={() => void edits.remove(event.id)}>
        <Trash2 aria-hidden="true" size={14} className="text-accentsoft" />
        Delete
      </Dropdown.Item>
    </>
  );
}

/**
 * The selected event under the timeline header: what it is, who found it and quick actions.
 * With nothing selected it says how to edit.
 */
export function EventBar({
  event,
  types,
  edits,
  onAdd,
}: {
  event: TimelineEvent | undefined;
  types: Map<string, EventType>;
  edits: EventEdits;
  onAdd: () => void;
}) {
  const list = [...types.values()];
  return (
    <div className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 rounded-[10px] bg-surface px-3 py-1 text-fg2">
      {event ? (
        <>
          <span className="flex min-w-0 items-center gap-2">
            <EventGlyph glyph={typeOf(types, event.type).glyph} color={typeOf(types, event.type).color} />
            <span className="truncate font-semibold text-fg">{eventName(event, typeOf(types, event.type))}</span>
            <span className="tnum text-fg3">{clock(event.t_start)}</span>
          </span>
          <span className="text-[11px] text-fg3">
            {eventState(event)}
            {event.source === "model" ? ` · ${foundBy(event)}` : ""}
            {event.confidence === "uncertain" ? " · uncertain" : ""}
            {event.edited ? " · edited" : ""}
          </span>
          <span className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => verify(edits, event.id, !event.verified)}
              aria-pressed={event.verified}
              className="ink-btn flex min-h-9 items-center gap-1.5 rounded-[8px] border px-2.5 text-[12px]"
              style={{
                borderColor: event.verified ? "var(--ok-line)" : "var(--line-3)",
                color: event.verified ? "var(--ok-text)" : "var(--text)",
                background: event.verified ? "var(--ok-bg)" : "transparent",
              }}
            >
              <Check aria-hidden="true" size={14} />
              {event.verified ? "Verified" : "Verify"}
            </button>
            <button
              type="button"
              onClick={() => hide(edits, event.id, !event.hidden)}
              className="ink-btn flex min-h-9 items-center gap-1.5 rounded-[8px] border border-line3 px-2.5 text-[12px] text-fg"
            >
              {event.hidden ? <Eye aria-hidden="true" size={14} /> : <EyeOff aria-hidden="true" size={14} />}
              {event.hidden ? "Unhide" : "Hide"}
            </button>
            <Dropdown.Root>
              <Dropdown.Trigger aria-label="More actions for this event" className="ink-btn flex h-9 w-9 items-center justify-center rounded-[8px] border border-line3 text-fg">
                <MoreHorizontal aria-hidden="true" size={16} />
              </Dropdown.Trigger>
              <Dropdown.Portal>
                <Dropdown.Content align="end" sideOffset={6} className={menuContent}>
                  <EventMenuItems event={event} types={list} edits={edits} />
                </Dropdown.Content>
              </Dropdown.Portal>
            </Dropdown.Root>
          </span>
        </>
      ) : (
        <>
          <span className="text-fg3">Select an event to edit it. Drag a chip to move it; right-click for more. Double-click the events track to add one.</span>
          <button
            type="button"
            onClick={onAdd}
            className="ink-btn ml-auto flex min-h-9 items-center gap-1.5 rounded-[8px] border border-line3 px-2.5 text-[12px] text-fg"
          >
            + Add at playhead
          </button>
        </>
      )}
    </div>
  );
}

/** Rename an event's label. An empty label falls back to the type's name. */
export function RenameDialog({ edits, types }: { edits: EventEdits; types: Map<string, EventType> }) {
  const id = useWorkspace((s) => s.renamingId);
  const setRenaming = useWorkspace((s) => s.setRenaming);
  const event = id ? edits.find(id) : undefined;
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (event) setText(event.label);
    // Only when a new event is opened, not on every cache update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const save = () => {
    if (event && text.trim() !== event.label.trim()) void edits.patch(event.id, { label: text.trim() });
    setRenaming(null);
  };

  return (
    <Dialog.Root open={!!event} onOpenChange={(o) => (o ? undefined : setRenaming(null))}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]" />
        <Dialog.Content
          onOpenAutoFocus={(e) => {
            // Radix would focus the Close button; the label field is what the user came for.
            e.preventDefault();
            input.current?.focus();
            input.current?.select();
          }}
          className="fixed left-1/2 top-1/2 z-50 flex w-[min(380px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4 text-[12px] text-fg"
        >
          <div className="flex items-start justify-between gap-2">
            <Dialog.Title className="font-head text-[16px]">Rename event</Dialog.Title>
            <Dialog.Close className="ink-btn -m-2 flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3" aria-label="Close">
              <X aria-hidden="true" size={16} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="text-fg3">
            {event ? `${typeOf(types, event.type).label} at ${clock(event.t_start)}. Leave empty to use the type's name.` : ""}
          </Dialog.Description>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
            className="flex flex-col gap-3"
          >
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-fg3">Label</span>
              <input
                ref={input}
                value={text}
                maxLength={80}
                onChange={(e) => setText(e.target.value)}
                placeholder={event ? typeOf(types, event.type).label : ""}
                className="min-h-11 rounded-[10px] border border-line3 bg-surface px-3 text-fg outline-none focus:border-fg3"
              />
            </label>
            <div className="flex justify-end gap-2">
              <Dialog.Close type="button" className="ink-btn min-h-11 rounded-[10px] border border-line3 px-3.5">
                Cancel
              </Dialog.Close>
              <button type="submit" className="ink-btn min-h-11 rounded-[10px] border border-accentfill bg-accentfill px-3.5 font-semibold text-onaccent">
                Save
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** "Moved Counter · Undo", bottom centre, gone after 5 s. Errors stay until closed. */
export function UndoToast({ edits }: { edits: EventEdits }) {
  const toast = useEdits((s) => s.toast);
  const clear = useEdits((s) => s.clearToast);
  const canUndo = useEdits((s) => {
    const n = s.toast?.undoSeq;
    const vid = useWorkspace.getState().videoId;
    return n !== undefined && !!vid && (s.stacks[vid] ?? []).some((e) => e.seq === n);
  });

  useEffect(() => {
    if (!toast || toast.error) return;
    const timer = setTimeout(clear, 5000);
    return () => clearTimeout(timer);
  }, [toast, clear]);

  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-5 z-50 flex justify-center px-4">
      <AnimatePresence>
        {toast ? (
          <motion.div
            key={toast.id}
            {...panelRise}
            role={toast.error ? "alert" : "status"}
            className="pointer-events-auto flex min-h-11 max-w-[min(560px,100%)] items-center gap-3 rounded-[12px] border bg-raised px-3.5 text-[12px] text-fg"
            style={{ borderColor: toast.error ? "var(--accent)" : "var(--line-2)" }}
          >
            <span className="min-w-0 truncate">{toast.text}</span>
            {canUndo && toast.undoSeq !== undefined ? (
              <button
                type="button"
                onClick={() => {
                  clear();
                  void edits.undo(toast.undoSeq);
                }}
                className="ink-btn flex min-h-9 shrink-0 items-center gap-1.5 rounded-[8px] px-2 font-semibold text-accentsoft"
              >
                <Undo2 aria-hidden="true" size={14} />
                Undo
              </button>
            ) : null}
            <button type="button" aria-label="Dismiss" onClick={clear} className="ink-btn -mr-1.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] text-fg3">
              <X aria-hidden="true" size={14} />
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
