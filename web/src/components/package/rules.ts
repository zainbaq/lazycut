// Reading a package's rule results (BUILD_SPEC 7.9, API_SHAPES "Packages").

import type { Goal, Package, RuleResult } from "@/lib/types";

export const GOAL_LABELS: Record<Goal, string> = {
  click_through: "Clicks",
  retention: "Retention",
  session_watch_time: "Session time",
  engagement: "Engagement",
  funnel: "Funnel",
};

export function ruleLabel(ruleId: string): string {
  if (ruleId.startsWith("claim_needs_fact")) return "Claim";
  return (
    {
      canonical_spelling: "Spelling",
      hashtag_count: "Hashtags",
      banned_tags: "Banned tags",
      number_needs_fact: "Number",
      search_first_title: "Search-first title",
      chapters_valid: "Chapters",
      tags_count: "Tag count",
      cannibalization: "Past uploads",
      length_limits: "Length",
    }[ruleId] ?? ruleId.replace(/_/g, " ")
  );
}

/** "title_alternates[1]" → "Alternate title 2", "thumbnail.word_options[0]" → "Thumbnail word 1". */
export function fieldLabel(path: string): string {
  const alt = /^title_alternates\[(\d+)\]$/.exec(path);
  if (alt) return `Alternate title ${Number(alt[1]) + 1}`;
  const word = /^thumbnail\.word_options\[(\d+)\]$/.exec(path);
  if (word) return `Thumbnail word ${Number(word[1]) + 1}`;
  return (
    {
      title: "Title",
      hook_line: "Hook line",
      description: "Description",
      chapters: "Chapters",
      tags: "Tags",
      hashtags: "Hashtags",
      pinned_comment: "Pinned comment",
      community_post: "Community post",
      opening_5s: "Opening 5 seconds",
    }[path] ?? path.replace(/_/g, " ")
  );
}

/** Checks that still need attention: warns and blocks that are not dismissed. */
export const openResults = (pkg: Package) =>
  pkg.rule_results.filter((r) => (r.severity === "block" || r.severity === "warn") && !r.dismissed);

export const dismissedResults = (pkg: Package) => pkg.rule_results.filter((r) => r.severity === "warn" && r.dismissed);

/** Results that belong to one field path. `tags` also gets nothing from `title`; exact match only. */
export const resultsFor = (pkg: Package, path: string) => pkg.rule_results.filter((r) => r.field === path);

export const isBlocked = (pkg: Package, path: string) => pkg.blocked_fields.includes(path);

/** Every auto-fix that changed something, as a short note ("Removed soulslike"). */
export const fixes = (pkg: Package) => pkg.rule_results.filter((r) => r.fixed);

export interface ClaimMark {
  phrase: string;
  backed: boolean;
  result: RuleResult;
}

/**
 * Claim phrases found in one field: a passing `claim_needs_fact.*` result means backed (a seal),
 * a warn/block means not backed (the slash). The phrase comes from `evidence.phrase` on a failure;
 * a pass carries no evidence, so it is read from the quoted phrase in its message.
 */
export function claimMarks(pkg: Package, path: string): ClaimMark[] {
  const marks: ClaimMark[] = [];
  for (const r of pkg.rule_results) {
    if (r.field !== path || !r.rule_id.startsWith("claim_needs_fact")) continue;
    const evidence = r.evidence as { phrase?: string } | null;
    const phrase = evidence?.phrase ?? /“([^”]+)”/.exec(r.message)?.[1];
    if (phrase) marks.push({ phrase, backed: r.severity === "pass", result: r });
  }
  return marks;
}

/** Split text around claim phrases (case-insensitive, word boundaries), for marking them up. */
export function splitClaims(text: string, marks: ClaimMark[]): (string | { text: string; mark: ClaimMark })[] {
  if (!marks.length || !text) return [text];
  const escaped = marks.map((m) => m.phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(?<![\\w])(${escaped.join("|")})(?![\\w])`, "gi");
  const out: (string | { text: string; mark: ClaimMark })[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const mark = marks.find((x) => x.phrase.toLowerCase() === m[0].toLowerCase()) ?? marks[0];
    out.push({ text: m[0], mark });
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** YouTube counts the separators, and a tag with a space as if it were quoted (matches the API's rule). */
export function tagsLength(tags: string[]): number {
  return tags.reduce((n, t) => n + t.length + (t.includes(" ") ? 2 : 0), 0) + Math.max(tags.length - 1, 0);
}

export const LIMITS: Partial<Record<string, number>> = { title: 100, description: 5000, tags: 500, pinned_comment: 10000 };
