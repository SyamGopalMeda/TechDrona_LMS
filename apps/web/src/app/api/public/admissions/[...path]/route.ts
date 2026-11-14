import { handlePublicAdmissions } from "@/lib/bff/public-admissions";

/**
 * Website → LMS admissions bridge (cross-origin, cookie-less, strict CORS allow-list). See
 * src/lib/bff/public-admissions.ts. The authenticated /api/v1 BFF and its CSRF checks are not
 * involved and unchanged.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const handler = (request: Request): Promise<Response> => handlePublicAdmissions(request);

export { handler as GET, handler as POST, handler as OPTIONS };
