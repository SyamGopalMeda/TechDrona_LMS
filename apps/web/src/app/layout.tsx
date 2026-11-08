import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";
import { preload } from "react-dom";
import { Providers } from "@/components/shell/Providers";
import "./globals.css";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: "Tech Drona: placement preparation, courses, tests and coding practice.",
  applicationName: APP_NAME,
  // Official icons copied from the Tech Drona website build (tech drona/dist): archer mark on white.
  icons: {
    icon: [{ url: "/favicon-32.png", sizes: "32x32", type: "image/png" }, { url: "/icon-512.png", sizes: "512x512", type: "image/png" }],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#10141c" },
  ],
};

/* Self-hosted brand fonts (src/styles/fonts.css); preload the latin subsets used on every page. */
const FONT_PRELOADS = ["/fonts/plus-jakarta-sans-latin.woff2", "/fonts/inter-latin.woff2"];

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Middleware sets a per-request CSP nonce. Reading request headers makes every page render
  // dynamically, which lets Next.js attach that nonce to its own scripts (static HTML could
  // not carry a per-request nonce and would be blocked by 'strict-dynamic').
  await headers();
  for (const href of FONT_PRELOADS) preload(href, { as: "font", type: "font/woff2", crossOrigin: "anonymous" });
  return (
    <html lang="en-IN">
      <body>
        <a
          href="#main"
          className="sr-only z-skip-link rounded-md bg-brand px-4 py-2.5 font-display font-semibold text-brand-on no-underline focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:shadow-focus"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
