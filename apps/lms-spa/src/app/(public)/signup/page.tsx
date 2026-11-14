import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AuthCard, OrDivider } from "@/features/auth/components/shared";
import { SignupForm } from "@/features/auth/components/SignupForm";
import { GoogleSignIn } from "@/features/auth/components/GoogleSignIn";
import { safeNextPath } from "@/features/auth/lib/validation";
import { googleSignInConfig } from "@/lib/firebase/config";

export const metadata: Metadata = { title: "Create your account" };

/** PUB-011 sign-up with DOB age gate and itemised consents (AUTH-01). `?next=` is kept (FE-10). */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const next = typeof sp.next === "string" ? safeNextPath(sp.next, "") || null : null;
  const google = googleSignInConfig();
  return (
    <AuthCard title="Create your account">
      {google ? (
        <>
          <GoogleSignIn config={google} next={next} staffHint={false} />
          <OrDivider />
        </>
      ) : null}
      <SignupForm next={next} />
    </AuthCard>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/signup/page.tsx#Page");
