"""Machine-readable role/permission catalogue (role-permission-matrix.md, single-company edition).

Source of truth for ``app/seeds/rbac_seed.py`` (loaded into ``roles``, ``permissions``,
``role_permissions`` by migrations rbac_0002/rbac_0004 and re-syncable at any time).

Single-company LMS (docs/single-company/REMOVAL-PLAN.md §4, §8 D2/D3): the roles are Admin
(key ``super_admin``), Trainer, Evaluator, Content manager and Student. The college coordinator
role and the Finance admin / Support agent / Security reviewer / Placement mentor roles were
removed; their permissions were folded into ``super_admin`` (``REMOVED_ROLES``). Grants are made
at ``platform``, ``batch`` or ``course`` scope only — ``organization`` is no longer a grant scope.

Matrix cells (columns STU EVL TRN CM SA):

* ``P``/``B``/``C`` — the role holds the permission; the letter is the scope the role is
  normally granted at (the grant row carries the actual scope).
* ``R`` — read-only variant "(r)": the role holds the permission (only read keys are marked R).
* ``S`` — ownership only ("self"): never a role permission; enforced by ownership checks.
* ``-`` — never.

Dual control (``DUAL_ROLES``, approvals) now means "two DIFFERENT admins" (maker != checker).
"""

from __future__ import annotations

from dataclasses import dataclass

ROLE_ORDER = (
    "student",
    "evaluator",
    "trainer",
    "content_manager",
    "super_admin",
)

ADMIN_ROLE = "super_admin"

# Roles removed by the single-company conversion. Their live grants are revoked by migration
# rbac_0004 (``college_removal`` / ``role_consolidation``) and their permissions belong to Admin.
REMOVED_ROLES: dict[str, str] = {
    "college_coordinator": "college_removal",
    "finance_admin": "role_consolidation",
    "support_agent": "role_consolidation",
    "security_reviewer": "role_consolidation",
    "placement_mentor": "role_consolidation",
}


@dataclass(frozen=True)
class RoleDef:
    key: str
    name: str
    session_tier: str
    mfa_required: bool
    allowed_scope_types: tuple[str, ...]
    default_scope: str


ROLES: dict[str, RoleDef] = {
    r.key: r
    for r in (
        RoleDef("student", "Student", "student", False, ("platform",), "platform"),
        RoleDef("evaluator", "Evaluator", "staff", True, ("batch", "platform"), "batch"),
        RoleDef("trainer", "Trainer", "staff", True, ("batch", "course"), "batch"),
        RoleDef("content_manager", "Content manager", "staff", True, ("platform", "course"), "platform"),
        RoleDef("super_admin", "Admin", "privileged", True, ("platform",), "platform"),
    )
}

GRANT_SCOPE_TYPES = ("platform", "batch", "course")

TIER_RANK = {"student": 0, "staff": 1, "privileged": 2}

# Granting/revoking these roles is Dual (role matrix §5, RBAC-04): a second, different admin
# approves.
DUAL_ROLES = frozenset({ADMIN_ROLE})
# SoD-10: mutually exclusive role pairs. The finance/security pair disappeared with D2 (both
# folded into Admin); maker != checker is enforced per approval instead.
EXCLUSIVE_ROLE_PAIRS: tuple[tuple[str, str], ...] = ()


def admin_roles() -> frozenset[str]:
    """Roles that may act as Admin: approver sets, alert recipients, "full IP" readers, ...

    Use this wherever code used to name ``finance_admin``, ``support_agent``,
    ``security_reviewer`` or ``placement_mentor`` (alone or together with ``super_admin``)."""
    return frozenset({ADMIN_ROLE})


_MODULE_PREFIX = {
    "user": "identity",
    "session": "sessions",
    "device": "sessions",
    "security": "security",
    "org": "orgs",
    "batch": "orgs",
    "rbac": "rbac",
    "course": "catalog",
    "resource": "catalog",
    "media": "media",
    "enrolment": "learning",
    "progress": "learning",
    "assignment": "learning",
    "grade": "learning",
    "certificate": "learning",
    "taxonomy": "placement",
    "question": "placement",
    "company_path": "placement",
    "test": "assessments",
    "attempt": "assessments",
    "integrity": "assessments",
    "coding_problem": "coding",
    "coding_test_case": "coding",
    "submission": "coding",
    "similarity": "coding",
    "product": "commerce",
    "price": "commerce",
    "coupon": "commerce",
    "order": "commerce",
    "payment": "commerce",
    "refund": "commerce",
    "subscription": "commerce",
    "invoice": "commerce",
    "reconciliation": "commerce",
    "entitlement": "entitlements",
    "analytics": "analytics",
    "report": "analytics",
    "notification": "notifications",
    "ticket": "support",
    "privacy": "admin",
    "audit": "audit",
    "policy": "admin",
    "feature_flag": "admin",
    "approval": "admin",
    "breakglass": "admin",
    "engage": "engage",
    "path": "paths",
}

# Permissions deleted by the single-company conversion (migration rbac_0004 removes the rows),
# and the mentoring permissions removed with the feature on 2026-11-14
# (docs/cleanup/feature-removal-plan.md §3.1; the live Firestore rows stay until the owner
# approves deleting them, and are no longer reseeded).
REMOVED_PERMISSIONS = frozenset(
    {
        "org.create",
        "org.update",
        "org.suspend",
        "org.settings.update",
        "org.member.import",
        "org.member.remove",
        "rbac.grant.org_staff",
        "contract.manage",
        "contract.terminate",
        "contract.read",
        "seat.assign",
        "seat.revoke",
        "audit.read.org",
        "security.network.verify",
        "mentor.slot.manage",
        "mentor.feedback.write",
        "mentor.notes.read",
    }
)

# key: (description, sensitivity flags, matrix cells STU EVL TRN CM SA)
# flags: "Up" = step-up required, "Sens" = audited with reason, "Dual" = second approval.
# ``org.read`` / ``org.member.read`` now mean "company / batch roster read".
_ROWS: dict[str, tuple[str, str, str]] = {
    # 2.1 identity, sessions, devices
    "user.profile.read_self": ("Read own profile", "Std", "S S S S S"),
    "user.profile.update_self": ("Update own profile", "Std", "S S S S S"),
    "user.read": ("Read another user's profile and account status", "Sens", "- B B - P"),
    "user.invite": ("Invite/create staff or student accounts (within scope)", "Sens", "- - - - P"),
    "user.deactivate": ("Disable an account (kills all sessions)", "Up Sens", "S - - - P"),
    "user.mfa.reset": ("Remove a user's MFA factors after identity verification", "Up Dual", "- - - - P"),
    "user.legal_name.change": ("Change a locked legal name", "Sens", "- - - - P"),
    "session.read": ("List another user's sessions", "Sens", "S - - - P"),
    "session.revoke": ("Revoke another user's sessions", "Up Sens", "S - - - P"),
    "device.reset": (
        "Remove a trusted device of another user within the support quota",
        "Up Sens",
        "S - - - P",
    ),
    "device.reset.beyond_quota": ("Device reset beyond the support quota", "Up Sens", "- - - - P"),
    # 2.2 security
    "security.status.read": ("See that an account is restricted and its level", "Std", "S - B - P"),
    "security.reason.read": ("See the student-facing reason text and history", "Sens", "S - - - P"),
    "security.evidence.read": ("See raw security signals", "Sens", "- - - - P"),
    "security.case.read": ("Read security cases", "Sens", "- - - - P"),
    "security.case.note": ("Add notes to security cases", "Sens", "- - - - P"),
    "security.case.assign": ("Assign security cases", "Std", "- - - - P"),
    "security.case.decide": ("Decide case outcome", "Sens", "- - - - P"),
    "security.restriction.apply_l1l2": ("Apply L1/L2 manually", "Sens", "- - - - P"),
    "security.restriction.apply_l3l4": ("Apply L3/L4 manually", "Up Sens", "- - - - P"),
    "security.restriction.lift_l1l2": ("Lift L1/L2", "Sens", "- - - - P"),
    "security.restriction.lift_l3l4": ("Lift L3/L4", "Up Sens", "- - - - P"),
    "security.unblock.triage": ("Read and route unblock requests/appeals", "Sens", "S - - - P"),
    "security.rule.read": ("Read risk rules", "Sens", "- - - - P"),
    "security.rule.propose": ("Propose risk rules", "Sens", "- - - - P"),
    "security.rule.simulate": ("Simulate risk rules", "Sens", "- - - - P"),
    "security.rule.publish": ("Activate a risk rule version", "Up Dual", "- - - - P"),
    "security.incident.read": ("Read the breach/incident register", "Sens", "- - - - P"),
    "security.incident.manage": ("Open and update incidents", "Up Sens", "- - - - P"),
    "security.engine.kill_switch": ("Emergency move of risk.mode to shadow", "Up Sens", "- - - - P"),
    "security.restriction.bulk_lift": ("Bulk false-positive lift of engine L3s", "Up Sens Dual", "- - - - P"),
    # 2.3 company (internal org), batches, rbac
    "org.read": ("Read org profile and settings", "Std", "S - B - P"),
    "org.member.read": ("Read org roster", "Sens", "- - B - P"),
    "batch.create": ("Create batches", "Std", "- - - - P"),
    "batch.update": ("Update batches", "Std", "- - - - P"),
    "batch.archive": ("Archive batches", "Std", "- - - - P"),
    "batch.member.manage": ("Add/move/remove batch members", "Std", "- - B - P"),
    # orgs_0005 (classes & attendance moved from the website back office)
    "batch.class.manage": ("Schedule classes and mark attendance in a batch", "Std", "- - B - P"),
    "rbac.grant.read": ("Read grants in scope", "Std", "- - - - P"),
    "rbac.grant.manage": ("Grant/revoke any role at any scope", "Up Sens", "- - - - P"),
    # 2.4 catalog, media, learning
    "course.create": ("Create course drafts", "Std", "- - C P -"),
    "course.edit": ("Edit course drafts", "Std", "- - C P -"),
    "course.publish": ("Publish a course version", "Sens", "- - - P -"),
    "course.archive": ("Archive course", "Sens", "- - - P P"),
    "course.preview": ("Preview drafts", "Std", "- - C P P"),
    "resource.manage": ("Manage downloadable resources", "Std", "- - C P -"),
    "media.upload": ("Upload media", "Std", "- - C P -"),
    "enrolment.read": ("Read enrolments in scope", "Std", "S - B - P"),
    "enrolment.manage": ("Manage enrolments in scope", "Sens", "- - B - P"),
    "progress.read": ("Read learners' progress in scope", "Sens", "S B B - P"),
    "assignment.manage": ("Create/edit assignments", "Std", "- - B - -"),
    "assignment.grade": ("Grade submissions", "Std", "- B B - -"),
    "grade.override_released": ("Change a released grade", "Up Sens", "- - B - -"),
    "certificate.issue_manual": ("Issue a certificate manually", "Sens", "- - - P P"),
    "certificate.revoke": ("Revoke a certificate", "Up Sens", "- - - P P"),
    # 2.5 placement, assessments, coding
    "taxonomy.manage": ("Subject/topic tree", "Sens", "- - - P -"),
    "question.create": ("Author questions", "Std", "- - C P -"),
    "question.edit": ("Edit questions", "Std", "- - C P -"),
    # Admin reviews too (QA 2026-11): with a single content manager, separation of duties
    # (reviewer != author) left that author's questions unreviewable.
    "question.review": ("Review questions", "Sens", "- - - P P"),
    "question.publish": ("Publish questions", "Sens", "- - - P P"),
    "question.retire": ("Retire questions", "Sens", "- - - P -"),
    "question.answer_key.read": ("Read answer keys outside review rules", "Sens", "- B B P -"),
    "question.import": ("Bulk import questions", "Sens", "- - - P -"),
    "company_path.manage": ("Companies and company paths", "Std", "- - - P -"),
    "test.create": ("Build tests", "Std", "- - B P -"),
    "test.edit": ("Edit tests", "Std", "- - B P -"),
    "test.assign": ("Assign tests", "Std", "- - B - P"),
    "test.override.grant": ("Extra time/attempt/extension", "Sens", "- - B - P"),
    "test.results.read": ("Read attempts and results in scope", "Sens", "S B B P P"),
    "test.results.release": ("Release results", "Std", "- B B - P"),
    "attempt.regrade": ("Trigger regrade", "Sens", "- B B P -"),
    "attempt.invalidate": ("Invalidate an attempt", "Up Sens", "- - B - -"),
    "integrity.flag.read": ("Read advisory integrity events", "Sens", "- B B - P"),
    "integrity.flag.decide": ("Record integrity review outcome", "Sens", "- B B - P"),
    "coding_problem.manage": ("Create/edit coding problems", "Std", "- - C P -"),
    "coding_test_case.hidden.read": ("Read/edit hidden test cases", "Sens", "- - C P -"),
    "submission.code.read": ("Read submitted code of others", "Sens", "S B B P P"),
    "similarity.run": ("Run similarity checks", "Std", "- B B - P"),
    # 2.6 commerce, entitlements (B2C only)
    "product.manage": ("Products and plans", "Up Sens", "- - - - P"),
    "price.manage": ("Prices", "Up Sens", "- - - - P"),
    "coupon.manage": ("Coupons", "Up Sens", "- - - - P"),
    "order.read": ("Read orders", "Sens", "S - - - P"),
    "payment.read": ("Read payments", "Sens", "S - - - P"),
    # admissions (manual UPI verification; rows seeded by migration admissions_0001)
    "payment.verify": (
        "Verify, correct or reject manual payment claims and manage admissions registrations",
        "Sens",
        "- - - - P",
    ),
    "payment.reverse": (
        "Reverse a verified manual payment or change a registration's fee",
        "Up Sens",
        "- - - - P",
    ),
    "refund.decide": ("Decide refunds within rule", "Up Sens", "S - - - P"),
    "refund.goodwill": ("Refund outside rule", "Up Dual", "- - - - P"),
    "subscription.admin_cancel": ("Cancel a subscription on a user's behalf", "Up Sens", "S - - - P"),
    "invoice.read": ("Read invoices", "Sens", "S - - - P"),
    "invoice.credit_note": ("Issue credit notes", "Up", "- - - - P"),
    "reconciliation.run": ("Settlement reconciliation", "Sens", "- - - - P"),
    "entitlement.read": ("Read entitlements in scope", "Sens", "S - - - P"),
    "entitlement.grant_manual": ("Manual entitlement grant", "Up Sens", "- - - - P"),
    "entitlement.revoke": ("Revoke an entitlement", "Up Sens", "- - - - P"),
    # 2.7 analytics, notifications, support, privacy, platform
    "analytics.read": ("Dashboards/reports in scope", "Sens", "S - B C P"),
    "analytics.read.platform": ("Platform-wide aggregates", "Sens", "- - - - P"),
    "report.export.request": ("Request an export job", "Up Sens", "- - B - P"),
    "report.export.approve": ("Approve an export job", "Up Sens", "- - - - P"),
    "notification.batch_announce": ("Announcements to batches", "Std", "- - B - P"),
    "notification.template.manage": ("Notification templates", "Sens", "- - - - P"),
    "ticket.read": ("Read support tickets", "Sens", "S - - P P"),
    "ticket.respond": ("Respond to tickets", "Std", "S - - P P"),
    "ticket.assign": ("Assign tickets", "Std", "S - - P P"),
    "ticket.escalate": ("Escalate tickets", "Std", "S - - P P"),
    "privacy.request.process": ("Process privacy requests", "Up Sens", "S - - - P"),
    "audit.read": ("Read the audit log", "Sens", "- - - - P"),
    "policy.propose": ("Propose a policy change", "Up Sens", "- - - - P"),
    "policy.edit": ("Approve/execute a policy change", "Up Dual", "- - - - P"),
    "feature_flag.manage": ("Feature flags", "Up Sens", "- - - - P"),
    "approval.decide": ("Approve a dual-control request", "Up Sens", "- - - - P"),
    "breakglass.activate": ("Time-boxed elevation", "Up", "- - - - P"),
    # engage (live activities)
    "engage.activity.manage": (
        "Create, run and review live activities (quizzes, polls, word clouds, surveys)",
        "Std",
        "- - B P P",
    ),
    # paths (guided learning paths)
    "path.manage": ("Create, edit, publish and archive learning paths and path articles", "Std", "- - B P P"),
    "path.allocate": (
        "Allocate learning paths to batches or learners and view their progress",
        "Std",
        "- - B P P",
    ),
}

GRANTING_CELLS = frozenset({"P", "B", "C", "R"})


@dataclass(frozen=True)
class PermissionDef:
    key: str
    module: str
    description: str
    is_sensitive: bool  # step-up required ("Up")
    dual: bool
    cells: dict[str, str]


def _module(key: str) -> str:
    head = key.split(".", 1)[0]
    return _MODULE_PREFIX[head]


PERMISSIONS: dict[str, PermissionDef] = {}
for _key, (_desc, _flags, _cells) in _ROWS.items():
    _tokens = _cells.split()
    if len(_tokens) != len(ROLE_ORDER):  # pragma: no cover - catalogue integrity
        raise RuntimeError(f"matrix row {_key} has {len(_tokens)} cells")
    PERMISSIONS[_key] = PermissionDef(
        key=_key,
        module=_module(_key),
        description=_desc,
        is_sensitive="Up" in _flags.split(),
        dual="Dual" in _flags.split(),
        cells=dict(zip(ROLE_ORDER, _tokens, strict=True)),
    )


def role_permission_pairs() -> list[tuple[str, str]]:
    """``(role_key, permission_key)`` for every granting cell."""
    return [
        (role, p.key)
        for p in PERMISSIONS.values()
        for role, cell in p.cells.items()
        if cell in GRANTING_CELLS
    ]


def permissions_for_role(role: str) -> frozenset[str]:
    return frozenset(p for r, p in role_permission_pairs() if r == role)
