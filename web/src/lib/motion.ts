// Shared motion presets (BUILD_SPEC 9.5). Durations in seconds for the `motion` package.

export const easeOutInk = [0.2, 0.8, 0.2, 1] as const;
export const EASE_OUT_INK_CSS = "cubic-bezier(.2,.8,.2,1)";

/** Event chips as analysis results arrive: scale 0.9→1 + fade, 260 ms, 60 ms stagger in time order. */
export const markIn = {
  initial: { opacity: 0, scale: 0.9 },
  animate: { opacity: 1, scale: 1 },
  duration: 0.26,
  stagger: 0.06,
  /** Long timelines would otherwise wait seconds for the last chip. */
  maxDelay: 1.5,
};

/** Clip bracket, scrubber, thumbnail bar: left/width, 320 ms. */
export const rangeMove = { duration: 0.32, ease: easeOutInk };

/** Playhead seek on click or event jump: left, 240 ms. */
export const playheadSeek = { duration: 0.24, ease: easeOutInk };
export const PLAYHEAD_SEEK_CSS = `left 240ms ${EASE_OUT_INK_CSS}`;

/** Section open, drawers, popovers: translateY 8→0 + fade, 200–260 ms. */
export const panelRise = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 8 },
  transition: { duration: 0.22, ease: easeOutInk },
};

/** Fact confirmed, event verified. */
export const stamp = {
  initial: { scale: 2.2, rotate: -18, opacity: 0 },
  animate: { scale: [2.2, 0.92, 1], rotate: [-18, -8, -6], opacity: 1 },
  transition: { duration: 0.42, ease: easeOutInk },
};

/** Toggles: knob left 3→17 px, 200 ms. */
export const switchKnob = { duration: 0.2, ease: easeOutInk };

/** Running job pill: thin bar oscillating 8%↔78% width, 2.2 s loop (CSS class `ink-busy-bar`). */
export const busy = { duration: 2.2 };

/** Copy buttons revert after this long. */
export const COPY_RESET_MS = 1600;

/** 9:16 crop switch: stage width animates 320 ms. */
export const crop = { duration: 0.32, ease: easeOutInk };

/** With reduced motion, movement becomes a plain fade. */
export function fadeOnly(reduced: boolean | null) {
  return reduced
    ? { initial: { opacity: 0 }, animate: { opacity: 1 } }
    : { initial: markIn.initial, animate: markIn.animate };
}
