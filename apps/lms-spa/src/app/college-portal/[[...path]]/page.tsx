import { redirect } from "next/navigation";

/**
 * SPA-only: Hosting redirects the old portal entry (/college-portal, /college-portal/index.html) to /colleges and
 * rewrites the rest of /college-portal/** (the data API) to lmsApi, so the LMS app reaches this route only by a
 * stray client navigation. Old portal links all land on the React Outreach Portal home. (An old
 * `index.html#/college/123` hash link cannot be mapped: the hash never reaches the server.)
 */
export default function Page() {
  redirect("/colleges");
}
