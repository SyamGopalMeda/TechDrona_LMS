// Shared helpers for the Tech Drona token build and contrast check.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const tokens = JSON.parse(readFileSync(join(ROOT, "tokens.json"), "utf8"));

/** Resolve "{color.neutral.50}" style references against tokens.color. */
export function resolve(value) {
  if (typeof value !== "string") return value;
  const m = value.match(/^\{color\.(.+)\}$/);
  if (!m) return value;
  let node = tokens.color;
  for (const part of m[1].split(".")) {
    if (node == null || !(part in node)) throw new Error(`Unresolved token reference ${value}`);
    node = node[part];
  }
  return resolve(node);
}

/** Flatten a semantic theme into [{name, path, value}] where name is the CSS variable suffix. */
export function flattenTheme(theme, prefix = []) {
  const out = [];
  for (const [k, v] of Object.entries(theme)) {
    const path = [...prefix, k];
    if (v && typeof v === "object") out.push(...flattenTheme(v, path));
    else {
      const name = path.filter((p) => p !== "DEFAULT").join("-");
      out.push({ name, path, value: resolve(v) });
    }
  }
  return out;
}

export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  return {
    r: parseInt(n.slice(0, 2), 16),
    g: parseInt(n.slice(2, 4), 16),
    b: parseInt(n.slice(4, 6), 16),
    a: n.length === 8 ? parseInt(n.slice(6, 8), 16) / 255 : 1,
  };
}

export function isOpaqueHex(v) {
  return typeof v === "string" && /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v);
}

function channel(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex) {
  const { r, g, b } = hexToRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrast(a, b) {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}
