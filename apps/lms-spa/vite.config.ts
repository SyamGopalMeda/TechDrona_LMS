import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { loadBuildEnv, publicEnv } from "./scripts/build-env";

const src = (p: string) => fileURLToPath(new URL(`./src/${p}`, import.meta.url));

/** next/* imports used by the copied apps/web code resolve to small React Router shims. */
export const nextShimAliases = [
  { find: /^next$/, replacement: src("spa/shims/next.ts") },
  { find: /^next\/link$/, replacement: src("spa/shims/link.tsx") },
  { find: /^next\/navigation$/, replacement: src("spa/shims/navigation.ts") },
  { find: /^next\/dynamic$/, replacement: src("spa/shims/dynamic.tsx") },
  { find: /^server-only$/, replacement: src("spa/shims/server-only.ts") },
  { find: /^@\//, replacement: `${src("")}` },
];

/**
 * `vite dev` proxy for `/api`. A local API (http://localhost:8000) is proxied as is. A remote one
 * (e.g. TD_DEV_API_PROXY=https://lms.35-244-50-26.sslip.io, to run this SPA locally against the
 * live LMS API) gets its own Host, Origin and Referer, so its host routing and CSRF/origin checks
 * see a same-origin request; its host-only cookies then land on localhost.
 */
function devProxy(target: string) {
  const remote = !/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(target);
  if (!remote) return { target, changeOrigin: false };
  const origin = new URL(target).origin;
  return {
    target,
    changeOrigin: true,
    secure: true,
    configure: (proxy: { on: (ev: "proxyReq", cb: (req: { getHeader: (n: string) => unknown; setHeader: (n: string, v: string) => void }) => void) => void }) => {
      proxy.on("proxyReq", (req) => {
        if (req.getHeader("origin")) req.setHeader("origin", origin);
        const ref = req.getHeader("referer");
        if (typeof ref === "string") req.setHeader("referer", origin + new URL(ref).pathname);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  // Public env only (scripts/build-env.ts): Firebase values for builds, the root .env for dev.
  const env = publicEnv(loadBuildEnv(mode));
  const devApi = process.env.TD_DEV_API_PROXY; // e.g. http://localhost:8000 for `vite dev`
  return {
    plugins: [
      react(),
      {
        name: "td-html-app-name",
        transformIndexHtml: (html: string) => html.replaceAll("%TD_APP_NAME%", (env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona").replace(/[<>&"]/g, "")),
      },
    ],
    resolve: { alias: nextShimAliases },
    define: {
      __TD_BUILD_ENV__: JSON.stringify(env),
      // `process.env.X` and `env["X"]` lookups in the copied code read this object (src/spa/env.ts).
      "process.env": "globalThis.__TD_ENV__",
    },
    build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
    server: devApi ? { proxy: { "/api": devProxy(devApi) } } : undefined,
  };
});
