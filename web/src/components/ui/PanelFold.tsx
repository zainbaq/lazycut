"use client";

import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";

import { type PanelName, useWorkspace } from "@/lib/store";

// Each panel sits beside the main column from its own width up; below it the panel stacks, and its strip is a row.
const LAYOUT: Record<PanelName, { clip: string; panel: string; open: string; folded: string; body: string; strip: string; label: string }> = {
  clips: {
    clip: "min-[720px]:overflow-x-clip",
    panel: "min-[720px]:transition-[width] min-[720px]:duration-200 min-[720px]:ease-out motion-reduce:transition-none",
    open: "min-[720px]:w-[260px]",
    folded: "min-[720px]:w-[52px]",
    body: "min-[720px]:w-[260px]",
    strip: "min-[720px]:flex-col min-[720px]:gap-2.5 min-[720px]:px-0 min-[720px]:py-3.5",
    label: "min-[720px]:[writing-mode:vertical-rl]",
  },
  package: {
    clip: "min-[1100px]:overflow-x-clip",
    panel: "min-[1100px]:transition-[width] min-[1100px]:duration-200 min-[1100px]:ease-out motion-reduce:transition-none",
    open: "min-[1100px]:w-[300px]",
    folded: "min-[1100px]:w-[52px]",
    body: "min-[1100px]:w-[300px]",
    strip: "min-[1100px]:flex-col min-[1100px]:gap-2.5 min-[1100px]:px-0 min-[1100px]:py-3.5",
    label: "min-[1100px]:[writing-mode:vertical-rl]",
  },
};

/**
 * Fold state of one side panel, with the classes that size it. `panel` goes on the panel itself and
 * `body` on its content, which keeps its full width so it is revealed, not squeezed, while the panel
 * animates. Toggling moves focus to the button that undoes it.
 */
export function usePanelFold(panel: PanelName) {
  const folded = useWorkspace((s) => s.folded[panel]);
  // No width animation until the saved state is in, so a folded panel does not visibly fold on load.
  const animate = useWorkspace((s) => s.panelsAnimate);
  const at = LAYOUT[panel];
  const toggle = () => {
    useWorkspace.getState().togglePanel(panel);
    // After React has swapped the buttons: focus the one that is shown now (the other is display: none).
    setTimeout(() => {
      const shown = Array.from(document.querySelectorAll<HTMLElement>(`[data-panel-toggle="${panel}"]`)).find((b) => b.offsetParent !== null);
      shown?.focus();
    }, 0);
  };
  return { folded, toggle, panelClass: `${at.clip} ${animate ? at.panel : ""} ${folded ? at.folded : at.open}`, bodyClass: at.body };
}

/** The button in an open panel's header that folds it away. */
export function FoldButton({ panel, label, onFold }: { panel: PanelName; label: string; onFold: () => void }) {
  const Icon = panel === "clips" ? PanelLeftClose : PanelRightClose;
  return (
    <button
      type="button"
      data-panel-toggle={panel}
      aria-expanded={true}
      aria-label={`Hide the ${label} panel`}
      title={`Hide the ${label} panel`}
      onClick={onFold}
      className="ink-btn flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] text-fg3"
    >
      <Icon aria-hidden="true" size={15} />
    </button>
  );
}

/** What a folded panel leaves behind: one button that opens it again, with what is worth knowing meanwhile. */
export function PanelStrip({
  panel,
  label,
  title,
  count,
  dot,
  onOpen,
}: {
  panel: PanelName;
  label: string;
  title: string;
  count?: number;
  /** Something in the folded panel wants a look; the text is read out with the button's name. */
  dot?: { tone: "accent" | "warn"; text: string } | null;
  onOpen: () => void;
}) {
  const Icon = panel === "clips" ? PanelLeftOpen : PanelRightOpen;
  const at = LAYOUT[panel];
  return (
    <div className="p-1">
      <button
        type="button"
        data-panel-toggle={panel}
        aria-expanded={false}
        aria-label={`Show the ${label} panel${count ? `, ${count}` : ""}${dot ? `, ${dot.text}` : ""}`}
        title={dot ? `Show the ${label} panel · ${dot.text}` : `Show the ${label} panel`}
        onClick={onOpen}
        className={`ink-btn flex min-h-11 w-full items-center gap-2 rounded-[10px] px-3 ${at.strip}`}
      >
        <Icon aria-hidden="true" size={15} className="shrink-0 text-fg3" />
        <span className={`font-head text-[14px] text-fg ${at.label}`}>{title}</span>
        {count ? <span className="tnum text-[11px] text-fg3">{count}</span> : null}
        {dot ? (
          <span
            aria-hidden="true"
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot.tone === "warn" ? "bg-warn" : "animate-pulse bg-accent"}`}
          />
        ) : null}
      </button>
    </div>
  );
}
