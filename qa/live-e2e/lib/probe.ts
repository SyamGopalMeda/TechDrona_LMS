import type { Page, TestInfo } from "@playwright/test";

/** Collects console errors, failed API calls and page errors while a page is visited. */
export function watch(page: Page) {
  const errors: string[] = [];
  const api: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 300)); });
  page.on("pageerror", (e) => errors.push(`pageerror: ${String(e).slice(0, 300)}`));
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/api/") && r.status() >= 400) api.push(`${r.status()} ${r.request().method()} ${u.split("/api/")[1]?.slice(0, 160)}`);
  });
  return { errors, api, reset() { errors.length = 0; api.length = 0; } };
}

/**
 * One layout problem. `kind`:
 * - hscroll: the page scrolls sideways; overflow: an element sticks out of the viewport (no scroll/clip ancestor);
 * - table: a table wider than its container without its own scroll container;
 * - clip: text cut off by overflow hidden without an ellipsis; font: visible text under 11px;
 * - tap: touch target under 24px (not inline text); tap-inline: small inline text link (WCAG 2.5.8 exception, info only);
 * - overlap: two interactive elements overlapping; under-header: content hidden under the sticky header at scroll 0;
 * - under-tabbar: the end of the page cannot be scrolled clear of the fixed mobile tab bar;
 * - fixed-overlap: two fixed/sticky bars on top of each other; fixed-overflow: a fixed layer (cookie banner, toast) sticking out of the viewport;
 * - text-overflow: text spilling out of its own box (overflow visible), e.g. a long word in a narrow card.
 */
export interface LayoutIssue { kind: string; detail: string }

/** Every layout check at the current viewport (scrolls to the bottom and back for the tab bar check). */
export async function layoutReport(page: Page): Promise<LayoutIssue[]> {
  return page.evaluate(async () => {
    const out: { kind: string; detail: string }[] = [];
    const de = document.documentElement;
    const vw = de.clientWidth;
    const vh = window.innerHeight;
    const touch = matchMedia("(pointer: coarse)").matches;
    const add = (kind: string, detail: string, cap = 6) => { if (out.filter((o) => o.kind === kind).length < cap) out.push({ kind, detail }); };
    const label = (el: Element) => {
      const cls = typeof el.className === "string" ? el.className.split(/\s+/).filter(Boolean).slice(0, 3).join(".") : "";
      const txt = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
      return `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${cls ? "." + cls : ""}${txt ? ` "${txt}"` : ""}`;
    };
    // closed <details> content still reports a layout box in Chromium (content-visibility), so skip it
    const hiddenish = (el: Element) => !!el.closest(".sr-only, [hidden], [inert], .z-skip-link") || (!!el.closest("details:not([open])") && !el.closest("summary"));
    const shown = (el: Element) => {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return null;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0) return null;
      if (hiddenish(el)) return null;
      return r;
    };
    const fixedLike = (el: Element) => { for (let p: Element | null = el; p && p !== document.body; p = p.parentElement) { const pos = getComputedStyle(p).position; if (pos === "fixed") return true; } return false; };
    const scrollAncestor = (el: Element) => { for (let p = el.parentElement; p && p !== document.body && p !== de; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === "auto" || o === "scroll" || o === "hidden" || o === "clip") return p; } return null; };
    const main = document.querySelector("main") ?? document.body;
    window.scrollTo(0, 0);
    await new Promise((r) => requestAnimationFrame(() => r(null)));

    if (de.scrollWidth > vw + 1) add("hscroll", `page ${de.scrollWidth}px > viewport ${vw}px`);

    const all = Array.from(document.querySelectorAll("body *"));
    // overflow: only the outermost offender of each subtree
    const offenders = new Set<Element>();
    for (const el of all) {
      const r = shown(el); if (!r) continue;
      if (r.right <= vw + 2 && r.left >= -2) continue;
      if (fixedLike(el) || scrollAncestor(el)) continue;
      if (el.parentElement && offenders.has(el.parentElement)) { offenders.add(el); continue; }
      offenders.add(el);
      add("overflow", `${label(el)} spans ${Math.round(r.left)}..${Math.round(r.right)} (vw ${vw})`);
    }
    for (const t of Array.from(document.querySelectorAll("table"))) {
      const r = shown(t); if (!r) continue;
      const box = t.parentElement?.getBoundingClientRect();
      if (box && r.width > box.width + 2 && !scrollAncestor(t)) add("table", `${label(t).slice(0, 80)} ${Math.round(r.width)}px in ${Math.round(box.width)}px container, no scroll wrapper`);
      else if (r.right > vw + 2 && !scrollAncestor(t)) add("table", `${label(t).slice(0, 80)} right=${Math.round(r.right)} > vw ${vw}`);
    }
    for (const el of all) {
      if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && (n.textContent ?? "").trim().length > 2)) continue;
      const r = shown(el); if (!r) continue;
      const cs = getComputedStyle(el);
      const ox = cs.overflowX, oy = cs.overflowY;
      const he = el as HTMLElement;
      if ((ox === "hidden" || ox === "clip") && he.scrollWidth > he.clientWidth + 2 && cs.textOverflow !== "ellipsis") add("clip", `${label(el)} text ${he.scrollWidth}px in ${he.clientWidth}px box`);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const clamp = (cs as any).webkitLineClamp ?? "none";
      if ((oy === "hidden" || oy === "clip") && clamp === "none" && he.scrollHeight > he.clientHeight + 4 && cs.whiteSpace !== "nowrap") add("clip", `${label(el)} text ${he.scrollHeight}px tall in ${he.clientHeight}px box`);
      if (ox === "visible" && cs.display !== "inline" && he.scrollWidth > he.clientWidth + 4 && he.clientWidth > 0) add("text-overflow", `${label(el)} text ${he.scrollWidth}px in ${he.clientWidth}px box`);
      const fs = parseFloat(cs.fontSize);
      if (fs < 11 && r.top < de.scrollHeight) add("font", `${fs}px ${label(el)}`);
    }

    const targets: { el: Element; r: DOMRect }[] = [];
    for (const el of Array.from(document.querySelectorAll("a[href], button, [role=button], input:not([type=hidden]), select, textarea, summary"))) {
      const r = shown(el); if (!r) continue;
      targets.push({ el, r });
      if (!touch || (r.width >= 24 && r.height >= 24)) continue;
      const cs = getComputedStyle(el);
      const parentText = (el.parentElement?.textContent ?? "").trim().length;
      const inline = el.tagName === "A" && cs.display === "inline" && parentText > (el.textContent ?? "").trim().length + 3;
      add(inline ? "tap-inline" : "tap", `${Math.round(r.width)}x${Math.round(r.height)} ${label(el)}`, inline ? 4 : 8);
    }
    // overlapping interactive elements (first viewport, not nested), using the part not clipped by a scroll/overflow ancestor
    const clipRect = (el: Element, r: DOMRect) => {
      let l = r.left, t = r.top, rr = r.right, b = r.bottom;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (cs.overflowX !== "visible" || cs.overflowY !== "visible") { const q = p.getBoundingClientRect(); l = Math.max(l, q.left); t = Math.max(t, q.top); rr = Math.min(rr, q.right); b = Math.min(b, q.bottom); }
      }
      return { left: l, top: t, right: rr, bottom: b, w: rr - l, h: b - t };
    };
    const inView = targets.filter((t) => t.r.bottom > 0 && t.r.top < vh).slice(0, 300).map((t) => ({ ...t, c: clipRect(t.el, t.r) })).filter((t) => t.c.w > 2 && t.c.h > 2);
    const abs = (el: Element) => getComputedStyle(el).position === "absolute";
    for (let i = 0; i < inView.length; i++) for (let j = i + 1; j < inView.length; j++) {
      const a = inView[i]!, b = inView[j]!;
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      // icon buttons placed inside a field on purpose (show password, clear search)
      if ((abs(a.el) || abs(b.el)) && a.el.parentElement && (a.el.parentElement.contains(b.el) || b.el.parentElement?.contains(a.el))) continue;
      const w = Math.min(a.c.right, b.c.right) - Math.max(a.c.left, b.c.left);
      const h = Math.min(a.c.bottom, b.c.bottom) - Math.max(a.c.top, b.c.top);
      if (w <= 2 || h <= 2) continue;
      const small = Math.min(a.c.w * a.c.h, b.c.w * b.c.h);
      if (w * h > 0.25 * small) add("overlap", `${label(a.el).slice(0, 60)} ⟷ ${label(b.el).slice(0, 60)}`);
    }
    // fixed layers (cookie banners, toasts, bars) sticking out of the viewport
    for (const el of all) {
      const r = shown(el); if (!r || !fixedLike(el)) continue;
      if (r.right <= vw + 2 && r.left >= -2) continue;
      if (scrollAncestor(el)) continue;
      if (el.parentElement && offenders.has(el.parentElement)) { offenders.add(el); continue; }
      offenders.add(el);
      add("fixed-overflow", `${label(el)} spans ${Math.round(r.left)}..${Math.round(r.right)} (vw ${vw})`);
    }
    // content under the sticky top bar at scroll 0
    const header = Array.from(document.querySelectorAll("header")).find((h) => { const p = getComputedStyle(h).position; return p === "sticky" || p === "fixed"; });
    const hb = header?.getBoundingClientRect();
    if (hb && hb.height > 0 && main !== document.body) {
      const mr = main.getBoundingClientRect();
      if (mr.top < hb.bottom - 2) add("under-header", `main top ${Math.round(mr.top)} < header bottom ${Math.round(hb.bottom)}`);
    }
    // fixed / sticky bars overlapping each other
    const bars = all.filter((el) => { const cs = getComputedStyle(el); return (cs.position === "fixed" || cs.position === "sticky") && cs.pointerEvents !== "none" && (el.textContent ?? "").trim().length > 0 && shown(el); }).filter((el) => !el.parentElement?.closest("[data-td-tabbar], header"));
    for (let i = 0; i < bars.length; i++) for (let j = i + 1; j < bars.length; j++) {
      const a = bars[i]!, b = bars[j]!;
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      // full-screen scrims/overlays are expected to cover things
      if (ra.width * ra.height > 0.8 * vw * vh || rb.width * rb.height > 0.8 * vw * vh) continue;
      const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (w > 4 && h > 4) add("fixed-overlap", `${label(a).slice(0, 60)} ⟷ ${label(b).slice(0, 60)} (${Math.round(w)}x${Math.round(h)})`);
    }
    // the end of the page must scroll clear of the student tab bar
    const tab = document.querySelector("[data-td-tabbar]");
    const tr = tab && shown(tab);
    if (tr) {
      window.scrollTo(0, de.scrollHeight);
      await new Promise((r) => setTimeout(r, 150));
      const t2 = tab!.getBoundingClientRect();
      let worst: Element | null = null; let bottom = 0;
      for (const el of Array.from(main.querySelectorAll("*"))) {
        const r = shown(el); if (!r || el.children.length > 0 && !(el.matches("a,button,input,select,textarea"))) continue;
        if (r.bottom > bottom) { bottom = r.bottom; worst = el; }
      }
      if (worst && bottom > t2.top + 1) add("under-tabbar", `${label(worst).slice(0, 70)} bottom ${Math.round(bottom)} > tab bar top ${Math.round(t2.top)}`);
      window.scrollTo(0, 0);
    }
    return out;
  });
}

/** Layout problems at the current viewport as short strings (kept for older specs). Inline text links are left out. */
export async function layoutIssues(page: Page): Promise<string[]> {
  return (await layoutReport(page)).filter((i) => i.kind !== "tap-inline").map((i) => `${i.kind}: ${i.detail}`);
}

export async function shot(page: Page, info: TestInfo, name: string) {
  const file = info.outputPath(`${name.replace(/[^a-z0-9-]+/gi, "_").slice(0, 80)}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}
