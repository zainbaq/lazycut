"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { MotionConfig } from "motion/react";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      {/* "user": honour prefers-reduced-motion for every transform animation (9.5). */}
      <MotionConfig reducedMotion="user">
        <Tooltip.Provider delayDuration={300}>{children}</Tooltip.Provider>
      </MotionConfig>
    </QueryClientProvider>
  );
}
