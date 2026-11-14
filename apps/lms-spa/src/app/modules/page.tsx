import { asyncComponent } from "@/spa/async";
import type React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Logo } from "@/components/ui/Logo";
import { AccountMenu } from "@/components/shell/AccountMenu";
import { ACCEPT_TERMS_PATH, CHANGE_PASSWORD_PATH, isRequiredConsentProblem, mfaEnrolPath } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { hasSessionCookie, serverApiGet } from "@/lib/api/server";
import { type HubModule, MODULE_ICONS } from "@/features/hub/modules";
import { continueHref } from "@/features/hub/last-page";

export const dynamic = "force-dynamic";
export const metadata = { title: "Choose a module", robots: { index: false, follow: false } };

/**
 * Central login hub: after one sign-in, staff pick LMS, Colleges Management or the Company
 * Website Admin (only the modules they may open: GET /me/modules). With a single module the
 * hub forwards straight to it, so nobody sees a one-card page.
 */
async function ModulesPage__server() {
  if (!(await hasSessionCookie())) redirect("/login?next=%2Fmodules");
  let modules: HubModule[] = [];
  try {
    modules = (await serverApiGet<{ modules: HubModule[] }>("me/modules", { navigation: true })).modules ?? [];
  } catch (e) {
    if (e instanceof ApiError) {
      // Signed in, but the role needs 2-step verification first (staff/Admin without an
      // authenticator). Sending them to /login here looped forever: login → /modules → /login.
      if (e.code === "mfa_enrolment_required") redirect(mfaEnrolPath(e.problem?.enrol_url));
      if (isRequiredConsentProblem(e.problem)) redirect(`${ACCEPT_TERMS_PATH}?next=%2Fmodules`);
      if (e.code === "password_change_required") redirect(`${CHANGE_PASSWORD_PATH}?next=%2Fmodules`);
      if (e.code === "account_restricted") redirect("/account/restricted");
      if (e.status === 401 || e.status === 403) redirect("/login?next=%2Fmodules");
    }
    throw e;
  }
  const only = modules.length === 1 ? modules[0] : undefined;
  if (only && !only.external) redirect(only.href);

  return (
    <div className="min-h-dvh bg-surface-canvas text-fg">
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3 sm:px-6">
        <Link href="/modules" aria-label="Tech Drona — modules" className="flex items-center rounded-md focus-visible:shadow-focus focus-visible:outline-none">
          <Logo alt="" tone="auto" className="h-7 sm:h-8" />
        </Link>
        <AccountMenu links={[{ href: "/app/settings/profile", label: "Settings" }]} />
      </header>
      <main id="main" className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
        <h1 className="font-display text-2xl font-bold text-fg-heading sm:text-3xl">Where do you want to work?</h1>
        <p className="mt-2 max-w-2xl text-fg-secondary">
          One sign-in for every Tech Drona module. You can switch at any time from the <strong>Modules</strong> menu at the top of each module.
        </p>
        <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {modules.map((m) => (
            <li key={m.key}>
              <ModuleAnchor
                external={m.external}
                href={cardHref(m)}
                className="group flex h-full flex-col rounded-xl border border-line bg-surface p-5 text-fg no-underline shadow-sm transition hover:border-brand hover:shadow-md focus-visible:shadow-focus focus-visible:outline-none"
              >
                <span aria-hidden="true" className="grid h-11 w-11 place-items-center rounded-lg bg-brand-subtle text-brand">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                    <path d={MODULE_ICONS[m.key] ?? MODULE_ICONS.lms} />
                  </svg>
                </span>
                <span className="mt-4 font-display text-lg font-bold text-fg-heading group-hover:text-brand">{m.title}</span>
                <span className="mt-1 text-sm text-fg-secondary">{m.description}</span>
                <span className="mt-4 text-xs font-semibold uppercase tracking-wide text-fg-muted">
                  Your role: {m.roles.map((r) => r.replace(/_/g, " ")).join(", ")}
                </span>
              </ModuleAnchor>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}

/**
 * LMS and Colleges cards resume the page this browser last had open in that module (/continue),
 * falling back to the module's own landing page. (The single-module forward above must keep the
 * plain href: /continue falls back to this hub.)
 */
function cardHref(m: HubModule): string {
  if (m.external) return m.href;
  if (m.key === "lms") return continueHref("lms", m.href);
  if (m.key === "colleges") return m.href; // always the full-screen portal (owner 2026-11-14)
  return m.href;
}

/** External modules (the website admin) open as a full page load; LMS modules use client navigation. */
function ModuleAnchor({ external, href, children, ...rest }: { external?: boolean; href: string; children: React.ReactNode; className?: string; "aria-current"?: "page" }) {
  return external ? (
    <a href={href} {...rest}>
      {children}
    </a>
  ) : (
    <Link href={href} prefetch={false} {...rest}>
      {children}
    </Link>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(ModulesPage__server, "app/modules/page.tsx#ModulesPage");
