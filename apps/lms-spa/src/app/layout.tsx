import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { AnalyticsBridge } from "@/components/shell/AnalyticsBridge";
import { Providers } from "@/components/shell/Providers";
import { analyticsConfig } from "@/lib/firebase/config";

/*
 * SPA override of apps/web/src/app/layout.tsx. <html lang="en-IN" data-theme="light">, the
 * viewport/theme metas, icons and the font preloads are static in index.html; globals.css is
 * imported by src/spa/main.tsx. The title template below is applied by src/spa/runtime.tsx.
 */
const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: "Tech Drona: placement preparation, courses, tests and coding practice.",
  applicationName: APP_NAME,
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light",
  themeColor: "#ffffff",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <a
        href="#main"
        className="sr-only z-skip-link rounded-md bg-brand px-4 py-2.5 font-display font-semibold text-brand-on no-underline focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:shadow-focus"
      >
        Skip to content
      </a>
      <Providers>{children}</Providers>
      {/* Firebase Analytics: loads only after analytics consent (null config = off). */}
      <AnalyticsBridge config={analyticsConfig()} />
    </>
  );
}
