/**
 * Page title + breadcrumb that a screen hands to the shell (old ctx.setBreadcrumb). Without a call, the shell
 * shows "Home › <route title>" (lib/routes.ts ROUTES). "Home" is added in front automatically.
 *
 *   usePortalPage({ title: college.name, crumbs: [{ label: "Colleges", to: portalPath.colleges }, { label: college.name }] });
 */
import { createContext, useContext, useEffect, type ReactNode } from "react";

export interface Crumb {
  label: string;
  to?: string;
}

export interface PageMeta {
  /** document title part and the phone top-bar title (default: the last crumb, else the route title) */
  title?: string;
  crumbs?: Crumb[];
}

type Setter = (meta: PageMeta | null) => void;
const PageMetaContext = createContext<Setter>(() => undefined);

export function PageMetaProvider({ set, children }: { set: Setter; children: ReactNode }) {
  return <PageMetaContext value={set}>{children}</PageMetaContext>;
}

/** Set this page's title / breadcrumb (cleared when the page unmounts). Pass stable values (strings). */
export function usePortalPage(meta: PageMeta): void {
  const set = useContext(PageMetaContext);
  const key = JSON.stringify(meta);
  useEffect(() => {
    set(JSON.parse(key) as PageMeta);
    return () => set(null);
  }, [set, key]);
}
