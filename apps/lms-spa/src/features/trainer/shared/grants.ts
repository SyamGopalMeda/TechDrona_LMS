"use client";

import { useApi } from "./use-api";

/** RBAC-06 `GET /me/grants` row (apps/api rbac `_grant_out`). */
export interface Grant {
  grant_id: string;
  role_key: string;
  scope_type: "platform" | "batch" | "course" | (string & {});
  scope_id: string | null;
  organization_id?: string | null;
  expires_at?: string | null;
}

export interface GrantsResponse {
  data: Grant[];
  portals?: string[];
}

export function useMyGrants() {
  return useApi<GrantsResponse>("me/grants");
}


/** Roles whose batch-scoped grants give a staff member "their" batches (trainer and evaluator portals). */
export const BATCH_STAFF_ROLE_KEYS: readonly string[] = ["trainer", "evaluator"];

/** Batches the user works in (`trainer` / `evaluator` @ `batch:{id}`), de-duplicated. */
export function trainerBatchIds(grants: Grant[] | undefined): string[] {
  const ids = (grants ?? [])
    .filter(
      (g) => BATCH_STAFF_ROLE_KEYS.includes(g.role_key) && g.scope_type === "batch" && g.scope_id,
    )
    .map((g) => g.scope_id!);
  return [...new Set(ids)];
}

/** True when the user holds any platform-scope grant (Admin, Content manager, platform evaluator…). */
export function hasPlatformGrant(grants: Grant[] | undefined): boolean {
  return (grants ?? []).some((g) => g.scope_type === "platform");
}
