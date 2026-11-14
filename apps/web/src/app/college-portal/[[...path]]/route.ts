import { handleCollegePortalRequest } from "@/lib/college-portal/proxy";

/**
 * College Data Portal proxy: /college-portal/* → TD_COLLEGE_PORTAL_URL. Every request is
 * authenticated against the LMS session and limited to Admin-portal users; the LMS session
 * cookie is never forwarded. Excluded from middleware (the portal sends its own CSP).
 * See src/lib/college-portal/proxy.ts.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const handler = (request: Request): Promise<Response> => handleCollegePortalRequest(request);

export { handler as GET, handler as HEAD, handler as POST, handler as PUT, handler as PATCH, handler as DELETE };
