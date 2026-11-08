import type { NextConfig } from "next";

/**
 * Security headers that do not depend on a per-request nonce. The nonce-based
 * Content-Security-Policy is set per request in `src/middleware.ts`.
 */
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(self)" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  // Standalone output for the container image (apps/web/Dockerfile is owned by DevOps).
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // Typed routes are not enabled: portal agents add routes concurrently.
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // Aliases: the PRD route prefixes are canonical (/security, /verify/[certificate_id]).
  async redirects() {
    return [
      { source: "/admin/security", destination: "/security", permanent: false },
      { source: "/admin/security/:path*", destination: "/security/:path*", permanent: false },
      { source: "/verify/certificate/:id", destination: "/verify/:id", permanent: false },
    ];
  },
};

export default nextConfig;
