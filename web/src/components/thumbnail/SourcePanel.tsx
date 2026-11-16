"use client";

import { Check, ImageUp, Loader2, ScanSearch, Sparkles } from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";

import { apiUrl, frameUrl } from "@/lib/api";
import { clock } from "@/lib/format";
import { useFindFrames, useFrames, useUploadThumbSource } from "@/lib/queries";
import type { FrameCandidate, ThumbnailState, Video } from "@/lib/types";

import { CORNER_LABELS, CornerGlyph, HUD_LABELS, SectionTitle } from "./bits";

export type PickedSource = { kind: "frame"; t: number } | { kind: "upload"; upload_id: string; url: string };

const UPLOAD_TYPES = ["image/jpeg", "image/png", "image/webp"];

function sameSource(a: PickedSource | null, b: PickedSource): boolean {
  if (!a || a.kind !== b.kind) return false;
  return a.kind === "frame" ? Math.abs(a.t - (b as { t: number }).t) < 0.05 : a.upload_id === (b as { upload_id: string }).upload_id;
}

function Tile({
  picked,
  onPick,
  img,
  alt,
  children,
}: {
  picked: boolean;
  onPick: () => void;
  img: string;
  alt: string;
  children?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={picked}
      onClick={onPick}
      className={
        "ink-chip group relative flex flex-col overflow-hidden rounded-[10px] border bg-surface text-left " +
        (picked ? "border-accent outline-2 outline-offset-2 outline-accent" : "border-line2")
      }
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- frames come from the local API */}
      <img src={img} alt={alt} loading="lazy" className="aspect-video w-full bg-stage object-cover" />
      {picked ? (
        <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded-full bg-accentfill px-2 py-0.5 text-[11px] font-semibold text-onaccent">
          <Check aria-hidden="true" size={12} />
          Source
        </span>
      ) : null}
      {children}
    </button>
  );
}

function CandidateTile({ videoId, frame, rank, picked, onPick }: { videoId: string; frame: FrameCandidate; rank: number; picked: boolean; onPick: () => void }) {
  const c = frame.claude;
  return (
    <Tile picked={picked} onPick={onPick} img={frameUrl(videoId, frame.t, 640)} alt={`Frame at ${clock(frame.t)}`}>
      <span className="flex flex-col gap-1 px-2.5 py-2">
        <span className="flex items-center gap-2 text-[12px]">
          <span className="tnum font-semibold text-fg">#{rank}</span>
          <span className="tnum text-fg2">{clock(frame.t)}</span>
          <span className="tnum ml-auto text-goldtext" title="Combined score (Claude 60%, sharpness and contrast 40%)">
            {Math.round(frame.score * 100)}
          </span>
        </span>
        <span className="line-clamp-2 text-[11px] text-fg3">{c?.reason || frame.why}</span>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-fg4">
          {c ? <span>{HUD_LABELS[c.hud]}</span> : null}
          <span className="flex items-center gap-1" title="Suggested corner for the word">
            <CornerGlyph corner={frame.text_corner} size={10} />
            {CORNER_LABELS[frame.text_corner]}
          </span>
        </span>
      </span>
    </Tile>
  );
}

/** Pick any moment with the filmstrip: dragging shows the nearest strip frame at once; "Use" sets it. */
function Scrubber({ video, onUse, current }: { video: Video; onUse: (t: number) => void; current: number | null }) {
  const frames = useFrames(video.id, video.status === "ready");
  const duration = video.duration_s ?? 0;
  const [t, setT] = useState(() => current ?? Math.round(duration * 0.5 * 10) / 10);
  const id = useId();
  const nearest = useMemo(() => {
    const f = frames.data;
    if (!f?.frames.length || !f.interval_s) return null;
    const i = Math.min(f.frames.length - 1, Math.max(0, Math.round(t / f.interval_s)));
    return f.frames[i];
  }, [frames.data, t]);
  if (!duration) return null;
  return (
    <div className="flex flex-col gap-2 rounded-[12px] bg-surface p-3">
      <label htmlFor={id} className="flex items-center gap-2 text-[12px] font-semibold text-fg2">
        Any moment
        <span className="tnum ml-auto font-normal text-fg3">{clock(t)}</span>
      </label>
      <div className="flex flex-col gap-2 min-[560px]:flex-row min-[560px]:items-center">
        {nearest ? (
          // eslint-disable-next-line @next/next/no-img-element -- filmstrip frames come from the local API
          <img src={apiUrl(nearest.url)} alt={`Filmstrip frame near ${clock(t)}`} className="aspect-video w-full rounded-[8px] bg-stage object-cover min-[560px]:w-[160px]" />
        ) : (
          <span className="ink-skeleton block aspect-video w-full rounded-[8px] min-[560px]:w-[160px]" />
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <input
            id={id}
            type="range"
            min={0}
            max={Math.max(0, duration - 0.1)}
            step={0.1}
            value={t}
            onChange={(e) => setT(Number(e.target.value))}
            className="ink-range h-11 w-full"
          />
          <button
            type="button"
            onClick={() => onUse(t)}
            className="ink-btn flex min-h-11 items-center justify-center gap-1.5 self-start rounded-[10px] border border-line3 px-3.5 text-[12px]"
          >
            <Check aria-hidden="true" size={14} />
            Use {clock(t)}
          </button>
        </div>
      </div>
    </div>
  );
}

export function SourcePanel({
  video,
  state,
  source,
  onSource,
}: {
  video: Video;
  state: ThumbnailState;
  source: PickedSource | null;
  onSource: (s: PickedSource) => void;
}) {
  const find = useFindFrames(video.id);
  const upload = useUploadThumbSource(video.id);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const finding = state.finding_frames || find.isPending;
  const finds = state.frames;
  const pickedFrame = source?.kind === "frame" ? source.t : null;
  const extra = source?.kind === "frame" && !finds?.frames.some((f) => Math.abs(f.t - source.t) < 0.05) ? source.t : null;

  return (
    <section aria-labelledby="source-heading" className="flex min-w-0 flex-col gap-3">
      <SectionTitle id="source-heading" aside={finds ? `${finds.frames.length} best of ${finds.looked_at} looked at · ranked by ${finds.ranked_by === "claude" ? "Claude" : "sharpness and contrast"}` : "a frame from the video, or your own image"}>
        Source
      </SectionTitle>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={finding || video.status !== "ready"}
          onClick={() => find.mutate()}
          aria-describedby="find-frames-note"
          className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px] font-semibold disabled:opacity-60"
        >
          {finding ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <ScanSearch aria-hidden="true" size={14} />}
          {finding ? "Looking at frames…" : finds ? "Find frames again" : "Find frames"}
        </button>
        <button
          type="button"
          disabled={upload.isPending}
          onClick={() => fileRef.current?.click()}
          className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px] disabled:opacity-60"
        >
          {upload.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <ImageUp aria-hidden="true" size={14} />}
          Upload image
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={UPLOAD_TYPES.join(",")}
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            setUploadError(null);
            if (!UPLOAD_TYPES.includes(file.type)) {
              setUploadError("Upload a JPEG, PNG or WebP image.");
              return;
            }
            upload.mutate(file, {
              onSuccess: (up) => onSource({ kind: "upload", upload_id: up.id, url: up.url }),
              onError: (err) => setUploadError(err.message),
            });
          }}
        />
        <span id="find-frames-note" className="text-[11px] text-fg4">
          Find frames scores sharpness and contrast around the fight&apos;s peaks for free, then one small Claude call
          {state.can_review ? " (about $0.02)" : ""} ranks the best eight{state.can_review ? "" : " (off: no ANTHROPIC_API_KEY, code ranking only)"}.
        </span>
      </div>
      {find.error ? (
        <span role="alert" className="rounded-[10px] border border-accent px-2.5 py-2 text-fg">
          {find.error.message}
        </span>
      ) : null}
      {uploadError ? (
        <span role="alert" className="rounded-[10px] border border-accent px-2.5 py-2 text-fg">
          {uploadError}
        </span>
      ) : null}

      {finding && !finds ? (
        <div className="grid grid-cols-2 gap-2.5 min-[720px]:grid-cols-4" aria-busy="true" aria-label="Looking for frames">
          {Array.from({ length: 4 }, (_, i) => (
            <span key={i} className="ink-skeleton block aspect-[4/3] rounded-[10px]" />
          ))}
        </div>
      ) : finds?.frames.length ? (
        <ul className="grid grid-cols-2 gap-2.5 min-[720px]:grid-cols-4" aria-label="Candidate frames, best first">
          {finds.frames.map((f, i) => (
            <li key={f.t} className="flex">
              <CandidateTile videoId={video.id} frame={f} rank={i + 1} picked={pickedFrame !== null && Math.abs(pickedFrame - f.t) < 0.05} onPick={() => onSource({ kind: "frame", t: f.t })} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex items-start gap-2 rounded-[12px] border border-dashed border-line3 p-3.5 text-fg3">
          <Sparkles aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-accentsoft" />
          <span>
            No frames found yet. <span className="text-fg2">Find frames</span> picks sharp, dramatic moments with a calm corner
            for the word; or choose any moment below, or upload your own image.
          </span>
        </div>
      )}

      {extra !== null ? (
        <div className="grid grid-cols-2 gap-2.5 min-[720px]:grid-cols-4">
          <Tile picked onPick={() => undefined} img={frameUrl(video.id, extra, 640)} alt={`Frame at ${clock(extra)}`}>
            <span className="tnum px-2.5 py-2 text-[12px] text-fg2">Your pick · {clock(extra)}</span>
          </Tile>
        </div>
      ) : null}

      <Scrubber video={video} current={pickedFrame} onUse={(t) => onSource({ kind: "frame", t: Math.round(t * 10) / 10 })} />

      {state.uploads.length ? (
        <div className="flex flex-col gap-2">
          <span className="text-[12px] font-semibold text-fg2">Your uploads</span>
          <ul className="grid grid-cols-3 gap-2 min-[720px]:grid-cols-6">
            {state.uploads.map((u) => {
              const s: PickedSource = { kind: "upload", upload_id: u.id, url: u.url };
              return (
                <li key={u.id} className="flex">
                  <Tile picked={sameSource(source, s)} onPick={() => onSource(s)} img={apiUrl(u.url)} alt="Uploaded image" />
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
