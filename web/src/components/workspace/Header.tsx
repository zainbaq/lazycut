"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import { FileDown, Loader2, MoreVertical, RotateCcw, Send, SlidersHorizontal, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { StatusPill } from "@/components/ui/StatusPill";
import { ApiError, exportUrl } from "@/lib/api";
import { useAnalyze, useDeleteVideo, usePackages, useUpdateVideo } from "@/lib/queries";
import type { Fact, Preset, Timeline, Video } from "@/lib/types";

import { EventGlyph } from "./glyphs";
import { ReanalyzeDialog } from "./ReanalyzeDialog";

function PresetDetails({ preset }: { preset: Preset }) {
  const hooks = preset.hooks ?? [];
  const rules = preset.claim_rules ?? [];
  return (
    <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto">
      <span className="font-head text-[14px]">{preset.name}</span>
      {preset.description ? <span className="text-fg3">{preset.description}</span> : null}
      <div className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold text-fg3">Event types</span>
        {preset.event_types.map((t) => (
          <span key={t.id} className="flex items-center gap-2 text-fg2">
            <EventGlyph glyph={t.glyph} color={t.color} />
            {t.label}
            {!t.show ? <span className="text-fg4">· hidden by default</span> : null}
          </span>
        ))}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold text-fg3">Facts</span>
        {preset.facts.length ? (
          preset.facts.map((f) => (
            <span key={f.key} className="text-fg2">
              {f.label}
              {f.required ? <span className="text-accentsoft"> · required</span> : null}
            </span>
          ))
        ) : (
          <span className="text-fg4">None</span>
        )}
      </div>
      <span className="text-fg2">
        {hooks.length} hooks · {rules.length} claim rules
      </span>
      {preset.title_patterns?.recommended ? (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold text-fg3">Title pattern</span>
          <code className="break-words text-fg2">{preset.title_patterns.recommended}</code>
        </div>
      ) : null}
      <span className="text-[11px] text-fg4">The preset editor arrives in Phase 3. Presets live in config/presets.</span>
    </div>
  );
}

const menuItem =
  "flex min-h-11 cursor-pointer items-center gap-2 rounded-[8px] px-3 text-[12px] text-fg outline-none data-[disabled]:cursor-not-allowed data-[disabled]:text-fg4 data-[highlighted]:bg-surface2";

export function Header({
  video,
  presets,
  timeline,
  facts,
  geminiReady,
}: {
  video: Video;
  presets: Preset[];
  timeline: Timeline | undefined;
  facts: Fact[] | undefined;
  geminiReady: boolean;
}) {
  const router = useRouter();
  const analyze = useAnalyze(video.id);
  const update = useUpdateVideo(video.id);
  const remove = useDeleteVideo();

  const [dialog, setDialog] = useState<null | { presetId?: string }>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const activePreset = presets.find((p) => p.id === video.preset_id);
  const targetPreset = dialog?.presetId ? presets.find((p) => p.id === dialog.presetId) : undefined;
  // Research and packaging run beside import and analysis and do not change the video's status (API_SHAPES).
  const busyJob =
    video.jobs.find((j) => (j.kind === "import" || j.kind === "analysis") && (j.status === "running" || j.status === "queued")) ?? null;
  const packages = usePackages(video.id, video.status === "ready");
  const hasPackage = !!packages.data?.packages.some((p) => p.platform === "youtube");
  const importing = video.status !== "ready";
  const crumb = [video.subject, video.topic].filter(Boolean).join(" · ") || video.title;

  const openDialog = (presetId?: string) => {
    setDialogError(null);
    setDialog({ presetId });
  };

  const confirm = async (discard: boolean) => {
    setDialogError(null);
    try {
      if (dialog?.presetId && dialog.presetId !== video.preset_id) {
        await update.mutateAsync({ preset_id: dialog.presetId });
      }
      if (geminiReady) await analyze.mutateAsync(discard);
      setDialog(null);
    } catch (e) {
      setDialogError(e instanceof ApiError || e instanceof Error ? e.message : String(e));
    }
  };

  const pillPresets = presets.length <= 3;

  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
        <Link href="/" className="py-3.5 text-fg">
          Library
        </Link>
        <span aria-hidden="true" className="text-fg4">
          /
        </span>
        <span className="truncate text-fg3" title={video.title}>
          {crumb}
        </span>
      </nav>

      <div role="group" aria-label="Preset" className="ml-auto flex flex-wrap items-center gap-1.5">
        <Popover.Root>
          <Popover.Trigger
            className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] border border-transparent text-accentsoft"
            aria-label="What this preset defines"
          >
            <SlidersHorizontal aria-hidden="true" size={14} />
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              sideOffset={6}
              align="end"
              className="z-50 w-[300px] rounded-[12px] border border-line2 bg-raised p-3.5 text-[12px] text-fg"
            >
              {activePreset ? <PresetDetails preset={activePreset} /> : <span className="text-fg3">Preset `{video.preset_id}` is not loaded.</span>}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
        {pillPresets ? (
          presets.map((p) => {
            const on = p.id === video.preset_id;
            return (
              <button
                key={p.id}
                type="button"
                aria-pressed={on}
                disabled={importing}
                onClick={() => (on ? undefined : openDialog(p.id))}
                className="ink-btn min-h-11 rounded-[22px] border px-3.5 text-[12px] disabled:opacity-60"
                style={{
                  background: on ? "var(--accent-fill)" : "transparent",
                  borderColor: on ? "var(--accent-fill)" : "var(--line-3)",
                  color: on ? "var(--on-accent)" : "var(--text)",
                }}
              >
                {p.name}
              </button>
            );
          })
        ) : (
          <label className="flex items-center gap-2">
            <span className="sr-only">Preset</span>
            <select
              value={video.preset_id}
              disabled={importing}
              onChange={(e) => openDialog(e.target.value)}
              className="min-h-11 rounded-[22px] border border-accentfill bg-accentfill px-3 text-[12px] text-onaccent"
            >
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <StatusPill status={video.display_status} job={busyJob} analyzed={!!video.analysis} />

      <Dropdown.Root>
        <Dropdown.Trigger
          className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] border border-line2 text-fg"
          aria-label="More options"
        >
          <MoreVertical aria-hidden="true" size={16} />
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content align="end" sideOffset={6} className="z-50 min-w-[220px] rounded-[12px] border border-line2 bg-raised p-1.5">
            <Dropdown.Item className={menuItem} disabled={importing || !!busyJob} onSelect={() => openDialog()}>
              <RotateCcw aria-hidden="true" size={14} />
              Re-analyze
            </Dropdown.Item>
            <Dropdown.Item className={menuItem} disabled>
              <Send aria-hidden="true" size={14} />
              Mark as published
            </Dropdown.Item>
            {hasPackage ? (
              <Dropdown.Item className={menuItem} asChild>
                <a href={exportUrl(video.id)} download>
                  <FileDown aria-hidden="true" size={14} />
                  Export Markdown
                </a>
              </Dropdown.Item>
            ) : (
              <Dropdown.Item className={menuItem} disabled title="Generate the package first">
                <FileDown aria-hidden="true" size={14} />
                Export Markdown
              </Dropdown.Item>
            )}
            <Dropdown.Separator className="my-1 h-px bg-line2" />
            <Dropdown.Item className={menuItem} onSelect={() => setDeleteOpen(true)}>
              <Trash2 aria-hidden="true" size={14} className="text-accentsoft" />
              Delete video
            </Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>

      <ReanalyzeDialog
        open={dialog !== null}
        onOpenChange={(o) => (o ? undefined : setDialog(null))}
        timeline={timeline}
        facts={facts}
        canAnalyze={geminiReady}
        title={targetPreset ? `Switch to ${targetPreset.name}?` : "Re-analyze this video?"}
        intro={
          targetPreset
            ? geminiReady
              ? `The video is analyzed again with the ${targetPreset.name} preset: its event types and facts replace the current ones.`
              : `The preset changes to ${targetPreset.name}, but the video is not re-analyzed until GEMINI_API_KEY is set in .env.`
            : undefined
        }
        confirmLabel={targetPreset ? (geminiReady ? "Switch and re-analyze" : "Switch preset") : "Re-analyze"}
        onConfirm={confirm}
        pending={analyze.isPending || update.isPending}
        error={dialogError}
      />

      <Dialog.Root open={deleteOpen} onOpenChange={setDeleteOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex w-[min(400px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4 text-[12px] text-fg">
            <div className="flex items-start justify-between gap-2">
              <Dialog.Title className="flex items-center gap-2 font-head text-[16px]">
                <Trash2 aria-hidden="true" size={16} className="text-accentsoft" />
                Delete this video?
              </Dialog.Title>
              <Dialog.Close className="ink-btn -m-2 flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3" aria-label="Close">
                <X aria-hidden="true" size={16} />
              </Dialog.Close>
            </div>
            <Dialog.Description className="text-fg2">
              “{video.title}”, its analysis and its copy inside LazyCut are removed. The original file in the import folder is
              not touched.
            </Dialog.Description>
            {remove.error ? (
              <span role="alert" className="rounded-[10px] border border-accent bg-surface p-2.5">
                {remove.error.message}
              </span>
            ) : null}
            <div className="flex justify-end gap-2">
              <Dialog.Close className="ink-btn min-h-11 rounded-[10px] border border-line3 px-3.5 text-[12px]">Cancel</Dialog.Close>
              <button
                type="button"
                disabled={remove.isPending}
                onClick={() => remove.mutate(video.id, { onSuccess: () => router.push("/") })}
                className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:opacity-60"
              >
                {remove.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Trash2 aria-hidden="true" size={14} />}
                Delete
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </header>
  );
}
