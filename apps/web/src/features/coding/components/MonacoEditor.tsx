"use client";

import Editor, { loader } from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";

/**
 * Monaco is self-hosted from /vendor/monaco/vs (copied from node_modules by
 * scripts/copy-monaco.mjs at dev/build time): the CSP allows only same-origin scripts,
 * styles, fonts and connections, so the default CDN loader would be blocked.
 */
loader.config({ paths: { vs: "/vendor/monaco/vs" } });

export interface MonacoEditorProps {
  value: string;
  language: string;
  onChange: (v: string) => void;
  fontSize: number;
  theme: "light" | "dark";
  ariaLabel: string;
  onRun?: () => void;
  onSubmit?: () => void;
  height?: string;
  /** Editor text focus changes (analytics coding.editor_focus/blur). */
  onFocus?: () => void;
  onBlur?: () => void;
}

export default function MonacoEditor({ value, language, onChange, fontSize, theme, ariaLabel, onRun, onSubmit, height = "100%", onFocus, onBlur }: MonacoEditorProps) {
  const focusRef = useRef({ onFocus, onBlur });
  focusRef.current = { onFocus, onBlur };
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    loader.init().catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  if (failed) {
    // Accessible fallback if the editor bundle cannot load (blocked network, old browser).
    return (
      <textarea
        aria-label={ariaLabel}
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={onFocus}
        onBlur={onBlur}
        className="h-full min-h-80 w-full resize-none bg-surface-sunken p-3 font-mono text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none"
        style={{ fontSize }}
      />
    );
  }

  return (
    <Editor
      height={height}
      language={language}
      value={value}
      theme={theme === "dark" ? "vs-dark" : "vs"}
      onChange={(v) => onChange(v ?? "")}
      options={{
        fontSize,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        automaticLayout: true,
        ariaLabel,
        tabSize: 4,
        accessibilitySupport: "auto",
      }}
      onMount={(editor, monaco) => {
        if (onRun) editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, onRun);
        if (onSubmit) editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter, onSubmit);
        editor.onDidFocusEditorText(() => focusRef.current.onFocus?.());
        editor.onDidBlurEditorText(() => focusRef.current.onBlur?.());
      }}
      loading={<div className="p-4 text-sm text-fg-muted">Loading editor…</div>}
    />
  );
}
