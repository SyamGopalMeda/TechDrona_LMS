import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { nextShimAliases } from "./vite.config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: nextShimAliases },
  define: { __TD_BUILD_ENV__: "{}" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
