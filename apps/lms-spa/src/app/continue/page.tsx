import { asyncComponent } from "@/spa/async";
import { redirect } from "next/navigation";
import { ACCEPT_TERMS_PATH, CHANGE_PASSWORD_PATH, isRequiredConsentProblem, mfaEnrolPath } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { hasSessionCookie } from "@/lib/api/server";
import { getIdentity } from "@/lib/api/session-cache";
import { ContinueRedirect } from "@/features/hub/ContinueRedirect";
import { type ContinueArea, continueFallback } from "@/features/hub/last-page";

export const dynamic = "force-dynamic";
export const metadata = { title: "Opening your last page", robots: { index: false, follow: false } };

/**
 * Resume link (`/continue?area=lms|colleges&fallback=<path>`): used by the company website's
 * account icon and module menu and by the module hub. Signed out → sign in first, then back here.
 * Signed in → the page this browser last had open in that module (ContinueRedirect), else the
 * fallback (the module's landing page, or the module hub, which forwards single-module users).
 */
async function ContinuePage__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const area: ContinueArea | undefined = sp.area === "lms" || sp.area === "colleges" ? sp.area : undefined;
  const fallback = continueFallback(area, typeof sp.fallback === "string" ? sp.fallback : undefined);
  const self = new URLSearchParams();
  if (area) self.set("area", area);
  if (typeof sp.fallback === "string") self.set("fallback", fallback);
  const qs = self.toString();
  const here = `/continue${qs ? `?${qs}` : ""}`;
  if (!(await hasSessionCookie())) redirect(`/login?next=${encodeURIComponent(here)}`);

  // Portals this account may open (RBAC), so a page remembered for another account on a shared
  // browser is never resumed. Unknown (api error) → just use the fallback.
  let portals: string[] | null = null;
  try {
    portals = (await getIdentity<{ portals?: string[] }>("me/grants")).portals ?? ["/app"];
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.code === "mfa_enrolment_required") redirect(mfaEnrolPath(e.problem?.enrol_url));
      if (isRequiredConsentProblem(e.problem)) redirect(`${ACCEPT_TERMS_PATH}?next=${encodeURIComponent(here)}`);
      if (e.code === "password_change_required") redirect(`${CHANGE_PASSWORD_PATH}?next=${encodeURIComponent(here)}`);
      if (e.code === "account_restricted") redirect("/account/restricted");
      if (e.status === 401) redirect(`/login?next=${encodeURIComponent(here)}`);
    } else throw e;
  }
  return <ContinueRedirect area={area} portals={portals} fallback={fallback} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(ContinuePage__server, "app/continue/page.tsx#ContinuePage");
