"use client";

import { ArrowLeft, Settings } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorCard } from "@/components/ui/Cards";
import { Rail } from "@/components/ui/Rail";
import { ApiError } from "@/lib/api";
import { isActive, jobOf, useThumbnails, useVideo } from "@/lib/queries";
import { useVideoUpdates } from "@/lib/sse";

import { OptionsPanel, type Options, defaultOptions } from "./OptionsPanel";
import { Results } from "./Results";
import { type PickedSource, SourcePanel } from "./SourcePanel";

function Skeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading thumbnails">
      <span className="ink-skeleton block h-12 rounded-[12px]" />
      <div className="grid grid-cols-2 gap-2.5 min-[720px]:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <span key={i} className="ink-skeleton block aspect-[4/3] rounded-[10px]" />
        ))}
      </div>
      <span className="ink-skeleton block h-64 rounded-[12px]" />
    </div>
  );
}

/** `/v/[id]/thumbnail`: pick a source, set the word and options, generate on Higgsfield, check and choose (BUILD_SPEC 7.13). */
export function ThumbnailPage({ id }: { id: string }) {
  const video = useVideo(id);
  const thumbs = useThumbnails(id);
  useVideoUpdates(id, video.isSuccess);
  const [source, setSource] = useState<PickedSource | null>(null);
  const [opts, setOpts] = useState<Options | null>(null);

  const state = thumbs.data;
  // Start from the best frame found, and the settings' defaults, once they load.
  useEffect(() => {
    if (!state) return;
    if (!opts) setOpts(defaultOptions(state));
    if (!source && state.frames?.frames.length) setSource({ kind: "frame", t: state.frames.frames[0].t });
  }, [state, opts, source]);

  if (video.error) {
    const missing = video.error instanceof ApiError && video.error.status === 404;
    return (
      <div className="flex min-h-screen">
        <Rail section="thumbnail" />
        <main className="flex max-w-xl flex-1 flex-col gap-3 p-6">
          <ErrorCard
            title={missing ? "Video not found" : "Could not load the video"}
            message={missing ? "It may have been deleted." : video.error.message}
            onRetry={missing ? undefined : () => void video.refetch()}
          />
          <Link href="/" className="text-accentsoft underline">
            Back to the library
          </Link>
        </main>
      </div>
    );
  }

  const v = video.data;
  const framesJob = jobOf(v, "thumbnail_frames");
  const thumbJob = jobOf(v, "thumbnail");
  const failedFrames = framesJob?.status === "error" && !isActive(framesJob) ? framesJob : undefined;
  const failedThumbs = thumbJob?.status === "error" && !isActive(thumbJob) ? thumbJob : undefined;

  return (
    <div className="flex min-h-screen">
      <Rail section="thumbnail" videoId={id} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-raised px-[18px] py-2.5">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
            <Link href="/" className="py-3.5 text-fg">
              Library
            </Link>
            <span aria-hidden="true" className="text-fg4">
              /
            </span>
            <Link href={`/v/${id}`} className="truncate py-3.5 text-fg" title={v?.title}>
              {v ? [v.subject, v.topic].filter(Boolean).join(" · ") || v.title : "…"}
            </Link>
            <span aria-hidden="true" className="text-fg4">
              /
            </span>
            <span className="text-fg3">Thumbnail</span>
          </nav>
          <div className="ml-auto flex gap-2">
            <Link href="/settings" className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px]">
              <Settings aria-hidden="true" size={14} />
              Models
            </Link>
            <Link href={`/v/${id}`} className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-line3 px-3.5 text-[12px]">
              <ArrowLeft aria-hidden="true" size={14} />
              Workspace
            </Link>
          </div>
        </header>

        <main className="mx-auto flex w-full max-w-[1280px] flex-col gap-5 px-4 py-5 min-[720px]:px-6">
          <div className="flex flex-col gap-1">
            <h1 className="font-head text-[22px] leading-tight">
              Thumbnail
              {v?.subject ? <span className="text-fg3"> · {v.subject}</span> : null}
            </h1>
            <span className="text-fg3">
              Higgsfield repaints your frame without the HUD; LazyCut draws the word, sizes it for YouTube and has Claude check it.
            </span>
          </div>

          {failedFrames ? (
            <ErrorCard title="Finding frames failed" message={failedFrames.error || failedFrames.message || "The job stopped without a message."} />
          ) : null}
          {failedThumbs ? (
            <ErrorCard title="Thumbnails failed" message={failedThumbs.error || failedThumbs.message || "The job stopped without a message."} />
          ) : null}

          {thumbs.error ? (
            <ErrorCard title="Could not load thumbnails" message={thumbs.error.message} onRetry={() => void thumbs.refetch()} />
          ) : !v || !state || !opts ? (
            <Skeleton />
          ) : (
            <>
              <div className="grid grid-cols-1 gap-6 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(320px,400px)]">
                <SourcePanel video={v} state={state} source={source} onSource={setSource} />
                <OptionsPanel videoId={id} state={state} source={source} opts={opts} setOpts={setOpts} />
              </div>
              <Results state={state} videoId={id} />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
