/**
 * AI & apps admin endpoints: the ONE place the /admin/ai page builds its api paths.
 * Platform-wide since WS3 (single company): `admin/ai-settings`, `admin/apps`, `admin/ai-usage`.
 */
export const AI_ADMIN_BASE = "admin";

export const AI_ADMIN_API = {
  settings: "admin/ai-settings",
  apps: "admin/apps",
  usage: (month: string) => `admin/ai-usage?month=${encodeURIComponent(month)}`,
} as const;
