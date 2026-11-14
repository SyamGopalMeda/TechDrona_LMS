import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { isApiError } from "@/lib/api/errors";
import { hasSessionCookie, serverApiGet } from "@/lib/api/server";
import { PORTALS, type PortalKey } from "@/lib/nav/portals";
import { canEnterPortal, homePortal, type MyGrantsPortals } from "./access";
import { PortalForbidden } from "./PortalForbidden";

/**
 * ADM-12: role-gates a staff portal layout using `GET /me/grants` `portals`. Without a session
 * the PortalShell inside redirects to sign-in, so nothing is fetched. A 401 sends the user to
 * sign-in; any other failure (api down) falls through to the shell, whose pages show their own
 * error states — the api remains the authority for every request.
 *
 * A signed-in user whose roles do not open this portal is sent straight to their own home portal
 * (a Student opening /admin lands on /app) — no error page. Only an account that opens no portal
 * at all sees the "no access yet" page.
 */
export async function StaffPortalGate({ portal, children }: { portal: PortalKey; children: ReactNode }) {
  if (!(await hasSessionCookie())) return <>{children}</>;
  const def = PORTALS[portal];
  let grants: MyGrantsPortals;
  try {
    grants = await serverApiGet<MyGrantsPortals>("me/grants");
  } catch (err) {
    if (isApiError(err) && err.status === 401) redirect(`/login?next=${encodeURIComponent(def.prefix)}`);
    return <>{children}</>;
  }
  if (canEnterPortal(grants.portals, portal, grants.data?.map((g) => g.role_key))) return <>{children}</>;
  const home = homePortal(grants.portals);
  if (home) redirect(home);
  return <PortalForbidden />;
}
