import { handleBffRequest } from "@/lib/bff/proxy";

/**
 * Same-origin BFF (ADR-0010): every browser call to /api/v1/* lands here and is proxied
 * to the internal api service after CSRF + Fetch-Metadata checks. See src/lib/bff/proxy.ts
 * and README.md "BFF". /api/v1/webhooks/* is NOT served here (404): the load balancer
 * routes it straight to api-webhooks.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const handler = (request: Request): Promise<Response> => handleBffRequest(request);

export { handler as GET, handler as HEAD, handler as POST, handler as PUT, handler as PATCH, handler as DELETE, handler as OPTIONS };
