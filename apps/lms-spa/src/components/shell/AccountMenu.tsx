"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/ui/cn";
import { SITE_URL } from "@/lib/site/website";
import { useSignOut } from "./SignOutButton";

/** The subset of `GET /me` (identity/router.py me) the header needs. */
interface MeSummary {
  user?: { email?: string | null };
  profile?: { full_name?: string | null; display_name?: string | null };
}

export interface AccountLink {
  href: string;
  label: string;
}

function initialsOf(text: string): string {
  const parts = text.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  const letters = parts.length > 1 ? `${parts[0]![0]}${parts[parts.length - 1]![0]}` : (parts[0] ?? "?").slice(0, 2);
  return letters.toUpperCase();
}

/**
 * Header account menu: who is signed in, account links (Settings, …) and Sign out (same logic and
 * unsynced-answers warning as SignOutButton). A disclosure, not an ARIA menu: Tab moves through
 * the links; Escape, a click outside and navigation close it. `GET me` failing just hides the name.
 */
export function AccountMenu({ links }: { links: AccountLink[] }) {
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState<MeSummary | null>(null);
  const pathname = usePathname();
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const { busy, start, dialog } = useSignOut();

  useEffect(() => {
    let live = true;
    api
      .get<MeSummary>("me", { handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false } })
      .then((r) => {
        if (live) setMe(r);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const name = me?.profile?.display_name?.trim() || me?.profile?.full_name?.trim() || null;
  const email = me?.user?.email ?? null;
  const who = name ?? email;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={who ? `Account: ${who}` : "Account"}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-touch items-center gap-2 rounded-full border border-transparent py-1 pl-1 pr-1.5 font-display text-sm font-semibold text-fg-heading transition-colors duration-fast hover:border-[#b4c5f2] focus-visible:shadow-focus focus-visible:outline-none md:border-[#e6eaf2] md:bg-surface md:pr-3"
      >
        {/* Website `.adm-me-btn` pill with the `.adm-av` gradient avatar. */}
        <span aria-hidden="true" className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[linear-gradient(135deg,#1d4ed8,#032269)] text-xs font-extrabold text-white">
          {who ? (
            initialsOf(who)
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
              <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7 8a7 7 0 0 1 14 0" />
            </svg>
          )}
        </span>
        <span aria-hidden="true" className="hidden max-w-[10rem] truncate md:inline">
          {name ?? "Account"}
        </span>
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={cn("hidden h-4 w-4 transition-transform md:block", open && "rotate-180")}>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      <div
        id={panelId}
        hidden={!open}
        className="absolute right-0 z-dropdown mt-2 w-[min(18rem,calc(100vw-2rem))] rounded-2xl border border-line bg-surface p-1.5 shadow-[0_30px_60px_-24px_rgba(5,11,36,0.35)]"
      >
        <div className="border-b border-line-subtle px-3 pb-2.5 pt-2">
          <p className="text-xs font-semibold text-fg-muted">Signed in as</p>
          <p className="truncate font-display text-sm font-bold text-fg-heading">{name ?? email ?? "Your account"}</p>
          {name && email ? <p className="truncate text-sm text-fg-secondary">{email}</p> : null}
        </div>
        <ul className="py-1">
          {links.map((l) => (
            <li key={l.href}>
              <Link
                href={l.href}
                className="flex min-h-touch items-center rounded-lg px-3 text-sm font-medium text-fg no-underline hover:bg-surface-hover hover:text-brand focus-visible:shadow-focus focus-visible:outline-none md:min-h-10"
              >
                {l.label}
              </Link>
            </li>
          ))}
          <li>
            {/* Back to the company website (absolute; it is a different site). */}
            <a
              href={SITE_URL}
              className="flex min-h-touch items-center justify-between gap-2 rounded-lg px-3 text-sm font-medium text-fg no-underline hover:bg-surface-hover hover:text-brand focus-visible:shadow-focus focus-visible:outline-none md:min-h-10"
            >
              Tech Drona website
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-fg-muted">
                <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
              </svg>
            </a>
          </li>
          <li className="mt-1 border-t border-line-subtle pt-1">
            <button
              type="button"
              aria-busy={busy || undefined}
              onClick={() => {
                if (busy) return;
                setOpen(false);
                void start();
              }}
              className="flex min-h-touch w-full items-center rounded-lg px-3 text-left text-sm font-semibold text-danger-fg hover:bg-danger-subtle focus-visible:shadow-focus focus-visible:outline-none md:min-h-10"
            >
              {busy ? "Signing out…" : "Sign out"}
            </button>
          </li>
        </ul>
      </div>
      {dialog}
    </div>
  );
}
