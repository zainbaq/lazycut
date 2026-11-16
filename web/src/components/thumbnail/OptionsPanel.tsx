"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ChevronDown, Coins, KeyRound, Loader2, Wand2 } from "lucide-react";
import { useId, useState } from "react";

import { panelRise } from "@/lib/motion";
import { useGenerateThumbnails, useThumbEstimate } from "@/lib/queries";
import type { Aspect, CornerChoice, TextMode, ThumbnailState } from "@/lib/types";

import { CORNER_LABELS, CornerGlyph, SectionTitle, Segmented, modelLabel, money } from "./bits";
import type { PickedSource } from "./SourcePanel";

const CORNER_CHOICES: CornerChoice[] = ["auto", "top_left", "top_right", "bottom_left", "bottom_right"];
const ASPECTS: Aspect[] = ["16:9", "9:16"];
const MAX_COMPARE = 4;

export interface Options {
  word: string;
  corner: CornerChoice;
  aspects: Aspect[];
  models: string[];
  textMode: TextMode;
  ownPrompt: string | null;
}

export function defaultOptions(state: ThumbnailState): Options {
  const s = state.settings;
  return {
    word: state.words[0]?.word ?? "",
    corner: s.text_corner,
    aspects: s.aspects.length ? s.aspects : ["16:9"],
    models: [s.model],
    textMode: s.text_mode,
    ownPrompt: null,
  };
}

function CostLine({ state, opts }: { state: ThumbnailState; opts: Options }) {
  const est = useThumbEstimate(opts.models, opts.aspects, state.can_generate);
  const n = opts.models.length * opts.aspects.length;
  if (!state.can_generate) return null;
  if (est.isLoading) return <span className="text-[11px] text-fg4">Getting Higgsfield&apos;s price…</span>;
  const list = est.data?.estimates ?? [];
  const known = list.filter((e) => e.usd != null);
  if (!list.length || known.length < list.length) {
    return <span className="text-[11px] text-fg3">Price unknown: Higgsfield gave no quote{est.error ? ` (${est.error.message})` : ""}. Each image is still a paid call.</span>;
  }
  const total = known.reduce((sum, e) => sum + (e.usd ?? 0), 0);
  const same = known.every((e) => e.usd === known[0].usd);
  return (
    <span className="text-[11px] text-fg3">
      {same ? `~${money(known[0].usd)} each` : "Prices differ by model"}
      {n > 1 ? ` · ~${money(total)} in all` : ""} · Higgsfield&apos;s quote, charged per image
    </span>
  );
}

export function OptionsPanel({
  videoId,
  state,
  source,
  opts,
  setOpts,
}: {
  videoId: string;
  state: ThumbnailState;
  source: PickedSource | null;
  opts: Options;
  setOpts: (o: Options) => void;
}) {
  const reduced = useReducedMotion();
  const generate = useGenerateThumbnails(videoId);
  const [promptOpen, setPromptOpen] = useState(false);
  const wordId = useId();
  const modelId = useId();
  const promptId = useId();
  const settings = state.settings;
  const set = (patch: Partial<Options>) => setOpts({ ...opts, ...patch });
  const n = opts.models.length * opts.aspects.length;
  const busy = state.running || generate.isPending;
  const blocker = !state.can_generate
    ? state.missing[0] ?? "Thumbnails are off"
    : !source
      ? "Pick a source first"
      : !opts.aspects.length
        ? "Pick at least one shape"
        : busy
          ? "Thumbnails are being made"
          : null;

  const toggleCompare = (id: string) => {
    if (opts.models.includes(id)) {
      if (opts.models.length > 1) set({ models: opts.models.filter((m) => m !== id) });
    } else if (opts.models.length < MAX_COMPARE) {
      set({ models: [...opts.models, id] });
    }
  };

  const submit = () => {
    if (blocker || !source) return;
    generate.mutate({
      source: source.kind === "frame" ? { kind: "frame", t: source.t } : { kind: "upload", upload_id: source.upload_id },
      models: opts.models,
      aspects: opts.aspects,
      word: opts.word.trim(),
      text_corner: opts.corner,
      text_mode: opts.textMode,
      prompt: opts.ownPrompt?.trim() ? opts.ownPrompt : undefined,
    });
  };

  return (
    <section aria-labelledby="options-heading" className="flex min-w-0 flex-col gap-3.5">
      <SectionTitle id="options-heading">Options</SectionTitle>

      {!state.can_generate ? (
        <div className="flex flex-col gap-1.5 rounded-[12px] border border-warnline bg-surface p-3.5">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-warn">
            <KeyRound aria-hidden="true" size={14} />
            Image generation is off
          </span>
          <span className="text-fg2">
            Set <code className="rounded bg-surface2 px-1 py-0.5 text-fg">HIGGSFIELD_API_KEY</code> in{" "}
            <code className="rounded bg-surface2 px-1 py-0.5 text-fg">.env</code> (the API key from console.higgsfield.ai),
            then restart the api container. You can still find frames and set everything up.
          </span>
        </div>
      ) : null}

      <div className="flex flex-col gap-1.5">
        <label htmlFor={wordId} className="text-[12px] font-semibold text-fg2">
          Word <span className="font-normal text-fg4">2–4 words, never the title; claims are checked against your facts</span>
        </label>
        {state.words.length ? (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Words from the package">
            {state.words.map((w) => (
              <button
                key={w.word}
                type="button"
                aria-pressed={opts.word === w.word}
                onClick={() => set({ word: w.word })}
                title={w.text_style ? `Style: ${w.text_style}` : undefined}
                className={
                  "ink-chip flex min-h-11 items-center rounded-[8px] border px-3 text-[12px] font-semibold tracking-wide " +
                  (opts.word === w.word ? "border-accent bg-chipon text-fg" : "border-line3 text-fg2")
                }
              >
                {w.word}
              </button>
            ))}
            <button
              type="button"
              aria-pressed={opts.word === ""}
              onClick={() => set({ word: "" })}
              className={
                "ink-chip flex min-h-11 items-center rounded-[8px] border px-3 text-[12px] " +
                (opts.word === "" ? "border-accent bg-chipon text-fg" : "border-line3 text-fg3")
              }
            >
              No word
            </button>
          </div>
        ) : (
          <span className="text-[11px] text-fg4">Generate the package first for rule-checked words, or type one.</span>
        )}
        <input
          id={wordId}
          value={opts.word}
          maxLength={40}
          placeholder="Or type your own"
          onChange={(e) => set({ word: e.target.value.toUpperCase() })}
          className="min-h-11 w-full rounded-[10px] border border-line3 bg-bg px-3 text-[13px] font-semibold tracking-wide text-fg outline-none focus:border-accent"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-semibold text-fg2">Word corner</span>
        <Segmented
          label="Word corner"
          value={opts.corner}
          options={CORNER_CHOICES}
          onChange={(corner) => set({ corner })}
          render={(c) => (
            <>
              <CornerGlyph corner={c} />
              {CORNER_LABELS[c]}
            </>
          )}
        />
        {opts.corner === "auto" ? <span className="text-[11px] text-fg4">Auto uses the calm corner the frame finder suggested.</span> : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-semibold text-fg2">Shapes</span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Shapes">
          {ASPECTS.map((a) => {
            const on = opts.aspects.includes(a);
            return (
              <button
                key={a}
                type="button"
                aria-pressed={on}
                onClick={() => set({ aspects: on ? opts.aspects.filter((x) => x !== a) : ASPECTS.filter((x) => x === a || opts.aspects.includes(x)) })}
                className={"ink-chip flex min-h-11 items-center gap-2 rounded-[8px] border px-3 text-[12px] " + (on ? "border-accent bg-chipon text-fg" : "border-line3 text-fg2")}
              >
                <span aria-hidden="true" className="block rounded-[2px] border border-current" style={a === "16:9" ? { width: 18, height: 10 } : { width: 9, height: 16 }} />
                {a === "16:9" ? "16:9 YouTube" : "9:16 Stories"}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={modelId} className="text-[12px] font-semibold text-fg2">
          Model
        </label>
        <select
          id={modelId}
          value={opts.models[0]}
          onChange={(e) => set({ models: [e.target.value, ...opts.models.slice(1).filter((m) => m !== e.target.value)] })}
          className="min-h-11 w-full rounded-[10px] border border-line3 bg-bg px-3 text-[13px] text-fg outline-none focus:border-accent"
        >
          {settings.models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
              {m.id === settings.model ? " (default)" : ""}
            </option>
          ))}
        </select>
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={`Compare models, up to ${MAX_COMPARE}`}>
          <span className="text-[11px] text-fg3">Compare on the same source:</span>
          {settings.models.map((m) => {
            const on = opts.models.includes(m.id);
            const full = !on && opts.models.length >= MAX_COMPARE;
            return (
              <button
                key={m.id}
                type="button"
                aria-pressed={on}
                disabled={full || (on && opts.models.length === 1)}
                onClick={() => toggleCompare(m.id)}
                className={"ink-chip flex min-h-11 items-center rounded-[8px] border px-2.5 text-[11px] disabled:opacity-50 " + (on ? "border-accent bg-chipon text-fg" : "border-line3 text-fg3")}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-semibold text-fg2">Who draws the word</span>
        <Segmented
          label="Who draws the word"
          value={opts.textMode}
          options={["app", "model"] as const}
          onChange={(textMode) => set({ textMode })}
          render={(m) => (m === "app" ? "LazyCut (exact, free to change)" : "The image model")}
        />
      </div>

      <section aria-label="Prompt" className="rounded-[12px] bg-surface px-3.5 py-1">
        <button type="button" aria-expanded={promptOpen} onClick={() => setPromptOpen(!promptOpen)} className="flex min-h-11 w-full items-center gap-2 text-[13px] font-semibold text-fg">
          <Wand2 aria-hidden="true" size={14} className="text-accentsoft" />
          Prompt
          <span className="ml-auto text-[11px] font-normal text-fg3">{opts.ownPrompt !== null ? "your own" : settings.custom_prompt ? "your saved template" : "built from the preset"}</span>
          <ChevronDown aria-hidden="true" size={14} className="text-fg3 transition-transform duration-200" style={{ transform: promptOpen ? "rotate(180deg)" : undefined }} />
        </button>
        <AnimatePresence initial={false}>
          {promptOpen ? (
            <motion.div key="prompt" {...(reduced ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } } : panelRise)} className="flex flex-col gap-2 pb-3">
              {opts.ownPrompt === null ? (
                <>
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-[10px] border border-line2 bg-bg p-3 text-[12px] text-fg2">{settings.prompt}</pre>
                  <button type="button" onClick={() => set({ ownPrompt: settings.prompt })} className="ink-btn flex min-h-11 items-center gap-1.5 self-start rounded-[10px] border border-line3 px-3.5 text-[12px]">
                    Use my own prompt
                  </button>
                </>
              ) : (
                <>
                  <label htmlFor={promptId} className="text-[12px] font-semibold text-fg2">
                    Your prompt for this run
                  </label>
                  <textarea
                    id={promptId}
                    value={opts.ownPrompt}
                    rows={9}
                    maxLength={4000}
                    onChange={(e) => set({ ownPrompt: e.target.value })}
                    className="w-full resize-y rounded-[10px] border border-line3 bg-bg p-3 text-[12px] text-fg outline-none focus:border-accent"
                  />
                  <button type="button" onClick={() => set({ ownPrompt: null })} className="ink-btn flex min-h-11 items-center gap-1.5 self-start rounded-[10px] border border-line3 px-3.5 text-[12px]">
                    Back to the default
                  </button>
                </>
              )}
              <span className="text-[11px] text-fg4">
                Filled in for you: {"{topic} {subject} {word} {text_style} {text_corner} {aspect} {text_instruction} {framing}"}. Save a
                template for every video in Settings.
              </span>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </section>

      <div className="flex flex-col gap-1.5 border-t border-line pt-3">
        <button
          type="button"
          disabled={!!blocker}
          onClick={submit}
          aria-describedby="generate-note"
          className="ink-btn flex min-h-11 items-center justify-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-4 text-[13px] font-semibold text-onaccent disabled:border-line3 disabled:bg-transparent disabled:text-fg3"
        >
          {busy ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Coins aria-hidden="true" size={14} />}
          Generate {n} {n === 1 ? "image" : "images"}
          {opts.models.length > 1 ? ` · ${opts.models.length} models` : ` · ${modelLabel(settings, opts.models[0])}`}
        </button>
        <span id="generate-note" className="flex flex-col gap-0.5">
          {blocker ? <span className="text-[11px] text-fg3">{blocker}</span> : <CostLine state={state} opts={opts} />}
          <span className="text-[11px] text-fg4">
            Each image is a paid Higgsfield call{settings.review && state.can_review ? ", then Claude checks it for faces, hands, leftover HUD and the word" : ""}.
          </span>
        </span>
        {generate.error ? (
          <span role="alert" className="rounded-[10px] border border-accent px-2.5 py-2 text-fg">
            {generate.error.message}
          </span>
        ) : null}
        {generate.data?.word_issues.length ? (
          <span role="status" className="rounded-[10px] border border-warnline px-2.5 py-2 text-fg2">
            {generate.data.word_issues.map((i) => i.message).join(" · ")}
          </span>
        ) : null}
      </div>
    </section>
  );
}
