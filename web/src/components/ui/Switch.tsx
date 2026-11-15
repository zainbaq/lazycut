"use client";

/** Ink switch (9.5): knob 3→17 px, 200 ms, track colour cross-fade. */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  disabled?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex min-h-11 items-center gap-2 bg-transparent text-[12px] text-fg2 disabled:opacity-50"
    >
      {children}
      <span
        aria-hidden="true"
        className="relative block h-5 w-[34px] shrink-0 rounded-[10px] transition-colors duration-200"
        style={{ background: checked ? "var(--accent-fill)" : "var(--line-3)" }}
      >
        <span
          className="absolute top-[3px] block h-3.5 w-3.5 rounded-full bg-fg transition-[left] duration-200"
          style={{ left: checked ? 17 : 3, transitionTimingFunction: "var(--ease-out-ink)" }}
        />
      </span>
    </button>
  );
}
