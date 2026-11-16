"use client";

import { ChevronDown, Search, Tag, Type } from "lucide-react";
import { useState } from "react";

import { ago } from "@/lib/format";
import type { Package, Seo, SeoTitleScore } from "@/lib/types";

const PICKED: Record<Seo["picked_by"], string> = {
  search_score: "Highest search score: overrode the writer's pick",
  search_score_agrees: "Highest search score: the writer agreed",
  writer: "Writer's pick: no search data",
};

export function score(n: number | undefined): string {
  return (n ?? 0).toFixed(2);
}

/** The candidate score for a title text, from the package's search-demand record. */
export function titleScoreFor(seo: Seo | undefined, text: string): SeoTitleScore | undefined {
  return seo?.title_scores.find((s) => s.text.trim() === text.trim());
}

export function hasSearchData(seo: Seo | undefined): seo is Seo {
  return !!seo?.source;
}

/** A title's search score as a small chip: "best" when no candidate beats it; rule issues in its tooltip. */
export function TitleScore({ pkg, text }: { pkg: Package; text: string }) {
  const seo = pkg.fields.seo;
  if (!hasSearchData(seo)) return null;
  const found = titleScoreFor(seo, text);
  const value = found ? found.score : text.trim() === pkg.fields.title.trim() ? seo.title_score?.score : undefined;
  if (value === undefined) return null;
  const top = Math.max(0, ...seo.title_scores.map((s) => s.score));
  const best = value > 0 && value + 0.005 >= top;
  const issues = found?.issues ?? [];
  return (
    <span
      className={`tnum inline-flex shrink-0 items-center gap-1 rounded-[8px] border px-1.5 py-0.5 text-[10.5px] ${best ? "border-okline text-ok" : "border-line3 text-fg3"}`}
      title={`Search score: the popular searches this title covers${issues.length ? `. Lowered by: ${issues.join("; ")}` : ""}`}
    >
      <Search aria-hidden="true" size={10} />
      {score(value)}
      {best ? <span>best</span> : null}
    </span>
  );
}

/** Rule issues that lowered a candidate's score (an unbacked number, say). */
export function TitleIssues({ pkg, text }: { pkg: Package; text: string }) {
  const issues = titleScoreFor(pkg.fields.seo, text)?.issues ?? [];
  if (!issues.length) return null;
  return <span className="text-[11px] text-warn">Score lowered: {issues.join("; ")}</span>;
}

function Mark({ on, icon, label }: { on?: boolean; icon: React.ReactNode; label: string }) {
  return (
    <span
      className={`inline-flex h-[18px] items-center gap-0.5 rounded-[6px] px-1 text-[10px] ${on ? "bg-okbg text-ok" : "text-fg4 opacity-50"}`}
      title={on ? `In the ${label}` : `Not in the ${label}`}
      aria-label={on ? `in the ${label}` : `not in the ${label}`}
      role="img"
    >
      {icon}
    </span>
  );
}

/** Search demand (BUILD_SPEC 7.7.1): who chose the title, how it scores, and the phrases behind it. */
export function SearchDemand({ pkg }: { pkg: Package }) {
  const seo = pkg.fields.seo;
  const [showRest, setShowRest] = useState(false);

  if (!hasSearchData(seo)) {
    return (
      <section aria-labelledby="pd-seo" className="flex flex-col gap-1.5">
        <h3 id="pd-seo" className="text-[12.5px] font-semibold">
          Search demand
        </h3>
        <span className="text-fg3">No search data for this package.</span>
      </section>
    );
  }

  const fitting = seo.phrases.filter((p) => p.fits).sort((a, b) => b.demand - a.demand);
  const rest = seo.phrases.filter((p) => !p.fits).sort((a, b) => b.demand - a.demand);
  const current = seo.title_score;
  const edited = pkg.edited_fields.includes("title");
  const lowered = !!current && current.score + 0.005 < current.best_candidate;

  return (
    <section aria-labelledby="pd-seo" className="flex flex-col gap-2">
      <h3 id="pd-seo" className="flex items-center gap-1.5 text-[12.5px] font-semibold">
        <Search aria-hidden="true" size={13} className="text-fg3" />
        Search demand
      </h3>

      <div className="flex flex-col gap-1 rounded-[10px] bg-surface p-2.5">
        <span className="text-fg2">{PICKED[seo.picked_by] ?? seo.picked_by}</span>
        {current ? (
          <span className="tnum text-[11.5px] text-fg3">
            Title score <span className="font-semibold text-fg">{score(current.score)}</span>
            {" · "}best candidate {score(current.best_candidate)}
          </span>
        ) : null}
        {lowered ? (
          <span className="text-[11px] text-warn">
            {edited ? "Your edit" : "This title"} scores lower than the best candidate: it covers fewer of the searches below.
          </span>
        ) : null}
      </div>

      {fitting.length ? (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] text-fg3">Searches this video answers, most popular first</span>
          <ul className="flex flex-col">
            {fitting.map((p) => (
              <li key={p.id} className="flex min-h-8 items-center gap-1.5 border-b border-line py-1 last:border-b-0">
                <span className="tnum w-9 shrink-0 text-[11px] text-fg3" title="Demand: 1.00 is a top suggestion">
                  {score(p.demand)}
                </span>
                <span className="min-w-0 flex-1 break-words text-fg2">{p.text}</span>
                <Mark on={p.in_title} icon={<Type aria-hidden="true" size={10} />} label="title" />
                <Mark on={p.in_tags} icon={<Tag aria-hidden="true" size={10} />} label="tags" />
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <span className="text-fg3">No search phrase fits this video.</span>
      )}

      {rest.length ? (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            onClick={() => setShowRest((s) => !s)}
            aria-expanded={showRest}
            className="ink-btn flex min-h-11 items-center gap-1 self-start rounded-[10px] px-1 text-[11.5px] text-fg3"
          >
            <ChevronDown aria-hidden="true" size={13} className={showRest ? "rotate-180" : undefined} />
            {rest.length} {rest.length === 1 ? "search does" : "searches do"} not fit this video
          </button>
          {showRest ? (
            <ul className="flex flex-wrap gap-1">
              {rest.map((p) => (
                <li key={p.id} className="rounded-[8px] bg-surface2 px-1.5 py-0.5 text-[11px] text-fg3">
                  {p.text}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {seo.excluded.length ? (
        <ul className="flex flex-col gap-0.5 text-[11px] text-fg3">
          {seo.excluded.map((p) => (
            <li key={p.text}>
              Left out “{p.text}”: {p.reason}
            </li>
          ))}
        </ul>
      ) : null}

      {seo.ambiguous_names.length ? (
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] text-fg3">Never used alone as a tag or hashtag</span>
          <span className="text-fg2">{seo.ambiguous_names.join(", ")}</span>
          <span className="text-[11px] text-fg4">On their own these are mostly searched for something else; the tags pair them with the game.</span>
        </div>
      ) : null}

      <span className="text-[10.5px] text-fg4">
        YouTube search suggestions{seo.harvested_at ? `, ${ago(seo.harvested_at)}` : ""}; demand is suggestion rank, not views.
      </span>
    </section>
  );
}
