"use client";

import { useParams } from "next/navigation";

import { ResearchPage } from "@/components/research/ResearchPage";

export default function VideoResearchPage() {
  const { id } = useParams<{ id: string }>();
  return <ResearchPage id={id} />;
}
