import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ServiceStatus, coreStatusFrom } from "@/features/public/components/ServiceStatus";
import type { ReadyDto } from "@/features/public/lib/types";
import { serverLoad } from "@/features/catalog/lib/server";
import { formatDateTime } from "@/features/catalog/lib/format";

export const metadata: Metadata = { title: "Service status" };

/** PUB-020: live readiness of the core platform (health/ready), probed per request. */
async function Page__server() {
  const result = await serverLoad<ReadyDto>("health/ready");
  return <ServiceStatus core={coreStatusFrom(result)} checkedAt={formatDateTime(new Date().toISOString())} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/status/page.tsx#Page");
