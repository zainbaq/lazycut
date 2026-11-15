"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { ChartLine, Clapperboard, Image as ImageIcon, LayoutGrid, Scissors, Search, Settings, Upload } from "lucide-react";
import Link from "next/link";

type Section = "library" | "new" | "workspace" | "research";

interface Item {
  id: string;
  label: string;
  icon: typeof LayoutGrid;
  href?: string;
  disabled?: string;
}

function LogoMark() {
  return (
    <div aria-hidden="true" className="mb-3.5 flex h-[34px] w-[34px] items-center justify-center rounded-[10px] bg-accentfill">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--on-accent)" strokeWidth="3.5" strokeLinecap="round">
        <path d="M5 19 19 5" />
        <path d="M5 11 11 5" strokeOpacity="0.55" />
      </svg>
    </div>
  );
}

function RailButton({ item, active }: { item: Item; active: boolean }) {
  const Icon = item.icon;
  const cls =
    "ink-btn flex h-11 w-11 items-center justify-center rounded-[10px] border " +
    (active ? "border-accent bg-surface2 text-fg" : "border-transparent text-fg3") +
    (item.disabled ? " opacity-50" : "");
  const inner = <Icon aria-hidden="true" size={18} strokeWidth={2} />;
  const trigger =
    item.href && !item.disabled ? (
      <Link href={item.href} aria-label={item.label} aria-current={active ? "page" : undefined} className={cls}>
        {inner}
      </Link>
    ) : (
      <button type="button" aria-label={item.disabled ? `${item.label} (${item.disabled})` : item.label} aria-disabled={item.disabled ? true : undefined} aria-current={active ? "page" : undefined} className={cls}>
        {inner}
      </button>
    );
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{trigger}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="right" sideOffset={8} className="z-50 rounded-md border border-line2 bg-surface px-2 py-1 text-[11px] text-fg2">
          {item.label}
          {item.disabled ? <span className="text-fg4"> · {item.disabled}</span> : null}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

/** The 60 px icon rail (9.4 region 1). Routes that arrive later show as disabled. */
export function Rail({ section, videoId }: { section: Section; videoId?: string }) {
  const items: Item[] = [
    { id: "library", label: "Library", icon: LayoutGrid, href: "/" },
    { id: "new", label: "Import video", icon: Upload, href: "/new" },
    { id: "workspace", label: "Workspace", icon: Scissors, href: videoId ? `/v/${videoId}` : undefined, disabled: videoId ? undefined : "open a video" },
    { id: "research", label: "Research", icon: Search, href: videoId ? `/v/${videoId}/research` : undefined, disabled: videoId ? undefined : "open a video" },
    { id: "thumbnail", label: "Thumbnail", icon: ImageIcon, disabled: "arrives later" },
    { id: "past", label: "Past uploads", icon: Clapperboard, disabled: "arrives later" },
  ];
  return (
    <nav aria-label="Sections" className="sticky top-0 flex h-screen w-[60px] shrink-0 flex-col items-center gap-2 border-r border-line bg-raised py-3.5">
      <Link href="/" aria-label="LazyCut library">
        <LogoMark />
      </Link>
      {items.map((item) => (
        <RailButton key={item.id} item={item} active={item.id === section} />
      ))}
      <div className="mt-auto flex flex-col items-center gap-2">
        <RailButton item={{ id: "perf", label: "Performance", icon: ChartLine, disabled: "Phase 4" }} active={false} />
        <RailButton item={{ id: "settings", label: "Settings", icon: Settings, disabled: "arrives later" }} active={false} />
      </div>
    </nav>
  );
}
