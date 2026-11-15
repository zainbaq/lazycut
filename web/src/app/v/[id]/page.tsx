"use client";

import { useParams } from "next/navigation";

import { Workspace } from "@/components/workspace/Workspace";

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  return <Workspace id={id} />;
}
