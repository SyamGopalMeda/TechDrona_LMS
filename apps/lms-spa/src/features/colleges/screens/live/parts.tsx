/**
 * Small shared pieces of the live official-data screens (port of js/views/live.js helpers).
 * Rules kept: a value is only shown as live when it came from the /live endpoints; every live value carries
 * "checked <time>" and its source; external links are http(s) only, new tab, rel="noopener noreferrer".
 */
import { useEffect, useState, type ReactNode } from "react";
import { fmt } from "../../lib/fmt";
import { Badge, EmptyState, Icon, cx, type Tone } from "../../ui";
import { RESEARCH_LABEL, absTime, nowMs, relTime, type LiveSource } from "./store";

export { RESEARCH_LABEL };

/** Re-render every `ms` (relative times stay current). */
export function useTick(ms = 30_000): void {
  const [, setN] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setN((n) => n + 1), ms);
    return () => clearInterval(t);
  }, [ms]);
}

export function safeUrl(u: unknown): string | null {
  if (typeof u !== "string" || !u.trim()) return null;
  try {
    const x = new URL(u.trim(), "https://x.invalid/");
    return (x.protocol === "http:" || x.protocol === "https:") && x.hostname !== "x.invalid" ? x.href : null;
  } catch {
    return null;
  }
}
export function hostOf(u: string): string {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return String(u || "");
  }
}

/** "9 Nov 2026" for a date, the raw text otherwise. */
export const dateOnly = (d: unknown): string => (d && /^\d{4}-\d{2}-\d{2}/.test(String(d)) ? fmt.date(String(d).slice(0, 10)) : d ? String(d) : "—");

/** External link (new tab, no opener, no referrer). Non-http(s) values are shown as plain text. */
export function ExtLink({ url, label, className }: { url: string | null | undefined; label?: ReactNode; className?: string }) {
  const href = safeUrl(url);
  if (!href) return url ? <span>{label ?? url}</span> : null;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cx("lv-ext", className)} title={href}>
      <span>{label ?? hostOf(href)}</span>
      <Icon name="external" size={13} />
    </a>
  );
}

/** <time> "12 min ago · 9 Nov, 6:35 pm" */
export function When({ iso, prefix = "" }: { iso: string | null | undefined; prefix?: string }) {
  if (!iso || Number.isNaN(Date.parse(iso))) return <span className="lv-muted">{prefix ? `${prefix}never` : "never"}</span>;
  return (
    <time dateTime={iso} className="lv-time" title={`${absTime(iso)} IST`}>
      {`${prefix}${relTime(iso)} · ${absTime(iso)}`}
    </time>
  );
}

export function Callout({ tone, title, children }: { tone: "good" | "info" | "warn" | "bad"; title?: ReactNode; children?: ReactNode }) {
  return (
    <div className={cx("lv-callout", `lv-callout--${tone}`)} role={tone === "warn" || tone === "bad" ? "status" : undefined}>
      <Icon name={tone === "good" ? "check" : tone === "info" ? "info" : "warn"} size={18} />
      <div>
        {title ? <strong>{title}</strong> : null}
        {children ? <div className="lv-callout__text">{children}</div> : null}
      </div>
    </div>
  );
}

/** "Live · checked X · source" line (or the "Source unreachable — last copy" warning). */
export function SourceLine({ src, checkedAt }: { src: Partial<LiveSource> & { source_name?: string | null } | null | undefined; checkedAt?: string | null }) {
  if (!src) return null;
  const name = src.name || src.source_name || src.id || "official source";
  if (src.using_fallback) {
    return (
      <div className="lv-srcline lv-srcline--warn">
        <Icon name="warn" size={14} />
        <span>
          Source unreachable — showing last successful copy from{" "}
          <strong>{src.last_success_at ? `${absTime(src.last_success_at)} (${relTime(src.last_success_at)})` : "an earlier check"}</strong>
          {" · "}
        </span>
        <ExtLink url={src.url} label={name} />
      </div>
    );
  }
  return (
    <div className="lv-srcline">
      <span className="lv-livedot" aria-hidden="true" />
      <span>
        Live · checked <When iso={checkedAt || src.last_success_at} />
        {" · "}
      </span>
      <ExtLink url={src.url} label={name} />
    </div>
  );
}

export function UnavailableNote({ what }: { what: string }) {
  return (
    <EmptyState
      icon="info"
      title="Live official data is not available here"
      text={`This server does not provide live ${what} yet. Research data elsewhere is labelled “${RESEARCH_LABEL}”.`}
    />
  );
}

/** Badge other views put next to research-only data. */
export function ResearchBadge() {
  return (
    <span className="lv-research" title="From the November 2026 research import — not refreshed from official sources.">
      <Badge tone="neutral">{RESEARCH_LABEL}</Badge>
    </span>
  );
}

/* ------------------------------------------------------------------ notices */

export interface Notice {
  uid?: string;
  title?: string | null;
  url?: string | null;
  date?: string | null;
  category?: string | null;
  dept?: string | null;
  section?: string | null;
  is_new?: boolean;
  attachments?: { name?: string | null; url?: string | null }[];
  [k: string]: unknown;
}
export interface NoticeCategory {
  id: string;
  label?: string;
  count?: number;
}
export interface NoticesAnswer {
  items?: Notice[];
  categories?: NoticeCategory[];
  source?: Partial<LiveSource>;
  checked_at?: string | null;
  [k: string]: unknown;
}

const CAT_TONE: Record<string, Tone> = { exam: "info", result: "good", calendar: "brand", holiday: "neutral", admission: "warn" };
export function CatBadge({ id, cats }: { id: string | null | undefined; cats?: NoticeCategory[] }) {
  const c = (cats ?? []).find((x) => x.id === id);
  return <Badge tone={(id && CAT_TONE[id]) || "neutral"}>{c ? (c.label ?? c.id) : id ? String(id) : "Other"}</Badge>;
}

/** "New" = first seen in the last 48 h (server) AND dated within the last 14 days. */
export function isNewNotice(r: Notice): boolean {
  if (!r.is_new) return false;
  const t = r.date ? Date.parse(`${String(r.date).slice(0, 10)}T00:00:00Z`) : Number.NaN;
  return Number.isNaN(t) || nowMs() - t <= 14 * 86_400_000;
}

function AttachmentLinks({ r }: { r: Notice }) {
  const att = Array.isArray(r.attachments) ? r.attachments.filter((a) => a && safeUrl(a.url)) : [];
  if (!att.length) return null;
  const norm = (x: unknown) =>
    String(x ?? "")
      .trim()
      .toLowerCase();
  const label = (a: { name?: string | null }, i: number) => (!a.name || norm(a.name) === norm(r.title) ? (att.length > 1 ? `Attachment ${i + 1}` : "Open attachment") : a.name);
  return (
    <ul className="lv-att" aria-label="Attachments">
      {att.map((a, i) => (
        <li key={i}>
          <ExtLink url={a.url} label={label(a, i)} className="lv-att__a" />
        </li>
      ))}
    </ul>
  );
}

export function NoticeMain({ r }: { r: Notice }) {
  const href = safeUrl(r.url);
  const title = r.title || "(untitled notice)";
  return (
    <div className="lv-notice">
      <div className="lv-notice__title">
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {title}
          </a>
        ) : (
          <span>{title}</span>
        )}
        {isNewNotice(r) ? (
          <span className="lv-new">
            <Badge tone="brand">New</Badge>
          </span>
        ) : null}
      </div>
      <AttachmentLinks r={r} />
    </div>
  );
}

export function NoticeStatus({ r }: { r: NoticesAnswer }) {
  const src = r.source ?? {};
  if (src.using_fallback || (src.last_status === "error" && src.last_success_at)) return <SourceLine src={{ ...src, using_fallback: true, name: src.name || "JNTUK notifications" }} />;
  if (src.last_status === "error")
    return (
      <Callout tone="bad" title="Source unreachable">
        <span>
          The JNTUK notifications page could not be read and no earlier copy exists. <ExtLink url={src.url} label="Open the official page" />
        </span>
      </Callout>
    );
  if (!src.last_success_at && !r.checked_at) return <div className="lv-srcline">Not fetched yet.</div>;
  return <SourceLine src={{ ...src, name: src.name || "JNTUK notifications" }} checkedAt={src.last_success_at || r.checked_at} />;
}

/** A short list of notices (date + title + attachments). */
export function NoticeList({ items }: { items: Notice[] }) {
  return (
    <ul className="lv-nlist">
      {items.map((n, i) => (
        <li key={n.uid ?? i} className="lv-nlist__item">
          <div className="lv-nlist__date">{dateOnly(n.date)}</div>
          <NoticeMain r={n} />
        </li>
      ))}
    </ul>
  );
}

/** 404 / 405 = this server has no live endpoints. */
export const isUnavailable = (e: unknown): boolean => {
  const st = (e as { status?: number } | null)?.status;
  return st === 404 || st === 405;
};
