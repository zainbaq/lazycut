"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { AnimatePresence, motion } from "motion/react";
import { Crop, MoreHorizontal, Pencil, Pin, Plus, Scissors, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import { FoldButton, PanelStrip, usePanelFold } from "@/components/ui/PanelFold";
import { menuContent, menuItem } from "@/components/workspace/EventActions";
import { frameUrl } from "@/lib/api";
import { clock, plural } from "@/lib/format";
import { EASE_OUT_INK_CSS, panelRise } from "@/lib/motion";
import { jobOf, useFindClips } from "@/lib/queries";
import { useWorkspace } from "@/lib/store";
import type { Clip, ClipList, EventType, Preset, ShortPlatform, Video } from "@/lib/types";

import { lengthText } from "./trim";
import type { ClipActions } from "./useClipActions";

const PLATFORMS: { id: ShortPlatform; label: string }[] = [
  { id: "shorts", label: "Shorts" },
  { id: "reels", label: "Reels" },
  { id: "tiktok", label: "TikTok" },
];
const LENGTHS = [0, 15, 30, 45, 60];

function ClipCard({
  clip,
  index,
  video,
  selected,
  actions,
}: {
  clip: Clip;
  index: number;
  video: Video;
  selected: boolean;
  actions: ClipActions;
}) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(clip.name);
  const duration = video.duration_s || 1;
  const left = Math.min(98, (clip.t_start / duration) * 100);
  const width = Math.max(2, Math.min(100 - left, (clip.duration_s / duration) * 100));
  const proposal = clip.status === "candidate";
  const save = () => {
    setRenaming(false);
    const next = name.trim();
    if (next && next !== clip.name) actions.patch(clip.id, { name: next });
    else setName(clip.name);
  };

  return (
    <motion.li
      layout="position"
      {...panelRise}
      className="relative flex min-w-0 flex-col rounded-[10px] bg-surface"
      style={{ outline: selected ? "2px solid var(--accent)" : "2px solid transparent", outlineOffset: 2, transition: `outline-color 200ms ${EASE_OUT_INK_CSS}` }}
    >
      <button
        type="button"
        aria-pressed={selected}
        aria-label={`${clip.name}, ${clock(clip.t_start)} to ${clock(clip.t_end)}, ${lengthText(clip.duration_s)}${proposal ? ", proposal" : ""}${selected ? ", selected" : ""}`}
        onClick={() => actions.select(selected ? null : clip.id)}
        className="group relative block overflow-hidden rounded-t-[10px] text-left"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={frameUrl(video.id, clip.frame_t, 320)}
          alt=""
          loading="lazy"
          draggable={false}
          className="aspect-video w-full bg-stage object-cover transition-transform duration-200 group-hover:scale-[1.03]"
        />
        {index < 9 ? (
          <span aria-hidden="true" className="tnum absolute left-1.5 top-1.5 rounded-[5px] bg-[rgba(7,7,7,0.78)] px-1.5 text-[10px] leading-[16px] text-fg2">
            {index + 1}
          </span>
        ) : null}
        <span className="tnum absolute bottom-2 right-1.5 rounded-[5px] bg-[rgba(7,7,7,0.78)] px-1.5 text-[10px] leading-[16px] text-fg">
          {lengthText(clip.duration_s)}
        </span>
        {clip.crop_warning ? (
          <span title="A 9:16 crop may cut off an event in this clip" className="absolute right-1.5 top-1.5 rounded-[5px] bg-[rgba(7,7,7,0.78)] p-1 text-warn">
            <Crop aria-hidden="true" size={11} />
            <span className="sr-only">Check the 9:16 crop</span>
          </span>
        ) : null}
        {/* Where the clip sits in the video, and how much of it it takes. */}
        <span aria-hidden="true" className="absolute inset-x-0 bottom-0 block h-[3px] bg-line2">
          <span
            className="absolute inset-y-0 block bg-accent"
            style={{ left: `${left}%`, width: `${width}%`, transition: `left 320ms ${EASE_OUT_INK_CSS}, width 320ms ${EASE_OUT_INK_CSS}` }}
          />
        </span>
      </button>
      <div className="flex min-h-9 items-center gap-1 pl-2">
        {renaming ? (
          <input
            autoFocus
            aria-label="Clip name"
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") {
                setName(clip.name);
                setRenaming(false);
              }
            }}
            className="min-w-0 flex-1 rounded-[6px] border border-linestrong bg-bg px-1.5 py-1 text-[12px] text-fg outline-none"
          />
        ) : (
          <span className={`line-clamp-2 min-w-0 flex-1 break-words py-1 text-[11px] leading-[1.3] ${proposal ? "text-fg2" : "text-fg"}`} title={clip.name} onDoubleClick={() => setRenaming(true)}>
            {clip.name}
          </span>
        )}
        <Dropdown.Root>
          <Dropdown.Trigger aria-label={`Actions for ${clip.name}`} className="ink-btn flex h-9 w-8 shrink-0 items-center justify-center rounded-[8px] text-fg3">
            <MoreHorizontal aria-hidden="true" size={14} />
          </Dropdown.Trigger>
          <Dropdown.Portal>
            <Dropdown.Content align="end" sideOffset={4} className={menuContent}>
              {clip.status !== "exported" ? (
                <Dropdown.Item className={menuItem} onSelect={() => actions.patch(clip.id, { status: proposal ? "selected" : "candidate" })}>
                  <Pin aria-hidden="true" size={14} className={proposal ? "" : "text-accentsoft"} />
                  {proposal ? "Keep this clip" : "Stop keeping"}
                </Dropdown.Item>
              ) : null}
              <Dropdown.Item
                className={menuItem}
                onSelect={() => {
                  setName(clip.name);
                  setRenaming(true);
                }}
              >
                <Pencil aria-hidden="true" size={14} />
                Rename
              </Dropdown.Item>
              <Dropdown.Item className={menuItem} onSelect={() => actions.remove(clip.id)}>
                <Trash2 aria-hidden="true" size={14} className="text-accentsoft" />
                Delete clip
              </Dropdown.Item>
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
      </div>
      {!proposal ? (
        <span title="Kept: a new search will not replace it" className="absolute -right-1 -top-1 rounded-full bg-accentfill p-[3px] text-onaccent">
          <Pin aria-hidden="true" size={9} />
          <span className="sr-only">Kept</span>
        </span>
      ) : null}
    </motion.li>
  );
}

/** What the finder said about the selected clip, and what is in it. */
function ClipDetail({ clip, types }: { clip: Clip; types: Map<string, EventType> }) {
  const counts = Object.entries(clip.event_counts)
    .map(([id, n]) => `${n} ${(types.get(id)?.label ?? id.replace(/_/g, " ")).toLowerCase()}`)
    .join(" · ");
  return (
    <div className="flex flex-col gap-1 rounded-[10px] bg-surface p-2.5 text-[11px] text-fg3">
      {clip.reason ? <span className="text-[12px] leading-[1.45] text-fg2">{clip.reason}</span> : null}
      <span>{counts || "No events in this range"}</span>
      {clip.dead_time_s >= 0.5 ? <span>{clip.dead_time_s.toFixed(1)} s of dead time</span> : null}
      {clip.prompt ? <span className="truncate">Asked for: {clip.prompt}</span> : null}
    </div>
  );
}

/** Clips panel (9.4 region 3): the finder's prompt, then the clips of this video as a two-column grid. */
export function ClipsPanel({
  video,
  preset,
  types,
  list,
  loading,
  loadError,
  actions,
}: {
  video: Video;
  preset: Preset | undefined;
  types: Map<string, EventType>;
  list: ClipList | undefined;
  loading: boolean;
  loadError: string | null;
  actions: ClipActions;
}) {
  const selectedId = useWorkspace((s) => s.selectedClipId);
  const find = useFindClips(video.id);
  const fold = usePanelFold("clips");
  const [open, setOpen] = useState(true);
  const [prompt, setPrompt] = useState("");
  const [platform, setPlatform] = useState<ShortPlatform>("reels");
  const [target, setTarget] = useState(0);
  const clips = list?.clips ?? [];
  const selected = clips.find((c) => c.id === selectedId);
  const job = jobOf(video, "clip_find");
  const finding = !!list?.finding || find.isPending;
  const saved = (preset?.saved_prompts as string[] | undefined) ?? [];
  const noEvents = !video.analysis?.event_count;

  const run = (text: string) => {
    if (finding) return;
    setPrompt(text);
    find.mutate({ prompt: text.trim(), platform, target_len_s: target || null });
  };

  return (
    <section
      aria-label="Clips"
      className={`flex shrink-0 flex-col border-b border-line min-[720px]:border-b-0 min-[720px]:border-r ${fold.panelClass}`}
    >
      {fold.folded ? (
        <PanelStrip
          panel="clips"
          label="clips"
          title="Clips"
          count={clips.length}
          dot={finding ? { tone: "accent", text: "looking for clips" } : null}
          onOpen={fold.toggle}
        />
      ) : null}
      {/* Folded, the content stays mounted so the prompt and a rename in progress are kept. */}
      <div className={`${fold.folded ? "hidden" : "flex"} flex-col gap-2.5 p-4 ${fold.bodyClass}`}>
      <div className="flex items-center justify-between gap-1">
        <h2 className="flex items-center gap-1.5 font-head text-[16px]">
          <Scissors aria-hidden="true" size={14} className="text-accentsoft" />
          Clips
          {clips.length ? <span className="tnum font-sans text-[11px] font-normal text-fg3">{clips.length}</span> : null}
        </h2>
        <span className="flex items-center">
          <FoldButton panel="clips" label="clips" onFold={fold.toggle} />
          <button
            type="button"
            aria-label="Find clips"
            aria-expanded={open}
            aria-pressed={open}
            title="Describe the clip you want"
            onClick={() => setOpen(!open)}
            className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] text-fg"
            style={open ? { background: "var(--surface-2)" } : undefined}
          >
            <Search aria-hidden="true" size={15} />
          </button>
          <button
            type="button"
            aria-label="New clip at the playhead"
            onClick={() => actions.mark("in")}
            disabled={actions.busy || !!selectedId}
            title={selectedId ? "Deselect the clip first (Esc) to start another one" : "Start a clip at the playhead (I)"}
            className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] text-fg disabled:opacity-40"
          >
            <Plus aria-hidden="true" size={16} />
          </button>
        </span>
      </div>

      <AnimatePresence initial={false}>
        {open ? (
          <motion.form
            key="find"
            {...panelRise}
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              run(prompt);
            }}
          >
            <div className="flex gap-1.5">
              <label className="min-w-0 flex-1">
                <span className="sr-only">Describe the clip you want</span>
                <input
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  maxLength={500}
                  placeholder="Describe the clip you want"
                  className="h-11 w-full rounded-[10px] border border-linestrong bg-surface px-2.5 text-[12px] text-fg outline-none placeholder:text-fg4 focus-visible:border-fg"
                />
              </label>
              <button
                type="submit"
                disabled={finding || noEvents}
                className="flex h-11 shrink-0 items-center gap-1.5 rounded-[10px] bg-accentfill px-3 text-[12px] font-semibold text-onaccent transition-transform duration-150 active:scale-[0.96] disabled:opacity-50"
              >
                <Search aria-hidden="true" size={14} />
                Find
              </button>
            </div>
            {saved.length ? (
              <div className="flex flex-wrap gap-1.5" aria-label="Saved prompts">
                {saved.map((p) => (
                  <button
                    key={p}
                    type="button"
                    disabled={finding || noEvents}
                    onClick={() => run(p)}
                    className="ink-btn min-h-8 rounded-[8px] border border-chipline bg-chip px-2 text-[11px] text-fg2 disabled:opacity-50"
                  >
                    {p}
                  </button>
                ))}
              </div>
            ) : null}
            <div className="flex items-center gap-1.5">
              <div role="radiogroup" aria-label="Platform" className="flex min-w-0 flex-1 rounded-[10px] border border-line3 p-0.5">
                {PLATFORMS.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    role="radio"
                    aria-checked={platform === p.id}
                    onClick={() => setPlatform(p.id)}
                    className="min-h-8 flex-1 rounded-[8px] text-[11px] transition-colors duration-200"
                    style={{ background: platform === p.id ? "var(--surface-2)" : "transparent", color: platform === p.id ? "var(--text)" : "var(--text-3)" }}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <label className="shrink-0">
                <span className="sr-only">Target length</span>
                <select
                  value={target}
                  onChange={(e) => setTarget(Number(e.target.value))}
                  className="h-9 rounded-[10px] border border-line3 bg-surface px-1.5 text-[11px] text-fg2"
                >
                  {LENGTHS.map((n) => (
                    <option key={n} value={n}>
                      {n ? `~${n} s` : "Any length"}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {noEvents ? (
              <span className="text-[11px] text-fg3">The finder reads the event timeline. Analyze the video or add events first, or mark a clip by hand.</span>
            ) : list && !list.can_find ? (
              <span className="text-[11px] text-fg3">No Anthropic key: clips come from the timeline alone and the prompt is not read.</span>
            ) : null}
          </motion.form>
        ) : null}
      </AnimatePresence>

      {find.error || actions.error ? (
        <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5 text-fg">
          {find.error?.message ?? actions.error}
        </span>
      ) : job?.status === "error" && !finding ? (
        <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5 text-fg">
          The finder stopped: {job.error ?? "no message"}
        </span>
      ) : null}
      {finding ? (
        <span className="flex flex-col gap-1.5 text-[11px] text-fg3" aria-live="polite">
          {job?.message && (job.status === "running" || job.status === "queued") ? job.message : "Looking for clips"}…
          <span className="relative block h-[3px] overflow-hidden rounded-full bg-line2">
            <span className="ink-busy-bar absolute inset-y-0 left-0 block rounded-full bg-accent" />
          </span>
        </span>
      ) : job?.status === "done" && job.message ? (
        <span className="text-[11px] text-fg3">{job.message}</span>
      ) : null}

      {loading ? (
        <ul className="grid grid-cols-2 gap-2.5" aria-busy="true">
          {[0, 1].map((i) => (
            <li key={i} className="ink-skeleton h-[104px] rounded-[10px]" />
          ))}
        </ul>
      ) : loadError ? (
        <span role="alert" className="text-fg2">
          Could not load the clips: {loadError}
        </span>
      ) : clips.length || finding ? (
        <ul className="grid max-h-[46vh] grid-cols-2 gap-x-2.5 gap-y-3 overflow-y-auto p-1 min-[720px]:max-h-[44vh]">
          <AnimatePresence initial={false}>
            {clips.map((clip, i) => (
              <ClipCard key={clip.id} clip={clip} index={i} video={video} selected={clip.id === selectedId} actions={actions} />
            ))}
          </AnimatePresence>
          {finding
            ? [0, 1, 2].map((i) => <li key={`sk${i}`} aria-hidden="true" className="ink-skeleton h-[104px] rounded-[10px]" />)
            : null}
        </ul>
      ) : (
        <div className="flex flex-col gap-1.5 rounded-[10px] border border-dashed border-line3 p-3 text-fg3">
          <span className="text-fg2">Describe the clip you want{saved.length ? ", or pick a saved prompt" : ""}.</span>
          <span>
            Or mark one by hand: <kbd className="rounded bg-surface2 px-1 text-fg">I</kbd> starts a clip at the playhead,{" "}
            <kbd className="rounded bg-surface2 px-1 text-fg">O</kbd> ends it.
          </span>
        </div>
      )}

      {selected ? <ClipDetail clip={selected} types={types} /> : clips.length ? (
        <span className="text-[11px] text-fg4">
          {plural(clips.filter((c) => c.status !== "candidate").length, "kept clip")}. A new search replaces the proposals you have not kept.
        </span>
      ) : null}
      </div>
    </section>
  );
}
