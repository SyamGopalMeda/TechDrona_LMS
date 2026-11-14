// @vitest-environment node
/**
 * FE-01 / FE-33 regression: no public page is a "Not yet implemented" placeholder, and public
 * pages do not print internal screen IDs (PUB-0xx) as visible eyebrows.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const PUBLIC_DIR = path.resolve(__dirname, "../../app/(public)");

function pages(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    return e.isDirectory() ? pages(full) : e.name === "page.tsx" ? [full] : [];
  });
}

describe("public pages", () => {
  const files = pages(PUBLIC_DIR);

  it("covers the sitemap routes that used to be placeholders", () => {
    const rel = files.map((f) => path.relative(PUBLIC_DIR, f).replace(/\\/g, "/"));
    for (const r of [
      "enquiries/page.tsx",
      "companies/page.tsx",
      "companies/[slug]/page.tsx",
      "free-resources/page.tsx",
      "help/page.tsx",
      "help/[article]/page.tsx",
      "status/page.tsx",
      "placement/page.tsx",
      "placement/[subject]/[topic]/page.tsx",
      "legal/terms/page.tsx",
      "legal/privacy/page.tsx",
      "legal/refund-policy/page.tsx",
      "legal/device-policy/page.tsx",
      "verify/page.tsx",
    ]) {
      expect(rel).toContain(r);
    }
  });

  it.each(files.map((f) => [path.relative(PUBLIC_DIR, f), f]))("%s is not a placeholder and shows no screen id", (_rel, file) => {
    const src = fs.readFileSync(file, "utf8");
    expect(src).not.toMatch(/NotImplemented/);
    expect(src).not.toMatch(/eyebrow="(PUB|STU)-\d+"/);
    expect(src).not.toMatch(/>\s*PUB-\d+/);
  });
});
