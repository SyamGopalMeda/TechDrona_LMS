"use client";

import dynamic from "next/dynamic";
import type { MonacoEditorProps } from "./MonacoEditor";

/** Lazy-loaded Monaco (keeps the editor out of every other route's JS). */
export const CodeEditor = dynamic<MonacoEditorProps>(() => import("./MonacoEditor"), {
  ssr: false,
  loading: () => (
    <div aria-busy="true" className="flex h-full min-h-80 items-center justify-center bg-surface-sunken text-sm text-fg-muted">
      Loading editor…
    </div>
  ),
});
