/**
 * Apps admin endpoints: the ONE place the /admin/ai page builds its api paths.
 * Platform-wide since WS3 (single company). `admin/ai-settings` is only read, for the provider
 * status; `admin/ai-usage` has no screen since the AI settings and Usage tabs were removed.
 */
export const AI_ADMIN_BASE = "admin";

export const AI_ADMIN_API = {
  settings: "admin/ai-settings",
  apps: "admin/apps",
} as const;
