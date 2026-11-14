/** `GET /me/modules` (apps/api/app/modules/hub/router.py): the modules the caller may open. */
export interface HubModule {
  key: "lms" | "colleges" | "website" | (string & {});
  title: string;
  description: string;
  /** Same-origin path. The website module goes through /sso/website (single sign-on hand-off). */
  href: string;
  external: boolean;
  roles: string[];
}

/** Outline icons (24×24 path data) per module. */
export const MODULE_ICONS: Record<string, string> = {
  lms: "M2 9l10-5 10 5-10 5L2 9zm4 2.5V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-4.5M22 9v6",
  colleges: "M3 21h18M5 21V10l7-5 7 5v11M9 21v-6h6v6M9 11h.01M15 11h.01",
  website: "M3 5h18v14H3zM3 9h18M7 7h.01M10 7h.01M7 13h6M7 16h4",
};
