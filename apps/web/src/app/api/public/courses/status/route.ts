import { handlePublicAdmissions } from "@/lib/bff/public-admissions";

/**
 * Website -> LMS course registration status (open / coming soon / closed), cross-origin and
 * cookie-less with the same strict CORS allow-list as the admissions bridge
 * (src/lib/bff/public-admissions.ts). Same-origin LMS pages use /api/v1/public/courses/status.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const handler = (request: Request): Promise<Response> => handlePublicAdmissions(request);

export { handler as GET, handler as OPTIONS };
