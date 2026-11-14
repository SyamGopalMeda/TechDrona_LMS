import { humanize } from "./console";

/**
 * Plain-language names for policy setting keys (audit Phase 2: no raw config keys as the only
 * label). Keys come from apps/api app/modules/admin/policy*.py; unknown keys fall back to a
 * humanized form of the key without its namespace (the category tab already names it).
 */
export const POLICY_LABELS: Record<string, string> = {
  "assessment.idle_hold_extra_minutes": "Extra minutes held when a test goes idle",
  "assessment.max_rebinds_per_attempt": "Device switches allowed per test attempt",
  "assessment.rebind_requires_otp_at_level": "Restriction level that needs a code to switch device in a test",
  "assessment.single_device_binding": "Tests stay on one device",
  "devices.new_device_verification": "Verify new devices",
  "devices.student.max_replacements_per_30d": "Student device replacements per 30 days",
  "devices.student.max_trusted": "Trusted devices per student",
  "devices.staff.max_trusted": "Trusted devices per faculty member (trainer, evaluator, content manager)",
  "devices.admin.cap_enabled": "Limit admins' trusted devices too (off = admins have no limit)",
  "devices.trusted_inactivity_expiry_days": "Days before an unused trusted device expires",
  "login.backoff_base_seconds": "Wait after a failed sign-in (seconds, first)",
  "login.backoff_cap_seconds": "Longest wait after failed sign-ins (seconds)",
  "login.hard_disable_after_failures": "Failed sign-ins before the account is locked",
  "login.ip_failed_limit_per_10min": "Failed sign-ins per network address in 10 minutes",
  "otp.email.max_per_day": "Email codes per day",
  "otp.email.max_per_hour": "Email codes per hour",
  "otp.max_verify_attempts": "Tries allowed per code",
  "otp.sms.max_per_number_per_day": "SMS codes per number per day",
  "otp.sms.max_per_number_per_hour": "SMS codes per number per hour",
  "otp.ttl_seconds": "Code expiry (seconds)",
  "playback.heartbeat_seconds": "Video check-in interval (seconds)",
  "playback.max_concurrent_streams": "Videos playing at once per account",
  "playback.otp_ttl_seconds": "Video licence expiry (seconds)",
  "playback.stale_after_seconds": "Video session timeout (seconds)",
  "playback.takeover_behavior": "When a video starts on another device",
  "risk.cgnat_asns": "Shared mobile networks (ASNs) treated as one",
  "risk.decay_half_life_days": "Days for a risk score to halve",
  "risk.fingerprint.enabled": "Use browser fingerprints",
  "risk.fingerprint.points_cap": "Most points from browser fingerprints",
  "risk.hc.auto_restrict_enabled": "Restrict automatically on high-confidence rules",
  "risk.hc.circuit_breaker.max_daily_restrictions": "Automatic restrictions allowed per day",
  "risk.hc.circuit_breaker.max_fp_rate": "Mistake rate that pauses automatic restrictions",
  "risk.hc.circuit_breaker.min_decisions": "Decisions needed before the mistake rate counts",
  "risk.minors_scoring_enabled": "Score accounts of under-18s",
  "risk.mode": "Engine mode (watching only or enforcing)",
  "risk.network_points_cap": "Most points from shared networks",
  "risk.owner_verification.max_age_days": "Days an owner check stays valid",
  "risk.owner_verification.refresh_prompt_days": "Days before asking to re-check the owner",
  "risk.repeat_window_days": "Days a repeat finding counts",
  "risk.window_days": "Days of activity scored",
  "sessions.remember_device.max_days": "Longest \"remember this device\" (days)",
  "sessions.staff.max_concurrent": "Staff sign-ins at once",
  "sessions.student.absolute_hours": "Student sign-in lasts at most (hours)",
  "sessions.student.at_limit_behavior": "When a student signs in on one device too many",
  "sessions.student.idle_minutes": "Student idle sign-out (minutes)",
  "sessions.student.max_concurrent": "Student sign-ins at once",
  "unblock.false_positive_extension": "Extra protection after a wrong restriction is lifted",
  "unblock.max_open_requests": "Open unblock requests per person",
  "unblock.max_requests_per_30d": "Unblock requests per person per 30 days",
  "unblock.sla.decision_hours": "Hours to decide an unblock request",
  "unblock.sla.first_response_hours": "Hours to first reply to an unblock request",
};

export function settingLabel(key: string): string {
  const known = POLICY_LABELS[key];
  if (known) return known;
  const parts = key.split(".");
  return (parts.length > 1 ? parts.slice(1) : parts).map((p) => humanize(p)).join(" · ");
}
