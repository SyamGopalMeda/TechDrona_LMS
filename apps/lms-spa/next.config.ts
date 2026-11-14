import { hostingHeaders } from "./src/spa/hosting-headers";

/**
 * Not a Next config: the SPA's Hosting header rules in the shape of next.config.ts `headers()`,
 * so the copied apps/web test (src/lib/firebase/firebase.test.ts, COOP rules) runs unchanged.
 * The source of truth is src/spa/hosting-headers.ts (→ hosting-headers.json for firebase.json).
 */
const config = {
  async headers() {
    return hostingHeaders({}).map((r) => ({ source: r.source.replace(/\/\*\*$/, "/:path*"), headers: r.headers }));
  },
};

export default config;
