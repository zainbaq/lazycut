"use client";

import { ArrowUpFromLine, Check, Loader2 } from "lucide-react";

import { shortPackagesOf, SHORT_PLATFORMS } from "@/components/package/ShortPackages";
import { isActive, jobOf, useExportClip, useGenerateShort, usePackages } from "@/lib/queries";
import { useWorkspace } from "@/lib/store";
import type { Clip, Video } from "@/lib/types";

import { lengthText } from "./trim";

/**
 * "Lift clip" (9.4 region 6): export the clip vertical and write its short-form packages in one
 * press. It turns green once the clip has a vertical export of its current range and an
 * up-to-date package for every platform switched on.
 */
export function LiftButton({ video, clip }: { video: Video; clip: Clip }) {
  const platforms = useWorkspace((s) => s.shortPlatforms);
  const list = usePackages(video.id, true);
  const exportClip = useExportClip(video.id);
  const generate = useGenerateShort(video.id);

  const wanted = SHORT_PLATFORMS.filter((p) => platforms[p.id]).map((p) => p.id);
  const mine = shortPackagesOf(list.data?.packages, clip.id);
  const toWrite = wanted.filter((p) => !mine.some((m) => m.platform === p && !m.stale));
  const exported = clip.exports.some(
    (x) => x.crop === "9x16" && x.t_start != null && x.t_end != null && Math.abs(x.t_start - clip.t_start) < 1e-3 && Math.abs(x.t_end - clip.t_end) < 1e-3,
  );
  const canWrite = !!list.data?.can_generate;
  const exporting = isActive(jobOf(video, "clip_export")) || exportClip.isPending;
  const writing = !!list.data?.running_short || isActive(jobOf(video, "clip_package")) || generate.isPending;
  const busy = exporting || writing;
  const lifted = exported && (!toWrite.length || !canWrite) && !busy;

  const lift = () => {
    if (!exported && !exporting) exportClip.mutate({ id: clip.id, crop: "9x16", mode: "accurate" });
    if (toWrite.length && canWrite && !writing) generate.mutate({ clipId: clip.id, platforms: toWrite });
  };

  let title = "Export the clip at 9:16 (1080×1920) and write the packages for the platforms switched on (one Claude call)";
  if (lifted) title = toWrite.length ? "Exported. The packages still need a confirmed fact or an Anthropic key" : "Exported and packaged";
  else if (!canWrite && toWrite.length) title = "Exports the clip at 9:16. Packages need the required facts confirmed and an Anthropic key";

  return (
    <button
      type="button"
      onClick={lift}
      disabled={busy || lifted}
      title={title}
      className="flex min-h-11 items-center gap-1.5 rounded-[10px] px-3.5 text-[12px] font-semibold transition-[background,color,transform] duration-300 active:scale-[0.96] disabled:cursor-default"
      style={{
        background: lifted ? "var(--ok)" : "var(--accent-fill)",
        color: lifted ? "var(--on-ok)" : "var(--on-accent)",
        opacity: busy ? 0.75 : 1,
      }}
    >
      {busy ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : lifted ? <Check aria-hidden="true" size={14} /> : <ArrowUpFromLine aria-hidden="true" size={14} />}
      {busy ? (exporting ? "Lifting…" : "Writing…") : lifted ? "Clip lifted" : `Lift clip · ${lengthText(clip.duration_s)}`}
    </button>
  );
}
