"use client";

import { motion, useReducedMotion } from "motion/react";
import { AlertTriangle, BadgeCheck, Check, Circle, ExternalLink, Pencil, RotateCcw, ShieldCheck, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { panelRise } from "@/lib/motion";
import type { ResearchEdit, ResearchField, ResearchSource, ResearchValue } from "@/lib/types";

export function showValue(value: ResearchValue): string {
  if (value === null || value === undefined || value === "") return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return value;
}

/** A source as a small chip: domain plus its rating, never colour alone. Opens in a new tab. */
export function SourceChip({ source }: { source: ResearchSource }) {
  const credible = source.rating === "credible";
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      title={source.title || source.url}
      aria-label={`${source.domain}, ${credible ? "credible" : "unrated"} source${source.title ? `: ${source.title}` : ""} (opens in a new tab)`}
      className={
        "ink-btn inline-flex min-h-8 max-w-full items-center gap-1 rounded-[14px] border px-2.5 text-[11px] " +
        (credible ? "border-okline text-oktext" : "border-line3 text-fg2")
      }
    >
      {credible ? <BadgeCheck aria-hidden="true" size={12} className="shrink-0" /> : <Circle aria-hidden="true" size={10} className="shrink-0 text-fg4" />}
      <span className="truncate">{source.domain || "pasted"}</span>
      <span className="shrink-0 text-fg4">{credible ? "credible" : "unrated"}</span>
      <ExternalLink aria-hidden="true" size={10} className="shrink-0 text-fg4" />
    </a>
  );
}

const choice = "ink-btn min-h-11 flex-1 rounded-[10px] border px-3 text-[12px] transition-colors duration-200";

/** Yes / No / Unknown for a bool field. Picking one sets the user's value. */
function BoolChoice({
  field,
  onPick,
  disabled,
}: {
  field: ResearchField;
  onPick: (value: boolean | null) => void;
  disabled: boolean;
}) {
  const current = field.effective_value;
  const options: { label: string; value: boolean | null }[] = [
    { label: "Yes", value: true },
    { label: "No", value: false },
    { label: "Unknown", value: null },
  ];
  return (
    <div role="radiogroup" aria-label={`${field.label}: set the value`} className="flex gap-1.5">
      {options.map((o) => {
        const on = current === o.value;
        return (
          <button
            key={o.label}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => {
              if (!on) onPick(o.value); // picking the value already in use changes nothing
            }}
            // Inline, like the preset pills: the global `.ink-btn:hover` rule would beat a utility class.
            style={{
              background: on ? "var(--accent-fill)" : undefined,
              borderColor: on ? "var(--accent-fill)" : "var(--line-3)",
              color: on ? "var(--on-accent)" : "var(--text)",
            }}
            className={`${choice} disabled:opacity-60`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Inline text editor: Enter saves, Escape cancels. An empty value means "unknown". */
function TextEditor({
  field,
  onSave,
  onCancel,
}: {
  field: ResearchField;
  onSave: (value: string | null) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(typeof field.effective_value === "string" ? field.effective_value : (typeof field.value === "string" ? field.value : ""));
  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  const save = () => onSave(draft.trim() || null);
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <label htmlFor={id} className="sr-only">
        {field.label}
      </label>
      <input
        id={id}
        ref={input}
        value={draft}
        maxLength={500}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
        placeholder="Leave empty for unknown"
        className="min-h-11 w-full rounded-[10px] border border-line3 bg-bg px-3 text-[13px] text-fg outline-none focus:border-accent"
      />
      <div className="flex gap-2">
        <button type="submit" className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent">
          <Check aria-hidden="true" size={14} />
          Save
        </button>
        <button type="button" onClick={onCancel} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px]">
          <X aria-hidden="true" size={14} />
          Cancel
        </button>
      </div>
    </form>
  );
}

/** One research field: value, sources, edit control and its state (BUILD_SPEC 7.7). */
export function FieldRow({
  field,
  onEdit,
  pending,
}: {
  field: ResearchField;
  onEdit: (body: ResearchEdit) => void;
  pending: boolean;
}) {
  const reduced = useReducedMotion();
  const [editing, setEditing] = useState(false);
  const labelId = useId();
  const found = field.value !== null && field.value !== "";
  const unused = field.no_credible_source;

  return (
    <li aria-labelledby={labelId} className="flex flex-col gap-2 border-b border-line py-3.5 last:border-b-0 min-[720px]:flex-row min-[720px]:gap-4">
      <div className="flex shrink-0 flex-col gap-1 min-[720px]:w-[180px]">
        <span id={labelId} className="text-[13px] font-semibold text-fg">
          {field.label}
        </span>
        {field.needs_credible_source ? (
          <span className="flex items-center gap-1 text-[11px] text-fg3">
            <ShieldCheck aria-hidden="true" size={12} className="text-accentsoft" />
            Needs a credible source
          </span>
        ) : null}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {field.type === "bool" ? (
          <BoolChoice field={field} disabled={pending} onPick={(value) => onEdit({ key: field.key, value })} />
        ) : editing ? (
          <TextEditor
            field={field}
            onCancel={() => setEditing(false)}
            onSave={(value) => {
              setEditing(false);
              const same = !field.overridden && value === field.effective_value;
              if (!same) onEdit({ key: field.key, value });
            }}
          />
        ) : (
          <div className="flex items-start gap-2">
            <span
              className={
                "min-w-0 flex-1 break-words text-[14px] " +
                (field.effective_value === null || field.effective_value === "" ? "text-fg4" : "text-fg")
              }
            >
              {unused ? "Not used" : field.effective_value === null || field.effective_value === "" ? (found || field.overridden ? "Unknown" : "Not found") : showValue(field.effective_value)}
            </span>
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={pending}
              aria-label={`Edit ${field.label}`}
              className="ink-btn flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] border border-line2 text-fg2 disabled:opacity-60"
            >
              <Pencil aria-hidden="true" size={14} />
            </button>
          </div>
        )}

        {unused ? (
          <motion.div {...(reduced ? { initial: { opacity: 0 }, animate: { opacity: 1 } } : panelRise)} className="flex flex-col gap-1 rounded-[10px] border border-warnline px-2.5 py-2">
            <span className="flex items-start gap-1.5 text-[12px] text-warn">
              <AlertTriangle aria-hidden="true" size={13} className="mt-0.5 shrink-0" />
              No credible source — not used in titles or claims until you set it.
            </span>
            <span className="text-[12px] text-fg3">
              Research found: <span className="text-fg3 line-through decoration-fg4">{showValue(field.value)}</span>
            </span>
          </motion.div>
        ) : null}

        {field.overridden ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
            <span className="flex items-center gap-1 text-accentsoft">
              <Pencil aria-hidden="true" size={11} />
              Edited by you
            </span>
            {found ? <span className="text-fg3">· research found {showValue(field.value)}</span> : null}
            <button
              type="button"
              disabled={pending}
              onClick={() => onEdit({ key: field.key, restore: true })}
              className="ink-btn flex min-h-11 items-center gap-1 rounded-[10px] px-2 text-fg2 underline decoration-line3 underline-offset-2 disabled:opacity-60"
            >
              <RotateCcw aria-hidden="true" size={12} />
              Restore research value
            </button>
          </div>
        ) : null}

        {field.sources.length ? (
          <ul aria-label={`Sources for ${field.label}`} className="flex flex-wrap gap-1.5">
            {field.sources.map((s) => (
              <li key={s.url} className="max-w-full">
                <SourceChip source={s} />
              </li>
            ))}
          </ul>
        ) : found && !field.overridden ? (
          <span className="text-[11px] text-fg4">No source given for this value.</span>
        ) : null}
      </div>
    </li>
  );
}
