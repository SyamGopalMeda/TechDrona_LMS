"""Static rule catalogue (RE §4) and the built-in v1 rulesets (RE §3.2, §4, §5).

``RULES`` is seeded into ``risk_rules`` by migration ``security_0001``. ``BUILTIN_RULESETS``
are the launch parameter sets (``sharing-1.0.0`` …). They are used whenever no
``risk_rule_versions`` row of that family is ``active``; a dual-approved DB version replaces
them (RE §5.4). Built-in HC-01/HC-02 start in ``shadow`` (RE §5.6 launch order); HC-T1..T3 are
protective and active from launch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuleDef:
    key: str
    family: str  # sharing | takeover | cap | abuse | integrity
    category: str | None  # C | D | N (sharing only)
    description: str
    explanation_key: str
    student_text: str


_R = RuleDef
RULES: tuple[RuleDef, ...] = (
    # sharing (adults)
    _R(
        "SH-01",
        "sharing",
        "C",
        "Overlapping engaged activity on two device tokens",
        "sh01.overlap_two_devices",
        "Video and tests were used at the same time on two devices.",
    ),
    _R(
        "SH-02",
        "sharing",
        "N",
        "Overlap on network clusters in different states",
        "sh02.two_states",
        "Those devices were in two different states at the same time.",
    ),
    _R(
        "SH-03",
        "sharing",
        "C",
        "Stream ping-pong between two devices",
        "sh03.stream_pingpong",
        "Video playback kept switching between two devices.",
    ),
    _R(
        "SH-04",
        "sharing",
        "C",
        "Session-cap evictions of other devices",
        "sh04.session_evictions",
        "Sign-ins on other devices were repeatedly signed out at the session limit.",
    ),
    _R(
        "SH-05",
        "sharing",
        "D",
        "Many distinct device tokens in 30 days",
        "sh05.many_devices",
        "Your account was used from many different browsers or devices this month.",
    ),
    _R(
        "SH-06",
        "sharing",
        "D",
        "Rapid device churn",
        "sh06.device_churn",
        "Several new browsers or devices were added within one day.",
    ),
    _R(
        "SH-07",
        "sharing",
        "D",
        "New-device codes not completed",
        "sh07.otp_abandoned",
        "New-device verification codes were requested but not completed.",
    ),
    _R(
        "SH-08",
        "sharing",
        "C",
        "Assessment conflict not resolved",
        "sh08.attempt_conflict",
        "A test in progress was opened from a second device.",
    ),
    _R(
        "SH-09",
        "sharing",
        "N",
        "Hosting, VPN or Tor network",
        "sh09.hosting_asn",
        "Sign-ins came through a hosting, VPN or anonymising network.",
    ),
    _R(
        "SH-10",
        "sharing",
        "N",
        "State-level geo-velocity",
        "sh10.geo_velocity",
        "Sign-ins came from far-apart states within a short time.",
    ),
    _R(
        "SH-11",
        "sharing",
        "D",
        "Device shared across many accounts",
        "sh11.shared_device_many_accounts",
        "A device you used was also used by several other accounts.",
    ),
    _R(
        "SH-12",
        "sharing",
        "D",
        "Fingerprint re-link (Phase 2)",
        "sh12.fingerprint_relink",
        "A removed device appears to have been added again.",
    ),
    _R(
        "SH-13",
        "sharing",
        "D",
        "Verification completed at a distance (OTP relay)",
        "sh13.verification_distance",
        "A verification code was used on a device far from where your account was active.",
    ),
    _R("SH-M1", "sharing", None, "Repeat modifier", "shm1.repeat", "A previous restriction was confirmed."),
    # takeover (all users)
    _R("TO-01", "takeover", None, "Failed-login burst", "to01.failed_burst", "Many failed sign-ins."),
    _R(
        "TO-02",
        "takeover",
        None,
        "Breached password at login",
        "to02.breached_password",
        "Your password appears in a known data breach.",
    ),
    _R(
        "TO-03",
        "takeover",
        None,
        "Correct password, failed second factor",
        "to03.mfa_failed",
        "The right password was used but the second step failed.",
    ),
    _R(
        "TO-04",
        "takeover",
        None,
        "Session/device mismatch (cookie replay)",
        "to04.cookie_replay",
        "A sign-in from your device was used from a different browser.",
    ),
    _R(
        "TO-05",
        "takeover",
        None,
        "Success from a stuffing source",
        "to05.stuffing_source",
        "A sign-in came from a network attacking many accounts.",
    ),
    _R(
        "TO-06",
        "takeover",
        None,
        "Sensitive change from a new device",
        "to06.sensitive_change",
        "Contact or security details changed from a new device.",
    ),
    _R("TO-07", "takeover", None, "Tor exit login", "to07.tor", "A sign-in came through Tor."),
    _R(
        "TO-08",
        "takeover",
        None,
        "Client drift within one session",
        "to08.client_drift",
        "A sign-in from your device was used from a different browser.",
    ),
    _R(
        "TO-09",
        "takeover",
        None,
        "First login from outside India",
        "to09.new_country",
        "A sign-in came from a new country.",
    ),
    _R(
        "TO-10",
        "takeover",
        None,
        "Remember-token reuse",
        "to10.remember_reuse",
        "An old 'remember me' credential was reused.",
    ),
    _R("TO-11", "takeover", None, "Abuse-derived (AB-01/AB-03)", "to11.abuse", "Unusual sign-in volume."),
    # high-confidence rules
    _R(
        "HC-01",
        "sharing",
        None,
        "Separated concurrent use",
        "hc01.separated_use",
        "Your account was used at the same time from two distant fixed-line networks on several days.",
    ),
    _R(
        "HC-02",
        "sharing",
        None,
        "Three or more separated users",
        "hc02.three_users",
        "Your account was used at the same time from three or more distant networks.",
    ),
    _R("HC-T1", "takeover", None, "Breached credential in use", "hct1.breached", "Breached password used."),
    _R(
        "HC-T2",
        "takeover",
        None,
        "Confirmed stuffing success",
        "hct2.stuffing",
        "Sign-in activity that may not have been you.",
    ),
    _R(
        "HC-T3",
        "takeover",
        None,
        "Replay confirmed",
        "hct3.replay",
        "Sign-in activity that may not have been you.",
    ),
    # abuse / integrity (never restrict)
    _R("AB-01", "abuse", None, "Rapid session creation", "ab01.rapid_sessions", "Unusual sign-in volume."),
    _R("AB-02", "abuse", None, "OTP send abuse / SMS pumping", "ab02.otp_send", "Too many codes requested."),
    _R("AB-03", "abuse", None, "OTP verify brute force", "ab03.otp_bruteforce", "Too many incorrect codes."),
    _R("AB-04", "abuse", None, "Credential stuffing source", "ab04.stuffing", ""),
    _R("AB-05", "abuse", None, "Password spray", "ab05.spray", ""),
    _R("AB-06", "abuse", None, "Automation / scraping", "ab06.automation", ""),
    _R("AB-07", "abuse", None, "Unknown or forged session tokens", "ab07.unknown_tokens", ""),
    _R("AB-08", "abuse", None, "Restricted-route probing", "ab08.restricted_probing", ""),
    _R("AB-09", "abuse", None, "Cross-tenant ID probing", "ab09.cross_tenant", ""),
    _R(
        "AB-10",
        "abuse",
        None,
        "Restricted account's device used for another account",
        "ab10.device_reuse",
        "",
    ),
    # AB-11 is retired (single company, D5: no shared lab devices); kept so historic signals render.
    _R("AB-11", "abuse", None, "Retired: shared-device login", "ab11.lab_cross_org", ""),
    _R("AB-12", "abuse", None, "Webhook signature invalid", "ab12.webhook_signature", ""),
    _R("IN-01", "integrity", None, "Learning-time plausibility violation", "in01.plausibility", ""),
    _R("IN-02", "integrity", None, "Ingest identity or clock forgery", "in02.ingest_forgery", ""),
    _R("IN-03", "integrity", None, "Hidden-test probing", "in03.hidden_test_probing", ""),
    # deterministic caps
    _R("cap.session", "cap", None, "Session cap hit", "cap.session", ""),
    _R("cap.stream", "cap", None, "Stream cap hit", "cap.stream", ""),
    _R("cap.device", "cap", None, "Trusted-device cap hit", "cap.device", ""),
    _R("cap.replacement", "cap", None, "Replacement quota hit", "cap.replacement", ""),
    _R("cap.attempt_bind", "cap", None, "Assessment binding conflict", "cap.attempt_bind", ""),
)
RULES_BY_KEY: dict[str, RuleDef] = {r.key: r for r in RULES}

NETWORK_RULES = frozenset({"SH-02", "SH-09", "SH-10"})
STATE_SIGNALS = frozenset({"SH-05"})  # recomputed daily: only the latest occurrence counts, undecayed
CONCURRENCY_RULES = frozenset(r.key for r in RULES if r.family == "sharing" and r.category == "C")
REPLAY_RULES = frozenset({"TO-04", "TO-08", "TO-10"})

# Sharing (RE §4.2): base points and 7-day caps.
_SHARING_POINTS: dict[str, tuple[float, float]] = {
    "SH-01": (15, 45),
    "SH-02": (6, 12),
    "SH-03": (8, 24),
    "SH-04": (6, 12),
    "SH-05": (8, 16),
    "SH-06": (8, 16),
    "SH-07": (8, 16),
    "SH-08": (10, 20),
    "SH-09": (4, 8),
    "SH-10": (4, 8),
    "SH-11": (4, 8),
    "SH-12": (5, 10),
    "SH-13": (10, 20),
}
_TAKEOVER_POINTS: dict[str, float] = {
    "TO-01": 20,
    "TO-02": 40,
    "TO-03": 35,
    "TO-04": 60,
    "TO-05": 30,
    "TO-06": 25,
    "TO-07": 15,
    "TO-08": 60,
    "TO-09": 15,
    "TO-10": 60,
    "TO-11": 20,
}

BUILTIN_RULESETS: dict[str, dict[str, Any]] = {
    "sharing": {
        "ruleset_version": "sharing-1.0.0",
        "semver": "1.0.0",
        "points": {k: v[0] for k, v in _SHARING_POINTS.items()},
        "caps": {k: v[1] for k, v in _SHARING_POINTS.items()},
        "params": {
            "sh05_high_points": 16,
            "sh05_low": 6,
            "sh05_high": 10,
            "sh06_new_devices": 4,
            "sh07_abandoned": 2,
            "sh11_accounts": 4,
            "sh04_evictions": 3,
            "sh13_window_minutes": 15,
            "overlap_min_buckets": 3,
            "sh10_max_hours": 2,
            "sh10_min_km": 1000,
        },
    },
    "takeover": {
        "ruleset_version": "takeover-1.0.0",
        "semver": "1.0.0",
        "points": dict(_TAKEOVER_POINTS),
        "thresholds": {"step_up": 40, "protect": 70},
        "params": {
            "to01_failures": 10,
            "to01_minutes": 15,
            "to03_count": 2,
            "to03_minutes": 60,
            "minor_to03_lock": 3,
        },
    },
    "abuse": {
        "ruleset_version": "abuse-1.0.0",
        "semver": "1.0.0",
        "params": {
            "ab01_per_hour": 10,
            "ab01_per_day": 20,
            "ab04_failures": 50,
            "ab04_accounts": 20,
            "ab05_accounts": 100,
            "ab07_unknown_tokens": 20,
            "ab08_denials": 30,
            "ab09_404_per_min": 20,
            "ab09_cross_tenant_per_hour": 5,
        },
    },
    "integrity": {
        "ruleset_version": "integrity-1.0.0",
        "semver": "1.0.0",
        "params": {"in02_rejections": 50, "in03_submits": 20},
    },
}

# Per-rule HC versions (RE §5.6).
BUILTIN_HC: dict[str, dict[str, Any]] = {
    "HC-01": {
        "status": "shadow",
        "semver": "1.0.0",
        "params": {"min_devices": 2, "min_days": 3, "window_days": 14},
    },
    "HC-02": {"status": "shadow", "semver": "1.0.0", "params": {"min_days": 2, "window_days": 7}},
    "HC-T1": {"status": "active", "semver": "1.0.0", "params": {}},
    "HC-T2": {"status": "active", "semver": "1.0.0", "params": {}},
    "HC-T3": {"status": "active", "semver": "1.0.0", "params": {}},
}

REASON_CODES = ("case_review", "appeal", "takeover_investigation", "qa_sample")
