import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { LoginForm } from "@/features/auth/components/LoginForm";
import { safeNextPath } from "@/features/auth/lib/validation";

export const metadata: Metadata = { title: "Log in" };

const REASONS: Record<string, string> = {
  unauthenticated: "Please log in to continue.",
  session_expired: "Your session timed out. Please log in again.",
  session_revoked: "You were signed out. Please log in again.",
};

/** PUB-012. The API client redirects here with `?next=<path>&reason=<code>`. */
export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const reason = typeof sp.reason === "string" ? REASONS[sp.reason] : undefined;
  const next = typeof sp.next === "string" ? safeNextPath(sp.next) : undefined;
  return (
    <div className="space-y-4">
      {reason ? (
        <p role="status" className="mx-auto max-w-[480px] rounded-md border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          {reason}
        </p>
      ) : null}
      <AuthCard title="Sign in">
        <LoginForm next={next} />
      </AuthCard>
    </div>
  );
}
