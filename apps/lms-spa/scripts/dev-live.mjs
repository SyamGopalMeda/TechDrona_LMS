// `npm run dev:live`: the SPA on http://localhost:5173 with /api proxied to the live LMS API
// (vite.config.ts devProxy). Sign in with a live account; nothing is deployed.
// Override the target with TD_DEV_API_PROXY=https://other-host npm run dev:live.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const env = { ...process.env, TD_DEV_API_PROXY: process.env.TD_DEV_API_PROXY || "https://lmsapi-q3b3zuhb4a-el.a.run.app" };
console.log(`/api -> ${env.TD_DEV_API_PROXY}`);
const vite = fileURLToPath(new URL("../node_modules/vite/bin/vite.js", import.meta.url));
const child = spawn(process.execPath, [vite, ...process.argv.slice(2)], { env, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
