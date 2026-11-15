"use client";

import { ArrowRight, Check, FileVideo, FolderOpen, Loader2, RefreshCw } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { ConfigErrorCard, ErrorCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { bytes, shortDate, titleFromFile } from "@/lib/format";
import { panelRise } from "@/lib/motion";
import { useConfigStatus, useCreateVideo, useImports, usePresets } from "@/lib/queries";
import type { ImportItem } from "@/lib/types";

function Field({
  label,
  hint,
  value,
  onChange,
  required,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[11px] text-fg3">
        {label}
        {required ? <span className="text-accentsoft"> *</span> : null}
      </label>
      <input
        id={id}
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-11 rounded-[10px] border border-linestrong bg-surface px-3 text-[12px] text-fg"
      />
      {hint ? <span className="text-[11px] text-fg4">{hint}</span> : null}
    </div>
  );
}

function Pills<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: T; name: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-fg3" id={`${label}-label`}>
        {label}
      </span>
      <div role="group" aria-labelledby={`${label}-label`} className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = o.id === value;
          return (
            <button
              key={o.id}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(o.id)}
              className="ink-btn min-h-11 rounded-[22px] border px-3.5 text-[12px]"
              style={{
                background: on ? "var(--accent-fill)" : "transparent",
                borderColor: on ? "var(--accent-fill)" : "var(--line-3)",
                color: on ? "var(--on-accent)" : "var(--text)",
              }}
            >
              {o.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function FileRow({ item, selected, onPick }: { item: ImportItem; selected: boolean; onPick: () => void }) {
  return (
    <li className="flex items-center gap-2">
      <button
        type="button"
        onClick={onPick}
        aria-pressed={selected}
        className="ink-btn flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-[10px] border px-3 py-2 text-left"
        style={{
          background: selected ? "var(--surface-2)" : "var(--surface)",
          borderColor: selected ? "var(--accent)" : "var(--line-2)",
        }}
      >
        <FileVideo aria-hidden="true" size={16} className="shrink-0 text-fg3" />
        <span className="min-w-0 flex-1 truncate text-[12px] text-fg">{item.name}</span>
        <span className="tnum hidden shrink-0 text-fg3 sm:inline">{bytes(item.size_bytes)}</span>
        <span className="tnum hidden shrink-0 text-fg3 md:inline">{shortDate(item.modified_at)}</span>
      </button>
      {item.imported_video_id ? (
        <Link
          href={`/v/${item.imported_video_id}`}
          className="flex min-h-11 shrink-0 items-center gap-1 rounded-[10px] px-2 text-[11px] text-oktext hover:bg-surface2"
          aria-label={`${item.name} is already imported. Open it`}
        >
          <Check aria-hidden="true" size={12} strokeWidth={2.5} />
          Imported
        </Link>
      ) : null}
    </li>
  );
}

export default function ImportPage() {
  const router = useRouter();
  const imports = useImports();
  const presets = usePresets();
  const status = useConfigStatus();
  const create = useCreateVideo();

  const [picked, setPicked] = useState<ImportItem | null>(null);
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("");
  const [topic, setTopic] = useState("");
  const [terms, setTerms] = useState("");
  const [kind, setKind] = useState<"long" | "clip">("long");
  const [presetId, setPresetId] = useState("general");

  useEffect(() => {
    if (picked) setTitle(titleFromFile(picked.name));
  }, [picked]);

  const presetOptions = (presets.data ?? []).map((p) => ({ id: p.id, name: p.name }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!picked || !title.trim()) return;
    create.mutate(
      {
        source: "local",
        ref: picked.ref,
        title: title.trim(),
        subject: subject.trim(),
        topic: topic.trim(),
        topic_terms: terms.trim(),
        kind,
        preset_id: presetId,
      },
      { onSuccess: (video) => router.push(`/v/${video.id}`) },
    );
  };

  return (
    <div className="flex min-h-screen">
      <Rail section="new" />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
          <nav aria-label="Breadcrumb" className="flex items-center gap-2">
            <Link href="/" className="py-3.5 text-fg">
              Library
            </Link>
            <span aria-hidden="true" className="text-fg4">
              /
            </span>
            <span className="text-fg3">Import</span>
          </nav>
        </header>

        <div className="flex flex-wrap gap-4 p-4">
          <section aria-labelledby="files-title" className="flex min-w-0 flex-[999_1_420px] flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h1 id="files-title" className="font-head text-[16px]">
                Import folder
              </h1>
              <button
                type="button"
                onClick={() => void imports.refetch()}
                className="ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] border border-transparent text-fg"
                aria-label="Refresh the file list"
              >
                <RefreshCw aria-hidden="true" size={16} className={imports.isFetching ? "animate-spin" : ""} />
              </button>
            </div>
            {imports.data ? (
              <span className="flex items-center gap-1.5 text-fg3">
                <FolderOpen aria-hidden="true" size={14} />
                <code className="truncate">{imports.data.folder}</code>
                <span className="text-fg4">· read-only</span>
              </span>
            ) : null}
            {imports.error ? (
              <ErrorCard title="Could not list the import folder" message={imports.error.message} onRetry={() => void imports.refetch()} />
            ) : null}
            {imports.isLoading ? (
              <ul className="flex flex-col gap-1.5" aria-busy="true">
                {Array.from({ length: 3 }, (_, i) => (
                  <li key={i} className="ink-skeleton h-11 rounded-[10px]" />
                ))}
              </ul>
            ) : null}
            {imports.data && imports.data.items.length === 0 ? (
              <div className="rounded-[12px] border border-line2 bg-surface p-4 text-fg2">
                No videos in the import folder. Put files in it, or set <code className="text-fg">IMPORT_DIR</code> in{" "}
                <code className="text-fg">.env</code> to the folder they are already in.
              </div>
            ) : null}
            {imports.data && imports.data.items.length > 0 ? (
              <ul className="flex flex-col gap-1.5">
                {imports.data.items.map((item) => (
                  <FileRow key={item.ref} item={item} selected={picked?.ref === item.ref} onPick={() => setPicked(item)} />
                ))}
              </ul>
            ) : null}
          </section>

          <section aria-labelledby="details-title" className="flex min-w-0 flex-[1_1_320px] flex-col gap-3">
            <h2 id="details-title" className="font-head text-[16px]">
              Details
            </h2>
            {status.data ? <ConfigErrorCard errors={status.data.errors} /> : null}
            <AnimatePresence mode="wait">
              {picked ? (
                <motion.form key="form" {...panelRise} onSubmit={submit} className="flex flex-col gap-3 rounded-[12px] bg-surface p-3.5">
                  <span className="truncate text-fg3">
                    From <span className="text-fg">{picked.name}</span>
                  </span>
                  <Field label="Title" value={title} onChange={setTitle} required />
                  <Field label="Subject" hint="Who or what the video is about, e.g. the boss name." value={subject} onChange={setSubject} />
                  <Field label="Topic" hint="The game or series. Research and playbooks match on it." value={topic} onChange={setTopic} />
                  <Field label="Extra terms" hint="Optional: the topic's own words, separated by spaces." value={terms} onChange={setTerms} />
                  <Pills
                    label="Kind"
                    value={kind}
                    onChange={setKind}
                    options={[
                      { id: "long", name: "Full video" },
                      { id: "clip", name: "Pre-trimmed clip" },
                    ]}
                  />
                  {presetOptions.length ? (
                    <Pills label="Preset" value={presetId} onChange={setPresetId} options={presetOptions} />
                  ) : null}
                  {create.error ? <ErrorCard title="Import did not start" message={create.error.message} /> : null}
                  <button
                    type="submit"
                    disabled={create.isPending || !title.trim()}
                    className="ink-btn mt-1 flex min-h-11 items-center justify-center gap-1.5 rounded-[22px] border border-accentfill bg-accentfill px-4 text-[12px] font-semibold text-onaccent disabled:opacity-60"
                  >
                    {create.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <ArrowRight aria-hidden="true" size={14} />}
                    {create.isPending ? "Starting import…" : "Import and open"}
                  </button>
                  <span className="text-[11px] text-fg4">The file is copied into LazyCut; the original stays where it is.</span>
                </motion.form>
              ) : (
                <motion.div key="empty" {...panelRise} className="rounded-[12px] border border-dashed border-line3 p-4 text-fg3">
                  Pick a file on the left.
                </motion.div>
              )}
            </AnimatePresence>
          </section>
        </div>
      </main>
    </div>
  );
}
