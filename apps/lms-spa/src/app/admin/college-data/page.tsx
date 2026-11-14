import { redirect } from "next/navigation";

/**
 * ADM-015 College Data Portal: the old embedded page. Since the cut-over (2026-11-14) the portal is the React
 * Outreach Portal at /colleges (full screen, its own CSP), so this URL only forwards there (a full page load:
 * spa/boundary.tsx + nav-store needsDocumentLoad).
 */
export default function Page() {
  redirect("/colleges");
}
