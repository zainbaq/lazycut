"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowLeft, ChevronDown, ClipboardPaste, Clock3, KeyRound, Loader2, RotateCcw, Search, SpellCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { ErrorCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { ApiError } from "@/lib/api";
import { ago } from "@/lib/format";
import { panelRise } from "@/lib/motion";
import {
  isActive,
  jobOf,
  useEditResearchField,
  useResearch,
  useRetryJob,
  useRevertSpelling,
  useRunResearch,
  useVideo,
} from "@/lib/queries";
import { useVideoUpdates } from "@/lib/sse";
import type { Job, Research, Video } from "@/lib/types";

import { Competitors } from "./Competitors";
import { FieldRow, SourceChip } from "./FieldRow";

const MAX_PASTE = 20000;

/** Re-render every 30 s so "2 min ago" stays true. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function methodLine(r: Research, now: number): string {
  if (r.method === "search") return `Researched ${ago(r.updated_at, now)} · web search`;
  if (r.method === "pasted") return `From your notes · ${ago(r.updated_at, now)}`;
  return "Not researched yet";
}

function BusyLine({ job: latest }: { job: Job | undefined }) {
  const job = isActive(latest) ? latest : undefined; // a finished job's message would be stale here
  return (
    <div role="status" className="relative flex items-center gap-2 overflow-hidden rounded-[12px] bg-surface px-3.5 py-3 text-fg2">
      <Clock3 aria-hidden="true" size={14} className="shrink-0 text-accentsoft" />
      <span className="truncate">{job?.message || (job?.status === "queued" ? "Queued" : "Researching…")}</span>
      <span aria-hidden="true" className="absolute bottom-0 left-0 h-[2px] w-full bg-line2">
        <span className="ink-busy-bar block h-full bg-accent" />
      </span>
    </div>
  );
}

function Heading({ video, research, job, now }: { video: Video; research: Research | undefined; job: Job | undefined; now: number }) {
  const run = useRunResearch(video.id);
  const running = !!research?.running || isActive(job);
  const canSearch = research?.can_search ?? false;
  const reason = !research ? null : !canSearch ? "Needs ANTHROPIC_API_KEY in .env" : running ? "Research is running" : null;
  const first = research?.method === "none";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h1 className="font-head text-[22px] leading-tight">
            {video.subject || video.title}
            {video.topic ? <span className="text-fg3"> · {video.topic}</span> : null}
          </h1>
          <span className="text-fg3">{research ? methodLine(research, now) : " "}</span>
        </div>
        <div className="flex flex-col items-start gap-1 min-[720px]:items-end">
          <button
            type="button"
            disabled={!research || !!reason || run.isPending}
            onClick={() => run.mutate({})}
            aria-describedby={reason ? "research-run-reason" : "research-run-cost"}
            className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:border-line3 disabled:bg-transparent disabled:text-fg3"
          >
            {run.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : first ? <Search aria-hidden="true" size={14} /> : <RotateCcw aria-hidden="true" size={14} />}
            {first ? "Research" : "Research again"}
          </button>
          {reason ? (
            <span id="research-run-reason" className="text-[11px] text-fg3">
              {reason}
            </span>
          ) : (
            <span id="research-run-cost" className="text-[11px] text-fg4">
              One Claude call with web search. Your edits are kept.
            </span>
          )}
        </div>
      </div>
      {run.error ? <ErrorCard title="Research did not start" message={run.error.message} /> : null}
      {running ? <BusyLine job={job} /> : null}
    </div>
  );
}

function CorrectionBanner({ research, videoId }: { research: Research; videoId: string }) {
  const revert = useRevertSpelling(videoId);
  if (!research.correction) return null;
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 rounded-[12px] border border-line2 bg-surface px-3.5 py-2.5">
      <SpellCheck aria-hidden="true" size={16} className="shrink-0 text-accentsoft" />
      <span className="min-w-0 flex-1 basis-[220px] text-fg2">
        Corrected from <span className="text-fg">“{research.correction.from}”</span> to{" "}
        <span className="text-fg">“{research.correction.to}”</span>, the spelling the sources use.
      </span>
      <button
        type="button"
        disabled={revert.isPending}
        onClick={() => revert.mutate()}
        className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px] disabled:opacity-60"
      >
        <RotateCcw aria-hidden="true" size={14} />
        Keep my spelling
      </button>
      {revert.error ? (
        <span role="alert" className="w-full text-[12px] text-accentsoft">
          {revert.error.message}
        </span>
      ) : null}
    </div>
  );
}

function PastePanel({ research, videoId, running }: { research: Research; videoId: string; running: boolean }) {
  const reduced = useReducedMotion();
  const run = useRunResearch(videoId);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const textId = useId();
  const urlId = useId();
  const countId = useId();
  const canSubmit = research.can_search && !running && !run.isPending && text.trim().length > 0;

  return (
    <section aria-label="Paste notes instead" className="rounded-[12px] bg-surface px-3.5 py-1">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex min-h-11 w-full items-center gap-2 text-[13px] font-semibold text-fg"
      >
        <ClipboardPaste aria-hidden="true" size={14} className="text-accentsoft" />
        Paste notes instead
        <span className="ml-auto text-[11px] font-normal text-fg3">no web search</span>
        <ChevronDown aria-hidden="true" size={14} className="text-fg3 transition-transform duration-200" style={{ transform: open ? "rotate(180deg)" : undefined }} />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.form
            key="paste"
            {...(reduced ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } } : panelRise)}
            className="flex flex-col gap-2.5 pb-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!canSubmit) return;
              run.mutate(
                { pasted_text: text, source_url: url.trim() || undefined },
                { onSuccess: () => setOpen(false) },
              );
            }}
          >
            <span className="text-fg3">
              Paste text from a wiki or guide. Claude sorts it into the fields below without searching the web; your
              edits are kept.
            </span>
            <label htmlFor={textId} className="text-[12px] font-semibold text-fg2">
              Notes
            </label>
            <textarea
              id={textId}
              value={text}
              maxLength={MAX_PASTE}
              rows={7}
              aria-describedby={countId}
              onChange={(e) => setText(e.target.value)}
              className="w-full resize-y rounded-[10px] border border-line3 bg-bg p-3 text-[13px] text-fg outline-none focus:border-accent"
            />
            <span id={countId} className="tnum self-end text-[11px] text-fg4">
              {text.length.toLocaleString()} / {MAX_PASTE.toLocaleString()}
            </span>
            <label htmlFor={urlId} className="text-[12px] font-semibold text-fg2">
              Where it came from <span className="font-normal text-fg4">(optional URL)</span>
            </label>
            <input
              id={urlId}
              type="url"
              inputMode="url"
              value={url}
              maxLength={2000}
              placeholder="https://"
              onChange={(e) => setUrl(e.target.value)}
              className="min-h-11 w-full rounded-[10px] border border-line3 bg-bg px-3 text-[13px] text-fg outline-none focus:border-accent"
            />
            {!research.can_search ? (
              <span className="text-[12px] text-fg3">Sorting notes also needs ANTHROPIC_API_KEY. You can still type each value in below.</span>
            ) : null}
            {run.error ? (
              <span role="alert" className="rounded-[10px] border border-accent px-2.5 py-2 text-fg">
                {run.error.message}
              </span>
            ) : null}
            <button
              type="submit"
              disabled={!canSubmit}
              className="ink-btn flex min-h-11 items-center gap-1.5 self-start rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:border-line3 disabled:bg-transparent disabled:text-fg3"
            >
              {run.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <ClipboardPaste aria-hidden="true" size={14} />}
              Sort my notes
            </button>
          </motion.form>
        ) : null}
      </AnimatePresence>
    </section>
  );
}

function NoKeyCard() {
  return (
    <div className="flex flex-col gap-1.5 rounded-[12px] border border-warnline bg-surface p-3.5">
      <span className="flex items-center gap-1.5 text-[13px] font-semibold text-warn">
        <KeyRound aria-hidden="true" size={14} />
        Automatic research is off
      </span>
      <span className="text-fg2">
        Set <code className="rounded bg-surface2 px-1 py-0.5 text-fg">ANTHROPIC_API_KEY</code> in{" "}
        <code className="rounded bg-surface2 px-1 py-0.5 text-fg">.env</code> to research automatically. You can still type
        each value in by hand below.
      </span>
    </div>
  );
}

function Sources({ research }: { research: Research }) {
  const credible = research.sources.filter((s) => s.rating === "credible").length;
  return (
    <section aria-labelledby="sources-heading" className="flex flex-col gap-2.5">
      <h2 id="sources-heading" className="font-head text-[16px]">
        Pages read <span className="text-[12px] font-normal text-fg3">· {research.sources.length}</span>
      </h2>
      {research.sources.length ? (
        <ul className="flex flex-col">
          {research.sources.map((s) => (
            <li key={s.url} className="flex flex-col gap-1 border-b border-line py-2 last:border-b-0 min-[720px]:flex-row min-[720px]:items-center min-[720px]:gap-3">
              <span className="min-w-0 flex-1 truncate text-fg2" title={s.title || s.url}>
                {s.title || s.url}
              </span>
              <span className="shrink-0">
                <SourceChip source={s} />
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-fg3">No pages yet.</span>
      )}
      <span className="text-[11px] text-fg4">
        A source counts as credible when its site is listed under <code className="text-fg3">credible_domains</code> in{" "}
        <code className="text-fg3">config/channel.yaml</code>; every other site is unrated.
        {research.sources.length && !credible ? " None of these sites is on that list yet, so fields that need a credible source stay unused until you set them." : ""}
      </span>
    </section>
  );
}

function Skeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading research">
      <span className="ink-skeleton block h-12 rounded-[12px]" />
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} className="ink-skeleton block h-14 rounded-[12px]" />
      ))}
    </div>
  );
}

/** `/v/[id]/research`: subject facts with sources and edit controls (BUILD_SPEC 7.7, 9.2). */
export function ResearchPage({ id }: { id: string }) {
  const now = useNow();
  const video = useVideo(id);
  const research = useResearch(id);
  const edit = useEditResearchField(id);
  const retry = useRetryJob(id);
  useVideoUpdates(id, video.isSuccess);

  const job = jobOf(video.data, "research");
  const running = !!research.data?.running || isActive(job);

  if (video.error) {
    const missing = video.error instanceof ApiError && video.error.status === 404;
    return (
      <div className="flex min-h-screen">
        <Rail section="research" />
        <main className="flex max-w-xl flex-1 flex-col gap-3 p-6">
          <ErrorCard
            title={missing ? "Video not found" : "Could not load the video"}
            message={missing ? "It may have been deleted." : video.error.message}
            onRetry={missing ? undefined : () => void video.refetch()}
          />
          <Link href="/" className="text-accentsoft underline">
            Back to the library
          </Link>
        </main>
      </div>
    );
  }

  const v = video.data;
  const r = research.data;
  const found = r ? r.fields.filter((f) => f.value !== null).length : 0;
  const failed = job?.status === "error" ? job : undefined;

  return (
    <div className="flex min-h-screen">
      <Rail section="research" videoId={id} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
            <Link href="/" className="py-3.5 text-fg">
              Library
            </Link>
            <span aria-hidden="true" className="text-fg4">
              /
            </span>
            <Link href={`/v/${id}`} className="truncate py-3.5 text-fg" title={v?.title}>
              {v ? [v.subject, v.topic].filter(Boolean).join(" · ") || v.title : "…"}
            </Link>
            <span aria-hidden="true" className="text-fg4">
              /
            </span>
            <span className="text-fg3">Research</span>
          </nav>
          <Link
            href={`/v/${id}`}
            className="ink-btn ml-auto flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px]"
          >
            <ArrowLeft aria-hidden="true" size={14} />
            Workspace
          </Link>
        </header>

        <main className="mx-auto flex w-full max-w-[880px] flex-col gap-4 px-4 py-5 min-[720px]:px-6">
          {!v ? (
            <Skeleton />
          ) : (
            <>
              <Heading video={v} research={r} job={job} now={now} />
              {failed && !running ? (
                <ErrorCard
                  title="Research failed"
                  message={failed.error || failed.message || "The job stopped without a message."}
                  onRetry={() => retry.mutate(failed.id)}
                  retrying={retry.isPending}
                />
              ) : null}
              {research.error ? (
                <ErrorCard title="Could not load the research" message={research.error.message} onRetry={() => void research.refetch()} />
              ) : !r ? (
                <Skeleton />
              ) : (
                <>
                  {!r.can_search ? <NoKeyCard /> : null}
                  <CorrectionBanner research={r} videoId={id} />
                  {r.method === "none" && !running ? (
                    <div className="flex flex-col gap-1 rounded-[12px] border border-dashed border-line3 p-3.5 text-fg3">
                      <span className="text-[13px] font-semibold text-fg2">Not researched yet</span>
                      <span>
                        {r.can_search
                          ? "Research looks up the subject's correct name, who it is and where it appears, each with its source. Or type values in below."
                          : "Type values in below, or paste notes once a key is set."}
                      </span>
                    </div>
                  ) : null}
                  <section aria-labelledby="fields-heading" className="flex flex-col gap-1">
                    <div className="flex items-baseline gap-2">
                      <h2 id="fields-heading" className="font-head text-[16px]">
                        Fields
                      </h2>
                      <span className="text-[12px] text-fg3">
                        {found} of {r.fields.length} found · accepted as found, change any of them
                      </span>
                    </div>
                    {r.fields.length ? (
                      <ul className="flex flex-col rounded-[12px] bg-surface px-3.5">
                        {r.fields.map((f) => (
                          <FieldRow key={f.key} field={f} pending={edit.isPending && edit.variables?.key === f.key} onEdit={(body) => edit.mutate(body)} />
                        ))}
                      </ul>
                    ) : (
                      <span className="text-fg3">This preset has no research fields.</span>
                    )}
                    {edit.error ? (
                      <span role="alert" className="mt-1 rounded-[10px] border border-accent px-2.5 py-2 text-fg">
                        {edit.error.message}
                      </span>
                    ) : null}
                  </section>
                  {r.fields.length ? <PastePanel research={r} videoId={id} running={running} /> : null}
                  <Sources research={r} />
                  <Competitors video={v} />
                </>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
