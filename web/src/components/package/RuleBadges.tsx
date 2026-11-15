"use client";

import * as Popover from "@radix-ui/react-popover";
import { AlertTriangle, CheckCircle2, CircleSlash, EyeOff, RotateCcw, Wand2 } from "lucide-react";

import type { Package, RuleResult } from "@/lib/types";

import { dismissedResults, fieldLabel, fixes, openResults, ruleLabel } from "./rules";

function evidenceText(evidence: unknown): string | null {
  if (evidence === null || evidence === undefined) return null;
  if (Array.isArray(evidence)) return evidence.map((e) => (typeof e === "string" ? e : JSON.stringify(e))).join(", ");
  if (typeof evidence === "string") return evidence;
  if (typeof evidence === "object") {
    const e = evidence as Record<string, unknown>;
    if (typeof e.from === "string" && typeof e.to === "string") return `${e.from} → ${e.to}`;
    if (typeof e.phrase === "string") return `Phrase: ${e.phrase}`;
  }
  return JSON.stringify(evidence);
}

/** One rule result as a pill; clicking it opens the message and evidence, with Dismiss for a warning. */
export function RuleBadge({
  result,
  onDismiss,
  showField = true,
  busy,
}: {
  result: RuleResult;
  onDismiss?: (key: string, dismiss: boolean) => void;
  showField?: boolean;
  busy?: boolean;
}) {
  const block = result.severity === "block";
  const warn = result.severity === "warn";
  const Icon = block ? CircleSlash : warn ? AlertTriangle : CheckCircle2;
  const evidence = evidenceText(result.evidence);
  return (
    <Popover.Root>
      <Popover.Trigger
        className="ink-btn flex min-h-9 max-w-full items-center gap-1.5 rounded-[22px] border px-2.5 text-[11.5px]"
        style={{
          borderColor: block ? "var(--accent)" : warn ? "var(--warn-line)" : "var(--ok-line)",
          color: block ? "var(--text)" : warn ? "var(--warn)" : "var(--ok-text)",
          opacity: result.dismissed ? 0.6 : 1,
        }}
        aria-label={`${block ? "Blocked" : warn ? "Warning" : "Passed"}: ${ruleLabel(result.rule_id)} on ${fieldLabel(result.field)}. ${result.message}`}
      >
        <Icon aria-hidden="true" size={12} className={block ? "shrink-0 text-accentsoft" : "shrink-0"} />
        <span className="truncate">
          {ruleLabel(result.rule_id)}
          {showField ? <span className="text-fg3"> · {fieldLabel(result.field)}</span> : null}
        </span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          align="start"
          collisionPadding={12}
          className="z-[60] flex w-[min(300px,calc(100vw-32px))] flex-col gap-2 rounded-[12px] border border-line2 bg-raised p-3 text-[12px] text-fg"
        >
          <span className="flex items-center gap-1.5 font-semibold">
            <Icon aria-hidden="true" size={13} className={block ? "text-accentsoft" : warn ? "text-warn" : "text-ok"} />
            {ruleLabel(result.rule_id)} · {fieldLabel(result.field)}
          </span>
          <span className="text-fg2">{result.message}</span>
          {evidence ? <span className="break-words text-[11px] text-fg3">{evidence}</span> : null}
          {block ? (
            <span className="text-[11px] text-fg3">Copy is off for this field until the text or the fact behind it changes.</span>
          ) : null}
          {warn && onDismiss ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => onDismiss(result.key, !result.dismissed)}
              className="ink-btn flex min-h-11 items-center justify-center gap-1.5 self-start rounded-[10px] border border-line3 px-3 text-[12px] disabled:opacity-50"
            >
              {result.dismissed ? <RotateCcw aria-hidden="true" size={13} /> : <EyeOff aria-hidden="true" size={13} />}
              {result.dismissed ? "Undismiss" : "Dismiss for this package"}
            </button>
          ) : null}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** Open checks as pills, a quiet passed count, auto-fix notes, and dismissed warnings that can come back. */
export function RuleBadges({
  pkg,
  onDismiss,
  busy,
}: {
  pkg: Package;
  onDismiss: (key: string, dismiss: boolean) => void;
  busy?: boolean;
}) {
  const open = openResults(pkg).sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "block" ? -1 : 1));
  const passed = pkg.rule_results.filter((r) => r.severity === "pass").length;
  const fixed = fixes(pkg);
  const dismissed = dismissedResults(pkg);
  return (
    <div className="flex flex-col gap-1.5">
      {open.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Checks that need attention">
          {open.map((r) => (
            <li key={r.key} className="max-w-full">
              <RuleBadge result={r} onDismiss={onDismiss} busy={busy} />
            </li>
          ))}
        </ul>
      ) : null}
      <span className="flex items-center gap-1 text-[11px] text-fg3">
        <CheckCircle2 aria-hidden="true" size={11} className="text-ok" />
        {passed} {passed === 1 ? "check" : "checks"} passed
        {!open.length ? " · nothing needs attention" : ""}
      </span>
      {fixed.length ? (
        <ul className="flex flex-col gap-0.5" aria-label="Fixed automatically">
          {fixed.map((r) => (
            <li key={r.key} className="flex items-start gap-1 text-[11px] text-fg3">
              <Wand2 aria-hidden="true" size={11} className="mt-[2px] shrink-0 text-accentsoft" />
              <span>{r.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {dismissed.length ? (
        <details className="text-[11px] text-fg3">
          <summary className="flex min-h-9 cursor-pointer items-center">{dismissed.length} dismissed</summary>
          <ul className="flex flex-wrap gap-1.5 pt-1">
            {dismissed.map((r) => (
              <li key={r.key} className="max-w-full">
                <RuleBadge result={r} onDismiss={onDismiss} busy={busy} />
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
