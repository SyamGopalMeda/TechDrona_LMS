// Plain (server-safe) module: imported by the /security/approvals server page.

/**
 * Dual-control action types decided from the Security console. Must match the handlers the api
 * registers in app/modules/security/controls.py (register_handlers) — audit 0.6: rule-version
 * activate/rollback requests were missing, so they never appeared in /security/approvals.
 */
export const SECURITY_APPROVAL_TYPES = [
  "security.export.per_user",
  "security.restriction.bulk_lift",
  "risk.kill_switch.ratify",
  "risk.ruleset.activate",
  "risk.ruleset.rollback",
] as const;
