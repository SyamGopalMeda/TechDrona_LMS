import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/ui/cn";
import { Icon, isIconName, type IconName } from "./Display";

/* Dashboard layout pieces, after the website back office (tech drona global.css §28): the
   `.adm-hello` welcome banner (navy→blue gradient, mint glow, dot texture, greeting kicker, white
   actions), `.adm-kpi` stat cards below it, `.adm-panel` cards and a quick-actions grid with hover
   lift. Server-safe (no hooks, no handlers); the greeting/date use Asia/Kolkata time. */

const IST = "Asia/Kolkata";
const today = () => new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: IST }).format(new Date());

/** "Good morning" / "Good afternoon" / "Good evening" by the hour in India. */
export function greeting(now: Date = new Date()): string {
  const h = Number(new Intl.DateTimeFormat("en-IN", { hour: "numeric", hourCycle: "h23", timeZone: IST }).format(now));
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export interface DashboardHeroProps {
  title: ReactNode;
  description?: ReactNode;
  /** Small line above the title (website `.adm-hello-k`); defaults to the time-of-day greeting. */
  kicker?: ReactNode;
  /** Small badges/links beside the title (e.g. "Audit log verified"). */
  meta?: ReactNode;
  /** Buttons on the right (use `inverse` / `inverse-secondary` variants: they sit on navy). */
  actions?: ReactNode;
  /** Usually a <StatGrid> of KPI cards, shown under the banner. */
  children?: ReactNode;
}

/**
 * Welcome banner at the top of a portal dashboard (website `.adm-hello`), then the KPI cards
 * (children) in a row beneath it (website `.adm-kpis`). Entrance: a CSS fade-up on first paint.
 */
export function DashboardHero({ title, description, kicker, meta, actions, children }: DashboardHeroProps) {
  return (
    <div className="mb-6 sm:mb-8">
      {/* 2026-11 redesign: a deep navy band; the KPI cards (children) overlap its lower edge. */}
      <header className={cn("td-adm-hello td-enter px-5 pt-6 sm:px-8 sm:pt-8", children ? "pb-16 sm:pb-20" : "pb-6 sm:pb-8")}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold uppercase tracking-[0.08em] text-[#8ee0b8]" suppressHydrationWarning>
              {kicker ?? greeting()}
            </p>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className="min-w-0 break-words font-display text-[1.6rem] font-extrabold leading-tight tracking-tight sm:text-[2rem]">{title}</h1>
              {meta ? <div className="flex flex-wrap items-center gap-2">{meta}</div> : null}
            </div>
            {description ? <p className="mt-1.5 max-w-prose text-[0.9375rem] text-[#c9d6f5]">{description}</p> : null}
          </div>
          <div className="flex shrink-0 flex-col gap-3 sm:items-end">
            <p className="inline-flex items-center gap-2 text-sm text-white/75" suppressHydrationWarning>
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[#34d399]" />
              {today()}
            </p>
            {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
          </div>
        </div>
      </header>
      {children ? <div className="relative z-[1] -mt-10 px-2 sm:-mt-12 sm:px-5">{children}</div> : null}
    </div>
  );
}

/** "View all →" link for a Card's `actions` slot. */
export function ViewAllLink({ href, children = "View all" }: { href: string; children?: ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex min-h-6 items-center gap-1 rounded-md text-sm font-semibold text-fg-secondary no-underline hover:text-brand focus-visible:shadow-focus focus-visible:outline-none"
    >
      {children}
      <Icon name="arrowRight" className="h-4 w-4" />
    </Link>
  );
}

export interface QuickAction {
  href: string;
  label: string;
  /** One short line, e.g. "3 awaiting review". */
  hint?: ReactNode;
  icon?: IconName | ReactNode;
  /** Plain anchor (new document), for routes that must load with their own CSP. */
  documentNav?: boolean;
}

/**
 * Grid of shortcut tiles: icon, label, one-line hint, arrow. `columns` = 2 inside a half-width card, 3 for a full-width card.
 * `columns` = 1 sits in a one-third column: between lg and xl (tablet landscape, sidebar open) that column is
 * narrow, so the icon tile is dropped there and long words wrap instead of overflowing (live re-check N5).
 */
export function QuickActions({ items, columns = 2 }: { items: QuickAction[]; columns?: 1 | 2 | 3 }) {
  return (
    <ul className={cn("grid grid-cols-1 gap-2.5", columns === 1 ? "sm:grid-cols-2 lg:grid-cols-1" : cn("sm:grid-cols-2", columns === 3 ? "xl:grid-cols-3" : "lg:grid-cols-1 2xl:grid-cols-2"))}>
      {items.map((a) => {
        const cls =
          "group flex min-h-touch items-center gap-3 rounded-xl border border-[#e6eaf2] bg-surface px-3.5 py-2.5 text-fg no-underline transition-[border-color,box-shadow,transform,background-color] duration-base hover:border-[#c7d2ee] hover:shadow-[0_8px_22px_rgba(3,34,105,0.08)] motion-safe:hover:-translate-y-0.5 focus-visible:shadow-focus focus-visible:outline-none";
        const inner = (
          <>
            {a.icon ? (
              <span aria-hidden="true" className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-brand-subtle text-brand transition-colors duration-base group-hover:bg-brand group-hover:text-brand-on [&_svg]:h-[1.125rem] [&_svg]:w-[1.125rem]", columns === 1 && "lg:max-xl:hidden")}>
                {isIconName(a.icon) ? <Icon name={a.icon} /> : a.icon}
              </span>
            ) : null}
            <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
              <span className="block font-semibold text-fg-heading">{a.label}</span>
              {a.hint ? <span className="block text-sm text-fg-muted">{a.hint}</span> : null}
            </span>
            <Icon name="arrowRight" className="h-4 w-4 shrink-0 text-fg-muted transition-transform duration-fast group-hover:translate-x-0.5 group-hover:text-brand" />
          </>
        );
        return (
          <li key={a.href}>
            {a.documentNav ? (
              <a href={a.href} className={cls}>
                {inner}
              </a>
            ) : (
              <Link href={a.href} className={cls}>
                {inner}
              </Link>
            )}
          </li>
        );
      })}
    </ul>
  );
}
