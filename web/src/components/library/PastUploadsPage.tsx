"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Clapperboard, ExternalLink, Loader2, Pencil, Plus, Scissors, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { ErrorCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { dayDate, isLink, plural, toDateInput } from "@/lib/format";
import { panelRise } from "@/lib/motion";
import { useAddLibraryItem, useDeleteLibraryItem, useEditLibraryItem, useLibrary } from "@/lib/queries";
import type { LibraryItem, LibraryItemInput } from "@/lib/types";

type Draft = Required<Omit<LibraryItemInput, "published_at">> & { published_at: string };

const EMPTY: Draft = { title: "", url: "", subject: "", topic: "", angle: "", hook: "", playlist: "", published_at: "" };

const FIELDS: { key: keyof Draft; label: string; placeholder?: string; type?: string; wide?: boolean }[] = [
  { key: "title", label: "Title", placeholder: "As it appears on YouTube", wide: true },
  { key: "url", label: "Link", placeholder: "https://youtu.be/…", type: "url", wide: true },
  { key: "subject", label: "Subject", placeholder: "e.g. Zhuo Bi" },
  { key: "topic", label: "Topic", placeholder: "Game or series" },
  { key: "angle", label: "Angle", placeholder: "What made this video different" },
  { key: "hook", label: "Hook", placeholder: "e.g. No Hit" },
  { key: "playlist", label: "Playlist" },
  { key: "published_at", label: "Published", type: "date" },
];

const inputCls =
  "min-h-11 w-full rounded-[10px] border border-linestrong bg-surface px-3 text-[12px] text-fg placeholder:text-fg4 aria-[invalid=true]:border-accent";
const primaryBtn =
  "ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:opacity-60";
const quietBtn = "ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px] text-fg";

function toDraft(item: LibraryItem): Draft {
  return {
    title: item.title,
    url: item.url,
    subject: item.subject,
    topic: item.topic,
    angle: item.angle,
    hook: item.hook,
    playlist: item.playlist,
    published_at: toDateInput(item.published_at),
  };
}

/** Only what changed, so an edit never rewrites a timestamp the user did not touch. */
function changes(before: Draft, after: Draft): LibraryItemInput {
  const out: LibraryItemInput = {};
  for (const key of Object.keys(after) as (keyof Draft)[]) {
    if (after[key].trim() !== before[key].trim()) {
      (out as Record<string, string | null>)[key] = key === "published_at" ? after[key] || null : after[key].trim();
    }
  }
  return out;
}

function newestFirst(list: LibraryItem[]): LibraryItem[] {
  return [...list].sort(
    (a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? "") || a.title.toLowerCase().localeCompare(b.title.toLowerCase()),
  );
}

/** Add or edit one past upload. Title is required; the link must be a full http(s) link (API_SHAPES). */
function ItemForm({
  initial,
  submitLabel,
  pending,
  serverError,
  onSubmit,
  onCancel,
}: {
  initial: Draft;
  submitLabel: string;
  pending: boolean;
  serverError: string | null;
  onSubmit: (draft: Draft) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState<Draft>(initial);
  const [tried, setTried] = useState(false);
  const titleMissing = !draft.title.trim();
  const badLink = !!draft.url.trim() && !isLink(draft.url);
  const invalid = titleMissing || badLink;

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (!invalid) onSubmit(draft);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCancel();
        }
      }}
      className="flex flex-col gap-3"
    >
      <div className="grid grid-cols-1 gap-3 min-[720px]:grid-cols-2">
        {FIELDS.map((f) => {
          const err =
            tried && f.key === "title" && titleMissing
              ? "A past upload needs a title"
              : f.key === "url" && badLink
                ? "Enter a full link starting with https://"
                : null;
          return (
            <div key={f.key} className={`flex flex-col gap-1 ${f.wide ? "min-[720px]:col-span-2" : ""}`}>
              <label htmlFor={`${id}-${f.key}`} className="text-[11px] font-semibold text-fg3">
                {f.label}
                {f.key === "title" ? (
                  <span className="text-accentsoft">
                    {" "}*<span className="sr-only"> (required)</span>
                  </span>
                ) : null}
              </label>
              <input
                id={`${id}-${f.key}`}
                type={f.type ?? "text"}
                value={draft[f.key]}
                autoFocus={f.key === "title"}
                placeholder={f.placeholder}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                aria-invalid={err ? true : undefined}
                aria-describedby={err ? `${id}-${f.key}-err` : undefined}
                className={inputCls}
              />
              {err ? (
                <span id={`${id}-${f.key}-err`} className="text-[11px] text-accentsoft">
                  {err}
                </span>
              ) : null}
            </div>
          );
        })}
      </div>
      {serverError ? (
        <span role="alert" className="rounded-[10px] border border-accent bg-surface p-2.5 text-fg">
          {serverError}
        </span>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onCancel} className={quietBtn}>
          Cancel
        </button>
        <button type="submit" disabled={pending} className={primaryBtn}>
          {pending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : null}
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

function FromAppMarker({ item }: { item: LibraryItem }) {
  if (!item.from_app || !item.video_id) return null;
  return (
    <Link
      href={`/v/${item.video_id}`}
      className="inline-flex min-h-6 items-center gap-1 rounded-[12px] border border-line3 px-2 text-[11px] text-fg2 hover:border-accent"
      title="Marked as published in LazyCut. Open its workspace."
    >
      <Scissors aria-hidden="true" size={11} className="text-accentsoft" />
      From LazyCut
    </Link>
  );
}

function TitleCell({ item }: { item: LibraryItem }) {
  return (
    <span className="flex min-w-0 flex-col items-start gap-1">
      {item.url ? (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-start gap-1 break-words font-semibold text-fg underline-offset-2 hover:underline"
        >
          {item.title}
          <ExternalLink aria-hidden="true" size={11} className="mt-[3px] shrink-0 text-fg3" />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      ) : (
        <span className="break-words font-semibold">{item.title}</span>
      )}
      <FromAppMarker item={item} />
    </span>
  );
}

function DeleteConfirm({ item, onDone }: { item: LibraryItem; onDone: () => void }) {
  const del = useDeleteLibraryItem();
  return (
    <div role="group" aria-label={`Delete “${item.title}”?`} className="flex flex-col gap-2">
      <span className="text-fg2">
        Delete this past upload?{" "}
        {item.from_app ? "It was added by “Mark as published”; the video itself stays published." : "This cannot be undone."}
      </span>
      {del.error ? (
        <span role="alert" className="text-accentsoft">
          {del.error.message}
        </span>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onDone} className={quietBtn} autoFocus>
          Keep it
        </button>
        <button
          type="button"
          disabled={del.isPending}
          onClick={() => del.mutate(item.id, { onSuccess: onDone })}
          className={primaryBtn}
        >
          {del.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Trash2 aria-hidden="true" size={14} />}
          Delete
        </button>
      </div>
    </div>
  );
}

function RowActions({ item, onEdit, onDelete }: { item: LibraryItem; onEdit: () => void; onDelete: () => void }) {
  return (
    <div className="flex gap-1">
      <button type="button" onClick={onEdit} aria-label={`Edit “${item.title}”`} className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] text-fg2 hover:text-fg">
        <Pencil aria-hidden="true" size={14} />
      </button>
      <button type="button" onClick={onDelete} aria-label={`Delete “${item.title}”`} className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] text-fg2 hover:text-accentsoft">
        <Trash2 aria-hidden="true" size={14} />
      </button>
    </div>
  );
}

function EditForm({ item, onDone }: { item: LibraryItem; onDone: () => void }) {
  const edit = useEditLibraryItem();
  const before = toDraft(item);
  return (
    <ItemForm
      initial={before}
      submitLabel="Save"
      pending={edit.isPending}
      serverError={edit.error?.message ?? null}
      onCancel={onDone}
      onSubmit={(draft) => {
        const body = changes(before, draft);
        if (!Object.keys(body).length) return onDone();
        edit.mutate({ id: item.id, body }, { onSuccess: onDone });
      }}
    />
  );
}

type Mode = { id: string; kind: "edit" | "delete" } | null;

const cell = "px-3 py-2.5 align-top text-fg2";
const muted = (v: string) => (v ? v : <span className="text-fg4">–</span>);

function Table({ items, mode, setMode }: { items: LibraryItem[]; mode: Mode; setMode: (m: Mode) => void }) {
  return (
    <div className="hidden overflow-hidden rounded-[12px] border border-line2 min-[900px]:block">
      <table className="w-full table-fixed border-collapse text-[12px]">
        <caption className="sr-only">Past uploads, newest first</caption>
        <colgroup>
          <col className="w-[28%]" />
          <col className="w-[11%]" />
          <col className="w-[11%]" />
          <col className="w-[14%]" />
          <col className="w-[10%]" />
          <col className="w-[10%]" />
          <col className="w-[9%]" />
          <col className="w-[104px]" />
        </colgroup>
        <thead className="bg-raised text-left text-[11px] text-fg3">
          <tr>
            {["Title", "Subject", "Topic", "Angle", "Hook", "Playlist", "Published"].map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-semibold">
                {h}
              </th>
            ))}
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) =>
            mode?.id === item.id && mode.kind === "edit" ? (
              <tr key={item.id} className="border-t border-line2 bg-surface">
                <td colSpan={8} className="p-3.5">
                  <EditForm item={item} onDone={() => setMode(null)} />
                </td>
              </tr>
            ) : (
              <tr key={item.id} className="border-t border-line2 bg-surface">
                <td className={`${cell} text-fg`}>
                  <TitleCell item={item} />
                </td>
                <td className={`${cell} break-words`}>{muted(item.subject)}</td>
                <td className={`${cell} break-words`}>{muted(item.topic)}</td>
                <td className={`${cell} break-words`}>{muted(item.angle)}</td>
                <td className={`${cell} break-words`}>{muted(item.hook)}</td>
                <td className={`${cell} break-words`}>{muted(item.playlist)}</td>
                <td className={`${cell} tnum`}>{item.published_at ? dayDate(item.published_at) : muted("")}</td>
                <td className="px-1 py-1 align-top">
                  {mode?.id === item.id && mode.kind === "delete" ? (
                    <span className="sr-only">Confirming delete below</span>
                  ) : (
                    <RowActions item={item} onEdit={() => setMode({ id: item.id, kind: "edit" })} onDelete={() => setMode({ id: item.id, kind: "delete" })} />
                  )}
                </td>
              </tr>
            ),
          ).flatMap((row, i) => {
            const item = items[i];
            if (mode?.id === item.id && mode.kind === "delete") {
              return [
                row,
                <tr key={`${item.id}-delete`} className="bg-surface">
                  <td colSpan={8} className="px-3.5 pb-3.5">
                    <DeleteConfirm item={item} onDone={() => setMode(null)} />
                  </td>
                </tr>,
              ];
            }
            return [row];
          })}
        </tbody>
      </table>
    </div>
  );
}

function CardList({ items, mode, setMode }: { items: LibraryItem[]; mode: Mode; setMode: (m: Mode) => void }) {
  return (
    <ul className="flex flex-col gap-2.5 min-[900px]:hidden" aria-label="Past uploads, newest first">
      {items.map((item) => (
        <li key={item.id} className="flex flex-col gap-2.5 rounded-[12px] border border-line2 bg-surface p-3.5">
          {mode?.id === item.id && mode.kind === "edit" ? (
            <EditForm item={item} onDone={() => setMode(null)} />
          ) : (
            <>
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <TitleCell item={item} />
                </div>
                <RowActions item={item} onEdit={() => setMode({ id: item.id, kind: "edit" })} onDelete={() => setMode({ id: item.id, kind: "delete" })} />
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
                {(
                  [
                    ["Subject", item.subject],
                    ["Topic", item.topic],
                    ["Angle", item.angle],
                    ["Hook", item.hook],
                    ["Playlist", item.playlist],
                    ["Published", item.published_at ? dayDate(item.published_at) : ""],
                  ] as const
                )
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-fg3">{k}</dt>
                      <dd className="min-w-0 break-words text-fg2">{v}</dd>
                    </div>
                  ))}
              </dl>
              {mode?.id === item.id && mode.kind === "delete" ? <DeleteConfirm item={item} onDone={() => setMode(null)} /> : null}
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex max-w-xl flex-col items-start gap-3 rounded-[12px] border border-line2 bg-surface p-5">
      <span className="flex items-center gap-2 font-head text-[15px]">
        <Clapperboard aria-hidden="true" size={16} className="text-accentsoft" />
        No past uploads yet
      </span>
      <span className="text-fg2">
        Past uploads are the videos already on your channel. LazyCut uses them in two places: the package points its{" "}
        <strong className="font-semibold text-fg">end screen</strong> at a specific past video instead of the channel page, and it{" "}
        <strong className="font-semibold text-fg">warns when a new video repeats</strong> a subject you have covered without a different
        angle.
      </span>
      <span className="text-fg3">
        Add them by hand here. A video you finish in LazyCut joins the list when you use “Mark as published” in its workspace.
      </span>
      <button type="button" onClick={onAdd} className={primaryBtn}>
        <Plus aria-hidden="true" size={14} />
        Add past upload
      </button>
    </div>
  );
}

export function PastUploadsPage() {
  const reduce = useReducedMotion();
  const { data, error, isLoading, refetch } = useLibrary();
  const add = useAddLibraryItem();
  const [adding, setAdding] = useState(false);
  const [mode, setMode] = useState<Mode>(null);
  const items = useMemo(() => newestFirst(data ?? []), [data]);

  const openAdd = () => {
    add.reset();
    setMode(null);
    setAdding(true);
  };

  return (
    <div className="flex min-h-screen">
      <Rail section="past" />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
          <h1 className="font-head text-[16px]">Past uploads</h1>
          {data ? <span className="text-fg3">{plural(data.length, "video")}</span> : null}
          <button type="button" onClick={openAdd} disabled={adding} className={`ml-auto ${primaryBtn} rounded-[22px] px-4`}>
            <Plus aria-hidden="true" size={14} />
            Add past upload
          </button>
        </header>

        <main className="mx-auto flex w-full max-w-[1180px] flex-col gap-4 px-4 py-5 min-[720px]:px-6">
          {data && data.length > 0 ? (
            <p className="max-w-3xl text-fg3">
              Used for the package’s end-screen target and the repeat-video warning. Newest first.
            </p>
          ) : null}

          <AnimatePresence initial={false}>
            {adding ? (
              <motion.section
                key="add"
                aria-label="Add a past upload"
                {...(reduce ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } } : panelRise)}
                className="flex flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-head text-[14px]">Add a past upload</h2>
                  <button type="button" onClick={() => setAdding(false)} aria-label="Close" className="ink-btn -m-2 flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3">
                    <X aria-hidden="true" size={16} />
                  </button>
                </div>
                <ItemForm
                  initial={EMPTY}
                  submitLabel="Add"
                  pending={add.isPending}
                  serverError={add.error?.message ?? null}
                  onCancel={() => setAdding(false)}
                  onSubmit={(draft) => {
                    const body: LibraryItemInput = {
                      title: draft.title.trim(),
                      url: draft.url.trim(),
                      subject: draft.subject.trim(),
                      topic: draft.topic.trim(),
                      angle: draft.angle.trim(),
                      hook: draft.hook.trim(),
                      playlist: draft.playlist.trim(),
                      published_at: draft.published_at || null,
                    };
                    add.mutate(body, { onSuccess: () => setAdding(false) });
                  }}
                />
              </motion.section>
            ) : null}
          </AnimatePresence>

          {error ? <ErrorCard title="Could not load past uploads" message={error.message} onRetry={() => void refetch()} /> : null}
          {isLoading ? (
            <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading past uploads">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="ink-skeleton h-14 rounded-[10px]" />
              ))}
            </div>
          ) : null}
          {data && data.length === 0 && !adding ? <EmptyState onAdd={openAdd} /> : null}
          {items.length ? (
            <>
              <Table items={items} mode={mode} setMode={setMode} />
              <CardList items={items} mode={mode} setMode={setMode} />
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}
