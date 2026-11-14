/** Policy values come from `policy_settings` and are JSON scalars. */
export type PolicyValue = number | string | boolean | null;

/** verified: app/modules/sessions/router.py `device_policy` (GET /me/device-policy). */
export interface DevicePolicyDto {
  devices: { max_trusted: PolicyValue; max_replacements_per_30d: PolicyValue; trusted_inactivity_expiry_days: PolicyValue };
  sessions: { max_concurrent: PolicyValue; at_limit_behavior?: PolicyValue; idle_minutes?: number; absolute_hours?: number; remember_device_max_days?: PolicyValue };
  streams: { max_concurrent: PolicyValue };
  attempts?: { max_rebinds_per_attempt: PolicyValue };
}
