import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { PublicStatusCheck } from "@/features/registration/components/PublicStatusCheck";

export const metadata: Metadata = {
  title: "Check my registration",
  description: "Check the status of your Tech Drona course registration with your registration number and email.",
};

type Search = Promise<Record<string, string | string[] | undefined>>;
const one = (v: string | string[] | undefined) => (typeof v === "string" && v.length <= 160 ? v : "");

/** Public registration status lookup: registration number + email. */
async function Page__server({ searchParams }: { searchParams: Search }) {
  const sp = await searchParams;
  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        eyebrow="Course registration"
        title="Check my registration"
        description="Enter the registration number from your confirmation and the email you registered with."
        back={{ href: "/register", label: "Courses" }}
      />
      <PublicStatusCheck initialRegNo={one(sp.reg_no)} initialEmail={one(sp.email)} />
      <p className="mt-6 text-center text-sm text-fg-secondary">
        Got your LMS login?{" "}
        <Link href="/login" className="font-semibold text-brand">
          Log in
        </Link>
      </p>
    </div>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/register/status/page.tsx#Page");
