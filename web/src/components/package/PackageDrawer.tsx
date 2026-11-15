"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AlertTriangle, ExternalLink, FileDown, Loader2, PenLine, RefreshCw, Sparkles, X } from "lucide-react";
import { useState } from "react";

import { exportUrl, frameUrl } from "@/lib/api";
import { ago, clock } from "@/lib/format";
import { easeOutInk } from "@/lib/motion";
import { useConfigStatus, useEditPackage, useRegeneratePackage } from "@/lib/queries";
import { useWorkspace } from "@/lib/store";
import type { EditableField, Goal, Package, Video } from "@/lib/types";

import { ClaimText, GoalChip, SweepCopy } from "./bits";
import { RuleBadge } from "./RuleBadges";
import { LIMITS, claimMarks, isBlocked, resultsFor, tagsLength } from "./rules";

const btn = "ink-btn flex min-h-11 items-center justify-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px] disabled:opacity-40";

/** One package field as a copyable block: character count, its rule badges, inline edit, Regenerate. */
function FieldBlock({
  pkg,
  videoId,
  label,
  path,
  value,
  field,
  count,
  limit,
  multiline,
  regenerateBlocked,
  display,
  hint,
  goal: goalOverride,
}: {
  pkg: Package;
  videoId: string;
  label: string;
  path: string;
  /** What Copy copies and the editor starts from. */
  value: string;
  /** Editable through PATCH when set. */
  field?: EditableField;
  count?: number;
  limit?: number;
  multiline?: boolean;
  regenerateBlocked?: string | null;
  display?: React.ReactNode;
  hint?: string;
  goal?: Goal;
}) {
  const edit = useEditPackage(videoId);
  const regenerate = useRegeneratePackage(videoId);
  const [draft, setDraft] = useState<string | null>(null);
  const results = resultsFor(pkg, path).filter((r) => r.severity !== "pass" || r.fixed);
  const blocked = isBlocked(pkg, path);
  const edited = !!field && pkg.edited_fields.includes(field);
  const size = count ?? value.length;
  const over = limit !== undefined && size > limit;
  const goal = goalOverride ?? pkg.fields.goals?.[path];
  const id = `pf-${path.replace(/[^\w]/g, "-")}`;

  const save = () => {
    if (!field || draft === null) return;
    edit.mutate({ id: pkg.id, body: { field, value: draft } }, { onSuccess: () => setDraft(null) });
  };

  return (
    <section aria-labelledby={id} className="flex flex-col gap-1.5 border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <h3 id={id} className="text-[12.5px] font-semibold text-fg">
          {label}
        </h3>
        <GoalChip goal={goal} />
        {edited ? (
          <span className="flex items-center gap-0.5 text-[11px] text-goldtext">
            <PenLine aria-hidden="true" size={11} />
            Edited by you
          </span>
        ) : null}
        {limit !== undefined || count !== undefined ? (
          <span className={`tnum ml-auto text-[11px] ${over ? "text-accentsoft" : "text-fg4"}`}>
            {size}
            {limit !== undefined ? ` / ${limit.toLocaleString()}` : ""} characters
          </span>
        ) : null}
      </div>
      {hint ? <span className="text-[11px] text-fg3">{hint}</span> : null}

      {draft !== null ? (
        <form
          className="flex flex-col gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <label>
            <span className="sr-only">{label}</span>
            {multiline ? (
              <textarea
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={Math.min(14, Math.max(3, draft.split("\n").length + 1))}
                className="w-full resize-y rounded-[10px] border border-line3 bg-surface p-2.5 text-[12.5px] leading-relaxed text-fg outline-none focus:border-fg3"
              />
            ) : (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="min-h-11 w-full rounded-[10px] border border-line3 bg-surface px-3 text-[13px] text-fg outline-none focus:border-fg3"
              />
            )}
          </label>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`tnum text-[11px] ${limit !== undefined && draft.length > limit ? "text-accentsoft" : "text-fg4"}`}>
              {draft.length} characters
            </span>
            <button type="button" className={`${btn} ml-auto`} onClick={() => setDraft(null)}>
              Cancel
            </button>
            <button type="submit" disabled={edit.isPending} className={`${btn} border-accentfill bg-accentfill font-semibold text-onaccent`}>
              {edit.isPending ? <Loader2 aria-hidden="true" size={13} className="animate-spin" /> : null}
              Save
            </button>
          </div>
          <span className="text-[11px] text-fg4">The rules run again when you save. Regenerate all keeps your edit unless you ask it not to.</span>
        </form>
      ) : (
        <div
          className="max-h-[320px] overflow-y-auto whitespace-pre-wrap break-words rounded-[10px] border p-2.5 text-[12.5px] leading-relaxed text-fg2"
          style={{ borderColor: blocked ? "var(--accent)" : "var(--line-2)", background: "var(--surface)" }}
        >
          {display ?? (value ? <ClaimText text={value} marks={claimMarks(pkg, path)} /> : <span className="text-fg4">Empty</span>)}
        </div>
      )}

      {results.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {results.map((r) => (
            <li key={r.key} className="max-w-full">
              <RuleBadge
                result={r}
                showField={false}
                busy={edit.isPending}
                onDismiss={(key, dismiss) => edit.mutate({ id: pkg.id, body: dismiss ? { dismiss: key } : { undismiss: key } })}
              />
            </li>
          ))}
        </ul>
      ) : null}

      {draft === null ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <SweepCopy text={value} disabled={blocked || !value} disabledReason={blocked ? "Blocked by a rule" : "Nothing to copy"} />
          {field ? (
            <button type="button" className={btn} onClick={() => setDraft(value)}>
              <PenLine aria-hidden="true" size={13} />
              Edit
            </button>
          ) : null}
          {field ? (
            <button
              type="button"
              className={btn}
              disabled={!!regenerateBlocked || regenerate.isPending}
              title={regenerateBlocked ?? "Write this field again (one Claude call); your edit to it is replaced"}
              onClick={() => regenerate.mutate({ id: pkg.id, body: { field } })}
            >
              <RefreshCw aria-hidden="true" size={13} className={regenerate.isPending ? "animate-spin" : undefined} />
              Regenerate
            </button>
          ) : null}
        </div>
      ) : null}
      {edit.error || regenerate.error ? (
        <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5 text-[12px] text-fg">
          {(edit.error ?? regenerate.error)?.message}
        </span>
      ) : null}
    </section>
  );
}

/** A YouTube search-result row, drawn in the Ink language: frame, duration, title, channel, snippet. */
function SearchPreview({ pkg, video, channel }: { pkg: Package; video: Video; channel: string | null }) {
  const t = pkg.fields.thumbnail.frame_ts[0] ?? 0;
  const snippet = pkg.fields.description.replace(/\s+/g, " ").trim().slice(0, 160);
  return (
    <figure className="flex flex-col gap-2" aria-label="How it may look in YouTube search">
      <figcaption className="text-[11px] font-semibold text-fg3">Search result preview</figcaption>
      <div className="flex flex-col gap-2 rounded-[12px] bg-surface p-2.5">
        <div className="relative aspect-video w-full overflow-hidden rounded-[8px] bg-stage">
          {/* eslint-disable-next-line @next/next/no-img-element -- a frame cut on demand by the API */}
          <img src={frameUrl(video.id, t, 320)} alt={`Frame at ${clock(t)}`} className="h-full w-full object-cover" />
          {video.duration_s ? (
            <span className="tnum absolute bottom-1 right-1 rounded-[4px] bg-[rgba(7,7,7,0.82)] px-1 text-[10.5px] text-fg">
              {clock(video.duration_s, 0)}
            </span>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <span className="line-clamp-2 text-[14px] font-semibold leading-snug text-fg">{pkg.fields.title}</span>
          <span className="text-[11px] text-fg3">
            {channel ?? "Your channel"} · {video.published_at ? ago(video.published_at) : "not published yet"}
          </span>
          <span className="line-clamp-2 text-[11.5px] text-fg3">{snippet}</span>
          {pkg.fields.title.length > 70 ? (
            <span className="text-[10.5px] text-warn">Search may cut titles after about 70 characters.</span>
          ) : null}
        </div>
      </div>
    </figure>
  );
}

/** The full package (9.4): every field, copyable and editable, with a search preview and the checklist. */
export function PackageDrawer({
  open,
  onOpenChange,
  pkg,
  video,
  running,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pkg: Package;
  video: Video;
  running: boolean;
}) {
  const reduced = useReducedMotion();
  const status = useConfigStatus();
  const regenerate = useRegeneratePackage(video.id);
  const [replaceEdits, setReplaceEdits] = useState(false);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const f = pkg.fields;
  const regenBlocked = running ? "A package is being written" : null;
  const seek = (t: number) => {
    onOpenChange(false);
    const ws = useWorkspace.getState();
    ws.pause();
    ws.seek(t);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open ? (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className="fixed inset-y-0 right-0 z-50 flex w-[min(1040px,100vw)] flex-col border-l border-line2 bg-raised text-[12px] text-fg"
                initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
                transition={{ duration: 0.24, ease: easeOutInk }}
              >
                <header className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
                  <Dialog.Title className="font-head text-[16px]">Full package</Dialog.Title>
                  <span className="text-fg3">
                    YouTube long-form · v{pkg.version} · {ago(pkg.created_at)}
                  </span>
                  <div className="ml-auto flex flex-wrap items-center gap-1.5">
                    <a href={exportUrl(video.id)} download className={btn}>
                      <FileDown aria-hidden="true" size={14} />
                      Export Markdown
                    </a>
                    <Dialog.Close className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3" aria-label="Close">
                      <X aria-hidden="true" size={16} />
                    </Dialog.Close>
                  </div>
                </header>

                <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-4 py-2">
                  {pkg.stale ? (
                    <span className="flex items-center gap-1.5 text-warn">
                      <AlertTriangle aria-hidden="true" size={13} />
                      Out of date: facts, events or research changed since this was written.
                    </span>
                  ) : (
                    <span className="text-fg3">
                      {pkg.counts.block ? `${pkg.counts.block} blocked · ` : ""}
                      {pkg.counts.warn} {pkg.counts.warn === 1 ? "warning" : "warnings"} open
                    </span>
                  )}
                  <label className="ml-auto flex min-h-11 items-center gap-2 text-fg2">
                    <input
                      type="checkbox"
                      checked={replaceEdits}
                      onChange={(e) => setReplaceEdits(e.target.checked)}
                      className="h-4 w-4 accent-[var(--accent-fill)]"
                    />
                    Replace my edits
                  </label>
                  <button
                    type="button"
                    disabled={!!regenBlocked || regenerate.isPending}
                    title={regenBlocked ?? "Write the whole package again (one Claude call)"}
                    onClick={() => regenerate.mutate({ id: pkg.id, body: { all: true, replace_edits: replaceEdits } })}
                    className={`${btn} border-accentfill bg-accentfill font-semibold text-onaccent`}
                  >
                    {running || regenerate.isPending ? (
                      <Loader2 aria-hidden="true" size={13} className="animate-spin" />
                    ) : (
                      <Sparkles aria-hidden="true" size={13} />
                    )}
                    {running ? "Writing…" : "Regenerate all"}
                  </button>
                  {regenerate.error ? (
                    <span role="alert" className="w-full rounded-[8px] border border-accent px-2 py-1.5 text-fg">
                      {regenerate.error.message}
                    </span>
                  ) : null}
                </div>

                <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto min-[900px]:grid-cols-[minmax(0,1fr)_340px]">
                  <div className="flex min-w-0 flex-col px-4">
                    <FieldBlock
                      pkg={pkg}
                      videoId={video.id}
                      label="Title"
                      path="title"
                      field="title"
                      value={f.title}
                      limit={LIMITS.title}
                      regenerateBlocked={regenBlocked}
                      hint={f.title_why || undefined}
                      goal={f.title_goal}
                    />
                    {f.title_alternates.length ? (
                      <section aria-label="Alternate titles" className="flex flex-col gap-1.5 border-b border-line py-3">
                        <h3 className="text-[12.5px] font-semibold">Alternate titles</h3>
                        <ul className="flex flex-col gap-2">
                          {f.title_alternates.map((a, i) => {
                            const path = `title_alternates[${i}]`;
                            const blocked = isBlocked(pkg, path);
                            const alts = resultsFor(pkg, path).filter((r) => r.severity !== "pass");
                            return (
                              <li key={path} className="flex flex-col gap-1 rounded-[10px] border p-2.5" style={{ borderColor: blocked ? "var(--accent)" : "var(--line-2)" }}>
                                <span className="break-words text-[13px] text-fg">
                                  <ClaimText text={a.text} marks={claimMarks(pkg, path)} />
                                </span>
                                <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-fg3">
                                  <GoalChip goal={a.goal} />
                                  <span className="tnum">{a.text.length} / 100</span>
                                  {a.why ? <span>· {a.why}</span> : null}
                                </span>
                                {alts.length ? (
                                  <ul className="flex flex-wrap gap-1.5">
                                    {alts.map((r) => (
                                      <li key={r.key}>
                                        <RuleBadge result={r} showField={false} />
                                      </li>
                                    ))}
                                  </ul>
                                ) : null}
                                <span className="self-end">
                                  <SweepCopy text={a.text} disabled={blocked} disabledReason="Blocked by a rule" compact label={`Copy alternate title ${i + 1}`} />
                                </span>
                              </li>
                            );
                          })}
                        </ul>
                      </section>
                    ) : null}
                    <FieldBlock pkg={pkg} videoId={video.id} label="Hook line" path="hook_line" field="hook_line" value={f.hook_line} multiline regenerateBlocked={regenBlocked} count={f.hook_line.length} />
                    <FieldBlock pkg={pkg} videoId={video.id} label="Description" path="description" field="description" value={f.description} limit={LIMITS.description} multiline regenerateBlocked={regenBlocked} />
                    <FieldBlock
                      pkg={pkg}
                      videoId={video.id}
                      label="Chapters"
                      path="chapters"
                      field="chapters"
                      value={f.chapters}
                      multiline
                      regenerateBlocked={regenBlocked}
                      hint={f.chapters ? "One per line, “m:ss Label”. First at 0:00, at least 3, each 10 s apart." : "The video has fewer than three valid sections, so the description has no chapters."}
                      display={
                        f.chapter_list.length ? (
                          <ul className="flex flex-col">
                            {f.chapter_list.map((c) => (
                              <li key={`${c.t}-${c.label}`} className="flex gap-2">
                                <button type="button" onClick={() => seek(c.t)} className="tnum text-accentsoft underline-offset-2 hover:underline" aria-label={`Seek to ${clock(c.t, 0)}`}>
                                  {clock(c.t, 0)}
                                </button>
                                <span>{c.label}</span>
                              </li>
                            ))}
                          </ul>
                        ) : undefined
                      }
                    />
                    <FieldBlock
                      pkg={pkg}
                      videoId={video.id}
                      label="Tags"
                      path="tags"
                      field="tags"
                      value={f.tags.join(", ")}
                      count={tagsLength(f.tags)}
                      limit={LIMITS.tags}
                      multiline
                      regenerateBlocked={regenBlocked}
                      hint={`${f.tags.length} tags, separated by commas`}
                      display={
                        f.tags.length ? (
                          <ul className="flex flex-wrap gap-1">
                            {f.tags.map((t) => (
                              <li key={t} className="rounded-[8px] bg-surface2 px-1.5 py-0.5 text-[11.5px] text-fg2">
                                {t}
                              </li>
                            ))}
                          </ul>
                        ) : undefined
                      }
                    />
                    <FieldBlock pkg={pkg} videoId={video.id} label="Hashtags" path="hashtags" field="hashtags" value={f.hashtags.join(" ")} regenerateBlocked={regenBlocked} hint="Separated by spaces" />
                    <FieldBlock pkg={pkg} videoId={video.id} label="Opening 5 seconds" path="opening_5s" field="opening_5s" value={f.opening_5s} multiline regenerateBlocked={regenBlocked} />
                    <FieldBlock pkg={pkg} videoId={video.id} label="Pinned comment" path="pinned_comment" field="pinned_comment" value={f.pinned_comment} multiline limit={LIMITS.pinned_comment} regenerateBlocked={regenBlocked} />
                    <FieldBlock pkg={pkg} videoId={video.id} label="Community post" path="community_post" field="community_post" value={f.community_post} multiline regenerateBlocked={regenBlocked} />
                    <FieldBlock pkg={pkg} videoId={video.id} label="Credit block" path="credit_block" value={f.credit_block} hint="From the research fields the preset credits; part of the description." />
                  </div>

                  <aside className="flex min-w-0 flex-col gap-4 border-line px-4 py-3 min-[900px]:border-l">
                    <SearchPreview pkg={pkg} video={video} channel={status.data?.channel ?? null} />

                    <section aria-labelledby="pd-thumb" className="flex flex-col gap-2">
                      <h3 id="pd-thumb" className="text-[12.5px] font-semibold">
                        Thumbnail
                      </h3>
                      {f.thumbnail.frame_ts.length ? (
                        <ul className="grid grid-cols-3 gap-1.5" aria-label="Suggested frames">
                          {f.thumbnail.frame_ts.map((t) => (
                            <li key={t}>
                              <button
                                type="button"
                                onClick={() => seek(t)}
                                className="ink-btn flex w-full flex-col gap-0.5 rounded-[8px] text-left"
                                aria-label={`Show the frame at ${clock(t)} in the preview`}
                              >
                                {/* eslint-disable-next-line @next/next/no-img-element -- a frame cut on demand by the API */}
                                <img src={frameUrl(video.id, t, 320)} alt="" className="aspect-video w-full rounded-[6px] bg-stage object-cover" />
                                <span className="tnum text-[11px] text-accentsoft">{clock(t)}</span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="text-fg3">No frames suggested.</span>
                      )}
                      {f.thumbnail.word_options.length ? (
                        <div className="flex flex-col gap-1">
                          <span className="text-[11px] text-fg3">Word options</span>
                          <ul className="flex flex-wrap gap-1.5">
                            {f.thumbnail.word_options.map((w, i) => {
                              const path = `thumbnail.word_options[${i}]`;
                              const blocked = isBlocked(pkg, path);
                              return (
                                <li key={`${w}-${i}`} className="flex items-center gap-1 rounded-[8px] border px-2 py-1 font-semibold tracking-wide" style={{ borderColor: blocked ? "var(--accent)" : "var(--line-3)" }}>
                                  <ClaimText text={w} marks={claimMarks(pkg, path)} />
                                </li>
                              );
                            })}
                          </ul>
                          {f.thumbnail.text_style ? <span className="text-[11px] text-fg3">Text style: {f.thumbnail.text_style}</span> : null}
                        </div>
                      ) : null}
                      {f.thumbnail.prompt ? (
                        <div className="flex flex-col gap-1">
                          <span className="text-[11px] text-fg3">Prompt for an image tool</span>
                          <p className="whitespace-pre-wrap break-words rounded-[10px] bg-surface p-2.5 text-fg2">{f.thumbnail.prompt}</p>
                          <span className="self-start">
                            <SweepCopy text={f.thumbnail.prompt} label="Copy prompt" />
                          </span>
                        </div>
                      ) : null}
                    </section>

                    <section aria-labelledby="pd-end" className="flex flex-col gap-1.5">
                      <h3 id="pd-end" className="text-[12.5px] font-semibold">
                        End screen
                      </h3>
                      <span className="text-fg2">{f.end_screen_target.label}</span>
                      {f.end_screen_target.url ? (
                        <a href={f.end_screen_target.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 self-start text-accentsoft underline">
                          {f.end_screen_target.title ?? f.end_screen_target.url}
                          <ExternalLink aria-hidden="true" size={12} />
                        </a>
                      ) : null}
                    </section>

                    <section aria-labelledby="pd-check" className="flex flex-col gap-1.5">
                      <h3 id="pd-check" className="text-[12.5px] font-semibold">
                        Before you publish
                      </h3>
                      <ul className="flex flex-col">
                        {f.checklist.map((c) => (
                          <li key={c.item}>
                            <label className="flex min-h-11 items-start gap-2 py-1.5">
                              <input
                                type="checkbox"
                                checked={!!checked[c.item]}
                                onChange={(e) => setChecked((s) => ({ ...s, [c.item]: e.target.checked }))}
                                className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--ok)]"
                              />
                              <span className={checked[c.item] ? "text-fg4 line-through" : "text-fg2"}>
                                <span className="font-semibold text-fg">{c.item}</span> · {c.detail}
                              </span>
                            </label>
                          </li>
                        ))}
                      </ul>
                      <span className="text-[11px] text-fg4">Ticks are not saved.</span>
                    </section>
                  </aside>
                </div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        ) : null}
      </AnimatePresence>
    </Dialog.Root>
  );
}
