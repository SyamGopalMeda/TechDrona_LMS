import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AuthCard } from "@/features/auth/components/shared";
import { RequiredPasswordChange } from "@/features/account/components/ChangePasswordForm";
import { safeNextPath } from "@/features/auth/lib/validation";
import { STAFF_LANDING } from "@/features/auth/lib/login-flow";
import { hasSessionCookie } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Choose a new password", robots: { index: false, follow: false } };

/**
 * Forced password change (admin ticked "Must change password on first login"). Target of
 * `403 password_change_required` (`change_url`) and of a login answering `must_change_password`.
 */
async function ChangePasswordPage__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const raw = typeof sp.next === "string" ? sp.next : undefined;
  let next = safeNextPath(raw, STAFF_LANDING);
  if (next === "/change-password" || next.startsWith("/change-password?")) next = STAFF_LANDING;
  if (!(await hasSessionCookie())) redirect(`/login?next=${encodeURIComponent("/change-password")}`);
  return (
    <AuthCard title="Choose a new password" description="Your admin asked you to choose your own password before you continue.">
      <RequiredPasswordChange next={next} />
    </AuthCard>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(ChangePasswordPage__server, "app/(public)/change-password/page.tsx#ChangePasswordPage");
