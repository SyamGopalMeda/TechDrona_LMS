import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AuthCard, OrDivider } from "@/features/auth/components/shared";
import { LoginForm } from "@/features/auth/components/LoginForm";
import { GoogleSignIn } from "@/features/auth/components/GoogleSignIn";
import { safeNextPath } from "@/features/auth/lib/validation";
import { redirect } from "next/navigation";
import { ACCEPT_TERMS_PATH, CHANGE_PASSWORD_PATH, isRequiredConsentProblem } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { hasSessionCookie, serverApiGet } from "@/lib/api/server";
import { googleSignInConfig } from "@/lib/firebase/config";

export const metadata: Metadata = { title: "Log in" };

const REASONS: Record<string, string> = {
  unauthenticated: "Please log in to continue.",
  session_expired: "Your session timed out. Please log in again.",
  session_revoked: "You were signed out. Please log in again.",
  session_cap_evicted:
    "You were signed out because your account signed in on another device and only a limited number of devices can stay signed in at once. Please log in again.",
};

/** PUB-012. The API client redirects here with `?next=<path>&reason=<code>`. */
async function LoginPage__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const reason = typeof sp.reason === "string" ? REASONS[sp.reason] : undefined;
  const next = typeof sp.next === "string" ? safeNextPath(sp.next) : undefined;
  // Already signed in (e.g. the website's account icon): don't ask again — go where they were
  // heading, else resume the last page (/continue). A half-finished sign-in (401 login_incomplete,
  // MFA enrolment, …) or any api error still shows the form.
  const state = sp.reason ? "no" : await signedIn();
  // Signed in but the admin asked for a new password first (simple authentication).
  if (state === "change_password") redirect(`${CHANGE_PASSWORD_PATH}?next=${encodeURIComponent(next ?? "/continue")}`);
  if (state === "accept_terms") redirect(`${ACCEPT_TERMS_PATH}?next=${encodeURIComponent(next ?? "/continue")}`);
  if (state === "yes") redirect(next ?? "/continue");
  // Google sign-in (students): runtime config, hidden when not configured or switched off.
  const google = googleSignInConfig();
  return (
    <div className="space-y-4">
      {reason ? (
        <p role="status" className="mx-auto max-w-[480px] rounded-md border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          {reason}
        </p>
      ) : null}
      <AuthCard title="Log in" description="Welcome back. Pick up where you left off.">
        {google ? (
          <>
            <GoogleSignIn config={google} next={next} />
            <OrDivider />
          </>
        ) : null}
        <LoginForm next={next} />
      </AuthCard>
    </div>
  );
}

async function signedIn(): Promise<"yes" | "no" | "change_password" | "accept_terms"> {
  if (!(await hasSessionCookie())) return "no";
  try {
    await serverApiGet("me/grants");
    return "yes";
  } catch (e) {
    if (e instanceof ApiError && e.code === "password_change_required") return "change_password";
    if (e instanceof ApiError && isRequiredConsentProblem(e.problem)) return "accept_terms";
    return "no";
  }
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(LoginPage__server, "app/(public)/login/page.tsx#LoginPage");
