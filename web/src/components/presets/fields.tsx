"use client";

import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, ArrowDown, ArrowUp, ChevronDown, Plus, Trash2, X } from "lucide-react";
import { useId, useState } from "react";

import { panelRise } from "@/lib/motion";
import type { Condition, ConditionOp, ConditionValue, PresetProblem } from "@/lib/types";

export const inputCls =
  "min-h-11 w-full rounded-[10px] border border-line3 bg-bg px-3 text-[13px] text-fg outline-none placeholder:text-fg4 focus:border-accent disabled:text-fg3";

/** Problems whose path is `prefix` or below it. */
export function under(problems: PresetProblem[], prefix: string): PresetProblem[] {
  return problems.filter((p) => p.path === prefix || p.path.startsWith(`${prefix}.`));
}

export function ProblemList({ items }: { items: PresetProblem[] }) {
  if (!items.length) return null;
  return (
    <ul role="alert" className="flex flex-col gap-1 rounded-[8px] border border-accent px-2.5 py-2 text-[12px] text-fg">
      {items.map((p, i) => (
        <li key={`${p.path}${i}`} className="flex items-start gap-1.5">
          <AlertTriangle aria-hidden="true" size={12} className="mt-0.5 shrink-0 text-accentsoft" />
          <span>
            {p.path && !p.message.startsWith(p.path) ? <code className="mr-1 text-fg3">{p.path}</code> : null}
            {p.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Text({
  label,
  value,
  onChange,
  placeholder,
  hint,
  mono,
  disabled,
  title,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  mono?: boolean;
  disabled?: boolean;
  title?: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1" title={title}>
      <span className="text-[12px] font-semibold text-fg2">{label}</span>
      <input
        id={id}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`${inputCls} ${mono ? "font-mono text-[12px]" : ""}`}
      />
      {hint ? <span className="text-[11px] text-fg4">{hint}</span> : null}
    </label>
  );
}

export function Area({
  label,
  value,
  onChange,
  rows = 3,
  hint,
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  hint?: string;
  mono?: boolean;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1">
      <span className="text-[12px] font-semibold text-fg2">{label}</span>
      <textarea
        id={id}
        value={value}
        rows={rows}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full resize-y rounded-[10px] border border-line3 bg-bg p-3 text-[13px] leading-[1.5] text-fg outline-none focus:border-accent ${mono ? "font-mono text-[12px]" : ""}`}
      />
      {hint ? <span className="text-[11px] text-fg4">{hint}</span> : null}
    </label>
  );
}

export function Pick<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1">
      <span className="text-[12px] font-semibold text-fg2">{label}</span>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value as T)} className={inputCls}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A list of short strings as removable chips, with a field to add one (Enter adds). */
export function Words({
  label,
  values,
  onChange,
  placeholder,
  hint,
  suggestions,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  hint?: string;
  /** Offer these as one-click chips (for lists that name ids, like event types). */
  suggestions?: string[];
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const word = raw.trim();
    if (word && !values.includes(word)) onChange([...values, word]);
    setDraft("");
  };
  const offer = (suggestions ?? []).filter((s) => !values.includes(s));
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-[12px] font-semibold text-fg2">
        {label}
      </label>
      {values.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {values.map((v, i) => (
            <li key={`${v}${i}`} className="flex min-h-9 items-center gap-1 rounded-[8px] border border-chipline bg-chip pl-2.5 text-[12px] text-fg">
              <span className="break-all">{v}</span>
              <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((_, j) => j !== i))} className="ink-btn flex h-9 w-8 items-center justify-center rounded-[8px] text-fg3">
                <X aria-hidden="true" size={12} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {suggestions ? (
        offer.length ? (
          <div className="flex flex-wrap gap-1.5">
            {offer.map((s) => (
              <button key={s} type="button" onClick={() => add(s)} className="ink-btn flex min-h-9 items-center gap-1 rounded-[8px] border border-dashed border-line3 px-2.5 text-[12px] text-fg3">
                <Plus aria-hidden="true" size={12} />
                {s}
              </button>
            ))}
          </div>
        ) : null
      ) : (
        <input
          id={id}
          value={draft}
          placeholder={placeholder ?? "Type and press Enter"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
          onBlur={() => add(draft)}
          className={inputCls}
        />
      )}
      {hint ? <span className="text-[11px] text-fg4">{hint}</span> : null}
    </div>
  );
}

/** One collapsible section of the form; the dot says it holds problems. */
export function Section({
  title,
  count,
  problems,
  children,
  defaultOpen = false,
  note,
}: {
  title: string;
  count?: number;
  problems: PresetProblem[];
  children: React.ReactNode;
  defaultOpen?: boolean;
  note?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  return (
    <section className="rounded-[12px] bg-surface px-3.5 py-1">
      <h2>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen(!open)}
          className="flex min-h-12 w-full items-center gap-2 text-left text-[14px] font-semibold text-fg"
        >
          {title}
          {count !== undefined ? <span className="tnum text-[12px] font-normal text-fg3">{count}</span> : null}
          {problems.length ? (
            <span className="flex items-center gap-1 text-[11px] font-normal text-accentsoft">
              <AlertTriangle aria-hidden="true" size={12} />
              {problems.length === 1 ? "1 problem" : `${problems.length} problems`}
            </span>
          ) : null}
          <ChevronDown aria-hidden="true" size={15} className="ml-auto text-fg3 transition-transform duration-200" style={{ transform: open ? "rotate(180deg)" : undefined }} />
        </button>
      </h2>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div key="body" id={bodyId} {...panelRise} className="flex flex-col gap-3 pb-3.5">
            {note ? <p className="text-[12px] leading-[1.5] text-fg3">{note}</p> : null}
            {children}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}

/** One item of a list section: move, remove, and the item's own problems. */
export function Item({
  title,
  index,
  total,
  onMove,
  onRemove,
  problems,
  children,
}: {
  title: string;
  index: number;
  total: number;
  onMove: (to: number) => void;
  onRemove: () => void;
  problems: PresetProblem[];
  children: React.ReactNode;
}) {
  const btn = "ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3 disabled:opacity-30";
  return (
    <li className="flex flex-col gap-2.5 rounded-[10px] border border-line2 bg-bg/40 p-3" style={problems.length ? { borderColor: "var(--accent)" } : undefined}>
      <div className="flex items-center gap-1">
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-fg">{title}</span>
        <button type="button" aria-label={`Move ${title} up`} disabled={index === 0} onClick={() => onMove(index - 1)} className={btn}>
          <ArrowUp aria-hidden="true" size={14} />
        </button>
        <button type="button" aria-label={`Move ${title} down`} disabled={index === total - 1} onClick={() => onMove(index + 1)} className={btn}>
          <ArrowDown aria-hidden="true" size={14} />
        </button>
        <button type="button" aria-label={`Remove ${title}`} onClick={onRemove} className={btn}>
          <Trash2 aria-hidden="true" size={14} />
        </button>
      </div>
      {children}
      <ProblemList items={problems} />
    </li>
  );
}

export function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="ink-btn flex min-h-11 items-center gap-1.5 self-start rounded-[10px] border border-dashed border-line3 px-3.5 text-[12px] text-fg2">
      <Plus aria-hidden="true" size={14} />
      {label}
    </button>
  );
}

export function moved<T>(list: T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

// ---- conditions (`when` / `requires` / `unless`) ----

export interface ConditionSubject {
  /** "fact:hits_taken" or "research:is_final_boss" */
  ref: string;
  label: string;
  kind: "int" | "text" | "bool" | "enum";
  options?: string[];
}

const OPS: { value: ConditionOp; label: string }[] = [
  { value: "eq", label: "is" },
  { value: "ne", label: "is not" },
  { value: "gt", label: "more than" },
  { value: "gte", label: "at least" },
  { value: "lt", label: "less than" },
  { value: "lte", label: "at most" },
  { value: "between", label: "between" },
  { value: "in", label: "one of" },
];

function parseOne(raw: string, kind: ConditionSubject["kind"]): string | number {
  if (kind === "int") {
    const n = Number(raw);
    return raw.trim() !== "" && Number.isFinite(n) ? n : raw;
  }
  return raw;
}

/** Edits `{fact|research, op, value}`; the value field follows the subject's type. */
export function ConditionField({
  label,
  value,
  onChange,
  subjects,
}: {
  label: string;
  value: Condition;
  onChange: (c: Condition) => void;
  subjects: ConditionSubject[];
}) {
  const ref = value.fact != null ? `fact:${value.fact}` : value.research != null ? `research:${value.research}` : "";
  const subject = subjects.find((s) => s.ref === ref);
  const kind = subject?.kind ?? "text";
  const set = (patch: Partial<Condition>) => onChange({ ...value, ...patch });
  const setRef = (next: string) => {
    const [side, key] = next.split(":");
    set({ fact: side === "fact" ? key : null, research: side === "research" ? key : null });
  };
  const ops = kind === "bool" ? OPS.filter((o) => o.value === "eq" || o.value === "ne") : kind === "int" ? OPS : OPS.filter((o) => ["eq", "ne", "in"].includes(o.value));
  const asList = (v: ConditionValue): (string | number)[] => (Array.isArray(v) ? v : v == null || v === "" ? [] : [v as string | number]);

  let valueField: React.ReactNode;
  if (kind === "bool") {
    valueField = (
      <Pick label="Value" value={value.value === false ? "false" : "true"} options={[{ value: "true", label: "yes" }, { value: "false", label: "no" }]} onChange={(v) => set({ value: v === "true" })} />
    );
  } else if (value.op === "between") {
    const [lo, hi] = asList(value.value);
    valueField = (
      <div className="grid grid-cols-2 gap-2">
        <Text label="From" value={lo == null ? "" : String(lo)} onChange={(v) => set({ value: [parseOne(v, kind), hi ?? ""] })} />
        <Text label="To" value={hi == null ? "" : String(hi)} onChange={(v) => set({ value: [lo ?? "", parseOne(v, kind)] })} />
      </div>
    );
  } else if (value.op === "in") {
    valueField = (
      <Text
        label="Values"
        hint="Separate with commas"
        value={asList(value.value).join(", ")}
        onChange={(v) => set({ value: v.split(",").map((x) => parseOne(x.trim(), kind)).filter((x) => x !== "") })}
      />
    );
  } else if (kind === "enum" && subject?.options?.length) {
    valueField = <Pick label="Value" value={String(value.value ?? subject.options[0])} options={subject.options.map((o) => ({ value: o, label: o }))} onChange={(v) => set({ value: v })} />;
  } else {
    valueField = <Text label="Value" value={value.value == null ? "" : String(value.value)} onChange={(v) => set({ value: parseOne(v, kind) })} />;
  }

  return (
    <fieldset className="flex flex-col gap-2 rounded-[10px] border border-line2 p-2.5">
      <legend className="px-1 text-[12px] font-semibold text-fg2">{label}</legend>
      <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-[1.4fr_1fr_1.2fr]">
        <Pick
          label="When"
          value={ref}
          options={[...(subject ? [] : [{ value: ref, label: ref ? `${ref} (not in this preset)` : "Pick a fact or research field" }]), ...subjects.map((s) => ({ value: s.ref, label: s.label }))]}
          onChange={setRef}
        />
        <Pick
          label="Test"
          value={value.op}
          options={ops.some((o) => o.value === value.op) ? ops : [...ops, OPS.find((o) => o.value === value.op)!]}
          onChange={(op) => set({ op, value: op === "between" ? [0, 0] : op === "in" ? asList(value.value) : Array.isArray(value.value) ? (value.value[0] ?? null) : value.value })}
        />
        {valueField}
      </div>
    </fieldset>
  );
}
