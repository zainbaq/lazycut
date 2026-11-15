"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, Send, Undo2, X } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import { isLink, todayIso } from "@/lib/format";
import { usePublish, useUnpublish } from "@/lib/queries";
import type { Video } from "@/lib/types";

const overlay = "fixed inset-0 z-40 bg-[rgba(7,7,7,0.72)]";
const panel =
  "fixed left-1/2 top-1/2 z-50 flex w-[min(420px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-[12px] border border-line2 bg-raised p-4 text-[12px] text-fg";
const inputCls =
  "min-h-11 w-full rounded-[10px] border border-linestrong bg-surface px-3 text-[12px] text-fg placeholder:text-fg4 aria-[invalid=true]:border-accent";
const primaryBtn =
  "ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:opacity-60";

function Head({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <Dialog.Title className="flex items-center gap-2 font-head text-[16px]">
        {icon}
        {title}
      </Dialog.Title>
      <Dialog.Close className="ink-btn -m-2 flex h-11 w-11 items-center justify-center rounded-[10px] text-fg3" aria-label="Close">
        <X aria-hidden="true" size={16} />
      </Dialog.Close>
    </div>
  );
}

function PublishForm({ video, onDone }: { video: Video; onDone: () => void }) {
  const id = useId();
  const publish = usePublish(video.id);
  const [url, setUrl] = useState("");
  const [date, setDate] = useState(todayIso());
  const [tried, setTried] = useState(false);
  const linkError = !url.trim() ? "Paste the video’s link" : !isLink(url) ? "Enter a full link starting with https://" : null;

  return (
    <form
      noValidate
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (linkError) return;
        publish.mutate({ url: url.trim(), published_at: date || null }, { onSuccess: onDone });
      }}
    >
      <Dialog.Description className="text-fg2">
        Paste the link of the uploaded video. LazyCut records it and adds this video to your past uploads, using the title and hook from its
        package, so later packages can point their end screen at it.
      </Dialog.Description>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-url`} className="text-[11px] font-semibold text-fg3">
          Video link
        </label>
        <input
          id={`${id}-url`}
          type="url"
          autoFocus
          value={url}
          placeholder="https://youtu.be/…"
          onChange={(e) => setUrl(e.target.value)}
          aria-invalid={tried && linkError ? true : undefined}
          aria-describedby={tried && linkError ? `${id}-err` : undefined}
          className={inputCls}
        />
        {tried && linkError ? (
          <span id={`${id}-err`} className="text-[11px] text-accentsoft">
            {linkError}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-date`} className="text-[11px] font-semibold text-fg3">
          Published on
        </label>
        <input id={`${id}-date`} type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} />
      </div>
      {publish.error ? (
        <span role="alert" className="rounded-[10px] border border-accent bg-surface p-2.5">
          {publish.error.message}
        </span>
      ) : null}
      <div className="flex justify-end gap-2">
        <Dialog.Close className="ink-btn min-h-11 rounded-[10px] border border-line3 px-3.5 text-[12px]">Cancel</Dialog.Close>
        <button type="submit" disabled={publish.isPending} className={primaryBtn}>
          {publish.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Send aria-hidden="true" size={14} />}
          Mark as published
        </button>
      </div>
    </form>
  );
}

/** "Mark as published" (7.8): paste the link, pick the date. Free; no model call. */
export function PublishDialog({ video, open, onOpenChange }: { video: Video; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={overlay} />
        <Dialog.Content className={panel}>
          <Head icon={<Send aria-hidden="true" size={16} className="text-accentsoft" />} title="Mark as published" />
          {/* Mounted only while open, so each opening starts with an empty link and today's date. */}
          {open ? <PublishForm video={video} onDone={() => onOpenChange(false)} /> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Undo "Mark as published": clears the link and removes the past-upload entry it created. */
export function UnpublishDialog({ video, open, onOpenChange }: { video: Video; open: boolean; onOpenChange: (o: boolean) => void }) {
  const unpublish = useUnpublish(video.id);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        if (o) unpublish.reset();
        onOpenChange(o);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className={overlay} />
        <Dialog.Content className={panel}>
          <Head icon={<Undo2 aria-hidden="true" size={16} className="text-accentsoft" />} title="Unpublish this video?" />
          <Dialog.Description className="text-fg2">
            LazyCut forgets the link{video.published_url ? <> (<span className="break-all text-fg">{video.published_url}</span>)</> : null} and the
            publish date, and removes the past-upload entry “Mark as published” created. The video on YouTube is not touched.
          </Dialog.Description>
          {unpublish.error ? (
            <span role="alert" className="rounded-[10px] border border-accent bg-surface p-2.5">
              {unpublish.error.message}
            </span>
          ) : null}
          <div className="flex justify-end gap-2">
            <Dialog.Close className="ink-btn min-h-11 rounded-[10px] border border-line3 px-3.5 text-[12px]">Cancel</Dialog.Close>
            <button
              type="button"
              disabled={unpublish.isPending}
              onClick={() => unpublish.mutate(undefined, { onSuccess: () => onOpenChange(false) })}
              className={primaryBtn}
            >
              {unpublish.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Undo2 aria-hidden="true" size={14} />}
              Unpublish
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
