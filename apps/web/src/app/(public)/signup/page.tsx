import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { SignupForm } from "@/features/auth/components/SignupForm";
import { safeNextPath } from "@/features/auth/lib/validation";

export const metadata: Metadata = { title: "Create your account" };

/** PUB-011 sign-up with DOB age gate and itemised consents (AUTH-01). `?next=` is kept (FE-10). */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const next = typeof sp.next === "string" ? safeNextPath(sp.next, "") || null : null;
  return (
    <AuthCard title="Create your account">
      <SignupForm next={next} />
    </AuthCard>
  );
}
