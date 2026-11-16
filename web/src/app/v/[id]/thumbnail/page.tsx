"use client";

import { useParams } from "next/navigation";

import { ThumbnailPage } from "@/components/thumbnail/ThumbnailPage";

export default function VideoThumbnailPage() {
  const { id } = useParams<{ id: string }>();
  return <ThumbnailPage id={id} />;
}
