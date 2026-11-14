import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { HelpCentre } from "@/features/public/components/HelpCentre";
import { hasSessionCookie } from "@/lib/api/server";

export const metadata: Metadata = { title: "Help", description: "Help centre: account, devices, refunds, certificates, contact and grievance officer." };

/** PUB-019 help centre (static articles + contact routes + grievance officer). */
async function Page__server() {
  return <HelpCentre signedIn={await hasSessionCookie()} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/(public)/help/page.tsx#Page");
