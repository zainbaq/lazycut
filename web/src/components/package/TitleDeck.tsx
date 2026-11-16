"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ChevronLeft, ChevronRight, CornerDownLeft, PenLine } from "lucide-react";
import { useState } from "react";

import { easeOutInk } from "@/lib/motion";
import type { Goal, Package } from "@/lib/types";

import { ClaimText, GoalChip, SweepCopy } from "./bits";
import { claimMarks, isBlocked } from "./rules";
import { TitleIssues, TitleScore } from "./SearchDemand";

interface Card {
  path: string;
  text: string;
  why: string;
  goal: Goal;
  recommended: boolean;
}

export function titleCards(pkg: Package): Card[] {
  const f = pkg.fields;
  return [
    { path: "title", text: f.title, why: f.title_why, goal: f.title_goal, recommended: true },
    // An alternate the user already took as the title is not offered twice.
    ...f.title_alternates
      .map((a, i) => ({ path: `title_alternates[${i}]`, text: a.text, why: a.why, goal: a.goal, recommended: false }))
      .filter((a) => a.text.trim() !== f.title.trim()),
  ];
}

/** The title deck (9.4 region 7): recommended title, its reason and goal, Next/Prev through the alternates, Copy. */
export function TitleDeck({
  pkg,
  onUseTitle,
  busy,
}: {
  pkg: Package;
  onUseTitle: (text: string) => void;
  busy?: boolean;
}) {
  const cards = titleCards(pkg);
  const [index, setIndex] = useState(0);
  const reduced = useReducedMotion();
  const at = Math.min(index, cards.length - 1);
  const card = cards[at];
  const blocked = isBlocked(pkg, card.path);
  const edited = card.recommended && pkg.edited_fields.includes("title");
  const step = (d: number) => setIndex((at + d + cards.length) % cards.length);

  return (
    <section aria-label="Title" className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[11px] text-fg3">
        <span className="font-semibold text-fg2">{card.recommended ? "Recommended title" : "Alternate"}</span>
        {edited ? (
          <span className="flex items-center gap-0.5 text-goldtext">
            <PenLine aria-hidden="true" size={11} />
            Edited by you
          </span>
        ) : null}
        <span className="tnum ml-auto" aria-live="polite">
          {at + 1} of {cards.length}
        </span>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={card.path + card.text}
          initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduced ? { opacity: 0 } : { opacity: 0, y: -6 }}
          transition={{ duration: 0.2, ease: easeOutInk }}
          className="flex flex-col gap-1.5 rounded-[10px] border p-2.5"
          style={{ borderColor: blocked ? "var(--accent)" : "var(--line-2)", background: "var(--surface-2)" }}
        >
          <p className="break-words font-head text-[15px] leading-snug text-fg">
            <ClaimText text={card.text} marks={claimMarks(pkg, card.path)} />
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            <GoalChip goal={card.goal} />
            <TitleScore pkg={pkg} text={card.text} />
            {card.recommended && pkg.fields.seo?.picked_by === "search_score" && !edited ? (
              <span className="text-[10.5px] text-fg3">Chosen by search score</span>
            ) : null}
            <span className="tnum text-[10.5px] text-fg4">{card.text.length} / 100</span>
          </div>
          {card.why ? <p className="text-[11.5px] text-fg3">{card.why}</p> : null}
          <TitleIssues pkg={pkg} text={card.text} />
        </motion.div>
      </AnimatePresence>
      <div className="flex flex-wrap items-center gap-1.5 whitespace-nowrap">
        <button
          type="button"
          onClick={() => step(-1)}
          disabled={cards.length < 2}
          aria-label="Previous title"
          className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] border border-line3 disabled:opacity-40"
        >
          <ChevronLeft aria-hidden="true" size={15} />
        </button>
        <button
          type="button"
          onClick={() => step(1)}
          disabled={cards.length < 2}
          className="ink-btn flex min-h-11 items-center gap-1 rounded-[10px] border border-line3 px-3 text-[12px] disabled:opacity-40"
        >
          Next
          <ChevronRight aria-hidden="true" size={15} />
        </button>
        {!card.recommended ? (
          <button
            type="button"
            disabled={busy || blocked}
            onClick={() => {
              onUseTitle(card.text);
              setIndex(0);
            }}
            title={blocked ? "This title makes a claim that is not backed" : "Make this the title (counts as your edit)"}
            aria-label="Use this title"
            className="ink-btn flex min-h-11 items-center gap-1 rounded-[10px] border border-line3 px-2.5 text-[12px] disabled:opacity-40"
          >
            <CornerDownLeft aria-hidden="true" size={13} />
            Use this
          </button>
        ) : null}
        <span className="ml-auto">
          <SweepCopy text={card.text} disabled={blocked} disabledReason="Blocked: a claim in this title is not backed" />
        </span>
      </div>
    </section>
  );
}
