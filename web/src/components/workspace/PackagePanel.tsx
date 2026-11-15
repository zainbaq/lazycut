"use client";

import * as Popover from "@radix-ui/react-popover";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AlertTriangle, ChevronDown, Circle, Minus, PackageOpen, Plus, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ResearchLink } from "@/components/research/ResearchLink";
import { Switch } from "@/components/ui/Switch";
import { panelRise, stamp } from "@/lib/motion";
import { useUpdateFact } from "@/lib/queries";
import type { Fact, FactUpdate, FactValue, Preset } from "@/lib/types";

function show(value: FactValue): string {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function Section({
  icon,
  title,
  tail,
  children,
  defaultOpen = true,
}: {
  icon: React.ReactNode;
  title: string;
  tail?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-[12px] bg-surface px-3 py-1">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex min-h-11 w-full items-center gap-2 text-[13px] font-semibold text-fg"
      >
        {icon}
        {title}
        {tail ? <span className="ml-auto text-[11px] font-normal text-fg3">{tail}</span> : null}
        <ChevronDown
          aria-hidden="true"
          size={14}
          className={`${tail ? "" : "ml-auto"} text-fg3 transition-transform duration-200`}
          style={{ transform: open ? "rotate(180deg)" : undefined }}
        />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div key="body" {...panelRise} className="pb-2">
            {children}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** The value editor that opens from a fact's value: stepper, text, select or yes/no by type. */
function FactEditor({ fact, onSave, onClose }: { fact: Fact; onSave: (body: FactUpdate) => void; onClose: () => void }) {
  const initial = fact.effective_value;
  const [draft, setDraft] = useState<string>(initial === null || initial === undefined ? "" : String(initial));
  const btn = "ink-btn flex min-h-11 items-center justify-center rounded-[10px] border border-line3 px-3 text-[12px] text-fg";

  const parsed = (): FactValue | undefined => {
    if (fact.type === "int") {
      if (draft.trim() === "") return null;
      const n = Number(draft);
      return Number.isInteger(n) && n >= 0 ? n : undefined;
    }
    if (fact.type === "text") return draft.trim() || null;
    return undefined;
  };
  const save = (value: FactValue, confirm = false) => {
    onSave(confirm ? { value, confirmed: true } : { value });
    onClose();
  };

  const proposal = (
    <span className="text-[11px] text-fg3">
      {fact.derive_from ? "Counted from events" : "Proposed"}: <span className="tnum text-fg2">{show(fact.proposed_value)}</span>
    </span>
  );

  if (fact.type === "bool" || fact.type === "enum") {
    const options: { label: string; value: FactValue }[] =
      fact.type === "bool" ? [{ label: "Yes", value: true }, { label: "No", value: false }] : fact.options.map((o) => ({ label: o, value: o }));
    return (
      <div className="flex flex-col gap-1">
        {proposal}
        {options.map((o) => (
          <button
            key={o.label}
            type="button"
            onClick={() => save(o.value)}
            aria-pressed={fact.effective_value === o.value}
            className="flex min-h-11 w-full items-center rounded-[8px] px-2 text-left hover:bg-surface2"
            style={{ background: fact.effective_value === o.value ? "var(--surface-2)" : undefined }}
          >
            {o.label}
          </button>
        ))}
        {fact.value !== null ? (
          <button type="button" onClick={() => save(null)} className="min-h-11 rounded-[8px] px-2 text-left text-fg3 hover:bg-surface2">
            Use the proposal again
          </button>
        ) : null}
      </div>
    );
  }

  const value = parsed();
  const invalid = value === undefined;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!invalid) save(value);
      }}
      className="flex flex-col gap-2"
    >
      {proposal}
      {fact.type === "int" ? (
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label="One less" className={`${btn} w-11 px-0`} onClick={() => setDraft(String(Math.max(0, (Number(draft) || 0) - 1)))}>
            <Minus aria-hidden="true" size={14} />
          </button>
          <label className="flex-1">
            <span className="sr-only">{fact.label}</span>
            <input
              autoFocus
              inputMode="numeric"
              value={draft}
              onChange={(e) => setDraft(e.target.value.replace(/[^\d]/g, ""))}
              className="tnum min-h-11 w-full rounded-[10px] border border-line3 bg-surface px-3 text-center text-[14px] text-fg outline-none focus:border-fg3"
            />
          </label>
          <button type="button" aria-label="One more" className={`${btn} w-11 px-0`} onClick={() => setDraft(String((Number(draft) || 0) + 1))}>
            <Plus aria-hidden="true" size={14} />
          </button>
        </div>
      ) : (
        <label>
          <span className="sr-only">{fact.label}</span>
          <input
            autoFocus
            value={draft}
            maxLength={200}
            onChange={(e) => setDraft(e.target.value)}
            className="min-h-11 w-full rounded-[10px] border border-line3 bg-surface px-3 text-fg outline-none focus:border-fg3"
          />
        </label>
      )}
      <div className="flex gap-1.5">
        {fact.value !== null ? (
          <button type="button" onClick={() => save(null)} className={`${btn} text-fg3`} title="Clear your value and use the proposal">
            Reset
          </button>
        ) : null}
        <button type="submit" disabled={invalid} className={`${btn} ml-auto disabled:opacity-40`}>
          Save
        </button>
        <button
          type="button"
          disabled={invalid || value === null}
          onClick={() => !invalid && save(value, true)}
          className={`${btn} border-accentfill bg-accentfill font-semibold text-onaccent disabled:opacity-40`}
        >
          Confirm
        </button>
      </div>
    </form>
  );
}

function stateText(f: Fact): string {
  if (f.confirmed) return "Confirmed";
  if (f.value !== null && f.value !== undefined) return "Your value, not confirmed";
  if (f.proposed_value === null || f.proposed_value === undefined) return "No proposal · set a value";
  return f.derive_from ? "Counted from events" : "Proposed by the analysis";
}

/** The check seal; plays the stamp when the fact becomes confirmed while on screen (9.5). */
function Seal({ confirmed }: { confirmed: boolean }) {
  const reduced = useReducedMotion();
  const was = useRef(confirmed);
  const [stampKey, setStampKey] = useState(0);
  useEffect(() => {
    if (confirmed && !was.current) setStampKey((k) => k + 1);
    was.current = confirmed;
  }, [confirmed]);
  if (!confirmed) return <Circle aria-hidden="true" size={14} className="shrink-0 text-fg4" />;
  return (
    <motion.span
      key={stampKey}
      aria-hidden="true"
      className="flex shrink-0"
      {...(stampKey && !reduced ? stamp : stampKey ? { initial: { opacity: 0 }, animate: { opacity: 1 } } : {})}
    >
      <ShieldCheck size={16} className="text-ok" />
    </motion.span>
  );
}

function FactRow({ fact, onUpdate }: { fact: Fact; onUpdate: (body: FactUpdate) => void }) {
  const [editing, setEditing] = useState(false);
  const editor = useRef<HTMLDivElement>(null);
  const derived = !!fact.derive_from && fact.event_count !== null;
  const hasValue = fact.effective_value !== null && fact.effective_value !== undefined && fact.effective_value !== "";
  const missing = fact.required && !fact.confirmed;

  return (
    <li className="flex flex-col gap-0.5 border-b border-line py-2 last:border-b-0">
      <div className="flex min-h-9 items-center gap-2">
        <Seal confirmed={fact.confirmed} />
        <span className="min-w-[96px] flex-1 truncate text-fg2" title={fact.label}>
          {fact.label}
          {fact.required ? (
            <span className="text-accentsoft" title="Required before packaging">
              {" "}
              *
            </span>
          ) : null}
        </span>
        <Popover.Root open={editing} onOpenChange={setEditing}>
          <Popover.Trigger
            disabled={fact.confirmed}
            title={fact.confirmed ? "Turn the switch off to edit" : "Edit the value"}
            aria-label={`${fact.label}: ${show(fact.effective_value)}. ${fact.confirmed ? "Confirmed" : "Edit"}`}
            className="ink-btn tnum flex min-h-9 min-w-[44px] max-w-[104px] items-center justify-end rounded-[8px] px-2 text-right text-[13px] text-fg enabled:hover:bg-surface2 disabled:cursor-default"
            style={{ textDecoration: fact.confirmed ? undefined : "underline dotted var(--line-strong)", textUnderlineOffset: 4 }}
          >
            <span className="min-w-0 truncate" title={show(fact.effective_value)}>
              {show(fact.effective_value)}
            </span>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              ref={editor}
              align="end"
              sideOffset={6}
              onOpenAutoFocus={(e) => {
                // Focus the value field (Radix would pick the first button).
                const field = editor.current?.querySelector("input");
                if (field) {
                  e.preventDefault();
                  field.focus();
                  field.select();
                }
              }}
              className="z-50 w-[240px] rounded-[12px] border border-line2 bg-raised p-2.5 text-[12px] text-fg">
              <span className="mb-1.5 block font-semibold">{fact.label}</span>
              <FactEditor fact={fact} onSave={onUpdate} onClose={() => setEditing(false)} />
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
        <Switch
          checked={fact.confirmed}
          disabled={!fact.confirmed && !hasValue}
          label={`${fact.confirmed ? "Unconfirm" : "Confirm"} ${fact.label}`}
          onChange={(on) => onUpdate({ confirmed: on })}
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-2 pl-6 text-[11px] text-fg3">
        <span>{stateText(fact)}</span>
        {derived ? (
          <span className="tnum">
            · {fact.verified_count ?? 0} of {fact.event_count} verified
          </span>
        ) : null}
        {missing ? <span className="text-accentsoft">· required</span> : null}
      </div>
      {fact.out_of_date && fact.event_count !== null ? (
        <div role="status" className="ml-6 mt-1 flex flex-wrap items-center gap-2 rounded-[8px] border border-warnline px-2 py-1 text-[11px] text-fg2">
          <AlertTriangle aria-hidden="true" size={12} className="shrink-0 text-warn" />
          <span className="tnum">May be out of date · count is now {fact.event_count}</span>
          <button
            type="button"
            onClick={() => onUpdate({ value: fact.event_count, confirmed: true })}
            className="ink-btn ml-auto min-h-8 rounded-[6px] px-2 font-semibold text-fg"
          >
            Use {fact.event_count}
          </button>
        </div>
      ) : null}
    </li>
  );
}

/** Right panel (9.4 region 7). Phase 1 step 4: facts are confirmed here; packaging arrives later. */
export function PackagePanel({
  videoId,
  preset,
  facts,
  factsLoading,
  factsError,
  analyzed,
}: {
  videoId: string;
  preset: Preset | undefined;
  facts: Fact[] | undefined;
  factsLoading: boolean;
  factsError: string | null;
  analyzed: boolean;
}) {
  const update = useUpdateFact(videoId);
  const hasClaims = (preset?.facts ?? []).length > 0;
  const confirmed = (facts ?? []).filter((f) => f.confirmed).length;
  const requiredLeft = (facts ?? []).filter((f) => f.required && !f.confirmed);
  return (
    <aside
      aria-label="Package"
      className="flex min-w-0 flex-col gap-3 border-t border-line bg-raised p-4 min-[1100px]:w-[300px] min-[1100px]:shrink-0 min-[1100px]:border-l min-[1100px]:border-t-0"
    >
      <h2 className="font-head text-[16px]">Package</h2>
      <Section
        icon={<ShieldCheck aria-hidden="true" size={14} className="text-accentsoft" />}
        title={hasClaims ? "Facts to confirm" : "Detected"}
        tail={facts && facts.length ? `${confirmed} of ${facts.length} confirmed` : undefined}
      >
        {factsLoading ? (
          <div className="flex flex-col gap-1.5" aria-busy="true">
            <span className="ink-skeleton block h-8 rounded-[8px]" />
            <span className="ink-skeleton block h-8 rounded-[8px]" />
          </div>
        ) : factsError ? (
          <span role="alert" className="block py-2 text-fg2">
            Could not load the facts: {factsError}
          </span>
        ) : facts && facts.length ? (
          <>
            {!analyzed ? <span className="block pb-1 text-[11px] text-fg3">Not analyzed yet: counts follow the events you add.</span> : null}
            <ul className="flex flex-col">
              {facts.map((f) => (
                <FactRow key={f.id} fact={f} onUpdate={(body) => update.mutate({ id: f.id, body })} />
              ))}
            </ul>
          </>
        ) : (
          <span className="block py-2 text-fg3">This preset defines no facts.</span>
        )}
        {update.error ? (
          <span role="alert" className="mt-1 block rounded-[8px] border border-accent px-2 py-1.5 text-fg">
            {update.error.message}
          </span>
        ) : null}
        {requiredLeft.length ? (
          <span className="block pt-1.5 text-[11px] text-fg3">
            Packaging needs {requiredLeft.map((f) => f.label).join(", ")} confirmed.
          </span>
        ) : facts && facts.length && hasClaims ? (
          <span className="block pt-1.5 text-[11px] text-oktext">Every required fact is confirmed.</span>
        ) : null}
      </Section>
      <ResearchLink videoId={videoId} />
      <div className="flex flex-col gap-2 rounded-[12px] border border-dashed border-line3 p-3 text-fg3">
        <span className="flex items-center gap-2 text-[13px] font-semibold text-fg2">
          <PackageOpen aria-hidden="true" size={14} className="text-accentsoft" />
          Platforms, titles and rules
        </span>
        <span>Packages are generated once the facts are confirmed. That part of LazyCut arrives in a later step.</span>
      </div>
    </aside>
  );
}
