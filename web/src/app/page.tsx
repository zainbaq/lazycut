"use client";

import { Film, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { StatusPill } from "@/components/ui/StatusPill";
import { frameUrl } from "@/lib/api";
import { clock, shortDate } from "@/lib/format";
import { useVideos } from "@/lib/queries";
import type { Video } from "@/lib/types";

function VideoCard({ video }: { video: Video }) {
  const busyJob = video.jobs.find((j) => j.status === "running" || j.status === "queued") ?? null;
  const thumb = video.status === "ready" && video.duration_s ? frameUrl(video.id, video.duration_s * 0.3, 480) : null;
  return (
    <Link
      href={`/v/${video.id}`}
      className="group flex flex-col overflow-hidden rounded-[12px] border border-line2 bg-surface transition-colors hover:border-line3"
    >
      <div className="relative aspect-video overflow-hidden bg-stageframe">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="ink-skeleton h-full w-full" aria-hidden="true" />
        )}
        {video.duration_s ? (
          <span className="tnum absolute bottom-2 right-2 rounded bg-[rgba(7,7,7,0.72)] px-1.5 py-0.5 text-[11px] text-fg2">
            {clock(video.duration_s, 0)}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-2 p-3">
        <span className="truncate text-[13px] font-semibold">{video.title}</span>
        <span className="truncate text-fg3">{[video.subject, video.topic].filter(Boolean).join(" · ") || "No subject yet"}</span>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <StatusPill status={video.display_status} job={busyJob} analyzed={!!video.analysis} compact />
          <span className="text-[11px] text-fg3">{shortDate(video.created_at)}</span>
        </div>
      </div>
    </Link>
  );
}

export default function LibraryPage() {
  const { data, error, isLoading, refetch } = useVideos();
  const [q, setQ] = useState("");

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = (data ?? [])
      .filter((v) => !needle || [v.title, v.subject, v.topic].join(" ").toLowerCase().includes(needle))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    const byTopic = new Map<string, Video[]>();
    for (const v of list) {
      const key = v.topic || "No topic";
      byTopic.set(key, [...(byTopic.get(key) ?? []), v]);
    }
    return [...byTopic.entries()];
  }, [data, q]);

  return (
    <div className="flex min-h-screen">
      <Rail section="library" />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
          <h1 className="font-head text-[16px]">Library</h1>
          <label className="relative ml-auto flex items-center">
            <span className="sr-only">Search videos</span>
            <Search aria-hidden="true" size={14} className="pointer-events-none absolute left-3 text-fg3" />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search title, subject or topic"
              className="min-h-11 w-[260px] rounded-[10px] border border-linestrong bg-surface pl-8 pr-3 text-[12px] text-fg placeholder:text-fg4"
            />
          </label>
          <Link
            href="/new"
            className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[22px] border border-accentfill bg-accentfill px-4 text-[12px] font-semibold text-onaccent"
          >
            <Plus aria-hidden="true" size={14} />
            Import video
          </Link>
        </header>

        <div className="flex flex-col gap-6 p-4">
          {error ? <ErrorCard title="Could not load the library" message={error.message} onRetry={() => void refetch()} /> : null}
          {isLoading ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3" aria-busy="true">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="ink-skeleton h-[220px] rounded-[12px]" />
              ))}
            </div>
          ) : null}
          {data && data.length === 0 ? (
            <div className="flex max-w-md flex-col items-start gap-3 rounded-[12px] border border-line2 bg-surface p-5">
              <span className="flex items-center gap-2 font-head text-[14px]">
                <Film aria-hidden="true" size={16} className="text-accentsoft" />
                No videos yet
              </span>
              <span className="text-fg2">Import a video from the import folder to start.</span>
              <Link
                href="/new"
                className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[22px] border border-accentfill bg-accentfill px-4 text-[12px] font-semibold text-onaccent"
              >
                <Plus aria-hidden="true" size={14} />
                Import video
              </Link>
            </div>
          ) : null}
          {data && data.length > 0 && groups.length === 0 ? <span className="text-fg3">No video matches “{q}”.</span> : null}
          {groups.map(([topic, videos]) => (
            <section key={topic} aria-label={topic} className="flex flex-col gap-3">
              <h2 className="text-[13px] font-semibold text-fg2">
                {topic} <span className="font-normal text-fg3">· {videos.length}</span>
              </h2>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
                {videos.map((v) => (
                  <VideoCard key={v.id} video={v} />
                ))}
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}
