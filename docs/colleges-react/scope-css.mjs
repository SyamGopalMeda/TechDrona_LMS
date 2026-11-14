// Scope the portal CSS under `.tdp` (see apps/lms-spa/src/features/colleges/styles/README in PORTING-GUIDE).
// usage: node scope-css.mjs <in.css> <out.css>
import { readFileSync, writeFileSync } from "node:fs";

const [, , inFile, outFile] = process.argv;
let css = readFileSync(inFile, "utf8");
// keep only the first header comment; drop the rest (smaller output, simpler parsing)
css = css.replace(/\/\*[\s\S]*?\*\//g, "");

function splitTop(s, sep) {
  const out = [];
  let depth = 0, quote = null, cur = "";
  for (const ch of s) {
    if (quote) { cur += ch; if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") depth--;
    if (ch === sep && depth === 0) { out.push(cur); cur = ""; continue; }
    cur += ch;
  }
  out.push(cur);
  return out;
}

function scopeSelector(sel) {
  let s = sel.trim().replace(/\s+/g, " ");
  if (!s) return s;
  s = s.replace(/\[data-theme(?=[\]=])/g, "[data-tdp-theme");
  const lead = s.match(/^(:root|html|body)(?=$|[\s[:.>+~])/);
  if (lead) return ".tdp" + s.slice(lead[0].length);
  if (s.startsWith("[data-tdp-theme")) return ".tdp" + s;
  return ".tdp " + s;
}

// returns [text, endIndex]
function parseBlock(s, i, verbatim) {
  let out = "";
  while (i < s.length) {
    // skip whitespace
    while (i < s.length && /\s/.test(s[i])) i++;
    if (i >= s.length) break;
    if (s[i] === "}") return [out, i + 1];
    // read prelude
    let j = i, quote = null, paren = 0;
    while (j < s.length) {
      const ch = s[j];
      if (quote) { if (ch === quote) quote = null; j++; continue; }
      if (ch === '"' || ch === "'") { quote = ch; j++; continue; }
      if (ch === "(") paren++;
      if (ch === ")") paren--;
      if (paren === 0 && (ch === "{" || ch === ";" || ch === "}")) break;
      j++;
    }
    const prelude = s.slice(i, j).trim();
    if (s[j] === ";" || s[j] === "}") {
      // a declaration (inside a rule) or an at-statement
      out += prelude + (s[j] === ";" ? ";" : "");
      i = s[j] === ";" ? j + 1 : j;
      continue;
    }
    // block
    const body = findBlockEnd(s, j + 1);
    const inner = s.slice(j + 1, body);
    if (verbatim) {
      out += `${prelude}{${inner.trim().replace(/\s+/g, " ")}}`;
    } else if (/^@(media|supports|container|layer)\b/.test(prelude)) {
      const [txt] = parseBlock(inner + "}", 0, false);
      out += `${prelude}{${txt}}\n`;
    } else if (/^@(-webkit-)?keyframes\b|^@font-face\b|^@page\b/.test(prelude)) {
      out += `${prelude}{${inner.trim().replace(/\s+/g, " ")}}\n`;
    } else {
      const sels = splitTop(prelude, ",").map(scopeSelector).join(",");
      out += `${sels}{${inner.trim().replace(/\s+/g, " ")}}\n`;
    }
    i = body + 1;
  }
  return [out, i];
}

function findBlockEnd(s, i) {
  let depth = 1, quote = null;
  for (; i < s.length; i++) {
    const ch = s[i];
    if (quote) { if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === "{") depth++;
    if (ch === "}") { depth--; if (depth === 0) return i; }
  }
  throw new Error("unbalanced braces");
}

const [result] = parseBlock(css, 0, false);
const name = inFile.split(/[\\/]/).pop();
writeFileSync(
  outFile,
  `/* GENERATED from apps/college-data/portal/public/css/${name} by docs/colleges-react/scope-css.mjs: every selector is scoped under .tdp\n   (the portal root), html/:root/body map to .tdp itself, [data-theme] becomes [data-tdp-theme]. Edit the port, not the source. */\n${result}`,
);
console.log(`${name}: ${result.length} bytes`);
