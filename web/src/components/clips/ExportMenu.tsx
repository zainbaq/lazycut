"use client";

import * as Popover from "@radix-ui/react-popover";
import { AlertTriangle, Download, FileVideo } from "lucide-react";
import { useEffect, useState } from "react";

import { apiUrl } from "@/lib/api";
import { bytes, clock } from "@/lib/format";
import { isActive, jobOf, useExportClip } from "@/lib/queries";
import { useWorkspace } from "@/lib/store";
import type { Clip, ClipExport, Video } from "@/lib/types";

import { lengthText } from "./trim";

type Shape = "9x16" | "none";
type Mode = "accurate" | "lossless";

/** What an exported file holds, and whether the clip has been trimmed since. */
function ExportRow({ item, clip }: { item: ClipExport; clip: Clip }) {
  const stale = item.t_start != null && item.t_end != null && (Math.abs(item.t_start - clip.t_start) > 1e-3 || Math.abs(item.t_end - clip.t_end) > 1e-3);
  const shifted = item.mode === "lossless" && item.real_start != null && item.t_start != null && Math.abs(item.real_start - item.t_start) > 0.02;
  return (
    <li className="flex items-center gap-2 rounded-[8px] bg-surface px-2 py-1.5">
      <FileVideo aria-hidden="true" size={14} className="shrink-0 text-fg3" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="tnum truncate text-fg">
          {item.width}×{item.height} · {item.fps ? `${Math.round(item.fps * 100) / 100} fps` : ""} · {lengthText(item.duration_s ?? 0)}
          {item.size_bytes ? ` · ${bytes(item.size_bytes)}` : ""}
        </span>
        <span className="tnum text-[11px] text-fg3">
          {item.crop === "9x16" ? "Vertical 9:16" : "Original frame"} · {item.mode === "lossless" ? "lossless" : "frame-exact"}
          {shifted ? ` · really starts at ${clock(item.real_start, 2)} (keyframe)` : ""}
        </span>
        {stale ? (
          <span className="flex items-center gap-1 text-[11px] text-warn">
            <AlertTriangle aria-hidden="true" size={11} />
            Trimmed since this export ({clock(item.t_start)} to {clock(item.t_end)})
          </span>
        ) : null}
      </span>
      <a
        href={apiUrl(item.url)}
        download
        aria-label={`Download the ${item.crop === "9x16" ? "vertical" : "original-frame"} ${item.mode} export`}
        className="ink-btn flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] border border-line3 text-fg"
      >
        <Download aria-hidden="true" size={14} />
      </a>
    </li>
  );
}

/** Export the selected clip with ffmpeg (7.6): vertical or original frame, frame-exact or lossless. */
export function ExportMenu({ video, clip }: { video: Video; clip: Clip }) {
  const crop916 = useWorkspace((s) => s.crop916);
  const run = useExportClip(video.id);
  const [open, setOpen] = useState(false);
  const [shape, setShape] = useState<Shape>(crop916 ? "9x16" : "none");
  const [mode, setMode] = useState<Mode>("accurate");
  const job = jobOf(video, "clip_export");
  const busy = isActive(job) || run.isPending;
  const fast = (video.fps ?? 0) > 31;

  // The shape follows the preview's 9:16 switch until the menu is open.
  useEffect(() => {
    if (!open) setShape(crop916 ? "9x16" : "none");
  }, [crop916, open]);

  const choice = "flex min-h-11 w-full items-start gap-2 rounded-[8px] px-2 py-1.5 text-left hover:bg-surface2";
  const dot = (on: boolean) => (
    <span aria-hidden="true" className="mt-[3px] flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border" style={{ borderColor: on ? "var(--accent)" : "var(--line-strong)" }}>
      {on ? <span className="block h-1.5 w-1.5 rounded-full bg-accent" /> : null}
    </span>
  );

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger className="ink-btn relative flex min-h-11 items-center gap-1.5 overflow-hidden rounded-[10px] border border-line3 px-3 text-[12px] text-fg">
        <Download aria-hidden="true" size={14} />
        {busy ? `Exporting ${Math.round((job?.progress ?? 0) * 100)}%` : "Export"}
        {clip.exports.length && !busy ? <span className="tnum text-fg3">{clip.exports.length}</span> : null}
        {busy ? <span aria-hidden="true" className="absolute inset-x-0 bottom-0 block h-[2px] bg-accent transition-[width] duration-300" style={{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }} /> : null}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="end" sideOffset={8} className="z-50 flex w-[340px] flex-col gap-2 rounded-[12px] border border-line2 bg-raised p-3 text-[12px] text-fg" aria-label="Export the clip">
          <span className="text-[11px] text-fg3">
            Cut from the source file at {video.fps ? `${Math.round(video.fps * 100) / 100} fps` : "its own frame rate"}. Nothing is added or upscaled.
          </span>
          <div role="radiogroup" aria-label="Shape" className="flex flex-col">
            <button type="button" role="radio" aria-checked={shape === "9x16"} onClick={() => { setShape("9x16"); setMode("accurate"); }} className={choice}>
              {dot(shape === "9x16")}
              <span>
                Vertical 9:16, 1080×1920
                <span className="block text-[11px] text-fg3">The centre of the frame, for Shorts, Reels and TikTok.</span>
              </span>
            </button>
            <button type="button" role="radio" aria-checked={shape === "none"} onClick={() => setShape("none")} className={choice}>
              {dot(shape === "none")}
              <span>
                Original frame{video.width && video.height ? `, ${video.width}×${video.height}` : ""}
                <span className="block text-[11px] text-fg3">Uncropped, at the source size.</span>
              </span>
            </button>
          </div>
          <div className="h-px bg-line2" />
          <div role="radiogroup" aria-label="Quality" className="flex flex-col">
            <button type="button" role="radio" aria-checked={mode === "accurate"} onClick={() => setMode("accurate")} className={choice}>
              {dot(mode === "accurate")}
              <span>
                Frame-exact
                <span className="block text-[11px] text-fg3">Re-encoded near-lossless. Starts and ends on the frames you chose.</span>
              </span>
            </button>
            <button type="button" role="radio" aria-checked={mode === "lossless"} disabled={shape === "9x16"} onClick={() => setMode("lossless")} className={`${choice} disabled:opacity-45`}>
              {dot(mode === "lossless")}
              <span>
                Lossless (approximate edges)
                <span className="block text-[11px] text-fg3">
                  No re-encode, so the cut starts on the keyframe before the in-point. Original frame only.
                </span>
              </span>
            </button>
          </div>
          {shape === "9x16" && fast ? (
            <span className="rounded-[8px] bg-surface px-2 py-1.5 text-[11px] text-fg3">
              The export keeps {Math.round(video.fps ?? 60)} fps. Shorts and TikTok play 60 fps; Reels may show it at 30 fps (not confirmed by Instagram).
            </span>
          ) : null}
          {clip.crop_warning && shape === "9x16" ? (
            <span className="flex items-start gap-1.5 rounded-[8px] border border-warnline px-2 py-1.5 text-[11px] text-fg2">
              <AlertTriangle aria-hidden="true" size={12} className="mt-0.5 shrink-0 text-warn" />
              An event in this clip may fall outside the 9:16 crop. Check it with the crop switch first.
            </span>
          ) : null}
          {run.error ? (
            <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5">{run.error.message}</span>
          ) : job?.status === "error" && !busy ? (
            <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5">The export stopped: {job.error ?? "no message"}</span>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={() => run.mutate({ id: clip.id, crop: shape, mode })}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-[10px] bg-accentfill px-3 font-semibold text-onaccent transition-transform duration-150 active:scale-[0.96] disabled:opacity-60"
          >
            <Download aria-hidden="true" size={14} />
            {busy ? `${job?.message ?? "Exporting"} ${Math.round((job?.progress ?? 0) * 100)}%` : `Export ${lengthText(clip.duration_s)}`}
          </button>
          {clip.exports.length ? (
            <ul className="flex flex-col gap-1.5" aria-label="Exported files">
              {clip.exports.map((x) => (
                <ExportRow key={x.id} item={x} clip={clip} />
              ))}
            </ul>
          ) : null}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
