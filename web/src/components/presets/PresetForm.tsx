"use client";

import { X } from "lucide-react";
import { useId } from "react";

import { Switch } from "@/components/ui/Switch";
import type { BannedTagDef, ClaimRuleDef, Condition, EventType, FactDef, HookDef, PresetDoc, PresetProblem, ResearchFieldDef } from "@/lib/types";

import { AddButton, Area, ConditionField, type ConditionSubject, Item, Pick, Section, Text, Words, inputCls, moved, under } from "./fields";

/** Variables every template may use (api/app/services/presets.py BUILTIN_VARIABLES). */
const BUILTIN = ["topic", "subject", "channel_name", "display_name", "handle", "tagline", "playlist_url", "subscribe_url", "full_video_ref", "chapters", "credit_block", "hashtags", "hook"];

const GLYPHS = ["slash", "dot", "ring", "diamond"] as const;
const COLORS = ["accent", "paper", "warn", "gold"] as const;

/** Ids already saved: renaming one would orphan what refers to it (events, facts, research), so they are locked here. */
export interface Locked {
  event_types: Set<string>;
  facts: Set<string>;
  research_fields: Set<string>;
  hooks: Set<string>;
  claim_rules: Set<string>;
}

const orNull = (v: string) => (v.trim() === "" ? null : v);
const LOCK_HINT = "Saved ids are fixed here because events, facts or research refer to them. Rename one in the YAML tab.";

function NumberField({ label, value, onChange, hint }: { label: string; value: number; onChange: (v: number) => void; hint?: string }) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1">
      <span className="text-[12px] font-semibold text-fg2">{label}</span>
      <input id={id} type="number" step={0.1} min={0} value={value} onChange={(e) => onChange(Number(e.target.value) || 0)} className={`${inputCls} tnum`} />
      {hint ? <span className="text-[11px] text-fg4">{hint}</span> : null}
    </label>
  );
}

/** A list of longer strings (title patterns, credit lines, seeds), one field each. */
function Lines({ label, values, onChange, hint, addLabel }: { label: string; values: string[]; onChange: (v: string[]) => void; hint?: string; addLabel: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] font-semibold text-fg2">{label}</span>
      {values.map((v, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <input
            aria-label={`${label} ${i + 1}`}
            value={v}
            onChange={(e) => onChange(values.map((x, j) => (j === i ? e.target.value : x)))}
            className={`${inputCls} font-mono text-[12px]`}
          />
          <button type="button" aria-label={`Remove ${label} ${i + 1}`} onClick={() => onChange(values.filter((_, j) => j !== i))} className="ink-btn flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] text-fg3">
            <X aria-hidden="true" size={14} />
          </button>
        </div>
      ))}
      <AddButton label={addLabel} onClick={() => onChange([...values, ""])} />
      {hint ? <span className="text-[11px] text-fg4">{hint}</span> : null}
    </div>
  );
}

export function PresetForm({
  draft,
  onChange,
  problems,
  locked,
}: {
  draft: PresetDoc;
  onChange: (next: PresetDoc) => void;
  problems: PresetProblem[];
  locked: Locked;
}) {
  const set = (patch: Partial<PresetDoc>) => onChange({ ...draft, ...patch });
  const eventIds = draft.event_types.map((e) => e.id).filter(Boolean);
  const factKeys = draft.facts.map((f) => f.key).filter(Boolean);
  const researchKeys = draft.research_fields.map((r) => r.key).filter(Boolean);
  const subjects: ConditionSubject[] = [
    ...draft.facts.filter((f) => f.key).map((f) => ({ ref: `fact:${f.key}`, label: `Fact · ${f.label || f.key}`, kind: f.type, options: f.options })),
    ...draft.research_fields.filter((r) => r.key).map((r) => ({ ref: `research:${r.key}`, label: `Research · ${r.label || r.key}`, kind: r.type })),
  ];
  const variables = [...BUILTIN, ...factKeys, ...researchKeys, ...Object.keys(draft.slots)];
  const varHint = `Variables: ${variables.map((v) => `{${v}}`).join(" ")}`;
  const firstSubject = (): Condition =>
    subjects[0]?.ref.startsWith("research:")
      ? { fact: null, research: subjects[0].ref.slice(9), op: "eq", value: true }
      : { fact: subjects[0]?.ref.slice(5) ?? null, research: null, op: "eq", value: 0 };

  function list<K extends "event_types" | "facts" | "research_fields" | "hooks" | "claim_rules">(key: K) {
    type T = PresetDoc[K][number];
    const items = draft[key] as T[];
    return {
      items,
      update: (i: number, patch: Partial<T>) => set({ [key]: items.map((x, j) => (j === i ? { ...x, ...patch } : x)) } as Partial<PresetDoc>),
      move: (from: number, to: number) => set({ [key]: moved(items, from, to) } as Partial<PresetDoc>),
      remove: (i: number) => set({ [key]: items.filter((_, j) => j !== i) } as Partial<PresetDoc>),
      add: (item: T) => set({ [key]: [...items, item] } as Partial<PresetDoc>),
      problems: (i: number) => under(problems, `${key}.${i}`),
    };
  }

  const events = list("event_types");
  const facts = list("facts");
  const research = list("research_fields");
  const hooks = list("hooks");
  const claims = list("claim_rules");
  const plainBans = draft.banned_tags.filter((b): b is string => typeof b === "string");
  const ruleBans = draft.banned_tags.filter((b): b is BannedTagDef => typeof b !== "string");
  const slotEntries = Object.entries(draft.slots);

  return (
    <div className="flex flex-col gap-2.5">
      <Section title="Name and description" problems={[...under(problems, "name"), ...under(problems, "description")]} defaultOpen>
        <Text label="Name" value={draft.name} onChange={(name) => set({ name })} />
        <Area label="Description" value={draft.description} rows={2} onChange={(description) => set({ description })} />
      </Section>

      <Section title="Event types" count={draft.event_types.length} problems={under(problems, "event_types")} note="What the analysis looks for. Gemini reads each definition. Removing a type leaves its events with a plain chip until the video is re-analyzed.">
        <ul className="flex flex-col gap-2">
          {events.items.map((e: EventType, i) => (
            <Item key={i} title={e.label || e.id || "New event type"} index={i} total={events.items.length} onMove={(to) => events.move(i, to)} onRemove={() => events.remove(i)} problems={events.problems(i)}>
              <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-2">
                <Text label="Id" mono value={e.id} disabled={locked.event_types.has(e.id)} title={locked.event_types.has(e.id) ? LOCK_HINT : undefined} onChange={(id) => events.update(i, { id })} />
                <Text label="Label" value={e.label} onChange={(label) => events.update(i, { label })} />
                <Pick label="Glyph" value={e.glyph} options={GLYPHS.map((g) => ({ value: g, label: g }))} onChange={(glyph) => events.update(i, { glyph })} />
                <Pick label="Colour" value={e.color} options={COLORS.map((c) => ({ value: c, label: c }))} onChange={(color) => events.update(i, { color })} />
              </div>
              <Area label="Definition" rows={2} value={e.definition} onChange={(definition) => events.update(i, { definition })} />
              <Switch checked={e.show} onChange={(show) => events.update(i, { show })} className="self-start">
                Shown on the timeline at first
              </Switch>
            </Item>
          ))}
        </ul>
        <AddButton label="Add an event type" onClick={() => events.add({ id: "", label: "", glyph: "dot", color: "paper", definition: "", show: true })} />
      </Section>

      <Section title="Facts" count={draft.facts.length} problems={under(problems, "facts")} note="What you confirm before packaging. A fact counted from events follows the timeline; claims and hooks only use confirmed facts.">
        <ul className="flex flex-col gap-2">
          {facts.items.map((f: FactDef, i) => (
            <Item key={i} title={f.label || f.key || "New fact"} index={i} total={facts.items.length} onMove={(to) => facts.move(i, to)} onRemove={() => facts.remove(i)} problems={facts.problems(i)}>
              <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-2">
                <Text label="Key" mono value={f.key} disabled={locked.facts.has(f.key)} title={locked.facts.has(f.key) ? LOCK_HINT : undefined} onChange={(key) => facts.update(i, { key })} />
                <Text label="Label" value={f.label} onChange={(label) => facts.update(i, { label })} />
                <Pick
                  label="Type"
                  value={f.type}
                  options={[{ value: "int", label: "number" }, { value: "text", label: "text" }, { value: "bool", label: "yes / no" }, { value: "enum", label: "one of a list" }]}
                  onChange={(type) => facts.update(i, { type })}
                />
                <Pick
                  label="Counted from"
                  value={f.derive_from ?? ""}
                  options={[{ value: "", label: "Not counted (typed or proposed)" }, ...eventIds.map((id) => ({ value: id, label: `${id} events` }))]}
                  onChange={(v) => facts.update(i, { derive_from: v || null })}
                />
              </div>
              {f.type === "enum" ? <Words label="Options" values={f.options} onChange={(options) => facts.update(i, { options })} /> : null}
              <Area label="Instructions for the analysis" rows={2} value={f.instructions ?? ""} onChange={(v) => facts.update(i, { instructions: orNull(v) })} />
              <Switch checked={f.required} onChange={(required) => facts.update(i, { required })} className="self-start">
                Required before packaging
              </Switch>
            </Item>
          ))}
        </ul>
        <AddButton label="Add a fact" onClick={() => facts.add({ key: "", label: "", type: "int", options: [], derive_from: null, required: false, instructions: null })} />
      </Section>

      <Section title="Research fields" count={draft.research_fields.length} problems={[...under(problems, "research_fields"), ...under(problems, "credit_fields")]} note="What subject research looks up, with a source for each.">
        <ul className="flex flex-col gap-2">
          {research.items.map((r: ResearchFieldDef, i) => (
            <Item key={i} title={r.label || r.key || "New field"} index={i} total={research.items.length} onMove={(to) => research.move(i, to)} onRemove={() => research.remove(i)} problems={research.problems(i)}>
              <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-3">
                <Text label="Key" mono value={r.key} disabled={locked.research_fields.has(r.key)} title={locked.research_fields.has(r.key) ? LOCK_HINT : undefined} onChange={(key) => research.update(i, { key })} />
                <Text label="Label" value={r.label ?? ""} placeholder={r.key.replace(/_/g, " ")} onChange={(v) => research.update(i, { label: orNull(v) })} />
                <Pick label="Type" value={r.type} options={[{ value: "text", label: "text" }, { value: "bool", label: "yes / no" }]} onChange={(type) => research.update(i, { type })} />
              </div>
              <Text label="Hint for the research model" value={r.hint ?? ""} onChange={(v) => research.update(i, { hint: orNull(v) })} />
              <Switch checked={r.needs_credible_source} onChange={(needs_credible_source) => research.update(i, { needs_credible_source })} className="self-start">
                Needs a credible source before it can back a claim
              </Switch>
            </Item>
          ))}
        </ul>
        <AddButton label="Add a research field" onClick={() => research.add({ key: "", label: null, type: "text", needs_credible_source: false, hint: null })} />
      </Section>

      <Section title="Hooks" count={draft.hooks.length} problems={under(problems, "hooks")} note="Short claims for titles and thumbnails. A hook is offered only when its condition holds, and its text may only use facts.">
        <ul className="flex flex-col gap-2">
          {hooks.items.map((h: HookDef, i) => (
            <Item key={i} title={h.text || h.id || "New hook"} index={i} total={hooks.items.length} onMove={(to) => hooks.move(i, to)} onRemove={() => hooks.remove(i)} problems={hooks.problems(i)}>
              <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-2">
                <Text label="Id" mono value={h.id} disabled={locked.hooks.has(h.id)} title={locked.hooks.has(h.id) ? LOCK_HINT : undefined} onChange={(id) => hooks.update(i, { id })} />
                <Text label="Text" value={h.text} hint={factKeys.length ? `Facts: ${factKeys.map((k) => `{${k}}`).join(" ")}` : undefined} onChange={(text) => hooks.update(i, { text })} />
                <Text label="Thumbnail word" value={h.thumbnail_word ?? ""} onChange={(v) => hooks.update(i, { thumbnail_word: orNull(v) })} />
                <Text label="Thumbnail text style" value={h.thumbnail_text_style ?? ""} placeholder="the channel's default" onChange={(v) => hooks.update(i, { thumbnail_text_style: orNull(v) })} />
              </div>
              <ConditionField label="Offered when" value={h.when} subjects={subjects} onChange={(when) => hooks.update(i, { when })} />
            </Item>
          ))}
        </ul>
        <AddButton label="Add a hook" onClick={() => hooks.add({ id: "", text: "", thumbnail_word: null, thumbnail_text_style: null, when: firstSubject() })} />
      </Section>

      <Section title="Claim rules" count={draft.claim_rules.length} problems={under(problems, "claim_rules")} note="Phrases that may only appear when a fact or research value backs them. Checked on every title, description and caption.">
        <ul className="flex flex-col gap-2">
          {claims.items.map((c: ClaimRuleDef, i) => (
            <Item key={i} title={c.id || "New claim rule"} index={i} total={claims.items.length} onMove={(to) => claims.move(i, to)} onRemove={() => claims.remove(i)} problems={claims.problems(i)}>
              <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-3">
                <Text label="Id" mono value={c.id} disabled={locked.claim_rules.has(c.id)} title={locked.claim_rules.has(c.id) ? LOCK_HINT : undefined} onChange={(id) => claims.update(i, { id })} />
                <Pick label="When it fails" value={c.severity} options={[{ value: "block", label: "Block" }, { value: "warn", label: "Warn" }]} onChange={(severity) => claims.update(i, { severity })} />
                <Text label="Suggest instead" value={c.suggest ?? ""} onChange={(v) => claims.update(i, { suggest: orNull(v) })} />
              </div>
              <Words label="Phrases" values={c.phrases} onChange={(phrases) => claims.update(i, { phrases })} />
              <ConditionField label="Allowed only when" value={c.requires} subjects={subjects} onChange={(requires) => claims.update(i, { requires })} />
            </Item>
          ))}
        </ul>
        <AddButton label="Add a claim rule" onClick={() => claims.add({ id: "", phrases: [], requires: firstSubject(), severity: "block", suggest: null })} />
      </Section>

      <Section title="Titles" problems={under(problems, "title_patterns")} note={varHint}>
        <Text label="Recommended pattern" mono value={draft.title_patterns.recommended} onChange={(recommended) => set({ title_patterns: { ...draft.title_patterns, recommended } })} />
        <Lines label="Alternates" addLabel="Add an alternate" values={draft.title_patterns.alternates} onChange={(alternates) => set({ title_patterns: { ...draft.title_patterns, alternates } })} />
      </Section>

      <Section title="Clips" problems={[...under(problems, "clip_rules"), ...under(problems, "saved_prompts")]} note="How the clip finder places edges, and the prompts offered as chips in the Clips panel.">
        <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-2">
          <NumberField label="Lead-in (s)" hint="Start this long before the first event" value={draft.clip_rules.lead_in_s} onChange={(lead_in_s) => set({ clip_rules: { ...draft.clip_rules, lead_in_s } })} />
          <NumberField label="Tail (s)" hint="End this long after the closing event" value={draft.clip_rules.tail_s} onChange={(tail_s) => set({ clip_rules: { ...draft.clip_rules, tail_s } })} />
          <Text label="Start cue" value={draft.clip_rules.start_cue ?? ""} onChange={(v) => set({ clip_rules: { ...draft.clip_rules, start_cue: orNull(v) } })} />
          <Text label="End cue" value={draft.clip_rules.end_cue ?? ""} onChange={(v) => set({ clip_rules: { ...draft.clip_rules, end_cue: orNull(v) } })} />
        </div>
        <Words label="Event types that close a clip" values={draft.clip_rules.end_on} suggestions={eventIds} onChange={(end_on) => set({ clip_rules: { ...draft.clip_rules, end_on } })} />
        <Words label="Saved prompts" values={draft.saved_prompts} onChange={(saved_prompts) => set({ saved_prompts })} />
      </Section>

      <Section title="Writer slots" count={slotEntries.length} problems={under(problems, "slots")} note="Text the writer fills, each with its instruction. Templates use a slot as {its_name}.">
        <ul className="flex flex-col gap-2">
          {slotEntries.map(([name, instruction], i) => (
            <li key={i} className="grid grid-cols-1 gap-2 rounded-[10px] border border-line2 p-3 min-[720px]:grid-cols-[180px_1fr_auto]">
              <Text
                label="Name"
                mono
                value={name}
                onChange={(next) => set({ slots: Object.fromEntries(slotEntries.map(([k, v], j) => (j === i ? [next, v] : [k, v]))) })}
              />
              <Area label="Instruction" rows={2} value={instruction} onChange={(v) => set({ slots: { ...draft.slots, [name]: v } })} />
              <button
                type="button"
                aria-label={`Remove slot ${name}`}
                onClick={() => set({ slots: Object.fromEntries(slotEntries.filter((_, j) => j !== i)) })}
                className="ink-btn flex h-11 w-11 items-center justify-center self-start rounded-[10px] text-fg3 min-[720px]:mt-5"
              >
                <X aria-hidden="true" size={14} />
              </button>
            </li>
          ))}
        </ul>
        <AddButton
          label="Add a slot"
          onClick={() => {
            let n = slotEntries.length + 1;
            while (`slot_${n}` in draft.slots) n += 1;
            set({ slots: { ...draft.slots, [`slot_${n}`]: "" } });
          }}
        />
      </Section>

      <Section title="Templates" problems={[...under(problems, "templates"), ...under(problems, "credit_lines"), ...under(problems, "playlist_name")]} note={varHint}>
        <Area label="Long-form description" mono rows={6} hint="Empty uses the channel's template (channel.yaml)." value={draft.templates.description ?? ""} onChange={(v) => set({ templates: { ...draft.templates, description: orNull(v) } })} />
        <Area label="Shorts description" mono rows={6} value={draft.templates.shorts_description ?? ""} onChange={(v) => set({ templates: { ...draft.templates, shorts_description: orNull(v) } })} />
        <Area label="Reel and TikTok" mono rows={7} hint="ON-SCREEN: is the text on the clip; CAPTION: and the rest is the caption." value={draft.templates.reel ?? ""} onChange={(v) => set({ templates: { ...draft.templates, reel: orNull(v) } })} />
        <Text label="Reel end text" mono value={draft.templates.reel_end_text ?? ""} onChange={(v) => set({ templates: { ...draft.templates, reel_end_text: orNull(v) } })} />
        <Text label="Playlist name to suggest" mono value={draft.playlist_name} onChange={(playlist_name) => set({ playlist_name })} />
        <Words label="Credit fields" values={draft.credit_fields} suggestions={researchKeys} onChange={(credit_fields) => set({ credit_fields })} />
        <Lines label="Credit lines" addLabel="Add a credit line" hint="A line whose first variable is empty is left out." values={draft.credit_lines} onChange={(credit_lines) => set({ credit_lines })} />
      </Section>

      <Section
        title="Tags, hashtags and search"
        problems={["thumbnail_words", "tag_recipe", "banned_tags", "search_seeds", "search_fit", "fallback_hashtags", "competitor_query"].flatMap((k) => under(problems, k))}
      >
        <Words label="Thumbnail words with no claim" values={draft.thumbnail_words} onChange={(thumbnail_words) => set({ thumbnail_words })} />
        <Words label="Tag recipe" values={draft.tag_recipe} hint="Groups of tags, in order." onChange={(tag_recipe) => set({ tag_recipe })} />
        <Words label="Banned tags" values={plainBans} onChange={(next) => set({ banned_tags: [...next, ...ruleBans] })} />
        {ruleBans.length ? (
          <ul className="flex flex-col gap-2">
            {ruleBans.map((b, i) => (
              <li key={i} className="flex flex-col gap-2 rounded-[10px] border border-line2 p-3">
                <div className="flex items-end gap-1.5">
                  <Text label="Banned tag" value={b.tag} onChange={(tag) => set({ banned_tags: [...plainBans, ...ruleBans.map((x, j) => (j === i ? { ...x, tag } : x))] })} />
                  <button type="button" aria-label={`Remove banned tag ${b.tag}`} onClick={() => set({ banned_tags: [...plainBans, ...ruleBans.filter((_, j) => j !== i)] })} className="ink-btn flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] text-fg3">
                    <X aria-hidden="true" size={14} />
                  </button>
                </div>
                {b.unless ? (
                  <ConditionField label="Allowed when" value={b.unless} subjects={subjects} onChange={(unless) => set({ banned_tags: [...plainBans, ...ruleBans.map((x, j) => (j === i ? { ...x, unless } : x))] })} />
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        <AddButton label="Ban a tag unless research backs it" onClick={() => set({ banned_tags: [...plainBans, ...ruleBans, { tag: "", unless: firstSubject() }] })} />
        <Lines label="Search seeds" addLabel="Add a seed" hint="Only {topic} and {name} may be used." values={draft.search_seeds} onChange={(search_seeds) => set({ search_seeds })} />
        <Area label="Which search phrases fit this kind of video" rows={3} value={draft.search_fit} onChange={(search_fit) => set({ search_fit })} />
        <Text
          label="Competitor search"
          mono
          hint="The YouTube search that finds videos like this one, on the research page. Only {topic} and {subject}."
          value={draft.competitor_query}
          onChange={(competitor_query) => set({ competitor_query })}
        />
        <Words label="Fallback hashtags" values={draft.fallback_hashtags} onChange={(fallback_hashtags) => set({ fallback_hashtags })} />
      </Section>
    </div>
  );
}
