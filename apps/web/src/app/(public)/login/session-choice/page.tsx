import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { SessionChoice } from "@/features/auth/components/SessionChoice";

export const metadata: Metadata = { title: "Choose a session to sign out" };

/** PUB-012 session-cap chooser (AUTH-14, FR-SES-006; copy DS §9.4). */
export default function Page() {
  return (
    <AuthCard title="You're signed in on too many devices" description="Sign out of one to continue here.">
      <SessionChoice />
    </AuthCard>
  );
}
