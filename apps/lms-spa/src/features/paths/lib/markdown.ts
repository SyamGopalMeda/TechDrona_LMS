/**
 * Parser for authored path articles (Markdown subset + container blocks). Produces a plain
 * block tree that ArticleRenderer turns into React elements — markup in the source is never
 * interpreted as HTML, so `<script>` etc. render as text.
 *
 * Supported: `#`/`##`/`###` headings, fenced code (```lang) with an optional ```output fence
 * right after it, callouts (:::key-idea | :::watch-out | :::note | :::tip … :::), exercises
 * (:::exercise Title … :::answer … :::), GFM pipe tables, bullet/numbered lists, `---`,
 * paragraphs. Inline: **bold**, *italic* / _italic_, `code`, [text](https://… | /relative).
 */

import type { TocEntry } from "./types";

export type CalloutKind = "key-idea" | "watch-out" | "note" | "tip";

export type Block =
  | { type: "heading"; level: 1 | 2 | 3; text: string; id: string }
  | { type: "code"; lang: string; code: string; output: string | null }
  | { type: "callout"; kind: CalloutKind; blocks: Block[] }
  | { type: "exercise"; title: string; body: Block[]; answer: Block[] }
  | { type: "table"; header: string[]; align: ("left" | "center" | "right" | null)[]; rows: string[][] }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "hr" }
  | { type: "paragraph"; text: string };

export const CALLOUT_KINDS: readonly CalloutKind[] = ["key-idea", "watch-out", "note", "tip"];

export const CALLOUT_TITLES: Record<CalloutKind, string> = {
  "key-idea": "Key idea",
  "watch-out": "Watch out",
  note: "Note",
  tip: "Tip",
};

/** Heading anchor slug: lowercase, non-alphanumerics → "-", trimmed. */
export function slugify(text: string): string {
  const s = text
    .toLowerCase()
    .replace(/[`*_[\]()]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || "section";
}

const FENCE = /^```\s*([A-Za-z0-9_+.#-]*)\s*$/;
const OPEN = /^:::\s*([a-z-]+)\s*(.*)$/;
const CLOSE = /^:::\s*$/;
const HEADING = /^(#{1,3})\s+(.+?)\s*#*\s*$/;
const LIST_ITEM = /^\s*([-*]|\d+[.)])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const HR = /^\s*(-{3,}|\*{3,})\s*$/;

interface Ctx {
  used: Map<string, number>;
}

function uniqueId(ctx: Ctx, text: string): string {
  const base = slugify(text);
  const n = (ctx.used.get(base) ?? 0) + 1;
  ctx.used.set(base, n);
  return n === 1 ? base : `${base}-${n}`;
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells: string[] = [];
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]!;
    if (ch === "\\" && s[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (ch === "|") {
      cells.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  cells.push(cur.trim());
  return cells;
}

function startsBlock(line: string, next: string | undefined): boolean {
  return (
    FENCE.test(line) ||
    OPEN.test(line) ||
    CLOSE.test(line) ||
    HEADING.test(line) ||
    HR.test(line) ||
    LIST_ITEM.test(line) ||
    (line.trim().startsWith("|") && next !== undefined && TABLE_SEP.test(next))
  );
}

/** Collect the body of a container opened at `start` (exclusive) up to its matching close. */
function readContainer(lines: string[], start: number): { body: string[]; end: number } {
  let depth = 0;
  let inFence = false;
  const body: string[] = [];
  let i = start;
  for (; i < lines.length; i++) {
    const line = lines[i]!;
    if (FENCE.test(line) || (inFence && /^```\s*$/.test(line))) {
      inFence = !inFence;
      body.push(line);
      continue;
    }
    if (!inFence) {
      const open = OPEN.exec(line);
      if (open && open[1] !== "answer") depth++;
      else if (CLOSE.test(line)) {
        if (depth === 0) return { body, end: i + 1 };
        depth--;
      }
    }
    body.push(line);
  }
  return { body, end: i };
}

function parseLines(lines: string[], ctx: Ctx): Block[] {
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const lang = (fence[1] ?? "").toLowerCase();
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i]!)) code.push(lines[i++]!);
      i++; // closing fence (or EOF)
      const text = code.join("\n");
      const prev = out[out.length - 1];
      if (lang === "output" && prev && prev.type === "code" && prev.output === null) prev.output = text;
      else out.push({ type: "code", lang, code: text, output: null });
      continue;
    }
    const open = OPEN.exec(line);
    if (open) {
      const name = open[1]!;
      const { body, end } = readContainer(lines, i + 1);
      i = end;
      if (name === "exercise") {
        let split = -1;
        let depth = 0;
        for (let j = 0; j < body.length; j++) {
          const o = OPEN.exec(body[j]!);
          if (o && o[1] === "answer" && depth === 0) {
            split = j;
            break;
          }
          if (o) depth++;
          else if (CLOSE.test(body[j]!)) depth--;
        }
        const q = split >= 0 ? body.slice(0, split) : body;
        const a = split >= 0 ? body.slice(split + 1) : [];
        out.push({ type: "exercise", title: (open[2] ?? "").trim() || "Exercise", body: parseLines(q, ctx), answer: parseLines(a, ctx) });
      } else {
        const kind = (CALLOUT_KINDS as readonly string[]).includes(name) ? (name as CalloutKind) : "note";
        out.push({ type: "callout", kind, blocks: parseLines(body, ctx) });
      }
      continue;
    }
    if (CLOSE.test(line)) {
      i++; // stray close marker
      continue;
    }
    const h = HEADING.exec(line);
    if (h) {
      const level = h[1]!.length as 1 | 2 | 3;
      const text = h[2]!.trim();
      out.push({ type: "heading", level, text, id: uniqueId(ctx, text) });
      i++;
      continue;
    }
    if (HR.test(line)) {
      out.push({ type: "hr" });
      i++;
      continue;
    }
    if (line.trim().startsWith("|") && lines[i + 1] !== undefined && TABLE_SEP.test(lines[i + 1]!)) {
      const header = splitRow(line);
      const align = splitRow(lines[i + 1]!).map((c) => {
        const l = c.startsWith(":");
        const r = c.endsWith(":");
        return l && r ? "center" : r ? "right" : l ? "left" : null;
      });
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i]!.trim().startsWith("|")) rows.push(splitRow(lines[i++]!));
      out.push({ type: "table", header, align, rows });
      continue;
    }
    const li = LIST_ITEM.exec(line);
    if (li) {
      const ordered = /\d/.test(li[1]!);
      const items: string[] = [];
      while (i < lines.length) {
        const m = LIST_ITEM.exec(lines[i]!);
        if (m && /\d/.test(m[1]!) === ordered) {
          items.push(m[2]!);
          i++;
        } else if (!m && lines[i]!.trim() && /^\s{2,}/.test(lines[i]!) && items.length) {
          items[items.length - 1] += ` ${lines[i]!.trim()}`; // continuation line
          i++;
        } else break;
      }
      out.push({ type: "list", ordered, items });
      continue;
    }
    const para: string[] = [line];
    i++;
    while (i < lines.length && lines[i]!.trim() && !startsBlock(lines[i]!, lines[i + 1])) para.push(lines[i++]!);
    out.push({ type: "paragraph", text: para.join("\n") });
  }
  return out;
}

export function parseArticle(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  return parseLines(lines, { used: new Map() });
}

/** "On this page" entries: level-2 and level-3 headings anywhere in the document, in order. */
export function tocOf(blocks: Block[]): TocEntry[] {
  const out: TocEntry[] = [];
  const walk = (bs: Block[]) => {
    for (const b of bs) {
      if (b.type === "heading" && b.level >= 2) out.push({ id: b.id, text: b.text, level: b.level });
      else if (b.type === "callout") walk(b.blocks);
      else if (b.type === "exercise") {
        walk(b.body);
        walk(b.answer);
      }
    }
  };
  walk(blocks);
  return out;
}

/* ------------------------------------------------------------------ inline tokens */

export type Inline =
  | { t: "text"; v: string }
  | { t: "strong"; v: string }
  | { t: "em"; v: string }
  | { t: "code"; v: string }
  | { t: "link"; v: string; href: string };

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)|\*[^*\n]+\*|_[^_\n]+_)/g;

/** Only https:// links or same-origin relative paths are kept; everything else is text. */
export function safeHref(href: string): string | null {
  if (/^https:\/\/[^\s"'<>]+$/i.test(href)) return href;
  if (/^\/(?!\/)[^\s\\"'<>]*$/.test(href)) return href;
  if (/^#[A-Za-z0-9_-]+$/.test(href)) return href;
  return null;
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    const tok = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push({ t: "text", v: text.slice(last, at) });
    if (tok.startsWith("**")) out.push({ t: "strong", v: tok.slice(2, -2) });
    else if (tok.startsWith("`")) out.push({ t: "code", v: tok.slice(1, -1) });
    else if (tok.startsWith("[")) {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok);
      const href = mm ? safeHref(mm[2]!) : null;
      out.push(href && mm ? { t: "link", v: mm[1]!, href } : { t: "text", v: tok });
    } else out.push({ t: "em", v: tok.slice(1, -1) });
    last = at + tok.length;
  }
  if (last < text.length) out.push({ t: "text", v: text.slice(last) });
  return out;
}
