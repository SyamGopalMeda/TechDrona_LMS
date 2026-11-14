import Link from "next/link";
import { SignOutButton } from "@/components/shell/SignOutButton";
import { Logo } from "@/components/ui/Logo";

/**
 * ADM-12: shown instead of a portal when the signed-in account opens no portal at all (users
 * with any role are redirected to their own portal by StaffPortalGate instead). LMS chrome only —
 * no website header/footer — and a way forward: help or sign out.
 */
export function PortalForbidden() {
  return (
    <div className="flex min-h-dvh flex-col bg-surface-canvas text-fg">
      <header className="flex items-center border-b border-line bg-surface px-4 py-3 sm:px-6">
        <Logo tone="auto" className="h-7 sm:h-8" />
      </header>
      <main id="main" tabIndex={-1} className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-10 focus:outline-none">
        <div className="rounded-xl border border-line bg-surface p-6 text-center shadow-xs">
          <h1 className="font-display text-xl font-bold text-fg-heading">Your account isn&apos;t set up yet</h1>
          <p className="mt-2 text-sm text-fg-secondary">
            You&apos;re signed in, but no area of Tech Drona has been opened for this account yet. Ask your administrator to assign you a role, or sign out and
            use a different account.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <SignOutButton />
            <Link href="/help" className="inline-flex min-h-touch items-center text-sm font-medium text-fg-link underline hover:text-fg-link-hover">
              Get help
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
