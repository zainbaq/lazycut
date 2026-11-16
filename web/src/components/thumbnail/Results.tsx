"use client";

import { AlertTriangle, Check, CircleCheck, Download, Loader2, PenLine, RotateCcw, ShieldAlert, Star, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { apiUrl, thumbDownloadUrl } from "@/lib/api";
import { ago, clock } from "@/lib/format";
import { useAdjustThumbnail, useDeleteThumbnail, useReviewThumbnail } from "@/lib/queries";
import type { Corner, ThumbFont, Thumbnail, ThumbnailState, ThumbReview } from "@/lib/types";

import { CHECK_LABELS, CORNER_LABELS, CORNERS, CornerGlyph, FONT_LABELS, SectionTitle, money, modelLabel } from "./bits";

function Verdict({ review }: { review: ThumbReview | null }) {
  if (!review || review.verdict == null) {
    return <span className="rounded-full border border-line3 px-2 py-0.5 text-[11px] text-fg3">Not reviewed</span>;
  }
  if (review.verdict === "ok") {
    return (
      <span className="flex items-center gap-1 rounded-full border border-okline bg-okbg px-2 py-0.5 text-[11px] text-oktext">
        <CircleCheck aria-hidden="true" size={12} />
        Looks clean
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 rounded-full border border-warnline px-2 py-0.5 text-[11px] text-warn">
      <ShieldAlert aria-hidden="true" size={12} />
      {review.problems ?? 1} to check
    </span>
  );
}

function Checks({ review }: { review: ThumbReview }) {
  const rows = [...review.checks, ...(review.code ?? [])];
  if (!rows.length) return null;
  return (
    <div className="flex flex-col gap-1">
      {review.summary ? <span className="text-[12px] text-fg2">{review.summary}</span> : null}
      <ul className="flex flex-col">
        {rows.map((c) => (
          <li key={c.id} className="flex items-start gap-1.5 py-0.5 text-[11px]">
            {c.ok ? (
              <Check aria-hidden="true" size={12} className="mt-0.5 shrink-0 text-ok" />
            ) : (
              <AlertTriangle aria-hidden="true" size={12} className="mt-0.5 shrink-0 text-warn" />
            )}
            <span className="sr-only">{c.ok ? "Passed:" : "Problem:"}</span>
            <span className={c.ok ? "text-fg3" : "text-fg"}>
              <span className="font-semibold">{CHECK_LABELS[c.id] ?? c.id}</span> · {c.note}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function WordEditor({ thumb, videoId, onDone }: { thumb: Thumbnail; videoId: string; onDone: () => void }) {
  const adjust = useAdjustThumbnail(videoId);
  const [word, setWord] = useState(thumb.word);
  const [corner, setCorner] = useState<Corner>(thumb.text_corner);
  const [font, setFont] = useState<ThumbFont>(thumb.font);
  const [style, setStyle] = useState(thumb.text_style);
  const ids = { word: useId(), corner: useId(), font: useId(), style: useId() };
  const changed = word !== thumb.word || corner !== thumb.text_corner || font !== thumb.font || style !== thumb.text_style;
  const input = "min-h-11 w-full rounded-[10px] border border-line3 bg-bg px-3 text-[13px] text-fg outline-none focus:border-accent";
  return (
    <form
      className="flex flex-col gap-2 rounded-[10px] border border-line2 bg-bg p-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!changed) return onDone();
        adjust.mutate({ id: thumb.id, body: { word: word.trim(), text_corner: corner, font, text_style: style.trim() } }, { onSuccess: onDone });
      }}
    >
      <div className="grid grid-cols-1 gap-2 min-[480px]:grid-cols-2">
        <label htmlFor={ids.word} className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold text-fg2">Word</span>
          <input id={ids.word} value={word} maxLength={40} onChange={(e) => setWord(e.target.value.toUpperCase())} className={input + " font-semibold tracking-wide"} />
        </label>
        <label htmlFor={ids.style} className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold text-fg2">Style</span>
          <input id={ids.style} value={style} maxLength={120} placeholder="white, heavy black outline" onChange={(e) => setStyle(e.target.value)} className={input} />
        </label>
        <label htmlFor={ids.corner} className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold text-fg2">Corner</span>
          <select id={ids.corner} value={corner} onChange={(e) => setCorner(e.target.value as Corner)} className={input}>
            {CORNERS.map((c) => (
              <option key={c} value={c}>
                {CORNER_LABELS[c]}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={ids.font} className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold text-fg2">Font</span>
          <select id={ids.font} value={font} onChange={(e) => setFont(e.target.value as ThumbFont)} className={input}>
            {(Object.keys(FONT_LABELS) as ThumbFont[]).map((f) => (
              <option key={f} value={f}>
                {FONT_LABELS[f]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {adjust.error ? (
        <span role="alert" className="rounded-[10px] border border-accent px-2.5 py-2 text-[12px] text-fg">
          {adjust.error.message}
        </span>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" disabled={adjust.isPending} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:opacity-60">
          {adjust.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <PenLine aria-hidden="true" size={14} />}
          Redraw
        </button>
        <button type="button" onClick={onDone} className="ink-btn flex min-h-11 items-center rounded-[10px] border border-line3 px-3.5 text-[12px]">
          Cancel
        </button>
        <span className="text-[11px] text-fg4">Free: no model call.</span>
      </div>
    </form>
  );
}

function ResultCard({ thumb, state, videoId }: { thumb: Thumbnail; state: ThumbnailState; videoId: string }) {
  const adjust = useAdjustThumbnail(videoId);
  const review = useReviewThumbnail(videoId);
  const del = useDeleteThumbnail(videoId);
  const [view, setView] = useState<"final" | "raw">("final");
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showChecks, setShowChecks] = useState(false);
  useEffect(() => {
    if (!confirmDelete) return;
    const t = setTimeout(() => setConfirmDelete(false), 4000);
    return () => clearTimeout(t);
  }, [confirmDelete]);

  const done = thumb.status === "done";
  const working = thumb.status === "queued" || thumb.status === "running";
  const src = view === "raw" ? thumb.urls.raw : thumb.urls.final;
  const tall = thumb.aspect === "9:16";
  const r = thumb.review;
  const label = modelLabel(state.settings, thumb.model);

  return (
    <article
      aria-label={`${label}, ${thumb.aspect}${thumb.chosen ? ", chosen" : ""}`}
      className={"flex min-w-0 flex-col gap-2 rounded-[12px] border bg-surface p-2.5 " + (thumb.chosen ? "border-gold" : "border-line2")}
    >
      <div className={"relative overflow-hidden rounded-[10px] bg-stage " + (tall ? "mx-auto aspect-[9/16] w-full max-w-[220px]" : "aspect-video w-full")}>
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- generated images come from the local API
          <img src={apiUrl(src)} alt={`${label} thumbnail${thumb.word ? ` with “${thumb.word}”` : ""}${view === "raw" ? ", as the model returned it" : ""}`} className="h-full w-full object-cover" />
        ) : null}
        {working ? (
          <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-stage/80 text-fg2">
            <Loader2 aria-hidden="true" size={20} className="animate-spin text-accentsoft" />
            <span className="text-[12px]">{thumb.status === "queued" ? "Queued" : `${label} is painting…`}</span>
            <span aria-hidden="true" className="absolute bottom-0 left-0 h-[2px] w-full bg-line2">
              <span className="ink-busy-bar block h-full bg-accent" />
            </span>
          </div>
        ) : null}
        {thumb.status === "failed" || thumb.status === "nsfw" ? (
          <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 p-3 text-center">
            <AlertTriangle aria-hidden="true" size={18} className="text-accentsoft" />
            <span className="text-[12px] text-fg">{thumb.status === "nsfw" ? "Stopped by the safety filter" : "Failed"}</span>
            <span className="line-clamp-4 text-[11px] text-fg3">{thumb.error}</span>
          </div>
        ) : null}
        {thumb.chosen ? (
          <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded-full bg-gold px-2 py-0.5 text-[11px] font-semibold text-notefg">
            <Star aria-hidden="true" size={11} />
            Chosen
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
        <span className="font-semibold text-fg">{label}</span>
        <span className="text-fg3">{thumb.aspect}</span>
        {thumb.cost_usd != null ? <span className="tnum text-fg4">{money(thumb.cost_usd)}</span> : null}
        {thumb.custom_prompt ? <span className="text-fg4">own prompt</span> : null}
        <span className="ml-auto">{done ? <Verdict review={r} /> : null}</span>
      </div>
      {done && thumb.word ? (
        <span className="flex items-center gap-1.5 text-[11px] text-fg3">
          <CornerGlyph corner={thumb.text_corner} size={10} />“{thumb.word}” · {thumb.text_mode === "app" ? FONT_LABELS[thumb.font] : "drawn by the model"}
        </span>
      ) : null}

      {done && r ? (
        <div className="flex flex-col gap-1.5">
          {r.stale ? (
            <span className="flex flex-wrap items-center gap-2 text-[11px] text-warn">
              The word changed since this review.
              {state.can_review ? (
                <button
                  type="button"
                  disabled={review.isPending || state.running}
                  onClick={() => review.mutate(thumb.id)}
                  className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px] text-fg disabled:opacity-60"
                >
                  {review.isPending ? <Loader2 aria-hidden="true" size={13} className="animate-spin" /> : <RotateCcw aria-hidden="true" size={13} />}
                  Review again
                </button>
              ) : null}
            </span>
          ) : null}
          {r.checks.length || r.code?.length ? (
            <button type="button" aria-expanded={showChecks} onClick={() => setShowChecks(!showChecks)} className="flex min-h-11 items-center self-start text-[12px] text-accentsoft underline-offset-2 hover:underline">
              {showChecks ? "Hide checks" : "Show checks"}
            </button>
          ) : null}
          {showChecks ? <Checks review={r} /> : null}
          {review.error ? (
            <span role="alert" className="text-[12px] text-accentsoft">
              {review.error.message}
            </span>
          ) : null}
        </div>
      ) : null}

      {editing ? <WordEditor thumb={thumb} videoId={videoId} onDone={() => setEditing(false)} /> : null}

      {adjust.error ? (
        <span role="alert" className="rounded-[10px] border border-accent px-2.5 py-2 text-[12px] text-fg">
          {adjust.error.message}
        </span>
      ) : null}
      {del.error ? (
        <span role="alert" className="text-[12px] text-accentsoft">
          {del.error.message}
        </span>
      ) : null}

      <div className="mt-auto flex flex-wrap gap-1.5">
        {done ? (
          <>
            <button
              type="button"
              aria-pressed={thumb.chosen}
              disabled={adjust.isPending}
              onClick={() => adjust.mutate({ id: thumb.id, body: { chosen: !thumb.chosen } })}
              className={
                "ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border px-3 text-[12px] font-semibold disabled:opacity-60 " +
                (thumb.chosen ? "border-gold text-goldtext" : "border-accentfill bg-accentfill text-onaccent")
              }
            >
              <Star aria-hidden="true" size={13} />
              {thumb.chosen ? "Chosen" : "Choose"}
            </button>
            {thumb.text_mode === "app" && !editing ? (
              <button type="button" onClick={() => setEditing(true)} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px]">
                <PenLine aria-hidden="true" size={13} />
                Word
              </button>
            ) : null}
            {thumb.urls.raw ? (
              <button
                type="button"
                aria-pressed={view === "raw"}
                onClick={() => setView(view === "raw" ? "final" : "raw")}
                className="ink-btn flex min-h-11 items-center rounded-[10px] border border-line3 px-3 text-[12px]"
              >
                {view === "raw" ? "Show final" : "Show raw"}
              </button>
            ) : null}
            <a href={thumbDownloadUrl(thumb.id)} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px]">
              <Download aria-hidden="true" size={13} />
              Download
            </a>
          </>
        ) : null}
        {!working ? (
          <button
            type="button"
            disabled={del.isPending}
            onClick={() => (confirmDelete ? del.mutate(thumb.id) : setConfirmDelete(true))}
            aria-label={confirmDelete ? "Confirm delete" : "Delete thumbnail"}
            className={
              "ink-btn ml-auto flex min-h-11 items-center gap-1.5 rounded-[10px] border px-3 text-[12px] disabled:opacity-60 " +
              (confirmDelete ? "border-accent text-accentsoft" : "border-line3 text-fg3")
            }
          >
            <Trash2 aria-hidden="true" size={13} />
            {confirmDelete ? "Delete?" : null}
          </button>
        ) : null}
      </div>
    </article>
  );
}

/** Thumbnails grouped by the Generate click that made them, newest first. */
export function Results({ state, videoId }: { state: ThumbnailState; videoId: string }) {
  const groups: { batch: string; rows: Thumbnail[] }[] = [];
  for (const t of state.thumbnails) {
    const g = groups.find((x) => x.batch === t.batch_id);
    if (g) g.rows.push(t);
    else groups.push({ batch: t.batch_id, rows: [t] });
  }
  const chosen = state.thumbnails.filter((t) => t.chosen);
  return (
    <section aria-labelledby="results-heading" className="flex flex-col gap-3">
      <SectionTitle id="results-heading" aside={chosen.length ? `chosen: ${chosen.map((t) => t.aspect).join(" and ")}` : state.thumbnails.length ? "choose one per shape" : undefined}>
        Thumbnails
      </SectionTitle>
      {!groups.length ? (
        <span className="rounded-[12px] border border-dashed border-line3 p-3.5 text-fg3">
          Nothing generated yet. Pick a source, set the options and generate; results land here with Claude&apos;s check for
          faces, hands, leftover HUD and the word.
        </span>
      ) : (
        groups.map((g) => {
          const first = g.rows[0];
          const tall = g.rows.filter((t) => t.aspect === "9:16");
          const wide = g.rows.filter((t) => t.aspect === "16:9");
          return (
            <div key={g.batch} className="flex flex-col gap-2">
              <span className="text-[12px] text-fg3">
                {ago(first.created_at)} · {first.source_kind === "frame" ? `frame at ${clock(first.source_t)}` : "your upload"}
                {first.word ? ` · “${first.word}”` : " · no word"}
              </span>
              {wide.length ? (
                <div className="grid grid-cols-1 gap-2.5 min-[640px]:grid-cols-2 min-[1200px]:grid-cols-3">
                  {wide.map((t) => (
                    <ResultCard key={t.id} thumb={t} state={state} videoId={videoId} />
                  ))}
                </div>
              ) : null}
              {tall.length ? (
                <div className="grid grid-cols-2 gap-2.5 min-[640px]:grid-cols-3 min-[1200px]:grid-cols-5">
                  {tall.map((t) => (
                    <ResultCard key={t.id} thumb={t} state={state} videoId={videoId} />
                  ))}
                </div>
              ) : null}
            </div>
          );
        })
      )}
    </section>
  );
}
