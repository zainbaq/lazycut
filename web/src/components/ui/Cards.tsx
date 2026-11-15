"use client";

import { AlertTriangle, Check, Copy, KeyRound, RotateCcw, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { COPY_RESET_MS } from "@/lib/motion";
import type { ConfigError } from "@/lib/types";

export function CopyButton({ text, label = "Copy error" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), COPY_RESET_MS);
        } catch {
          // Clipboard refused (insecure origin); nothing else to do.
        }
      }}
      className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border px-3 text-[12px] transition-colors duration-200"
      style={{
        background: copied ? "var(--ok)" : "transparent",
        borderColor: copied ? "var(--ok)" : "var(--line-3)",
        color: copied ? "var(--on-ok)" : "var(--text)",
      }}
    >
      {copied ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
      {copied ? "Copied" : label}
    </button>
  );
}

/** Inline error card with Retry and Copy error (9.7). */
export function ErrorCard({
  title,
  message,
  onRetry,
  retrying,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <div role="alert" className="flex flex-col gap-2.5 rounded-[12px] border border-accent bg-surface p-3.5">
      <span className="flex items-center gap-1.5 text-[13px] font-semibold">
        <TriangleAlert aria-hidden="true" size={14} className="text-accentsoft" />
        {title}
      </span>
      <span className="whitespace-pre-wrap break-words text-fg2">{message}</span>
      <div className="flex flex-wrap gap-2">
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying}
            className="ink-btn flex min-h-11 items-center gap-1.5 rounded-[10px] border border-accentfill bg-accentfill px-3.5 text-[12px] font-semibold text-onaccent disabled:opacity-60"
          >
            <RotateCcw aria-hidden="true" size={14} />
            {retrying ? "Retrying…" : "Retry"}
          </button>
        ) : null}
        <CopyButton text={message} />
      </div>
    </div>
  );
}

/** No Gemini key: say exactly what to set (9.7). */
export function SetupCard() {
  return (
    <div className="flex flex-col gap-2 rounded-[12px] border border-warnline bg-surface p-3.5">
      <span className="flex items-center gap-1.5 text-[13px] font-semibold text-warn">
        <KeyRound aria-hidden="true" size={14} />
        Video analysis is off
      </span>
      <span className="text-fg2">
        Set <code className="rounded bg-surface2 px-1 py-0.5 text-fg">GEMINI_API_KEY</code> in{" "}
        <code className="rounded bg-surface2 px-1 py-0.5 text-fg">.env</code>, then restart with{" "}
        <code className="rounded bg-surface2 px-1 py-0.5 text-fg">docker compose up</code>. Playback, the filmstrip and
        intensity work without it.
      </span>
    </div>
  );
}

/** A YAML file that failed validation (9.7). */
export function ConfigErrorCard({ errors }: { errors: ConfigError[] }) {
  if (!errors.length) return null;
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-[12px] border border-warnline bg-surface p-3.5">
      <span className="flex items-center gap-1.5 text-[13px] font-semibold text-warn">
        <AlertTriangle aria-hidden="true" size={14} />
        Config problem
      </span>
      <ul className="flex flex-col gap-1.5">
        {errors.map((e) => (
          <li key={e.file} className="text-fg2">
            <code className="rounded bg-surface2 px-1 py-0.5 text-fg">config/{e.file}</code> {e.problem}
          </li>
        ))}
      </ul>
      <span className="text-fg3">The app runs on the built-in General preset until it is fixed.</span>
    </div>
  );
}
