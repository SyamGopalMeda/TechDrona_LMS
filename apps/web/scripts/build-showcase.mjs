#!/usr/bin/env node
/**
 * Static showcase for Firebase Hosting (docs/firebase/MIGRATION-PLAN.md §5.3 option S1, P1).
 *
 * The real app cannot be statically exported (nonce CSP middleware, BFF route handlers,
 * cookies, per-request rendering). Instead this script SNAPSHOTS the public marketing pages
 * from a running LMS web server (default: the dev stack on http://localhost:13000, i.e. the
 * seeded catalogue) and writes plain HTML + CSS + images to `out/showcase/`:
 *
 * - every <script> is removed (no hydration, no API calls, no cookies), so the hosting CSP can
 *   be `script-src 'none'` — no 'unsafe-inline' exception is needed;
 * - the enquiry form is replaced by a "static demo: email us" notice (nothing can be POSTed);
 * - a demo banner is added to each page; links to sign-in, signup and the portals are sent to
 *   /demo by firebase.json redirects;
 * - assets referenced by the pages and their CSS are copied (public/ except the Monaco vendor
 *   bundle, /_next/static CSS/fonts/media).
 *
 * Usage (from apps/web):  node scripts/build-showcase.mjs [--source http://localhost:13000]
 * Deploy (owner, after `firebase login`):  see docs/firebase/p1.md.
 */

import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "..");
const OUT = path.join(WEB, "out", "showcase");
const argSource = process.argv.indexOf("--source");
const SOURCE = (argSource > 0 ? process.argv[argSource + 1] : process.env.TD_SHOWCASE_SOURCE) || "http://localhost:13000";
const CONTACT_EMAIL = process.env.TD_SHOWCASE_CONTACT_EMAIL || "info@techdrona.com";
const LIVE_URL = process.env.TD_SHOWCASE_LIVE_URL || "https://techdrona.in";

/** Public marketing pages (portals, auth and token pages are never exported). */
const PAGES = [
  "/",
  "/courses",
  "/pricing",
  "/placement",
  "/companies",
  "/free-resources",
  "/enquiries",
  "/help",
  "/help/grievance",
  "/legal/terms",
  "/legal/privacy",
  "/legal/refund-policy",
  "/legal/device-policy",
];
const COURSE_LINK = /href="(\/courses\/[a-z0-9][a-z0-9-]{0,80})"/g;

const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const BANNER = `<div role="note" style="background:#032269;color:#fff;font:600 14px/1.4 'Plus Jakarta Sans',system-ui,sans-serif;padding:10px 16px;text-align:center">
Demo preview of the Tech Drona LMS. Sign-in, sign-up and payments are turned off here.
Questions? <a href="mailto:${escapeHtml(CONTACT_EMAIL)}" style="color:#fff;text-decoration:underline">${escapeHtml(CONTACT_EMAIL)}</a></div>`;

const ENQUIRY_NOTICE = `<div role="note" style="border:1px solid #c9d3e6;border-radius:12px;padding:16px;background:#f3f6fb;color:#0b1b3f">
<p style="margin:0 0 8px;font-weight:600">This demo can't send the form.</p>
<p style="margin:0">Email your enquiry to <a href="mailto:${escapeHtml(CONTACT_EMAIL)}?subject=${encodeURIComponent("Corporate training enquiry")}" style="color:#032269;text-decoration:underline">${escapeHtml(CONTACT_EMAIL)}</a> with your company name, team size and what you'd like your team to learn. We reply within two working days.</p></div>`;

const assets = new Set();

function collectAssets(html) {
  for (const m of html.matchAll(/(?:href|src)="(\/[^"#?]+\.(?:css|woff2?|png|jpe?g|gif|webp|svg|ico|avif))"/g)) assets.add(m[1]);
  for (const m of html.matchAll(/srcSet="([^"]+)"/gi)) {
    for (const part of m[1].split(",")) {
      const u = part.trim().split(/\s+/)[0];
      if (u?.startsWith("/") && !u.startsWith("/_next/image")) assets.add(u.split("?")[0]);
    }
  }
}

/** End index (exclusive) of the element whose `<div` starts at `start` (balanced divs). */
function divEnd(html, start) {
  const re = /<div\b|<\/div>/gi;
  re.lastIndex = start;
  let depth = 0;
  for (let m = re.exec(html); m; m = re.exec(html)) {
    depth += m[0].toLowerCase() === "</div>" ? -1 : 1;
    if (depth === 0) return m.index + m[0].length;
  }
  return -1;
}

/** End index (exclusive) of the Suspense boundary comment opened at `start` (`<!--$?-->`). */
function boundaryEnd(html, start) {
  const re = /<!--\$[?!]?-->|<!--\/\$-->/g;
  re.lastIndex = start;
  let depth = 0;
  for (let m = re.exec(html); m; m = re.exec(html)) {
    depth += m[0] === "<!--/$-->" ? -1 : 1;
    if (depth === 0) return m.index + m[0].length;
  }
  return -1;
}

/** Removes `<div hidden id="<id>">…</div>` and returns its inner HTML (null if absent). */
function takeSegment(state, id) {
  const re = new RegExp(`<div hidden(?:="")? id="${id.replace(/[^A-Za-z0-9:]/g, "")}">`);
  const m = re.exec(state.html);
  if (!m) return null;
  const end = divEnd(state.html, m.index);
  if (end < 0) return null;
  const inner = state.html.slice(m.index + m[0].length, end - "</div>".length);
  state.html = state.html.slice(0, m.index) + state.html.slice(end);
  return inner;
}

/**
 * Streamed Suspense content arrives in hidden `<div hidden id="S:n">` segments that React's
 * inline scripts move into place: `$RS("S:n","P:m")` fills a `<template id="P:m">` placeholder
 * and `$RC("B:k","S:n")` replaces the `<!--$?--><template id="B:k">fallback<!--/$-->` boundary.
 * Without scripts, replay those operations here (in document order) so the content is visible.
 */
export function resolveSuspense(html) {
  const ops = [...html.matchAll(/\$R([SC])\("([A-Za-z]:[0-9a-z]+)","([A-Za-z]:[0-9a-z]+)"\)/g)];
  const state = { html };
  for (const [, kind, a, b] of ops) {
    if (kind === "S") {
      const content = takeSegment(state, a);
      const marker = `<template id="${b}"></template>`;
      if (content !== null) state.html = state.html.replace(marker, () => content);
    } else {
      const content = takeSegment(state, b);
      const marker = `<template id="${a}"></template>`;
      const at = state.html.indexOf(marker);
      if (content === null || at < 0) continue;
      const open = state.html.lastIndexOf("<!--$?-->", at);
      const end = open >= 0 ? boundaryEnd(state.html, open) : -1;
      state.html =
        open < 0 || end < 0
          ? state.html.slice(0, at) + content + state.html.slice(at + marker.length)
          : `${state.html.slice(0, open)}<!--$-->${content}<!--/$-->${state.html.slice(end)}`;
    }
  }
  return state.html;
}

/** Static-only HTML: no scripts, no preloads of scripts, no nonces; enquiry form replaced. */
export function staticHtml(html, route) {
  let out = resolveSuspense(html)
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<link\b[^>]*rel="(?:modulepreload|preload)"[^>]*as="script"[^>]*>/gi, "")
    .replace(/<link\b[^>]*as="script"[^>]*rel="preload"[^>]*>/gi, "")
    .replace(/\snonce="[^"]*"/gi, "")
    // Next/Image optimiser URLs cannot work on a static host: use the original file.
    .replace(/\/_next\/image\?url=([^&"]+)[^"]*/g, (_m, u) => decodeURIComponent(u))
    .replace(/\ssrcSet="[^"]*"/gi, "");
  if (route === "/enquiries") out = out.replace(/<form\b[\s\S]*?<\/form>/i, ENQUIRY_NOTICE);
  out = out.replace(/<body([^>]*)>/i, `<body$1>${BANNER}`);
  return out;
}

async function fetchText(url) {
  const res = await fetch(url, { headers: { accept: "text/html", "user-agent": "td-showcase-snapshot/1" }, redirect: "manual" });
  return { status: res.status, text: res.status === 200 ? await res.text() : "" };
}

function fileFor(route) {
  if (route === "/") return "index.html";
  return `${route.slice(1)}.html`; // cleanUrls: /courses -> courses.html, /courses/x -> courses/x.html
}

async function writeOut(rel, data) {
  const file = path.join(OUT, rel);
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, data);
}

async function copyAsset(urlPath) {
  const res = await fetch(new URL(urlPath, SOURCE));
  if (!res.ok) {
    console.warn(`  asset ${urlPath}: HTTP ${res.status} (skipped)`);
    return;
  }
  const buf = Buffer.from(await res.arrayBuffer());
  if (urlPath.endsWith(".css")) {
    for (const m of buf.toString("utf8").matchAll(/url\((?:"|')?(\/[^)"'?#]+)/g)) {
      if (!assets.has(m[1])) {
        assets.add(m[1]);
        await copyAsset(m[1]);
      }
    }
  }
  await writeOut(urlPath.slice(1), buf);
}

function demoPage(css) {
  const links = css.map((h) => `<link rel="stylesheet" href="${h}">`).join("");
  return `<!doctype html><html lang="en-IN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo preview · Tech Drona</title><link rel="icon" href="/favicon-32.png">${links}</head>
<body style="background:#faf8f4;margin:0">${BANNER}
<main id="main" style="max-width:560px;margin:48px auto;padding:0 16px;font-family:'Plus Jakarta Sans',system-ui,sans-serif;color:#0b1b3f">
<h1 style="font-size:28px;margin:0 0 12px">This part needs the full app</h1>
<p>You're looking at a static preview of the Tech Drona LMS. Signing in, creating an account, buying a course and the learner and staff portals run on the full application, which isn't part of this preview.</p>
<p>To see a live walkthrough or to get access, email <a href="mailto:${escapeHtml(CONTACT_EMAIL)}">${escapeHtml(CONTACT_EMAIL)}</a> or visit <a href="${escapeHtml(LIVE_URL)}">${escapeHtml(LIVE_URL.replace(/^https?:\/\//, ""))}</a>.</p>
<p><a href="/">Back to the home page</a> · <a href="/courses">Browse courses</a></p></main></body></html>`;
}

async function main() {
  process.stdout.write(`Snapshotting public pages from ${SOURCE} -> ${path.relative(WEB, OUT)}\n`);
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });
  await cp(path.join(WEB, "public"), OUT, {
    recursive: true,
    filter: (src) => !src.split(path.sep).includes("vendor"),
  });

  const queue = [...PAGES];
  const done = new Set();
  const css = new Set();
  while (queue.length) {
    const route = queue.shift();
    if (done.has(route)) continue;
    done.add(route);
    const { status, text } = await fetchText(new URL(route, SOURCE).href);
    if (status !== 200) {
      console.warn(`  ${route}: HTTP ${status} (skipped)`);
      continue;
    }
    if (route === "/courses") for (const m of text.matchAll(COURSE_LINK)) queue.push(m[1]);
    collectAssets(text);
    for (const m of text.matchAll(/href="(\/_next\/static\/css\/[^"]+\.css)"/g)) css.add(m[1]);
    await writeOut(fileFor(route), staticHtml(text, route));
    process.stdout.write(`  ${route}\n`);
  }
  if (!done.has("/") || !css.size) throw new Error(`No pages captured from ${SOURCE}: is the LMS web server running?`);

  const nf = await fetch(new URL("/__showcase-not-found__", SOURCE));
  if (nf.status === 404) {
    const html = await nf.text();
    collectAssets(html);
    await writeOut("404.html", staticHtml(html, "/404"));
  }
  await writeOut("demo.html", demoPage([...css]));
  for (const a of [...assets]) await copyAsset(a);
  process.stdout.write(`Done: ${done.size} routes, ${assets.size} assets. Deploy: see docs/firebase/p1.md\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    console.error(e instanceof Error ? e.message : e);
    process.exit(1);
  });
}
