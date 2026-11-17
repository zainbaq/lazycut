"use client";

import { useParams } from "next/navigation";

import { PresetsPage } from "@/components/presets/PresetsPage";

export default function PresetEditorPage() {
  const { id } = useParams<{ id: string }>();
  return <PresetsPage id={id} />;
}
