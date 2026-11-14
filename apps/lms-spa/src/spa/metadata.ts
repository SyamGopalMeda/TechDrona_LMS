/**
 * Next `metadata` / `generateMetadata` → document head. Only the fields the app uses are applied:
 * title (with the root layout's `%s · App` template), description and robots.
 */
import type { Metadata, MetadataTitle } from "next";

export interface MetadataTemplate {
  default: string;
  template: string | null;
}

export function resolveTitle(title: MetadataTitle | undefined, tpl: MetadataTemplate): string {
  if (title === undefined || title === null) return tpl.default;
  if (typeof title === "string") return tpl.template ? tpl.template.replace("%s", title) : title;
  if (title.absolute) return title.absolute;
  if (title.default) return tpl.template ? tpl.template.replace("%s", title.default) : title.default;
  return tpl.default;
}

export function robotsContent(robots: Metadata["robots"]): string | null {
  if (!robots) return null;
  if (typeof robots === "string") return robots;
  const parts: string[] = [];
  if (robots.index !== undefined) parts.push(robots.index ? "index" : "noindex");
  if (robots.follow !== undefined) parts.push(robots.follow ? "follow" : "nofollow");
  return parts.length ? parts.join(", ") : null;
}

function setMeta(name: string, content: string | null): void {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (content === null) {
    if (el && el.dataset.tdDynamic === "1") el.remove();
    return;
  }
  if (!el) {
    el = document.createElement("meta");
    el.name = name;
    el.dataset.tdDynamic = "1";
    document.head.appendChild(el);
  }
  el.content = content;
}

let defaultDescription: string | null = null;

export function applyMetadata(md: Metadata | null | undefined, tpl: MetadataTemplate): void {
  if (typeof document === "undefined") return;
  if (defaultDescription === null) {
    defaultDescription = document.head.querySelector<HTMLMetaElement>('meta[name="description"]')?.content ?? "";
  }
  document.title = resolveTitle(md?.title, tpl);
  const description = typeof md?.description === "string" ? md.description : defaultDescription;
  setMeta("description", description || null);
  setMeta("robots", robotsContent(md?.robots));
}
