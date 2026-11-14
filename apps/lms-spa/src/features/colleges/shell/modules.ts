/**
 * The Modules menu data (same list as the LMS top-bar ModuleSwitcher): GET /api/v1/me/modules through the LMS
 * client, limited to what this account may open. Colleges Management is marked current; LMS resumes the last
 * LMS page (/continue); the Company Website Admin goes through /sso/website (a full page load).
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { continueHref } from "@/features/hub/last-page";
import type { HubModule } from "@/features/hub/modules";

export interface ModuleLink {
  key: string;
  label: string;
  href: string;
  current: boolean;
  /** leave the SPA (full page load) */
  reload: boolean;
}

export function moduleLinks(mods: HubModule[]): ModuleLink[] {
  const out = mods
    .filter((m) => m && m.href)
    .map((m) => ({
      key: m.key,
      label: m.key === "colleges" ? `${m.title} (you are here)` : m.title,
      href: m.key === "lms" ? continueHref("lms", m.href || "/modules") : m.key === "colleges" ? "/colleges" : m.href,
      current: m.key === "colleges",
      reload: !!m.external,
    }));
  out.push({ key: "all", label: "All modules", href: "/modules", current: false, reload: false });
  return out;
}

/** Module links (empty until loaded, and when the account opens fewer than two modules). Silent on failure. */
export function useModuleLinks(): ModuleLink[] {
  const [mods, setMods] = useState<HubModule[]>([]);
  useEffect(() => {
    let live = true;
    api
      .get<{ modules?: HubModule[] }>("me/modules", { handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false } })
      .then((r) => live && setMods(r.modules ?? []))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  return mods.length < 2 ? [] : moduleLinks(mods);
}
