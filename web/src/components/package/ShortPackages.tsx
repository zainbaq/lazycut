"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AlertTriangle, Ban, Check, Loader2, Maximize2, RefreshCw, Smartphone, Sparkles, X } from "lucide-react";
import { useState } from "react";

import { frameUrl } from "@/lib/api";
import { ago, clock } from "@/lib/format";
import { easeOutInk } from "@/lib/motion";
import { isActive, jobOf, useClips, useGenerateShort, usePackages, useRegeneratePackage } from "@/lib/queries";
import { useWorkspace } from "@/lib/store";
import type { Clip, Package, ShortPackage, ShortPlatform, Video } from "@/lib/types";

import { SweepCopy } from "./bits";
import { FieldBlock } from "./PackageDrawer";

export const SHORT_PLATFORMS: { id: ShortPlatform; label: string; short: string }[] = [
  { id: "shorts", label: "YouTube Shorts", short: "Shorts" },
  { id: "reels", label: "Instagram Reels", short: "Reels" },
  { id: "tiktok", label: "TikTok", short: "TikTok" },
];
const LABEL = Object.fromEntries(SHORT_PLATFORMS.map((p) => [p.id, p.label])) as Record<ShortPlatform, string>;
const LIMITS: Record<ShortPlatform, Record<string, number>> = {
  shorts: { title: 100, description: 5000 },
  reels: { caption: 2200 },
  tiktok: { caption: 2200 },
};
const btn = "ink-btn flex min-h-11 items-center justify-center gap-1.5 rounded-[10px] border px-3 text-[12px] disabled:opacity-50";

/** The short-form packages of one clip, whatever their platform. */
export function shortPackagesOf(packages: Package[] | undefined, clipId: string | null | undefined): ShortPackage[] {
  return ((packages ?? []).filter((p) => p.clip_id && p.clip_id === clipId) as unknown) as ShortPackage[];
}

/** The text a platform is mainly posted with: what the quick Copy button copies. */
function mainText(pkg: ShortPackage): string {
  return (pkg.platform === "shorts" ? pkg.fields.description : pkg.fields.caption) ?? "";
}

/**
 * A phone frame for a vertical clip (9.4): the centre crop of the frame at the clip's payoff, the
 * safe-margin guides from the channel profile, and where the on-screen text and caption sit.
 */
function PhonePreview({ video, pkg, clip }: { video: Video; pkg: ShortPackage; clip: Clip | undefined }) {
  const f = pkg.fields;
  const { top_pct: top, bottom_pct: bottom } = f.safe_margins ?? { top_pct: 12, bottom_pct: 15 };
  const t = clip?.frame_t ?? (f.clip.t_start + f.clip.t_end) / 2;
  const line = pkg.platform === "shorts" ? f.title : (f.caption ?? "").split("\n")[0];
  return (
    <figure className="flex flex-col gap-2" aria-label={`How it may look on ${LABEL[pkg.platform]}`}>
      <figcaption className="flex items-center gap-1.5 text-[11px] font-semibold text-fg3">
        <Smartphone aria-hidden="true" size={12} />
        {LABEL[pkg.platform]} preview
      </figcaption>
      <div className="relative mx-auto aspect-[9/16] w-[220px] overflow-hidden rounded-[22px] border-2 border-line3 bg-stage">
        {/* eslint-disable-next-line @next/next/no-img-element -- a frame cut on demand by the API */}
        <img src={frameUrl(video.id, t, 960)} alt={`Frame at ${clock(t)}, cropped to 9:16`} className="h-full w-full object-cover" />
        {/* Safe-margin guides: the platform's own interface covers what is outside them. */}
        <span aria-hidden="true" className="absolute inset-x-0 top-0 border-b border-dashed border-[rgba(240,106,80,0.9)] bg-[rgba(7,7,7,0.35)]" style={{ height: `${top}%` }} />
        <span aria-hidden="true" className="absolute inset-x-0 bottom-0 border-t border-dashed border-[rgba(240,106,80,0.9)] bg-[rgba(7,7,7,0.35)]" style={{ height: `${bottom}%` }} />
        <span aria-hidden="true" className="absolute right-1.5 text-[9px] text-accentsoft" style={{ top: `calc(${top}% + 2px)` }}>
          safe area
        </span>
        {f.on_screen_text ? (
          <span
            className="absolute inset-x-3 text-center text-[13px] font-bold leading-tight text-white"
            style={{ top: `calc(${top}% + 18px)`, textShadow: "0 0 3px #000, 0 1px 2px #000, 0 0 8px rgba(0,0,0,0.8)" }}
          >
            {f.on_screen_text}
          </span>
        ) : null}
        {f.end_text ? (
          <span className="absolute inset-x-3 text-center text-[10px] text-white/80" style={{ bottom: `calc(${bottom}% + 6px)`, textShadow: "0 0 3px #000" }}>
            {f.end_text}
          </span>
        ) : null}
        <span className="absolute inset-x-2 bottom-1.5 line-clamp-2 text-[9.5px] leading-snug text-white/90" style={{ maxHeight: `${bottom}%` }}>
          {line}
        </span>
      </div>
      <span className="text-center text-[11px] text-fg4">
        Text is not drawn into the video. Add it in the platform&apos;s editor, inside the guides ({top}% top, {bottom}% bottom).
      </span>
    </figure>
  );
}

/** Every field of one short-form package as copyable, editable blocks, beside the phone preview. */
function ShortDrawer({
  open,
  onOpenChange,
  pkg,
  video,
  clip,
  running,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pkg: ShortPackage;
  video: Video;
  clip: Clip | undefined;
  running: boolean;
}) {
  const reduced = useReducedMotion();
  const regenerate = useRegeneratePackage(video.id);
  const f = pkg.fields;
  const base = pkg as unknown as Package;
  const blocked = running ? "A package is being written" : null;
  const limits = LIMITS[pkg.platform];
  const clipIssue = pkg.rule_results.find((r) => r.field === "clip" && r.severity !== "pass");
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open ? (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div className="fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className="fixed inset-y-0 right-0 z-50 flex w-[min(920px,100vw)] flex-col border-l border-line2 bg-raised text-[12px] text-fg"
                initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
                transition={{ duration: 0.24, ease: easeOutInk }}
              >
                <header className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
                  <Dialog.Title className="font-head text-[16px]">{LABEL[pkg.platform]}</Dialog.Title>
                  <span className="text-fg3">
                    {f.clip.name} · {clock(f.clip.t_start)} to {clock(f.clip.t_end)} · v{pkg.version} · {ago(pkg.created_at)}
                  </span>
                  <span className="ml-auto flex items-center gap-1.5">
                    <button
                      type="button"
                      className={`${btn} border-line3`}
                      disabled={!!blocked || regenerate.isPending}
                      title={blocked ?? "Write this platform again (one Claude call); your edits are kept"}
                      onClick={() => regenerate.mutate({ id: pkg.id, body: { all: true, replace_edits: false } })}
                    >
                      <RefreshCw aria-hidden="true" size={13} className={running ? "animate-spin" : undefined} />
                      Regenerate
                    </button>
                    <Dialog.Close aria-label="Close" className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px]">
                      <X aria-hidden="true" size={16} />
                    </Dialog.Close>
                  </span>
                </header>
                <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 min-[760px]:flex-row">
                  <div className="flex min-w-0 flex-1 flex-col">
                    {pkg.stale ? (
                      <span className="mb-1 flex items-center gap-1.5 rounded-[10px] border border-warnline px-2.5 py-1.5 text-fg2">
                        <AlertTriangle aria-hidden="true" size={13} className="shrink-0 text-warn" />
                        Out of date: the clip, the facts or the research changed since this was written.
                      </span>
                    ) : null}
                    {clipIssue ? (
                      <span className="mb-1 flex items-center gap-1.5 rounded-[10px] border border-warnline px-2.5 py-1.5 text-fg2">
                        <AlertTriangle aria-hidden="true" size={13} className="shrink-0 text-warn" />
                        {clipIssue.message}
                      </span>
                    ) : null}
                    {pkg.platform === "shorts" ? (
                      <>
                        <FieldBlock pkg={base} videoId={video.id} label="Title" path="title" value={f.title ?? ""} field="title" limit={limits.title} regenerateBlocked={blocked} />
                        <FieldBlock pkg={base} videoId={video.id} label="Description" path="description" value={f.description ?? ""} field="description" limit={limits.description} multiline regenerateBlocked={blocked} />
                      </>
                    ) : (
                      <>
                        <FieldBlock
                          pkg={base}
                          videoId={video.id}
                          label="On-screen text"
                          path="on_screen_text"
                          value={f.on_screen_text ?? ""}
                          field="on_screen_text"
                          count={(f.on_screen_text ?? "").length}
                          hint="Plain words, typed onto the video in the platform's editor from the first frame."
                          regenerateBlocked={blocked}
                        />
                        <FieldBlock pkg={base} videoId={video.id} label="Caption" path="caption" value={f.caption ?? ""} field="caption" limit={limits.caption} multiline regenerateBlocked={blocked} />
                        <FieldBlock pkg={base} videoId={video.id} label="End text" path="end_text" value={f.end_text ?? ""} field="end_text" count={(f.end_text ?? "").length} hint="For the last second of the clip." regenerateBlocked={blocked} />
                      </>
                    )}
                    <FieldBlock pkg={base} videoId={video.id} label="Hashtags" path="hashtags" value={f.hashtags.join(" ")} field="hashtags" hint="Already inside the text above; editing them here rewrites that line too." regenerateBlocked={blocked} />
                    <FieldBlock pkg={base} videoId={video.id} label="Pinned comment" path="pinned_comment" value={f.pinned_comment} field="pinned_comment" count={f.pinned_comment.length} regenerateBlocked={blocked} />
                  </div>
                  <div className="shrink-0 min-[760px]:w-[260px]">
                    <PhonePreview video={video} pkg={pkg} clip={clip} />
                  </div>
                </div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        ) : null}
      </AnimatePresence>
    </Dialog.Root>
  );
}

/** Short-form for the selected clip (9.4 region 7): write the packages, then copy or open each platform. */
export function ShortSection({ video }: { video: Video }) {
  const selectedId = useWorkspace((s) => s.selectedClipId);
  const platforms = useWorkspace((s) => s.shortPlatforms);
  const clips = useClips(video.id, video.status === "ready");
  const list = usePackages(video.id, video.status === "ready");
  const generate = useGenerateShort(video.id);
  const [openId, setOpenId] = useState<string | null>(null);
  const clip = selectedId ? clips.data?.clips.find((c) => c.id === selectedId) : undefined;
  if (!clip) return null;

  const job = jobOf(video, "clip_package");
  const running = !!list.data?.running_short || isActive(job) || generate.isPending;
  const mine = shortPackagesOf(list.data?.packages, clip.id);
  const wanted = SHORT_PLATFORMS.filter((p) => platforms[p.id]).map((p) => p.id);
  const todo = wanted.filter((p) => !mine.some((m) => m.platform === p && !m.stale));
  const opened = mine.find((m) => m.id === openId);

  let reason: string | null = null;
  if (list.data && !list.data.can_write) reason = "Needs ANTHROPIC_API_KEY in .env";
  else if (list.data?.missing_facts.length) reason = `Confirm ${list.data.missing_facts.join(", ")} first`;
  else if (!wanted.length) reason = "Switch on Shorts, Reels or TikTok above";
  else if (running) reason = "A package is being written";
  const names = (todo.length ? todo : wanted).map((p) => SHORT_PLATFORMS.find((x) => x.id === p)?.short).join(" + ");

  return (
    <div className="flex flex-col gap-2 border-t border-line2 pt-3">
      <span className="text-[11px] font-semibold text-fg3">
        Short-form · <span className="text-fg2">{clip.name}</span>
      </span>
      {running ? (
        <div role="status" className="relative flex items-center gap-2 overflow-hidden rounded-[10px] bg-surface2 px-3 py-2.5 text-fg2">
          <Loader2 aria-hidden="true" size={13} className="shrink-0 animate-spin text-accentsoft" />
          <span className="truncate">{(isActive(job) && job?.message) || "Writing the short-form package…"}</span>
          <span aria-hidden="true" className="absolute bottom-0 left-0 h-[2px] w-full bg-line2">
            <span className="ink-busy-bar block h-full bg-accent" />
          </span>
        </div>
      ) : null}
      {mine.map((pkg) => {
        const text = mainText(pkg);
        const state = pkg.counts.block ? "blocked" : pkg.stale ? "stale" : pkg.counts.warn ? "warn" : "ok";
        return (
          <div key={pkg.id} className="flex flex-col gap-1.5 rounded-[10px] bg-surface p-2.5">
            <span className="flex items-center gap-1.5">
              <span className="font-semibold text-fg">{LABEL[pkg.platform]}</span>
              <span className="ml-auto flex items-center gap-1 text-[11px]" style={{ color: state === "blocked" ? "var(--accent-soft)" : state === "ok" ? "var(--ok-text)" : "var(--warn)" }}>
                {state === "blocked" ? <Ban aria-hidden="true" size={11} /> : state === "ok" ? <Check aria-hidden="true" size={11} /> : <AlertTriangle aria-hidden="true" size={11} />}
                {state === "blocked" ? `${pkg.counts.block} blocked` : state === "stale" ? "Out of date" : state === "warn" ? `${pkg.counts.warn} to check` : "Rules pass"}
              </span>
            </span>
            <span className="line-clamp-2 text-fg2">{pkg.fields.on_screen_text || pkg.fields.title}</span>
            <span className="flex flex-wrap items-center gap-1.5">
              <SweepCopy
                text={text}
                label={pkg.platform === "shorts" ? "Copy description" : "Copy caption"}
                disabled={pkg.blocked_fields.includes(pkg.platform === "shorts" ? "description" : "caption") || !text}
                disabledReason="Blocked by a rule: open it to see why"
              />
              <button type="button" onClick={() => setOpenId(pkg.id)} className={`${btn} border-line3`}>
                <Maximize2 aria-hidden="true" size={13} />
                Open
              </button>
            </span>
          </div>
        );
      })}
      {todo.length || !mine.length ? (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            disabled={!!reason}
            onClick={() => generate.mutate({ clipId: clip.id, platforms: todo.length ? todo : wanted })}
            className={`${btn} border-accentfill bg-accentfill font-semibold text-onaccent`}
          >
            <Sparkles aria-hidden="true" size={14} />
            Write {names || "short-form"}
          </button>
          <span className="text-[11px] text-fg3">{reason ?? "One Claude call writes every platform switched on; code checks the claims and the link back."}</span>
        </div>
      ) : null}
      {generate.error ? (
        <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5 text-fg">{generate.error.message}</span>
      ) : job?.status === "error" && !running ? (
        <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5 text-fg">Writing stopped: {job.error ?? "no message"}</span>
      ) : null}
      {opened ? <ShortDrawer open onOpenChange={(o) => (o ? undefined : setOpenId(null))} pkg={opened} video={video} clip={clip} running={running} /> : null}
    </div>
  );
}
