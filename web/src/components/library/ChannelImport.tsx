"use client";

import { Check, ListPlus, Loader2, RefreshCw, Youtube } from "lucide-react";
import { useEffect, useState } from "react";

import { ErrorCard } from "@/components/ui/Cards";
import { dayDate, plural } from "@/lib/format";
import { useAddPlaylists, useImportStatus, useStartImport } from "@/lib/queries";
import type { ChannelSync, ImportStatus } from "@/lib/types";

const quietBtn = "ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px] text-fg disabled:opacity-50";

/** Header button: import (or refresh) past uploads from the channel. */
export function ImportButton({ status }: { status: ImportStatus | undefined }) {
  const start = useStartImport();
  const running = !!status?.running || start.isPending;
  const why = !status ? undefined : !status.key_set ? "Add YOUTUBE_API_KEY to .env to import the channel" : !status.handle ? "Set handle in config/channel.yaml" : undefined;
  return (
    <button type="button" onClick={() => start.mutate()} disabled={!status?.can_import || running} title={why} className={`${quietBtn} rounded-[22px] px-4`}>
      {running ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : status?.last ? <RefreshCw aria-hidden="true" size={14} /> : <Youtube aria-hidden="true" size={14} />}
      {status?.last ? "Import again" : "Import from YouTube"}
    </button>
  );
}

function PlaylistOffer({ last }: { last: ChannelSync }) {
  const add = useAddPlaylists();
  const missing = last.playlists.filter((p) => !p.in_config);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(missing.map((p) => p.id)));
  const missingKey = missing.map((p) => p.id).join(",");
  useEffect(() => setPicked(new Set(missingKey ? missingKey.split(",") : [])), [missingKey]);
  if (!missing.length) {
    return (
      <span className="flex items-center gap-1.5 text-[12px] text-oktext">
        <Check aria-hidden="true" size={13} />
        Every playlist on the channel is in channel.yaml.
      </span>
    );
  }
  return (
    <fieldset className="flex flex-col gap-2 rounded-[10px] border border-line2 p-3">
      <legend className="px-1 text-[12px] font-semibold text-fg2">{plural(missing.length, "playlist")} on the channel but not in channel.yaml</legend>
      <span className="text-[12px] text-fg3">
        The package links a topic&apos;s playlist, and the Shorts description is blocked without one. Each is added with its title as the topic.
      </span>
      <ul className="flex flex-col">
        {missing.map((p) => (
          <li key={p.id}>
            <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[12px]">
              <input
                type="checkbox"
                checked={picked.has(p.id)}
                onChange={(e) => {
                  const next = new Set(picked);
                  if (e.target.checked) next.add(p.id);
                  else next.delete(p.id);
                  setPicked(next);
                }}
                className="h-4 w-4 accent-[var(--accent)]"
              />
              <span className="text-fg">{p.title}</span>
              <span className="tnum text-fg3">{plural(p.count, "video")}</span>
            </label>
          </li>
        ))}
      </ul>
      {add.error ? <span role="alert" className="text-accentsoft">{add.error.message}</span> : null}
      <button type="button" disabled={!picked.size || add.isPending} onClick={() => add.mutate([...picked])} className={`${quietBtn} self-start`}>
        {add.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <ListPlus aria-hidden="true" size={14} />}
        Add {picked.size ? plural(picked.size, "playlist") : "playlists"} to channel.yaml
      </button>
    </fieldset>
  );
}

/** What the import is doing, or what the last one found. */
export function ImportPanel({ status, onShowUnread }: { status: ImportStatus; onShowUnread: () => void }) {
  const job = status.running;
  const failed = !job && status.last_job?.status === "error" ? status.last_job : null;
  const last = status.last;
  if (!job && !failed && !last) return null;
  return (
    <section aria-label="Import from YouTube" className="flex flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4">
      {job ? (
        <div className="flex flex-col gap-2" aria-live="polite">
          <span className="text-[12px] text-fg2">{job.message ?? "Starting"}…</span>
          <span className="relative block h-[3px] overflow-hidden rounded-full bg-line2">
            <span className="absolute inset-y-0 left-0 block rounded-full bg-accent transition-[width] duration-300" style={{ width: `${Math.max(4, job.progress * 100)}%` }} />
          </span>
        </div>
      ) : null}
      {failed ? <ErrorCard title="The import stopped" message={failed.error ?? failed.message ?? "No message"} /> : null}
      {last && !job ? (
        <>
          <div className="flex flex-col gap-1">
            <span className="text-[13px] text-fg">
              <span className="font-semibold">{last.channel.title}</span> · imported {dayDate(last.at)}: {plural(last.long, "video")} and {plural(last.shorts, "Short")}
            </span>
            <span className="text-[12px] text-fg3">
              {last.new ? `${last.new} new · ` : ""}
              {last.linked ? `${plural(last.linked, "entry", "entries")} you had typed in matched by link · ` : ""}
              topic and subject read from each title, no paid call · {last.units} of YouTube&apos;s 10,000 free daily quota units
            </span>
            {last.unread ? (
              <button type="button" onClick={onShowUnread} className="self-start text-[12px] text-accentsoft underline underline-offset-2">
                {plural(last.unread, "title")} could not be read: fill in topic and subject
              </button>
            ) : null}
          </div>
          <PlaylistOffer last={last} />
        </>
      ) : null}
    </section>
  );
}

export { useImportStatus };
