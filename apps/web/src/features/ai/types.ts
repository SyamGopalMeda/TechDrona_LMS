/**
 * Local types for the AI admin + learner endpoints (apps/api/app/modules/ai). Those routes
 * return untyped dicts, so the generated API types (src/lib/api-types) carry no response
 * schemas for them; keep these in sync with the api module.
 */

export type AIProviderName = "anthropic" | "fake" | "disabled";

/** Platform AI settings (WS3 `ai_settings` singleton). Caps are always numbers (SEC-05). */
export interface AISettings {
  enabled: boolean;
  model: string;
  monthly_token_cap: number;
  monthly_call_cap: number;
  per_activity_default_cap: number;
  tutor_per_minute: number;
  tutor_per_day: number;
  generate_per_hour: number;
  generate_per_day: number;
  updated_at: string | null;
}

/** GET/PATCH admin/ai-settings. Provider keys are never returned. */
export interface AISettingsOut {
  ai: AISettings;
  provider: { name: AIProviderName; configured: boolean };
  allowed_models: string[];
}

/** PATCH admin/ai-settings body: every field optional; caps can no longer be cleared (null → 422). */
export interface AISettingsPatch {
  enabled?: boolean;
  model?: string;
  monthly_token_cap?: number;
  monthly_call_cap?: number;
  per_activity_default_cap?: number;
  tutor_per_minute?: number;
  tutor_per_day?: number;
  generate_per_hour?: number;
  generate_per_day?: number;
}

export type AppKey = "assignments" | "assessments" | "question_banks" | "engage" | "paths" | "ai_tutor" | "ai_grading" | "ai_generation";
export type AppCategory = "learning" | "ai";

export interface OrgApp {
  app_key: AppKey | (string & {});
  label: string;
  category: AppCategory;
  enabled: boolean;
}

/** GET/PATCH admin/apps (platform-wide). */
export interface OrgAppsOut {
  apps: OrgApp[];
}

export interface OrgAppsPatch {
  apps: Record<string, boolean>;
}

export type AIFeature = "question_generation" | "grading" | "tutor" | "path_generation";

export interface AIUsageTotals {
  calls: number;
  tokens_in: number;
  tokens_out: number;
  /** Decimal USD as a string. */
  cost_estimate: string;
}

/** GET admin/ai-usage?month=YYYY-MM (platform totals). */
export interface AIUsageOut {
  period_start: string;
  period_end: string;
  totals: AIUsageTotals;
  caps: { monthly_token_cap: number; monthly_call_cap: number };
  by_feature: ({ feature: AIFeature | (string & {}) } & AIUsageTotals)[];
  by_day: { date: string; calls: number; tokens: number }[];
}

/** GET me/enabled-apps (platform-wide set). */
export interface EnabledAppsOut {
  apps: Record<string, boolean>;
  ai_enabled: boolean;
}

export type AITutorMode = "guide" | "explain";

export interface AITutorReply {
  reply_md: string;
  used: number;
  /** Effective limit (activity limit, else the platform default); never null since WS3/WS4. */
  limit: number;
}

/** Problem codes AI-backed endpoints return (403 / 429 / 503). */
export const AI_PROBLEM_CODES = ["ai_disabled", "ai_quota_exceeded", "ai_unavailable"] as const;
export type AIProblemCode = (typeof AI_PROBLEM_CODES)[number];
