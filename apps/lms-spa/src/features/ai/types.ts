/**
 * Local types for the AI admin + learner endpoints (apps/api/app/modules/ai). Those routes
 * return untyped dicts, so the generated API types (src/lib/api-types) carry no response
 * schemas for them; keep these in sync with the api module.
 */

export type AIProviderName = "anthropic" | "fake" | "disabled";

/** The part of GET admin/ai-settings the Apps page reads. Provider keys are never returned. */
export interface AIProviderStatusOut {
  provider: { name: AIProviderName; configured: boolean };
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

/** GET me/enabled-apps (platform-wide set). */
export interface EnabledAppsOut {
  apps: Record<string, boolean>;
  ai_enabled: boolean;
  /** True while AI runs on the placeholder (fake) adapter: screens say "Not integrated yet". */
  ai_simulated?: boolean;
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
