import type { ReactNode } from "react";

/**
 * Minimal Markdown → React renderer for staff-authored product copy (`description_md`, FE-21).
 * Supports paragraphs, `-`/`*`/`1.` lists, `**bold**`, `*italic*`/`_italic_`, `` `code` `` and
 * `[text](https://… or /path)`. It builds React elements only — never HTML strings — so markup
 * in the source is shown as text and cannot inject scripts. Unsupported syntax stays as text.
 */
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)|\*[^*\n]+\*|_[^_\n]+_)/g;

function safeHref(href: string): string | null {
  if (/^https:\/\/[^\s]+$/i.test(href)) return href;
  if (/^\/(?!\/)[^\s\\]*$/.test(href)) return href;
  return null;
}

export function renderInline(text: string, keyPrefix = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(INLINE)) {
    const tok = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyPrefix}-${n++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key} className="rounded bg-surface-subtle px-1 font-mono text-[0.9em]">{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("[")) {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok);
      const href = mm ? safeHref(mm[2]!) : null;
      out.push(
        href ? (
          <a key={key} href={href} className="text-fg-link underline" {...(href.startsWith("https://") ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
            {mm![1]}
          </a>
        ) : (
          tok
        ),
      );
    } else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function SafeMarkdown({ source, className }: { source: string; className?: string }) {
  const blocks = source.replace(/\r\n?/g, "\n").split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  return (
    <div className={className}>
      {blocks.map((block, bi) => {
        const lines = block.split("\n");
        const bullet = lines.every((l) => /^\s*[-*]\s+/.test(l));
        const numbered = lines.every((l) => /^\s*\d+[.)]\s+/.test(l));
        if (bullet || numbered) {
          const items = lines.map((l) => l.replace(/^\s*(?:[-*]|\d+[.)])\s+/, ""));
          const Tag = numbered ? "ol" : "ul";
          return (
            <Tag key={bi} className={`${numbered ? "list-decimal" : "list-disc"} space-y-1 pl-5`}>
              {items.map((it, ii) => (
                <li key={ii}>{renderInline(it, `${bi}-${ii}`)}</li>
              ))}
            </Tag>
          );
        }
        return <p key={bi}>{lines.flatMap((l, li) => (li ? [<br key={`br-${li}`} />, ...renderInline(l, `${bi}-${li}`)] : renderInline(l, `${bi}-${li}`)))}</p>;
      })}
    </div>
  );
}
