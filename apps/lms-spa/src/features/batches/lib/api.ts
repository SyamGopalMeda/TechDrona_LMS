import { ApiError } from "@/lib/api/errors";

/*
 * Batch endpoints (WS1/WS4, verified against the regenerated openapi.json) are called with literal
 * paths in the components so the contract test (src/features/__contract__) covers them:
 * `batches`, `batches/{id}` (+ `/archive`, `/members`, `/members/{uid}`),
 * `analytics/reports/batches/{id}`, `admin/users?q=`, `rbac/grants` and `rbac/grants/{id}/revoke`.
 * Adding a member creates or reactivates the company org membership server-side
 * (`orgs.service.ensure_org_membership`), so any active account can be added.
 */

/** Batch-scoped staff roles an Admin can assign (plan §4: Trainer, Evaluator). */
export const BATCH_STAFF_ROLES = [
  { value: "trainer", label: "Trainer" },
  { value: "evaluator", label: "Evaluator" },
] as const;

/** Archived batches are read-only server-side; turn that 409 into a clear message. */
export async function archivedBatchGuard<T>(p: Promise<T>): Promise<T> {
  try {
    return await p;
  } catch (err) {
    if (err instanceof ApiError && err.status === 409 && err.code === "invalid_state_transition" && (err.problem as { current_state?: unknown } | null)?.current_state === "archived")
      throw new ApiError(409, { ...err.problem!, title: "This batch is archived", detail: "Archived batches are read-only. Refresh the page to see its current state." }, err.requestId);
    throw err;
  }
}
