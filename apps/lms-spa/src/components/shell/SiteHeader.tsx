"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { LMS_CONTACT_HREF, LMS_COURSES_HREF, SITE_INFO, SITE_MENU, type SiteMenuItem } from "@/lib/site/website";

/*
 * Public/auth header, a copy of the company website header (tech drona/src/components/Layout.jsx
 * `Header`; CSS .site-header, .nav-link, .nav-split, .menu, .header-login, .header-contact-btn,
 * .nav-toggle-round, .mp in global.css → src/styles/site.css `td-*`). The website's own sections
 * (Solutions, Training & Careers, Projects, About) go to the main website (absolute URLs); whatever
 * the LMS has a page for stays in the LMS: the logo (LMS home), Login / Dashboard, Contact (the help
 * centre's contact section) and, when signed in, Courses (the in-app catalogue).
 */

/** The website menu with LMS-owned entries swapped in (signed in: Courses → the in-app catalogue). */
function menuFor(signedIn: boolean): SiteMenuItem[] {
  return signedIn ? SITE_MENU.map((m) => (m.label === "Courses" && !m.items && !m.groups ? { ...m, href: LMS_COURSES_HREF } : m)) : SITE_MENU;
}

/** Same-origin hrefs use a client-side Link; absolute website URLs a plain anchor. */
function NavAnchor({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  return href.startsWith("/") ? (
    <Link href={href} className={className}>
      {children}
    </Link>
  ) : (
    <a href={href} className={className}>
      {children}
    </a>
  );
}

const svg = { "aria-hidden": true, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeLinecap: "round", strokeLinejoin: "round" } as const;

export function ArrowIcon({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <svg {...svg} width={size} height={size} strokeWidth={2.2} className={className}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
function ChevronIcon() {
  return (
    <svg {...svg} width={14} height={14} strokeWidth={2.2} className="td-nav-chev">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
function UserIcon() {
  return (
    <svg {...svg} width={16} height={16} strokeWidth={2}>
      <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7 8a7 7 0 0 1 14 0" />
    </svg>
  );
}

function Dropdown({ item, open, onOpen, onClose }: { item: SiteMenuItem; open: boolean; onOpen: () => void; onClose: () => void }) {
  const menuId = useId();
  // Hover opens the menu; on touch the emulated mouseenter fires just before the tap's click, so a
  // click right after a hover-open keeps it open instead of toggling it shut again.
  const hoverAt = useRef(0);
  const all = { href: item.allHref ?? item.href, label: item.allLabel ?? `View all ${item.label.toLowerCase()}` };
  return (
    <li
      className={`td-nav-item${open ? " is-open" : ""}`}
      onMouseEnter={() => {
        if (!open) hoverAt.current = Date.now();
        onOpen();
      }}
      onMouseLeave={onClose}
    >
      {/* The label opens the website page; hovering (or the arrow button, for keyboard and touch) shows the menu. */}
      <span className="td-nav-split">
        <a href={item.href} className="td-nav-link">
          {item.label}
        </a>
        <button
          type="button"
          className="td-nav-chev-btn"
          aria-expanded={open}
          aria-controls={menuId}
          aria-label={`${open ? "Hide" : "Show"} ${item.label} menu`}
          onClick={() => {
            if (open && Date.now() - hoverAt.current < 500) return;
            if (open) onClose();
            else onOpen();
          }}
        >
          <ChevronIcon />
        </button>
      </span>
      <div id={menuId} className="td-menu">
        <div className={`td-menu-inner${item.groups ? " td-menu-inner--groups" : ""}`}>
          {item.groups ? (
            <div className="td-menu-groups">
              {item.groups.map((g) => (
                <div key={g.title}>
                  <p className="td-menu-group-title">{g.title}</p>
                  {g.items.map((s) => (
                    <a key={s.href} href={s.href} className="td-menu-link">
                      <strong>{s.label}</strong>
                      {s.desc ? <small>{s.desc}</small> : null}
                    </a>
                  ))}
                </div>
              ))}
            </div>
          ) : (
            item.items?.map((s) => (
              <a key={s.href} href={s.href} className="td-menu-link">
                <strong>{s.label}</strong>
                {s.desc ? <small>{s.desc}</small> : null}
              </a>
            ))
          )}
          <a href={all.href} className="td-menu-all">
            {all.label} <ArrowIcon />
          </a>
        </div>
      </div>
    </li>
  );
}

/** Desktop navigation (from 1100px): Home, Solutions ▾, Training & Careers ▾, Courses, Projects, About. */
function SiteNav({ signedIn }: { signedIn: boolean }) {
  const [menu, setMenu] = useState<string | null>(null);
  const navRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    const onPointer = (e: PointerEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) setMenu(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [menu]);
  return (
    <nav ref={navRef} aria-label="Main" className="td-nav">
      <ul>
        {menuFor(signedIn).map((item) =>
          item.items || item.groups ? (
            <Dropdown
              key={item.label}
              item={item}
              open={menu === item.label}
              onOpen={() => setMenu(item.label)}
              onClose={() => setMenu((m) => (m === item.label ? null : m))}
            />
          ) : (
            <li key={item.label} className="td-nav-item">
              <NavAnchor href={item.href} className="td-nav-link">
                {item.label}
              </NavAnchor>
            </li>
          ),
        )}
      </ul>
    </nav>
  );
}

/**
 * Slide-in menu panel below 1100px (website `.mp`): a modal dialog from the right with the website
 * sections, the LMS sign-in and "Contact us". Escape, the scrim, the close button and following a
 * link close it; focus moves into it on open and back to the toggle on close.
 */
function MenuPanel({ id, signedIn, onClose }: { id: string; signedIn: boolean; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const root = document.documentElement;
    const prev = root.style.overflow;
    root.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      root.style.overflow = prev;
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  const links = menuFor(signedIn).map((m) => ({ href: m.href, label: m.label }));
  return createPortal(
    <div className="td-mp" role="dialog" aria-modal="true" aria-label="Menu">
      <button type="button" className="td-mp-scrim" onClick={onClose} aria-label="Close menu" tabIndex={-1} />
      <aside
        id={id}
        className="td-mp-panel"
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("a")) onClose();
        }}
      >
        <div className="td-mp-head">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/logo-lockup-navy.svg" alt="Tech Drona" width={170} height={37} />
          <button ref={closeRef} type="button" className="td-mp-x" onClick={onClose} aria-label="Close menu">
            <svg {...svg} width={20} height={20} strokeWidth={2}>
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="td-mp-body">
          <p className="td-mp-k">Explore Tech Drona</p>
          <nav aria-label="Main" className="td-mp-nav">
            {links.map((l) => (
              <NavAnchor key={l.href} href={l.href} className="td-mp-link">
                {l.label}
                <ArrowIcon size={15} className="td-mp-go" />
              </NavAnchor>
            ))}
          </nav>
        </div>
        <div className="td-mp-foot">
          {signedIn ? (
            <Link href="/app" className="td-mp-cta">
              Go to dashboard <ArrowIcon size={17} />
            </Link>
          ) : (
            <Link href="/login" className="td-mp-cta">
              Log in to Tech Drona <ArrowIcon size={17} />
            </Link>
          )}
          <Link href={LMS_CONTACT_HREF} className="td-mp-cta td-mp-cta--green">
            Contact us <ArrowIcon size={17} />
          </Link>
          <a href={`mailto:${SITE_INFO.email}`} className="td-al-foot" style={{ textDecoration: "none" }}>
            {SITE_INFO.email}
          </a>
        </div>
      </aside>
    </div>,
    document.body,
  );
}

/** Public/auth header. `signedIn` swaps "Login" for "Dashboard" (UX hint; the api decides). */
export function SiteHeader({ signedIn = false }: { signedIn?: boolean }) {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const onPop = () => setOpen(false);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    toggleRef.current?.focus();
  }, []);

  return (
    <header data-td-public-header="" className={`td-site-header${scrolled ? " is-scrolled" : ""}`}>
      <div className="td-site-header-inner">
        {/* LMS home: signed out → sign in, signed in → the module hub. A full page load (not
            <Link>) because the edge proxy decides where "/" goes. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a href="/" aria-label="Tech Drona LMS home" className="shrink-0 rounded-md">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/logo-lockup-navy.svg" alt="" width={211} height={46} className="td-brand-logo" />
        </a>
        <SiteNav signedIn={signedIn} />
        <div className="td-header-actions">
          {signedIn ? (
            <Link href="/app" className="td-header-login" aria-label="Go to dashboard">
              <UserIcon />
              <span>Dashboard</span>
            </Link>
          ) : (
            <Link href="/login" className="td-header-login" aria-label="Login">
              <UserIcon />
              <span>Login</span>
            </Link>
          )}
          <Link href={LMS_CONTACT_HREF} className="td-header-contact-btn">
            <span>
              Contact<span className="td-hide-xs"> us</span>
            </span>
            <ArrowIcon />
          </Link>
          <button
            ref={toggleRef}
            type="button"
            className="td-nav-toggle-round"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label="Menu"
            onClick={() => setOpen((v) => !v)}
          >
            <svg {...svg} width={18} height={18} strokeWidth={2}>
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
        </div>
      </div>
      {open ? <MenuPanel id={panelId} signedIn={signedIn} onClose={close} /> : null}
    </header>
  );
}
