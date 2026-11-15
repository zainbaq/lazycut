"use client";

import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Switch } from "@/components/ui/Switch";
import { apiUrl } from "@/lib/api";
import { clock } from "@/lib/format";
import { crop as cropMotion, PLAYHEAD_SEEK_CSS } from "@/lib/motion";
import { useWorkspace } from "@/lib/store";
import type { EventType, TimelineEvent, Video } from "@/lib/types";

import { eventName, typeOf } from "./glyphs";
import { eventAt, stepEvent } from "./nav";

function Scrubber({ duration }: { duration: number }) {
  const playhead = useWorkspace((s) => s.playhead);
  const seeking = useWorkspace((s) => s.seeking);
  const seek = useWorkspace((s) => s.seek);
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const pct = duration > 0 ? Math.min(100, (playhead / duration) * 100) : 0;

  const at = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r || duration <= 0) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * duration;
  };

  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label="Playback position"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration * 10) / 10}
      aria-valuenow={Math.round(playhead * 10) / 10}
      aria-valuetext={clock(playhead)}
      className="relative h-6 cursor-pointer touch-none"
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        seek(at(e.clientX), { animate: false });
      }}
      onPointerMove={(e) => {
        if (dragging.current) seek(at(e.clientX), { animate: false });
      }}
      onPointerUp={() => {
        dragging.current = false;
      }}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 5 : 1;
        if (e.key === "ArrowLeft") seek(playhead - step);
        else if (e.key === "ArrowRight") seek(playhead + step);
        else if (e.key === "Home") seek(0);
        else if (e.key === "End") seek(duration);
        else return;
        e.preventDefault();
      }}
    >
      <span aria-hidden="true" className="absolute left-0 right-0 top-[9px] block h-1.5 rounded-[3px] bg-line2">
        <span
          className="absolute bottom-0 left-0 top-0 block rounded-[3px] bg-accent"
          style={{ width: `${pct}%`, transition: seeking ? `width 240ms var(--ease-out-ink)` : undefined }}
        />
        <span
          className="absolute -top-1 -ml-[7px] block h-3.5 w-3.5 rounded-full bg-fg"
          style={{ left: `${pct}%`, transition: seeking ? PLAYHEAD_SEEK_CSS : undefined }}
        />
      </span>
    </div>
  );
}

function HeadLabel({ events, types }: { events: TimelineEvent[]; types: Map<string, EventType> }) {
  const playhead = useWorkspace((s) => s.playhead);
  const e = eventAt(events, playhead);
  if (!e) return null;
  return (
    <span className="pointer-events-none absolute bottom-3.5 left-1/2 max-w-[80%] -translate-x-1/2 truncate whitespace-nowrap rounded border border-accent bg-[rgba(7,7,7,0.8)] px-2.5 py-1 text-fg">
      {eventName(e, typeOf(types, e.type))}
    </span>
  );
}

function TimeReadout() {
  const playhead = useWorkspace((s) => s.playhead);
  return <span className="tnum text-fg2">{clock(playhead)}</span>;
}

/** Preview stage, transport and scrubber (9.4 region 4). Owns the <video> element. */
export function Preview({
  video,
  events,
  types,
}: {
  video: Video;
  events: TimelineEvent[];
  types: Map<string, EventType>;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const setVideoEl = useWorkspace((s) => s.setVideoEl);
  const setPlayhead = useWorkspace((s) => s.setPlayhead);
  const setPlaying = useWorkspace((s) => s.setPlaying);
  const playing = useWorkspace((s) => s.playing);
  const togglePlay = useWorkspace((s) => s.togglePlay);
  const seek = useWorkspace((s) => s.seek);
  const select = useWorkspace((s) => s.select);
  const crop916 = useWorkspace((s) => s.crop916);
  const setCrop916 = useWorkspace((s) => s.setCrop916);
  const [stage, setStage] = useState({ w: 0, h: 0 });
  const [mediaError, setMediaError] = useState<string | null>(null);

  const duration = video.duration_s ?? 0;

  useEffect(() => {
    setVideoEl(ref.current);
    return () => setVideoEl(null);
  }, [setVideoEl]);

  // While playing, the playhead follows video.currentTime every frame.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const el = ref.current;
      if (el) setPlayhead(el.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, setPlayhead]);

  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setStage({ w: entry.contentRect.width, h: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const jump = (dir: 1 | -1) => {
    const e = stepEvent(events, useWorkspace.getState().playhead, dir);
    if (!e) return;
    useWorkspace.getState().pause();
    select(e.id);
    seek(e.t_start);
  };

  // 9:16 frame width inside the stage; the rest is dimmed.
  const cropW = stage.h * (9 / 16);
  const side = crop916 ? Math.max(0, (stage.w - cropW) / 2) : 0;

  return (
    <section aria-label="Preview" className="flex min-w-0 flex-[999_1_380px] flex-col gap-2.5 p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-[13px] font-semibold">{video.title}</span>
        <Switch checked={crop916} onChange={setCrop916}>
          9:16 crop
        </Switch>
      </div>
      <div ref={stageRef} className="relative flex aspect-video max-h-[46vh] w-full justify-center overflow-hidden rounded-[12px] bg-stage">
        <video
          ref={ref}
          src={apiUrl(video.media_url)}
          preload="auto"
          playsInline
          className="h-full w-full object-contain"
          onPlay={() => setPlaying(true)}
          onPause={() => {
            setPlaying(false);
            if (ref.current) setPlayhead(ref.current.currentTime);
          }}
          onSeeked={() => {
            if (ref.current && ref.current.paused) setPlayhead(ref.current.currentTime);
          }}
          onLoadedData={() => setMediaError(null)}
          onError={() => setMediaError("The video could not be loaded from the API.")}
          onClick={togglePlay}
        />
        <motion.div
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0 left-0 top-0 bg-[rgba(7,7,7,0.72)]"
          animate={{ width: side }}
          transition={cropMotion}
        />
        <motion.div
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0 right-0 top-0 bg-[rgba(7,7,7,0.72)]"
          animate={{ width: side }}
          transition={cropMotion}
        />
        <div aria-hidden="true" className="pointer-events-none absolute bottom-0 left-1/2 top-0 border-l border-dashed border-[rgba(240,106,80,0.7)]" />
        <HeadLabel events={events} types={types} />
        {mediaError ? (
          <span role="alert" className="absolute inset-x-4 top-4 rounded-[10px] border border-accent bg-surface p-2.5 text-fg">
            {mediaError}
          </span>
        ) : null}
      </div>
      <div className="flex items-center justify-between">
        <TimeReadout />
        <div className="flex items-center gap-1">
          <button type="button" aria-label="Previous event" onClick={() => jump(-1)} className="ink-btn flex h-11 w-11 items-center justify-center rounded-full text-fg">
            <SkipBack aria-hidden="true" size={16} fill="currentColor" />
          </button>
          <button
            type="button"
            aria-label={playing ? "Pause" : "Play"}
            onClick={togglePlay}
            className="flex h-11 w-11 items-center justify-center rounded-full border border-accentfill bg-accentfill text-onaccent transition-transform duration-150 active:scale-95"
          >
            {playing ? <Pause aria-hidden="true" size={16} fill="currentColor" /> : <Play aria-hidden="true" size={16} fill="currentColor" />}
          </button>
          <button type="button" aria-label="Next event" onClick={() => jump(1)} className="ink-btn flex h-11 w-11 items-center justify-center rounded-full text-fg">
            <SkipForward aria-hidden="true" size={16} fill="currentColor" />
          </button>
        </div>
        <span className="tnum text-fg3">{clock(duration)}</span>
      </div>
      <Scrubber duration={duration} />
    </section>
  );
}
