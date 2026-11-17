"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import { keys, useCreateClip, useDeleteClip, useUpdateClip } from "@/lib/queries";
import { useWorkspace } from "@/lib/store";
import type { Clip, ClipList, ClipPatch } from "@/lib/types";

import { type Edge, moveEdge, nearestEdge, newRange, nudgeEdge, type Range, sameRange, SNAP_S } from "./trim";

/** Show the frame an edge sits on: the first frame of the clip, or its last one. */
function showEdge(range: Range, edge: Edge) {
  const ws = useWorkspace.getState();
  ws.pause();
  ws.seek(edge === "in" ? range.t_start : Math.max(range.t_start, range.t_end - 0.04), { animate: false });
}

export interface ClipActions {
  clips: () => Clip[];
  selected: () => Clip | undefined;
  /** Select a clip and show its first frame; null goes back to the whole video. */
  select: (id: string | null) => void;
  selectIndex: (index: number) => void;
  /** Store a dragged or typed range. */
  commit: (id: string, range: Range, show?: Edge) => void;
  nudge: (edge: Edge, delta: number) => void;
  /** `[` and `]`: move the edge nearest the playhead. */
  nudgeNearest: (delta: number) => void;
  /** `I` and `O`: put that edge of the selected clip at the playhead, or start a new clip there. */
  mark: (edge: Edge) => void;
  patch: (id: string, body: ClipPatch) => void;
  remove: (id: string) => void;
  error: string | null;
  busy: boolean;
}

/** Everything the clips panel, the bracket, the action bar and the keys do to clips. */
export function useClipActions(videoId: string, duration: number): ClipActions {
  const qc = useQueryClient();
  const update = useUpdateClip(videoId);
  const create = useCreateClip(videoId);
  const del = useDeleteClip(videoId);
  const { mutate: updateClip } = update;
  const { mutate: createClip } = create;
  const { mutate: deleteClip } = del;
  const error = update.error?.message ?? create.error?.message ?? del.error?.message ?? null;
  const busy = create.isPending;

  return useMemo(() => {
    const clips = () => qc.getQueryData<ClipList>(keys.clips(videoId))?.clips ?? [];
    const selected = () => {
      const id = useWorkspace.getState().selectedClipId;
      return id ? clips().find((c) => c.id === id) : undefined;
    };
    const select = (id: string | null) => {
      const ws = useWorkspace.getState();
      ws.selectClip(id);
      const clip = id ? clips().find((c) => c.id === id) : undefined;
      if (clip) {
        ws.pause();
        ws.seek(clip.t_start);
      }
    };
    const commit = (id: string, range: Range, show?: Edge) => {
      const clip = clips().find((c) => c.id === id);
      const ws = useWorkspace.getState();
      if (!clip || sameRange(clip, range)) {
        if (ws.clipDraft?.id === id) ws.setClipDraft(null);
        return;
      }
      if (show) showEdge(range, show);
      updateClip(
        { id, body: { t_start: range.t_start, t_end: range.t_end } },
        {
          // The draft covers the gap until the list holds the new edges.
          onSettled: () => {
            const draft = useWorkspace.getState().clipDraft;
            if (draft?.id === id && sameRange(draft, range)) useWorkspace.getState().setClipDraft(null);
          },
        },
      );
    };
    const nudge = (edge: Edge, delta: number) => {
      const clip = selected();
      if (clip) commit(clip.id, nudgeEdge(clip, edge, delta, duration), edge);
    };
    return {
      clips,
      selected,
      select,
      selectIndex: (index) => {
        const clip = clips()[index];
        if (clip) select(clip.id);
      },
      commit,
      nudge,
      nudgeNearest: (delta) => {
        const clip = selected();
        if (clip) nudge(nearestEdge(clip, useWorkspace.getState().playhead), delta);
      },
      mark: (edge) => {
        const playhead = useWorkspace.getState().playhead;
        const clip = selected();
        if (clip) {
          commit(clip.id, moveEdge(clip, edge, Math.round(playhead * 1000) / 1000, duration), edge);
          return;
        }
        if (duration < 3) return;
        const range = newRange(Math.round(playhead / SNAP_S) * SNAP_S, duration, edge);
        createClip(range, { onSuccess: (made) => useWorkspace.getState().selectClip(made.id) });
      },
      patch: (id, body) => updateClip({ id, body }),
      remove: (id) => {
        if (useWorkspace.getState().selectedClipId === id) useWorkspace.getState().selectClip(null);
        deleteClip(id);
      },
      error,
      busy,
    };
  }, [qc, videoId, duration, updateClip, createClip, deleteClip, error, busy]);
}
