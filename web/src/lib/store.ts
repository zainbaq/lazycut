// Workspace UI state (playhead, zoom, selection, type filter). Server state lives in TanStack Query.

import { create } from "zustand";

interface WorkspaceState {
  videoId: string | null;
  /** The preview's <video>; seeking goes through it so the picture follows the playhead. */
  videoEl: HTMLVideoElement | null;
  playhead: number;
  playing: boolean;
  /** True briefly after a click-seek, so the playhead animates instead of jumping. */
  seeking: boolean;
  zoom: number;
  selectedEventId: string | null;
  /** Event types switched off in the timeline filter. */
  hiddenTypes: Record<string, boolean>;
  filterReady: boolean;
  /** Show hidden events on the timeline (dimmed) so they can be unhidden. */
  showHidden: boolean;
  crop916: boolean;
  /** Review mode (the eye test, 9.4): the events to step through, fixed when it starts. */
  review: { ids: string[]; index: number; halfSpeed: boolean } | null;
  /** Event whose label is being renamed. */
  renamingId: string | null;

  reset: (videoId: string) => void;
  setShowHidden: (on: boolean) => void;
  startReview: (ids: string[]) => void;
  reviewGo: (index: number) => void;
  setHalfSpeed: (on: boolean) => void;
  stopReview: () => void;
  setRenaming: (id: string | null) => void;
  setVideoEl: (el: HTMLVideoElement | null) => void;
  setPlayhead: (t: number) => void;
  setPlaying: (playing: boolean) => void;
  seek: (t: number, opts?: { animate?: boolean }) => void;
  togglePlay: () => void;
  pause: () => void;
  setZoom: (zoom: number) => void;
  select: (id: string | null) => void;
  initFilter: (hidden: Record<string, boolean>) => void;
  toggleType: (type: string) => void;
  setCrop916: (on: boolean) => void;
}

let seekTimer: ReturnType<typeof setTimeout> | undefined;

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  videoId: null,
  videoEl: null,
  playhead: 0,
  playing: false,
  seeking: false,
  zoom: 1,
  selectedEventId: null,
  hiddenTypes: {},
  filterReady: false,
  showHidden: false,
  crop916: false,
  review: null,
  renamingId: null,

  reset: (videoId) =>
    set({
      videoId,
      playhead: 0,
      playing: false,
      seeking: false,
      zoom: 1,
      selectedEventId: null,
      hiddenTypes: {},
      filterReady: false,
      showHidden: false,
      crop916: false,
      review: null,
      renamingId: null,
    }),
  setShowHidden: (showHidden) => set({ showHidden }),
  startReview: (ids) => set({ review: { ids, index: 0, halfSpeed: get().review?.halfSpeed ?? false } }),
  reviewGo: (index) =>
    set((s) => (s.review ? { review: { ...s.review, index: Math.max(0, Math.min(index, s.review.ids.length)) } } : {})),
  setHalfSpeed: (halfSpeed) => set((s) => (s.review ? { review: { ...s.review, halfSpeed } } : {})),
  stopReview: () => {
    const el = get().videoEl;
    if (el) el.playbackRate = 1;
    set({ review: null });
  },
  setRenaming: (renamingId) => set({ renamingId }),
  setVideoEl: (videoEl) => set({ videoEl }),
  setPlayhead: (playhead) => set({ playhead }),
  setPlaying: (playing) => set({ playing }),
  seek: (t, opts) => {
    const el = get().videoEl;
    const max = el && Number.isFinite(el.duration) ? el.duration : Number.POSITIVE_INFINITY;
    const target = Math.max(0, Math.min(t, max));
    if (el) el.currentTime = target;
    clearTimeout(seekTimer);
    const animate = opts?.animate ?? true;
    set({ playhead: target, seeking: animate });
    if (animate) seekTimer = setTimeout(() => set({ seeking: false }), 260);
  },
  togglePlay: () => {
    const el = get().videoEl;
    if (!el) return;
    if (el.paused) void el.play().catch(() => undefined);
    else el.pause();
  },
  pause: () => get().videoEl?.pause(),
  setZoom: (zoom) => set({ zoom }),
  select: (selectedEventId) => set({ selectedEventId }),
  initFilter: (hiddenTypes) => set({ hiddenTypes, filterReady: true }),
  toggleType: (type) => set((s) => ({ hiddenTypes: { ...s.hiddenTypes, [type]: !s.hiddenTypes[type] } })),
  setCrop916: (crop916) => set({ crop916 }),
}));
