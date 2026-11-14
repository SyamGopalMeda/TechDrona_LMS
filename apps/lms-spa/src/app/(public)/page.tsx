import { asyncComponent } from "@/spa/async";
import { redirect } from "next/navigation";
import { homeRedirect, probeSession } from "@/spa/session";

/**
 * The LMS host's `/` has no page of its own: signed in → `/modules`, otherwise `/login`. A
 * document load of `/` is already redirected at app start (src/spa/main.tsx); this covers
 * client-side links to `/` (e.g. the logo on `/read/[id]`). The marketing home is the website.
 */
async function HomeRedirect__server(): Promise<never> {
  redirect(homeRedirect("/", await probeSession()) ?? "/login");
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(HomeRedirect__server, "app/(public)/page.tsx#HomeRedirect");
