import { asyncComponent } from "@/spa/async";
import { redirect } from "next/navigation";
import { hasSessionCookie } from "@/lib/api/server";
import { WebsiteSso } from "@/features/hub/WebsiteSso";

export const dynamic = "force-dynamic";
export const metadata = { title: "Opening the website admin", robots: { index: false, follow: false } };

/** Module switch into the Company Website Admin Panel (single sign-on, see WebsiteSso). */
async function WebsiteSsoPage__server() {
  if (!(await hasSessionCookie())) redirect("/login?next=%2Fsso%2Fwebsite");
  return <WebsiteSso />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(WebsiteSsoPage__server, "app/sso/website/page.tsx#WebsiteSsoPage");
