"use client";

import { useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";
import { CALLOUT_TITLES, parseArticle, parseInline, tocOf, type Block, type CalloutKind } from "../lib/markdown";
import type { TocEntry } from "../lib/types";

/**
 * Renders an authored article (see lib/markdown.ts) with React elements only — no HTML strings,
 * so any markup in the source shows as text. The api sanitises the Markdown on save as well.
 */

export function Inline({ text }: { text: string }) {
  const parts = parseInline(text);
  return (
    <>
      {parts.map((p, i) => {
        switch (p.t) {
          case "strong":
            return <strong key={i}>{p.v}</strong>;
          case "em":
            return <em key={i}>{p.v}</em>;
          case "code":
            return (
              <code key={i} className="rounded bg-surface-sunken px-1 font-mono text-[0.9em]">
                {p.v}
              </code>
            );
          case "link":
            return (
              <a
                key={i}
                href={p.href}
                className="text-fg-link underline"
                {...(p.href.startsWith("https://") ? { target: "_blank", rel: "noopener noreferrer" } : {})}
              >
                {p.v}
              </a>
            );
          default:
            return <span key={i}>{p.v}</span>;
        }
      })}
    </>
  );
}

function Lines({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((l, i) => (
        <span key={i}>
          {i ? <br /> : null}
          <Inline text={l} />
        </span>
      ))}
    </>
  );
}

function CodeBlock({ lang, code, output }: { lang: string; code: string; output: string | null }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <figure className="my-4 overflow-hidden rounded-lg border border-line">
      <div className="flex items-center justify-between bg-surface-sunken px-3 py-1.5 text-xs text-fg-muted">
        <span className="font-mono">{lang || "code"}</span>
        <button type="button" onClick={() => void copy()} className="rounded px-2 py-0.5 font-medium text-fg hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none" aria-label="Copy code">
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto bg-surface p-3 font-mono text-sm leading-relaxed text-fg">
        <code>{code}</code>
      </pre>
      {output !== null ? (
        <div className="border-t border-line bg-surface-sunken">
          <p className="px-3 pt-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">Output</p>
          <pre className="overflow-x-auto px-3 pb-3 pt-1 font-mono text-sm text-fg-secondary">{output}</pre>
        </div>
      ) : null}
    </figure>
  );
}

const CALLOUT_STYLE: Record<CalloutKind, { box: string; icon: string }> = {
  "key-idea": { box: "border-info-border bg-info-subtle", icon: "🔑" },
  "watch-out": { box: "border-warning-border bg-warning-subtle", icon: "⚠" },
  note: { box: "border-line-strong bg-surface-sunken", icon: "ℹ" },
  tip: { box: "border-success-border bg-success-subtle", icon: "💡" },
};

function Callout({ kind, children }: { kind: CalloutKind; children: ReactNode }) {
  const s = CALLOUT_STYLE[kind];
  return (
    <aside className={cn("my-4 rounded-lg border-l-4 border p-4", s.box)} data-callout={kind} aria-label={CALLOUT_TITLES[kind]}>
      <p className="mb-1 flex items-center gap-2 text-sm font-semibold text-fg">
        <span aria-hidden="true">{s.icon}</span>
        {CALLOUT_TITLES[kind]}
      </p>
      <div className="text-sm text-fg-secondary">{children}</div>
    </aside>
  );
}

function Exercise({ title, body, answer }: { title: string; body: Block[]; answer: Block[] }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="my-4 rounded-lg border border-line bg-surface p-4" aria-label={`Exercise: ${title}`}>
      <p className="font-semibold text-fg">{title}</p>
      <Blocks blocks={body} />
      {answer.length ? (
        <>
          <button
            type="button"
            className="mt-2 text-sm font-medium text-fg-link underline focus-visible:shadow-focus focus-visible:outline-none"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide answer" : "Show answer"}
          </button>
          {open ? (
            <div className="mt-2 rounded-md bg-surface-sunken p-3">
              <Blocks blocks={answer} />
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => {
        switch (b.type) {
          case "heading": {
            const cls = b.level === 1 ? "mt-6 text-2xl" : b.level === 2 ? "mt-8 text-xl" : "mt-6 text-lg";
            const Tag = b.level === 1 ? "h2" : b.level === 2 ? "h3" : "h4";
            return (
              <Tag key={i} id={b.id} className={cn("scroll-mt-20 font-display font-semibold text-fg", cls)}>
                <Inline text={b.text} />
              </Tag>
            );
          }
          case "code":
            return <CodeBlock key={i} lang={b.lang} code={b.code} output={b.output} />;
          case "callout":
            return (
              <Callout key={i} kind={b.kind}>
                <Blocks blocks={b.blocks} />
              </Callout>
            );
          case "exercise":
            return <Exercise key={i} title={b.title} body={b.body} answer={b.answer} />;
          case "table":
            return (
              <div key={i} className="my-4 overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead>
                    <tr>
                      {b.header.map((h, j) => (
                        <th key={j} scope="col" className="border border-line bg-surface-sunken px-3 py-2 text-left font-semibold" style={b.align[j] ? { textAlign: b.align[j]! } : undefined}>
                          <Inline text={h} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, ri) => (
                      <tr key={ri}>
                        {b.header.map((_, j) => (
                          <td key={j} className="border border-line px-3 py-2 align-top" style={b.align[j] ? { textAlign: b.align[j]! } : undefined}>
                            <Inline text={r[j] ?? ""} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "list": {
            const Tag = b.ordered ? "ol" : "ul";
            return (
              <Tag key={i} className={cn("my-3 space-y-1 pl-6", b.ordered ? "list-decimal" : "list-disc")}>
                {b.items.map((it, j) => (
                  <li key={j}>
                    <Inline text={it} />
                  </li>
                ))}
              </Tag>
            );
          }
          case "hr":
            return <hr key={i} className="my-6 border-line" />;
          default:
            return (
              <p key={i} className="my-3 leading-relaxed">
                <Lines text={b.text} />
              </p>
            );
        }
      })}
    </>
  );
}

export function ArticleRenderer({ source, className }: { source: string; className?: string }) {
  const blocks = useMemo(() => parseArticle(source), [source]);
  return (
    <div className={cn("td-article max-w-none break-words text-fg", className)}>
      <Blocks blocks={blocks} />
    </div>
  );
}

/** Table of contents computed from the same parse as the renderer, so anchors always match. */
export function useArticleToc(source: string): TocEntry[] {
  return useMemo(() => tocOf(parseArticle(source)), [source]);
}

export function OnThisPage({ toc }: { toc: TocEntry[] }) {
  if (!toc.length) return null;
  const list = (
    <ul className="space-y-1 text-sm">
      {toc.map((t) => (
        <li key={t.id} className={t.level === 3 ? "pl-3" : undefined}>
          <a href={`#${t.id}`} className="text-fg-secondary hover:text-fg hover:underline">
            {t.text}
          </a>
        </li>
      ))}
    </ul>
  );
  return (
    <nav aria-label="On this page">
      <details className="rounded-lg border border-line p-3 lg:hidden">
        <summary className="cursor-pointer text-sm font-semibold">On this page</summary>
        <div className="mt-2">{list}</div>
      </details>
      <div className="sticky top-20 hidden lg:block">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">On this page</p>
        {list}
      </div>
    </nav>
  );
}
