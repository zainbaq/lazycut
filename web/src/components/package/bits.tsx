"use client";

import { motion, useReducedMotion } from "motion/react";
import { Ban, Check, Copy, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { COPY_RESET_MS, easeOutInk } from "@/lib/motion";
import type { Goal } from "@/lib/types";

import { type ClaimMark, GOAL_LABELS, splitClaims } from "./rules";

/** Copy (9.5): the background sweeps to --ok, the icon becomes a check, and it reverts after 1.6 s. */
export function SweepCopy({
  text,
  label = "Copy",
  disabled,
  disabledReason,
  compact,
}: {
  text: string;
  label?: string;
  disabled?: boolean;
  disabledReason?: string;
  compact?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const reduced = useReducedMotion();
  return (
    <button
      type="button"
      disabled={disabled}
      title={disabled ? disabledReason : undefined}
      aria-label={compact ? `${label}${disabled && disabledReason ? ` (${disabledReason})` : ""}` : undefined}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setFailed(false);
          setCopied(true);
          setTimeout(() => setCopied(false), COPY_RESET_MS);
        } catch {
          setFailed(true);
          setTimeout(() => setFailed(false), COPY_RESET_MS);
        }
      }}
      className={`ink-btn relative flex min-h-11 shrink-0 items-center justify-center gap-1.5 overflow-hidden rounded-[10px] border px-3 text-[12px] disabled:opacity-40 ${compact ? "w-11 px-0" : ""}`}
      style={{ borderColor: copied ? "var(--ok)" : "var(--line-3)", color: copied ? "var(--on-ok)" : "var(--text)" }}
    >
      <motion.span
        aria-hidden="true"
        className="absolute inset-0 origin-left bg-ok"
        initial={false}
        animate={{ scaleX: copied ? 1 : 0, opacity: copied ? 1 : 0 }}
        transition={reduced ? { duration: 0 } : { duration: 0.26, ease: easeOutInk }}
      />
      <span className="relative flex items-center gap-1.5">
        {copied ? <Check aria-hidden="true" size={14} /> : disabled ? <Ban aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
        {compact ? null : copied ? "Copied" : failed ? "Copy refused" : label}
      </span>
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied" : failed ? "The browser refused to copy" : ""}
      </span>
    </button>
  );
}

export function GoalChip({ goal }: { goal: Goal | undefined | null }) {
  if (!goal) return null;
  return (
    <span className="inline-flex shrink-0 items-center rounded-[8px] border border-line3 px-1.5 py-0.5 text-[10.5px] text-fg3" title="What this recommendation is for">
      {GOAL_LABELS[goal] ?? goal}
    </span>
  );
}

/** A claim phrase that is not backed: the strike-through draws left to right and shakes once (Slash, 9.5). */
function Slashed({ text, reason }: { text: string; reason: string }) {
  const reduced = useReducedMotion();
  return (
    <motion.span
      className="relative inline-block text-accentsoft"
      title={reason}
      initial={false}
      animate={reduced ? undefined : { x: [0, -4, 4, -2, 0] }}
      transition={{ duration: 0.28, delay: 0.22 }}
    >
      {text}
      <motion.span
        aria-hidden="true"
        className="absolute left-0 right-0 top-1/2 block h-[2px] origin-left bg-accent"
        initial={{ scaleX: reduced ? 1 : 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: reduced ? 0 : 0.22, ease: easeOutInk }}
      />
      <span className="sr-only"> (claim not backed: {reason})</span>
    </motion.span>
  );
}

/** Text with its claim phrases marked: a small round check seal when backed, the slash when not. */
export function ClaimText({ text, marks }: { text: string; marks: ClaimMark[] }) {
  const parts = splitClaims(text, marks);
  return (
    <>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          <span key={i}>{p}</span>
        ) : p.mark.backed ? (
          <span key={i} className="whitespace-nowrap" title={p.mark.result.message}>
            {p.text}
            <span
              className="ml-0.5 inline-flex h-[15px] w-[15px] translate-y-[-1px] items-center justify-center rounded-full bg-okbg align-middle text-ok"
              aria-label="claim backed by a confirmed fact"
              role="img"
            >
              <ShieldCheck aria-hidden="true" size={10} />
            </span>
          </span>
        ) : (
          <Slashed key={i} text={p.text} reason={p.mark.result.message} />
        ),
      )}
    </>
  );
}
