import type { Metadata } from "next";
import { HelpCentre } from "@/features/public/components/HelpCentre";
import { hasSessionCookie } from "@/lib/api/server";

export const metadata: Metadata = { title: "Help", description: "Help centre: account, devices, refunds, certificates, contact and grievance officer." };

/** PUB-019 help centre (static articles + contact routes + grievance officer). */
export default async function Page() {
  return <HelpCentre signedIn={await hasSessionCookie()} />;
}
