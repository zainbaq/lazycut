"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, ChevronRight, KeyRound, Loader2, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";

import { CORNER_LABELS, CornerGlyph, FONT_LABELS, SelectField, Segmented, money } from "@/components/thumbnail/bits";
import { ErrorCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";
import { useResetThumbSettings, useSaveThumbSettings, useThumbSettings } from "@/lib/queries";
import type { Aspect, CornerChoice, ParamValue, TextMode, ThumbFont, ThumbSettings, ThumbSettingsInput } from "@/lib/types";

const CORNER_CHOICES: CornerChoice[] = ["auto", "top_left", "top_right", "bottom_left", "bottom_right"];
const ASPECTS: Aspect[] = ["16:9", "9:16"];

interface Draft {
  model: string;
  params: Record<string, Record<string, ParamValue>>;
  text_mode: TextMode;
  review: boolean;
  text_corner: CornerChoice;
  font: ThumbFont;
  aspects: Aspect[];
  prompt: string;
}

function draftOf(s: ThumbSettings): Draft {
  return {
    model: s.model,
    // Only the options the page can change; other params stay as the YAML sets them.
    params: Object.fromEntries(s.models.map((m) => [m.id, Object.fromEntries(Object.keys(m.options).map((k) => [k, m.params[k]]))])),
    text_mode: s.text_mode,
    review: s.review,
    text_corner: s.text_corner,
    font: s.font,
    aspects: s.aspects,
    prompt: s.prompt,
  };
}

function toInput(d: Draft, s: ThumbSettings): ThumbSettingsInput {
  const custom = d.prompt.trim() && d.prompt.trim() !== s.default_prompt.trim() ? d.prompt : undefined;
  return {
    model: d.model,
    params: d.params,
    text_mode: d.text_mode,
    review: d.review,
    text_corner: d.text_corner,
    font: d.font,
    aspects: d.aspects,
    ...(custom ? { prompt: custom } : {}),
  };
}

function KeyLine({ ok, label, vars }: { ok: boolean | undefined; label: string; vars: string[] }) {
  return (
    <li className="flex flex-wrap items-center gap-2 py-1.5">
      {ok ? <Check aria-hidden="true" size={14} className="text-ok" /> : <KeyRound aria-hidden="true" size={14} className="text-warn" />}
      <span className="text-fg">{label}</span>
      <span className={ok ? "text-oktext" : "text-warn"}>{ok ? "set" : "not set"}</span>
      {!ok ? (
        <span className="text-fg3">
          · add {vars.map((v, i) => (
            <span key={v}>
              {i ? " and " : ""}
              <code className="rounded bg-surface2 px-1 py-0.5 text-fg">{v}</code>
            </span>
          ))}{" "}
          to <code className="rounded bg-surface2 px-1 py-0.5 text-fg">.env</code>
        </span>
      ) : null}
    </li>
  );
}

function ThumbnailSettings({ settings }: { settings: ThumbSettings }) {
  const save = useSaveThumbSettings();
  const reset = useResetThumbSettings();
  const [draft, setDraft] = useState<Draft>(() => draftOf(settings));
  const [saved, setSaved] = useState(false);
  useEffect(() => setDraft(draftOf(settings)), [settings]);
  const ids = { model: useId(), prompt: useId() };
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(draftOf(settings)), [draft, settings]);
  const set = (patch: Partial<Draft>) => {
    setSaved(false);
    setDraft({ ...draft, ...patch });
  };
  const quote = useQuery({
    queryKey: ["thumb-estimate-settings", draft.model, JSON.stringify(draft.params[draft.model] ?? {})],
    queryFn: () => api.estimateThumbnails({ models: [draft.model], aspects: ["16:9"] }),
    enabled: !!settings.keys?.higgsfield && !dirty,
    retry: false,
    staleTime: 10 * 60_000,
  });
  const usd = quote.data?.estimates[0]?.usd;

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(toInput(draft, settings), { onSuccess: () => setSaved(true) });
      }}
    >
      <ul className="flex flex-col rounded-[12px] bg-surface px-3.5 py-1.5">
        <KeyLine ok={settings.keys?.higgsfield} label="Higgsfield (image generation)" vars={["HIGGSFIELD_API_KEY"]} />
        <KeyLine ok={settings.keys?.anthropic} label="Claude (frame ranking and review)" vars={["ANTHROPIC_API_KEY"]} />
      </ul>

      <div className="grid grid-cols-1 gap-3 min-[720px]:grid-cols-2">
        <SelectField
          id={ids.model}
          label="Default model"
          value={draft.model}
          onChange={(model) => set({ model })}
          hint={settings.keys?.higgsfield ? (dirty ? "Save to see the price" : usd != null ? `~${money(usd)} per 16:9 image (Higgsfield's quote)` : quote.isLoading ? "Getting the price…" : "No price quote") : undefined}
        >
          {settings.models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </SelectField>
      </div>

      <fieldset className="flex flex-col gap-3 rounded-[12px] border border-line2 p-3.5">
        <legend className="px-1 text-[12px] font-semibold text-fg2">Model options</legend>
        {settings.models.map((m) => (
          <div key={m.id} className="flex flex-col gap-2">
            <span className="flex items-baseline gap-2 text-[13px] font-semibold text-fg">
              {m.label}
              {m.id === draft.model ? <span className="text-[11px] font-normal text-accentsoft">default</span> : null}
              <code className="ml-auto truncate text-[11px] font-normal text-fg4">{m.path}</code>
            </span>
            <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-2 min-[960px]:grid-cols-3">
              {Object.entries(m.options).map(([key, values]) => (
                <SelectField
                  key={key}
                  id={`${m.id}-${key}`}
                  label={key.replace(/_/g, " ")}
                  value={String(draft.params[m.id]?.[key])}
                  onChange={(raw) => {
                    const value = values.find((v) => String(v) === raw) ?? raw;
                    set({ params: { ...draft.params, [m.id]: { ...draft.params[m.id], [key]: value } } });
                  }}
                >
                  {values.map((v) => (
                    <option key={String(v)} value={String(v)}>
                      {String(v)}
                    </option>
                  ))}
                </SelectField>
              ))}
            </div>
          </div>
        ))}
      </fieldset>

      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-semibold text-fg2">Who draws the word</span>
        <Segmented label="Who draws the word" value={draft.text_mode} options={["app", "model"] as const} onChange={(text_mode) => set({ text_mode })} render={(m) => (m === "app" ? "LazyCut (exact spelling, same template)" : "The image model")} />
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-semibold text-fg2">Default word corner</span>
        <Segmented
          label="Default word corner"
          value={draft.text_corner}
          options={CORNER_CHOICES}
          onChange={(text_corner) => set({ text_corner })}
          render={(c) => (
            <>
              <CornerGlyph corner={c} />
              {CORNER_LABELS[c]}
            </>
          )}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 min-[720px]:grid-cols-2">
        <SelectField id="thumb-font" label="Font" value={draft.font} onChange={(f) => set({ font: f as ThumbFont })}>
          {(Object.keys(FONT_LABELS) as ThumbFont[]).map((f) => (
            <option key={f} value={f}>
              {FONT_LABELS[f]}
            </option>
          ))}
        </SelectField>
        <div className="flex flex-col gap-1">
          <span className="text-[12px] font-semibold text-fg2">Default shapes</span>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Default shapes">
            {ASPECTS.map((a) => {
              const on = draft.aspects.includes(a);
              return (
                <button
                  key={a}
                  type="button"
                  aria-pressed={on}
                  disabled={on && draft.aspects.length === 1}
                  onClick={() => set({ aspects: on ? draft.aspects.filter((x) => x !== a) : ASPECTS.filter((x) => x === a || draft.aspects.includes(x)) })}
                  title={on && draft.aspects.length === 1 ? "Keep at least one shape" : undefined}
                  className={"ink-chip flex min-h-11 items-center rounded-[8px] border px-3 text-[12px] " + (on ? "border-accent bg-chipon text-fg" : "border-line3 text-fg2")}
                >
                  {a === "16:9" ? "16:9 YouTube" : "9:16 Stories"}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <Switch checked={draft.review} onChange={(review) => set({ review })} className="self-start text-left">
        Claude reviews every result (faces, hands, leftover HUD, the word) · a small paid call each
      </Switch>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={ids.prompt} className="flex flex-wrap items-baseline gap-2 text-[12px] font-semibold text-fg2">
          Prompt template
          <span className="font-normal text-fg4">{draft.prompt.trim() === settings.default_prompt.trim() ? "the default" : "your own"}</span>
        </label>
        <textarea
          id={ids.prompt}
          value={draft.prompt}
          rows={10}
          maxLength={4000}
          onChange={(e) => set({ prompt: e.target.value })}
          className="w-full resize-y rounded-[10px] border border-line3 bg-bg p-3 text-[12px] text-fg outline-none focus:border-accent"
        />
        <span className="text-[11px] text-fg4">
          Variables: {"{topic} {subject} {word} {text_style} {text_corner} {aspect} {avoid} {text_instruction} {framing}"}. Leave
          it as the default to keep following config/thumbnails.yaml.
        </span>
        {draft.prompt.trim() !== settings.default_prompt.trim() ? (
          <button type="button" onClick={() => set({ prompt: settings.default_prompt })} className="ink-btn flex min-h-11 items-center gap-1.5 self-start rounded-[10px] border border-line3 px-3.5 text-[12px]">
            Use the default prompt
          </button>
        ) : null}
      </div>

      {save.error ? <ErrorCard title="Settings were not saved" message={save.error.message} /> : null}
      {reset.error ? <ErrorCard title="Could not reset" message={reset.error.message} /> : null}

      <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-2 border-t border-line bg-raised px-4 py-3 min-[720px]:-mx-6 min-[720px]:px-6">
        <button
          type="submit"
          disabled={!dirty || save.isPending}
          className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-4 text-[12px] font-semibold text-onaccent disabled:border-line3 disabled:bg-transparent disabled:text-fg3"
        >
          {save.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Save aria-hidden="true" size={14} />}
          Save
        </button>
        <button
          type="button"
          disabled={!dirty}
          onClick={() => setDraft(draftOf(settings))}
          className="ink-btn flex min-h-11 items-center rounded-[10px] border border-line3 px-3.5 text-[12px] disabled:opacity-50"
        >
          Discard changes
        </button>
        <button
          type="button"
          disabled={reset.isPending}
          onClick={() => {
            setSaved(false);
            reset.mutate();
          }}
          className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px] disabled:opacity-60"
        >
          <RotateCcw aria-hidden="true" size={14} />
          Reset all to defaults
        </button>
        <span role="status" className="text-[12px] text-oktext">
          {saved && !dirty ? "Saved" : reset.isSuccess && !dirty ? "Back to the defaults" : ""}
        </span>
      </div>
    </form>
  );
}

/** `/settings`: Advanced settings. Thumbnails today (BUILD_SPEC 7.13). */
export function SettingsPage() {
  const settings = useThumbSettings();
  return (
    <div className="flex min-h-screen">
      <Rail section="settings" />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
            <Link href="/" className="py-3.5 text-fg">
              Library
            </Link>
            <span aria-hidden="true" className="text-fg4">
              /
            </span>
            <span className="text-fg3">Settings</span>
          </nav>
        </header>
        <main className="mx-auto flex w-full max-w-[880px] flex-col gap-4 px-4 pt-5 min-[720px]:px-6">
          <div className="flex flex-col gap-1">
            <h1 className="font-head text-[22px] leading-tight">Advanced settings</h1>
            <span className="text-fg3">Saved in the app on top of config/thumbnails.yaml. Changes apply to the next Generate.</span>
          </div>
          <Link
            href="/settings/presets"
            className="ink-btn flex min-h-14 items-center gap-3 rounded-[12px] border border-line2 bg-surface px-4 py-3"
          >
            <SlidersHorizontal aria-hidden="true" size={16} className="shrink-0 text-accentsoft" />
            <span className="flex min-w-0 flex-col">
              <span className="text-[14px] font-semibold text-fg">Presets</span>
              <span className="text-[12px] text-fg3">Event types, facts, hooks, claim rules, clip rules and templates, saved to config/presets</span>
            </span>
            <ChevronRight aria-hidden="true" size={16} className="ml-auto shrink-0 text-fg3" />
          </Link>
          <section aria-labelledby="thumb-settings-heading" className="flex flex-col gap-3">
            <h2 id="thumb-settings-heading" className="font-head text-[16px]">
              Thumbnails
            </h2>
            {settings.error ? (
              <ErrorCard title="Could not load the settings" message={settings.error.message} onRetry={() => void settings.refetch()} />
            ) : !settings.data ? (
              <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading settings">
                {Array.from({ length: 4 }, (_, i) => (
                  <span key={i} className="ink-skeleton block h-14 rounded-[12px]" />
                ))}
              </div>
            ) : (
              <ThumbnailSettings settings={settings.data} />
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
