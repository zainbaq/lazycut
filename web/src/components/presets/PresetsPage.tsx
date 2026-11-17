"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Copy, FileCode2, ListChecks, Loader2, Plus, Save, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ConfigErrorCard, ErrorCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { useConfigStatus, useCreatePreset, useDeletePreset, usePresetDoc, usePresetYaml, usePresets, useSavePreset } from "@/lib/queries";
import type { Preset, PresetDoc, PresetProblem } from "@/lib/types";

import { ProblemList, Text, inputCls } from "./fields";
import { type Locked, PresetForm } from "./PresetForm";

type Tab = "form" | "yaml";

/** Read-only keys the API adds; never part of an edit or of "is it changed". */
function editable(doc: PresetDoc): PresetDoc {
  const rest = { ...doc };
  delete rest.file;
  delete rest.video_count;
  return rest;
}

function same(a: unknown, b: unknown) {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Validate a draft on the server while the owner types (debounced); stale answers are dropped. */
function useLiveCheck(id: string, body: { preset?: PresetDoc; yaml?: string } | null) {
  const [problems, setProblems] = useState<PresetProblem[]>([]);
  const [checking, setChecking] = useState(false);
  const seq = useRef(0);
  const key = body ? JSON.stringify(body) : "";
  useEffect(() => {
    const mine = ++seq.current;
    if (!key) {
      setProblems([]);
      setChecking(false);
      return;
    }
    setChecking(true);
    const timer = setTimeout(() => {
      api
        .checkPreset(id, JSON.parse(key))
        .then((r) => mine === seq.current && setProblems(r.problems))
        .catch((e: Error) => mine === seq.current && setProblems([{ path: "", message: `Could not check: ${e.message}` }]))
        .finally(() => mine === seq.current && setChecking(false));
    }, 350);
    return () => clearTimeout(timer);
  }, [id, key]);
  return { problems, checking };
}

function useLeaveGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

function SaveBar({
  dirty,
  problems,
  checking,
  saving,
  saved,
  onDiscard,
}: {
  dirty: boolean;
  problems: PresetProblem[];
  checking: boolean;
  saving: boolean;
  saved: boolean;
  onDiscard: () => void;
}) {
  const blocked = problems.length > 0;
  return (
    <div className="sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center gap-2 border-t border-line bg-raised px-4 py-3 min-[720px]:-mx-6 min-[720px]:px-6">
      <button
        type="submit"
        disabled={!dirty || blocked || saving || checking}
        className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-4 text-[12px] font-semibold text-onaccent disabled:border-line3 disabled:bg-transparent disabled:text-fg3"
      >
        {saving ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Save aria-hidden="true" size={14} />}
        Save
      </button>
      <button type="button" disabled={!dirty || saving} onClick={onDiscard} className="ink-btn flex min-h-11 items-center rounded-[10px] border border-line3 px-3.5 text-[12px] disabled:opacity-50">
        Discard changes
      </button>
      <span role="status" className="text-[12px]">
        {!dirty ? (saved ? <span className="text-oktext">Saved to the file</span> : <span className="text-fg4">No changes</span>) : checking ? (
          <span className="text-fg3">Checking…</span>
        ) : blocked ? (
          <span className="text-accentsoft">{plural(problems.length, "problem")} to fix before saving</span>
        ) : (
          <span className="text-fg3">Valid · not saved yet</span>
        )}
      </span>
    </div>
  );
}

function FormTab({ doc, onDirty }: { doc: PresetDoc; onDirty: (d: boolean) => void }) {
  const base = useMemo(() => editable(doc), [doc]);
  const [draft, setDraft] = useState<PresetDoc>(base);
  const [saved, setSaved] = useState(false);
  useEffect(() => setDraft(base), [base]);
  const dirty = !same(draft, base);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  const save = useSavePreset(doc.id);
  const live = useLiveCheck(doc.id, dirty ? { preset: draft } : null);
  const locked: Locked = useMemo(
    () => ({
      event_types: new Set(base.event_types.map((e) => e.id)),
      facts: new Set(base.facts.map((f) => f.key)),
      research_fields: new Set(base.research_fields.map((r) => r.key)),
      hooks: new Set(base.hooks.map((h) => h.id)),
      claim_rules: new Set(base.claim_rules.map((c) => c.id)),
    }),
    [base],
  );
  // Problems on a list item show on that item; the rest are listed here (each section also flags its own).
  const general = live.problems.filter((p) => !/^(event_types|facts|research_fields|hooks|claim_rules)\.\d+/.test(p.path));

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({ form: draft }, { onSuccess: () => setSaved(true) });
      }}
    >
      <ProblemList items={general} />
      <PresetForm
        draft={draft}
        problems={live.problems}
        locked={locked}
        onChange={(next) => {
          setSaved(false);
          setDraft(next);
        }}
      />
      {save.error ? <ErrorCard title="Not saved" message={save.error.message} /> : null}
      <SaveBar dirty={dirty} problems={live.problems} checking={live.checking} saving={save.isPending} saved={saved} onDiscard={() => setDraft(base)} />
    </form>
  );
}

function YamlTab({ id, onDirty }: { id: string; onDirty: (d: boolean) => void }) {
  const file = usePresetYaml(id);
  const base = file.data?.text ?? "";
  const [text, setText] = useState(base);
  const [saved, setSaved] = useState(false);
  useEffect(() => setText(base), [base]);
  const dirty = !!file.data && text !== base;
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  const save = useSavePreset(id);
  const live = useLiveCheck(id, dirty ? { yaml: text } : null);

  if (file.error) return <ErrorCard title="Could not read the file" message={file.error.message} onRetry={() => void file.refetch()} />;
  if (!file.data) return <span className="ink-skeleton block h-[420px] rounded-[12px]" aria-busy="true" />;
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({ yaml: text }, { onSuccess: () => setSaved(true) });
      }}
    >
      <p className="text-[12px] text-fg3">The file exactly as saved, comments included. Saving here writes your text as typed, once it is valid.</p>
      <label className="flex flex-col gap-1">
        <span className="sr-only">Preset YAML</span>
        <textarea
          value={text}
          spellCheck={false}
          onChange={(e) => {
            setSaved(false);
            setText(e.target.value);
          }}
          rows={Math.min(40, Math.max(16, text.split("\n").length + 1))}
          className="w-full resize-y rounded-[12px] border border-line3 bg-bg p-3.5 font-mono text-[12px] leading-[1.55] text-fg outline-none focus:border-accent"
          style={{ tabSize: 2 }}
        />
      </label>
      <ProblemList items={live.problems} />
      {save.error ? <ErrorCard title="Not saved" message={save.error.message} /> : null}
      <SaveBar dirty={dirty} problems={live.problems} checking={live.checking} saving={save.isPending} saved={saved} onDiscard={() => setText(base)} />
    </form>
  );
}

function slug(name: string) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^[^a-z]+/, "")
    .slice(0, 40);
}

function NewPresetDialog({ presets, from, open, onOpenChange }: { presets: Preset[]; from: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const create = useCreatePreset();
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [copyFrom, setCopyFrom] = useState(from);
  useEffect(() => {
    if (open) {
      setName("");
      setId("");
      setIdTouched(false);
      setCopyFrom(from);
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the dialog opens
  }, [open]);
  const shownId = idTouched ? id : slug(name);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex w-[min(440px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4 text-[12px] text-fg">
          <div className="flex items-center justify-between">
            <Dialog.Title className="font-head text-[16px]">New preset</Dialog.Title>
            <Dialog.Close className="ink-btn -m-2 flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3" aria-label="Close">
              <X aria-hidden="true" size={16} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="text-fg3">A new file in config/presets. Copying keeps the other preset&apos;s comments.</Dialog.Description>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate(
                { id: shownId, name: name.trim(), copy_from: copyFrom || null },
                {
                  onSuccess: (made) => {
                    onOpenChange(false);
                    router.push(`/settings/presets/${made.id}`);
                  },
                },
              );
            }}
          >
            <Text label="Name" value={name} placeholder="Souls boss" onChange={setName} />
            <Text
              label="Id"
              mono
              value={shownId}
              hint="Lower-case letters, digits and _. Also the file name. Fixed once made."
              onChange={(v) => {
                setIdTouched(true);
                setId(v);
              }}
            />
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-fg2">Start from</span>
              <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)} className={inputCls}>
                {presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    A copy of {p.name}
                  </option>
                ))}
              </select>
            </label>
            {create.error ? <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5">{create.error.message}</span> : null}
            <div className="flex justify-end gap-2">
              <Dialog.Close className="ink-btn min-h-11 rounded-[10px] border border-line3 px-3.5 text-[12px]">Cancel</Dialog.Close>
              <button
                type="submit"
                disabled={!name.trim() || !shownId || create.isPending}
                className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-4 text-[12px] font-semibold text-onaccent disabled:opacity-50"
              >
                {create.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Plus aria-hidden="true" size={14} />}
                Make preset
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DeleteDialog({ doc, open, onOpenChange }: { doc: PresetDoc; open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const remove = useDeletePreset();
  const count = doc.video_count ?? 0;
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        if (o) remove.reset();
        onOpenChange(o);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex w-[min(400px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4 text-[12px] text-fg">
          <Dialog.Title className="font-head text-[16px]">Delete {doc.name}?</Dialog.Title>
          <Dialog.Description className="text-fg2">
            {doc.file ? <code>{doc.file}</code> : "The file"} is deleted from the config folder.{" "}
            {count ? `${plural(count, "video")} using it switch to General.` : "No video uses it."} This cannot be undone here.
          </Dialog.Description>
          {remove.error ? <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5">{remove.error.message}</span> : null}
          <div className="flex justify-end gap-2">
            <Dialog.Close className="ink-btn min-h-11 rounded-[10px] border border-line3 px-3.5 text-[12px]">Cancel</Dialog.Close>
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(doc.id, {
                  onSuccess: () => {
                    onOpenChange(false);
                    router.push("/settings/presets/general");
                  },
                })
              }
              className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accent px-3.5 text-[12px] font-semibold text-fg disabled:opacity-50"
            >
              <Trash2 aria-hidden="true" size={14} className="text-accentsoft" />
              Delete preset
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Editor({ id, presets }: { id: string; presets: Preset[] }) {
  const doc = usePresetDoc(id);
  const [tab, setTab] = useState<Tab>("form");
  const [dirty, setDirty] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  useLeaveGuard(dirty);
  useEffect(() => setDirty(false), [id]);

  if (doc.error) return <ErrorCard title="Could not load the preset" message={doc.error.message} onRetry={() => void doc.refetch()} />;
  if (!doc.data) {
    return (
      <div className="flex flex-col gap-2.5" aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className="ink-skeleton block h-12 rounded-[12px]" />
        ))}
      </div>
    );
  }
  const d = doc.data;
  const tabBtn = (t: Tab, label: string, Icon: typeof ListChecks) => (
    <button
      type="button"
      role="tab"
      aria-selected={tab === t}
      disabled={dirty && tab !== t}
      title={dirty && tab !== t ? "Save or discard your changes first" : undefined}
      onClick={() => setTab(t)}
      className="flex min-h-11 items-center gap-1.5 rounded-[8px] px-3 text-[12px] transition-colors duration-200 disabled:opacity-40"
      style={{ background: tab === t ? "var(--surface-2)" : "transparent", color: tab === t ? "var(--text)" : "var(--text-3)" }}
    >
      <Icon aria-hidden="true" size={14} />
      {label}
    </button>
  );

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <h1 className="font-head text-[22px] leading-tight">{d.name}</h1>
          <span className="text-[12px] text-fg3">
            <code>{d.id}</code> · {d.file ?? "built in (saving makes presets/general.yaml)"} · {d.video_count ? `used by ${plural(d.video_count, "video")}` : "no video uses it"}
          </span>
        </div>
        <button type="button" onClick={() => setNewOpen(true)} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px]">
          <Copy aria-hidden="true" size={14} />
          New or copy
        </button>
        {d.id !== "general" ? (
          <button type="button" onClick={() => setDeleteOpen(true)} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px]">
            <Trash2 aria-hidden="true" size={14} className="text-accentsoft" />
            Delete
          </button>
        ) : null}
      </div>
      <div role="tablist" aria-label="Edit as" className="flex self-start rounded-[10px] border border-line3 p-0.5">
        {tabBtn("form", "Form", ListChecks)}
        {tabBtn("yaml", "YAML", FileCode2)}
      </div>
      {tab === "form" ? <FormTab key={`form-${id}`} doc={d} onDirty={setDirty} /> : <YamlTab key={`yaml-${id}`} id={id} onDirty={setDirty} />}
      <NewPresetDialog presets={presets} from={d.id} open={newOpen} onOpenChange={setNewOpen} />
      <DeleteDialog doc={d} open={deleteOpen} onOpenChange={setDeleteOpen} />
    </div>
  );
}

/** `/settings/presets/[id]`: the preset list and the editor (BUILD_SPEC 5, 9.2). */
export function PresetsPage({ id }: { id: string }) {
  const presets = usePresets();
  const status = useConfigStatus();
  const list = presets.data ?? [];
  return (
    <div className="flex min-h-screen">
      <Rail section="settings" />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
            <Link href="/" className="py-3.5 text-fg">
              Library
            </Link>
            <span aria-hidden="true" className="text-fg4">/</span>
            <Link href="/settings" className="py-3.5 text-fg">
              Settings
            </Link>
            <span aria-hidden="true" className="text-fg4">/</span>
            <span className="text-fg3">Presets</span>
          </nav>
        </header>
        <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-4 px-4 pt-5 min-[960px]:flex-row min-[960px]:items-start min-[720px]:px-6">
          <nav aria-label="Presets" className="flex flex-col gap-1.5 min-[960px]:sticky min-[960px]:top-5 min-[960px]:w-[220px] min-[960px]:shrink-0">
            <span className="px-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-fg3">Presets</span>
            {presets.error ? <ErrorCard title="Could not load presets" message={presets.error.message} onRetry={() => void presets.refetch()} /> : null}
            <ul className="flex flex-row flex-wrap gap-1.5 min-[960px]:flex-col">
              {list.map((p) => (
                <li key={p.id}>
                  <Link
                    href={`/settings/presets/${p.id}`}
                    aria-current={p.id === id ? "page" : undefined}
                    className="ink-btn flex min-h-11 flex-col justify-center rounded-[10px] border px-3 py-1.5"
                    style={{ borderColor: p.id === id ? "var(--accent)" : "var(--line-2)", background: p.id === id ? "var(--surface-2)" : undefined }}
                  >
                    <span className="text-[13px] text-fg">{p.name}</span>
                    <span className="text-[11px] text-fg3">
                      {p.id}
                      {typeof p.video_count === "number" && p.video_count ? ` · ${plural(p.video_count, "video")}` : ""}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            {status.data ? <ConfigErrorCard errors={status.data.errors.filter((e) => e.file.startsWith("presets/"))} /> : null}
          </nav>
          <main className="min-w-0 flex-1 pb-6">
            {presets.data && !list.some((p) => p.id === id) ? (
              <ErrorCard title={`No preset \`${id}\``} message="It may have been deleted, or its file does not validate (see the list)." />
            ) : (
              <Editor key={id} id={id} presets={list} />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
