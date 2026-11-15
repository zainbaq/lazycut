"use client";

import { AlertTriangle, KeyRound, Loader2, Maximize2, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";

import { Switch } from "@/components/ui/Switch";
import { isActive, jobOf, useEditPackage, useGeneratePackage, usePackages, useRegeneratePackage, useVideo } from "@/lib/queries";
import type { Video } from "@/lib/types";

import { PackageDrawer } from "./PackageDrawer";
import { RuleBadges } from "./RuleBadges";
import { TitleDeck } from "./TitleDeck";

const btn = "ink-btn flex min-h-11 items-center justify-center gap-1.5 rounded-[10px] border px-3 text-[12px] disabled:opacity-50";

const SHORT_FORM = ["Shorts", "Instagram Reels", "TikTok"];

/** Platforms, Generate, the title deck, rule badges and the stale state (9.4 region 7, Phase 1 long-form flow). */
export function PackageSection({ video }: { video: Video }) {
  const ready = video.status === "ready";
  const list = usePackages(video.id, ready);
  const live = useVideo(video.id);
  const generate = useGeneratePackage(video.id);
  const regenerate = useRegeneratePackage(video.id);
  const edit = useEditPackage(video.id);
  const [youtube, setYoutube] = useState(true);
  const [drawer, setDrawer] = useState(false);

  const job = jobOf(live.data ?? video, "package");
  const data = list.data;
  const pkg = data?.packages.find((p) => p.platform === "youtube");
  const running = !!data?.running || isActive(job);
  const message = (isActive(job) && job?.message) || "Writing the package…";

  let reason: string | null = null;
  if (!ready) reason = "Waiting for the import";
  else if (data && !data.can_write) reason = "Needs ANTHROPIC_API_KEY in .env";
  else if (data && data.missing_facts.length) reason = `Confirm ${data.missing_facts.join(", ")} first`;
  else if (!youtube) reason = "Switch on a platform";
  else if (running) reason = "A package is being written";

  const dismiss = (key: string, on: boolean) => {
    if (pkg) edit.mutate({ id: pkg.id, body: on ? { dismiss: key } : { undismiss: key } });
  };
  const error = generate.error ?? regenerate.error ?? edit.error;

  return (
    <div className="flex flex-col gap-3">
      <fieldset className="flex flex-col">
        <legend className="mb-0.5 text-[11px] font-semibold text-fg3">Platforms</legend>
        <Switch checked={youtube} onChange={setYoutube} label="YouTube long-form" className="w-full">
          <span className="mr-auto text-fg">YouTube long-form</span>
        </Switch>
        {SHORT_FORM.map((name) => (
          <Switch key={name} checked={false} onChange={() => undefined} disabled label={`${name}: comes with clips`} className="w-full">
            <span className="mr-auto text-fg3">
              {name} <span className="text-[11px] text-fg4">· comes with clips</span>
            </span>
          </Switch>
        ))}
      </fieldset>

      {list.isLoading ? (
        <span className="ink-skeleton block h-24 rounded-[10px]" aria-busy="true" />
      ) : list.error ? (
        <span role="alert" className="text-fg2">
          Could not load the package: {list.error.message}
        </span>
      ) : null}

      {running ? (
        <div role="status" className="relative flex items-center gap-2 overflow-hidden rounded-[10px] bg-surface2 px-3 py-2.5 text-fg2">
          <Loader2 aria-hidden="true" size={13} className="shrink-0 animate-spin text-accentsoft" />
          <span className="truncate">{message}</span>
          <span aria-hidden="true" className="absolute bottom-0 left-0 h-[2px] w-full bg-line2">
            <span className="ink-busy-bar block h-full bg-accent" />
          </span>
        </div>
      ) : null}

      {data && !pkg && !running ? (
        <div className="flex flex-col gap-1.5">
          <button
            type="button"
            disabled={!!reason || generate.isPending}
            onClick={() => generate.mutate()}
            className={`${btn} border-accentfill bg-accentfill font-semibold text-onaccent`}
          >
            {generate.isPending ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Sparkles aria-hidden="true" size={14} />}
            Generate package
          </button>
          <span className="flex items-start gap-1 text-[11px] text-fg3">
            {data.can_write ? null : <KeyRound aria-hidden="true" size={11} className="mt-[2px] shrink-0 text-warn" />}
            {reason ?? "One Claude call writes the title deck, description, tags and the rest; code checks every claim."}
          </span>
        </div>
      ) : null}

      {pkg ? (
        <>
          {pkg.stale ? (
            <div role="status" className="flex flex-wrap items-center gap-2 rounded-[10px] border border-warnline px-2.5 py-1.5 text-[11.5px] text-fg2">
              <AlertTriangle aria-hidden="true" size={13} className="shrink-0 text-warn" />
              <span>Out of date</span>
              <button
                type="button"
                disabled={!!reason || regenerate.isPending}
                title={reason ?? "Write the package again (one Claude call); your edits are kept"}
                onClick={() => regenerate.mutate({ id: pkg.id, body: { all: true, replace_edits: false } })}
                className="ink-btn ml-auto flex min-h-9 items-center gap-1 rounded-[8px] px-2 font-semibold text-fg disabled:opacity-50"
              >
                <RefreshCw aria-hidden="true" size={12} />
                Regenerate
              </button>
            </div>
          ) : null}
          <TitleDeck pkg={pkg} busy={edit.isPending || running} onUseTitle={(text) => edit.mutate({ id: pkg.id, body: { field: "title", value: text } })} />
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold text-fg3">Rules</span>
            <RuleBadges pkg={pkg} onDismiss={dismiss} busy={edit.isPending} />
          </div>
          <button type="button" onClick={() => setDrawer(true)} className={`${btn} border-line3`}>
            <Maximize2 aria-hidden="true" size={13} />
            Open full package
          </button>
          <PackageDrawer open={drawer} onOpenChange={setDrawer} pkg={pkg} video={live.data ?? video} running={running} />
        </>
      ) : null}

      {error ? (
        <span role="alert" className="rounded-[8px] border border-accent px-2 py-1.5 text-fg">
          {error.message}
        </span>
      ) : null}
    </div>
  );
}
