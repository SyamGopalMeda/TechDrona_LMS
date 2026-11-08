import Link from "next/link";
import { PublicShell } from "@/components/shell/PublicShell";
import { SignOutButton } from "@/components/shell/SignOutButton";

const linkCls = "font-medium text-fg-link underline hover:text-fg-link-hover";

/**
 * ADM-12: shown instead of a staff portal's shell and navigation when the signed-in user holds
 * no grant for it. Lists only the portals the user can open (portal switcher, matrix rule 6).
 */
export function PortalForbidden({ portalTitle, reachable }: { portalTitle: string; reachable: { href: string; title: string }[] }) {
  return (
    <PublicShell signedIn>
      <div className="mx-auto max-w-prose py-8 text-center">
        <p className="font-display text-5xl font-bold text-fg-muted" aria-hidden="true">
          403
        </p>
        <h1 className="mt-2 font-display text-2xl font-bold text-fg">You don&apos;t have access to the {portalTitle} portal</h1>
        <p className="mt-2 text-sm text-fg-muted">
          Your account has no role that opens this area. If you think this is wrong, ask your administrator to grant you the role.
        </p>
        {reachable.length ? (
          <nav aria-label="Your portals" className="mt-6">
            <ul className="flex flex-wrap justify-center gap-4 text-sm">
              {reachable.map((p) => (
                <li key={p.href}>
                  <Link href={p.href} className={linkCls}>
                    Go to {p.title}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
        <div className="mt-6 flex justify-center">
          <SignOutButton />
        </div>
      </div>
    </PublicShell>
  );
}
