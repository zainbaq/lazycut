import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";

import "./globals.css";
import { Providers } from "./providers";

const body = Inter({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-body-family" });
const head = Fraunces({ subsets: ["latin"], weight: ["700"], variable: "--font-head-family" });

export const metadata: Metadata = {
  title: "LazyCut",
  description: "Turn one video into a rule-checked publishing package.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${body.variable} ${head.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
