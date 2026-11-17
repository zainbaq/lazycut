"use client";

import { AlertTriangle, Compass, Loader2, RefreshCw, Search, Sparkles, TrendingUp } from "lucide-react";

import { ErrorCard } from "@/components/ui/Cards";
import { jobOf, useCompetitors, useRunCompetitors } from "@/lib/queries";
import type { CompetitorMetrics, CompetitorReadOut, CompetitorVideo, Video } from "@/lib/types";

function k(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1).replace(/\.0$/, "")}k`;
  return String(Math.round(n));
}

function age(days: number): string {
  if (days < 2) return "1 day";
  if (days < 60) return `${days} days`;
  if (days < 730) return `${Math.round(days / 30)} months`;
  return `${Math.round(days / 365)} years`;
}

const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);

const CONCENTRATION = {
  spread: { label: "Spread out", note: "No channel owns this search: room for a small one", tone: "text-oktext" },
  moderate: { label: "Moderate", note: "A few channels hold most of the views", tone: "text-fg" },
  concentrated: { label: "Concentrated", note: "One or two channels hold most of the views", tone: "text-warn" },
} as const;

function Tile({ label, value, note, tone = "text-fg" }: { label: string; value: string; note: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-[10px] bg-surface px-3 py-2.5">
      <span className="text-[11px] text-fg3">{label}</span>
      <span className={`tnum font-head text-[18px] leading-tight ${tone}`}>{value}</span>
      <span className="text-[11px] leading-[1.35] text-fg3">{note}</span>
    </div>
  );
}

function FieldNumbers({ m }: { m: CompetitorMetrics }) {
  const c = m.concentration ? CONCENTRATION[m.concentration] : null;
  return (
    <div className="grid grid-cols-2 gap-2 min-[720px]:grid-cols-4">
      <Tile
        label="Who holds the views"
        value={c ? c.label : "–"}
        tone={c?.tone}
        note={c ? `${c.note}. Leader ${m.leader?.channel ?? ""} has ${pct(m.leader?.share)}.` : "No results"}
      />
      <Tile label="Small channels' share" value={pct(m.small_share)} note={`Views won by channels under 10k subscribers (${m.small_videos ?? 0} of ${m.videos} videos)`} />
      <Tile label="Posted in 30 days" value={String(m.recent_30d)} note={`Of the first ${m.videos}: how fresh the competition is`} />
      <Tile label="Median views a day" value={m.median_per_day == null ? "–" : k(m.median_per_day)} note={`${k(m.views)} views across the first page`} />
    </div>
  );
}

function ReadCard({ read }: { read: CompetitorReadOut }) {
  return (
    <div className="flex flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-3.5">
      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-accentsoft">
        <Sparkles aria-hidden="true" size={13} />
        Claude&apos;s read
      </span>
      <p className="text-[13px] leading-[1.55] text-fg">{read.read}</p>
      {read.unclaimed.length ? (
        <div className="flex flex-col gap-1.5">
          <h3 className="flex items-center gap-1.5 text-[12px] font-semibold text-fg2">
            <Compass aria-hidden="true" size={13} />
            Angles nobody on the first page takes
          </h3>
          <ul className="flex flex-col gap-1.5">
            {read.unclaimed.map((u) => (
              <li key={u.angle} className="flex flex-col gap-0.5 rounded-[10px] bg-surface px-3 py-2" style={u.blocked_by.length ? { outline: "1px solid var(--warn-line)" } : undefined}>
                <span className="text-[13px] font-semibold text-fg">{u.angle}</span>
                <span className="text-[12px] text-fg2">{u.why}</span>
                {u.blocked_by.length ? (
                  <span className="flex items-center gap-1 text-[11px] text-warn">
                    <AlertTriangle aria-hidden="true" size={12} />
                    Your confirmed facts do not back this claim ({u.blocked_by.join(", ")}); the rules would block it in a title.
                  </span>
                ) : (
                  <span className="text-[11px] text-fg3">Backed by: {u.backed_by}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-3 min-[720px]:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold text-fg2">Angles taken</h3>
          <ul className="flex flex-wrap gap-1.5">
            {read.angles_taken.map((a) => (
              <li key={a.angle} className="rounded-[8px] border border-chipline bg-chip px-2 py-1 text-[12px] text-fg2">
                {a.angle} <span className="tnum text-fg3">×{a.count}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold text-fg2">Words on their thumbnails</h3>
          {read.thumbnail_words.length ? (
            <ul className="flex flex-wrap gap-1.5">
              {read.thumbnail_words.map((w) => (
                <li key={w.word} className="rounded-[8px] border border-line3 px-2 py-1 font-head text-[12px] text-fg">
                  {w.word} <span className="tnum font-sans text-fg3">×{w.count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-[12px] text-fg3">None printed</span>
          )}
          <span className="text-[12px] text-fg3">{read.thumbnail_look}</span>
        </div>
      </div>
      {read.patterns.length ? (
        <div className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-semibold text-fg2">Title patterns</h3>
          <ul className="flex flex-col gap-1">
            {read.patterns.map((p) => (
              <li key={p.pattern} className="flex flex-wrap items-baseline gap-2 text-[12px]">
                <code className="break-words text-fg">{p.pattern}</code>
                <span className="tnum text-fg3">{p.count} titles</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Card({ v, breakout }: { v: CompetitorVideo; breakout: boolean }) {
  return (
    <li className="flex min-w-0 flex-col overflow-hidden rounded-[10px] bg-surface" style={v.own ? { outline: "2px solid var(--accent)", outlineOffset: 2 } : undefined}>
      <a href={v.url} target="_blank" rel="noopener noreferrer" className="group relative block">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={v.thumbnail} alt="" loading="lazy" className="aspect-video w-full bg-stage object-cover" />
        <span className="tnum absolute bottom-1.5 right-1.5 rounded-[5px] bg-[rgba(7,7,7,0.78)] px-1.5 text-[10px] leading-[16px] text-fg">
          {Math.floor(v.duration_s / 60)}:{String(Math.round(v.duration_s % 60)).padStart(2, "0")}
        </span>
        {breakout ? (
          <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded-[5px] bg-accentfill px-1.5 text-[10px] font-semibold leading-[16px] text-onaccent" title="Views against its channel's average per video">
            <TrendingUp aria-hidden="true" size={10} />
            {v.outlier}× its channel
          </span>
        ) : null}
      </a>
      <div className="flex flex-col gap-1 p-2.5">
        <a href={v.url} target="_blank" rel="noopener noreferrer" className="line-clamp-2 break-words text-[12px] font-semibold leading-[1.35] text-fg hover:underline">
          {v.title}
          <span className="sr-only"> (opens YouTube in a new tab)</span>
        </a>
        <span className="truncate text-[11px] text-fg3">
          {v.own ? <span className="text-accentsoft">Yours · </span> : null}
          {v.channel} · {v.subs == null ? "subscribers hidden" : `${k(v.subs)} subs`}
        </span>
        <span className="tnum text-[11px] text-fg2">
          {k(v.views)} views · {age(v.age_days)} · {k(v.views_per_day)}/day
          {!breakout && v.outlier != null ? <span className="text-fg3"> · {v.outlier}×</span> : null}
        </span>
      </div>
    </li>
  );
}

/** Competitor research on the research page (7.7): who covers this subject, the numbers, Claude's read. */
export function Competitors({ video }: { video: Video }) {
  const view = useCompetitors(video.id);
  const run = useRunCompetitors(video.id);
  const job = jobOf(video, "competitors");
  const v = view.data;
  const result = v?.result;
  const busy = !!v?.running || run.isPending;
  const failed = !busy && job?.status === "error" ? job : null;
  const breakouts = new Set(result?.metrics.breakouts ?? []);
  const readCurrent = !!result?.read && result.read_for === result.searched_at;

  return (
    <section aria-labelledby="competitors-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 id="competitors-heading" className="font-head text-[16px]">
          Competitors
        </h2>
        {v ? <span className="text-[12px] text-fg3">YouTube search: “{v.query}”</span> : null}
        <span className="ml-auto flex flex-wrap gap-2">
          {result && v?.can_read && v.fresh ? (
            <button type="button" disabled={busy} onClick={() => run.mutate(true)} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3 text-[12px] disabled:opacity-50" title="One more Claude call on today's search, about 5 cents">
              <RefreshCw aria-hidden="true" size={14} />
              Read again
            </button>
          ) : null}
          {result && v?.fresh ? null : (
          <button
            type="button"
            disabled={busy || !v || (!v.can_search && !v.fresh)}
            onClick={() => run.mutate(false)}
            title={v && !v.can_search ? "Add YOUTUBE_API_KEY to .env" : undefined}
            className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:opacity-50"
          >
            {busy ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Search aria-hidden="true" size={14} />}
            {result ? "Search again" : "Find competitors"}
          </button>
          )}
        </span>
      </div>
      <span className="text-[12px] text-fg3">
        One YouTube search per subject a day (free quota, 100 of 10,000 daily units){v?.can_read ? ", then one Claude read of the titles and thumbnails, about 5 cents" : ""}.
        {v && !v.can_read ? " Without ANTHROPIC_API_KEY you get the videos and the numbers, not the read." : ""}
      </span>
      {view.error ? <ErrorCard title="Could not load competitors" message={view.error.message} onRetry={() => void view.refetch()} /> : null}
      {run.error ? <ErrorCard title="Did not start" message={run.error.message} /> : null}
      {failed ? <ErrorCard title="Competitor research stopped" message={failed.error ?? failed.message ?? "No message"} onRetry={() => run.mutate(false)} /> : null}
      {busy ? (
        <span className="flex flex-col gap-1.5 text-[12px] text-fg3" aria-live="polite">
          {job?.message && job.status === "running" ? job.message : "Searching"}…
          <span className="relative block h-[3px] overflow-hidden rounded-full bg-line2">
            <span className="ink-busy-bar absolute inset-y-0 left-0 block rounded-full bg-accent" />
          </span>
        </span>
      ) : null}
      {result ? (
        <>
          <FieldNumbers m={result.metrics} />
          {result.read && readCurrent ? <ReadCard read={result.read} /> : null}
          {result.read && !readCurrent ? <span className="text-[12px] text-fg3">Claude&apos;s read is from an older search; press Read again.</span> : null}
          <ul className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[900px]:grid-cols-3">
            {result.rows.map((row) => (
              <Card key={row.id} v={row} breakout={breakouts.has(row.id)} />
            ))}
          </ul>
          <span className="text-[11px] text-fg4">
            Searched {new Date(result.searched_at).toLocaleString()} · {result.units} quota units · the numbers cover the first{" "}
            {result.metrics.videos} videos from other channels
          </span>
        </>
      ) : v && !busy ? (
        <div className="rounded-[12px] border border-dashed border-line3 p-3.5 text-fg3">
          {v.can_search ? "Find who already covers this subject, how their views are spread, and the angle nobody has taken." : "Add YOUTUBE_API_KEY to .env to search for competing videos."}
        </div>
      ) : null}
    </section>
  );
}
