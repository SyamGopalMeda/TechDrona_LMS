"""User security timeline (H12; SEC-13) and device-account graph (H2; SEC-15).

IPs are shown as /24 (IPv4) or /48 (IPv6); ``evidence_ref`` values (``la_<id>``, ``as_<id>``) can
be revealed with SEC-16 (audited ``pii.reveal``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import to_rfc3339
from app.modules.security import repo_fs_engine as fx
from app.modules.security.models import (
    AccountRestriction,
    CaseDecision,
    CaseNote,
    RiskEvaluation,
    SecurityCase,
    SecuritySignal,
)
from app.modules.sessions import public as sessions_public
from app.modules.sessions.ua import mask_ip

ALL_TYPES = frozenset({"login", "session", "network", "signal", "evaluation", "restriction", "otp", "case"})


_US = timedelta(microseconds=1)


def _between(rows: Any, attr: str, since: datetime, until: datetime) -> list[Any]:
    """SQL ``attr BETWEEN since AND until`` (inclusive both ends) over a public-API result."""
    return [r for r in rows if getattr(r, attr) is not None and since <= getattr(r, attr) <= until]


async def timeline(
    session: AsyncSession, user_id: uuid.UUID, since: datetime, until: datetime, types: set[str] | None
) -> list[dict[str, Any]]:
    want = types or set(ALL_TYPES)
    if fx.fs():
        return await _timeline_fs(session, user_id, since, until, want)
    ev: list[dict[str, Any]] = []
    labels: dict[uuid.UUID, str] = {}

    async def label(dev_id: uuid.UUID | None) -> str | None:
        if dev_id is None:
            return None
        if dev_id not in labels:
            d = await sessions_public.get_device(session, dev_id)
            labels[dev_id] = (d.label_hint if d else None) or "Unknown device"
        return labels[dev_id]

    if "login" in want:
        for la in _between(
            await sessions_public.list_login_attempts(
                session, since=since - _US, until=until, user_id=user_id
            ),
            "attempted_at",
            since,
            until,
        ):
            ev.append(
                {
                    "at": to_rfc3339(la.attempted_at),
                    "type": "login",
                    "outcome": la.outcome,
                    "method": la.method,
                    "mfa_method": la.mfa_method,
                    "device_label": await label(la.device_id),
                    "net": mask_ip(la.ip),
                    "evidence_ref": f"la_{la.id}",
                }
            )
    if "session" in want:
        for s in _between(
            await sessions_public.list_sessions(
                session, user_id=user_id, created_after=since - _US, created_until=until
            ),
            "created_at",
            since,
            until,
        ):
            ev.append(
                {
                    "at": to_rfc3339(s.created_at),
                    "type": "session",
                    "session_id": str(s.id),
                    "device_label": await label(s.device_id),
                    "net": mask_ip(s.ip_first),
                    "asn": s.asn,
                    "network_type": s.network_type,
                    "region": s.geo_region,
                    "status": s.status,
                    "auth_method": s.created_via,
                    "last_active_at": to_rfc3339(s.last_seen_at),
                    "ended_at": to_rfc3339(s.ended_at) if s.ended_at else None,
                    "end_reason": s.end_reason,
                    "evidence_ref": f"as_{s.id}",
                }
            )
    if "network" in want:
        for o in _between(
            await sessions_public.list_observations(session, user_id=user_id, since=since - _US, until=until),
            "first_seen_at",
            since,
            until,
        ):
            ev.append(
                {
                    "at": to_rfc3339(o.first_seen_at),
                    "type": "network",
                    "session_id": str(o.auth_session_id),
                    "net_cluster": o.net_cluster,
                    "network_type": o.network_type,
                    "region": o.geo_region,
                }
            )
    if "signal" in want or "cap" in want:
        for sg in (
            await session.execute(
                select(SecuritySignal).where(
                    SecuritySignal.user_id == user_id, SecuritySignal.occurred_at.between(since, until)
                )
            )
        ).scalars():
            ev.append(
                {
                    "at": to_rfc3339(sg.occurred_at),
                    "type": "cap" if sg.family == "cap" else "signal",
                    "rule": sg.rule_key,
                    "rule_version": sg.rule_version,
                    "category": sg.category,
                    "base_points": float(sg.base_points),
                    "multipliers": sg.multipliers,
                    "evidence": sg.evidence,
                    "suppressed": sg.suppressed_by_decision_id is not None,
                }
            )
    if "evaluation" in want:
        for e in (
            await session.execute(
                select(RiskEvaluation).where(
                    RiskEvaluation.user_id == user_id, RiskEvaluation.evaluated_at.between(since, until)
                )
            )
        ).scalars():
            ev.append(
                {
                    "at": to_rfc3339(e.evaluated_at),
                    "type": "evaluation",
                    "evaluation_id": str(e.id),
                    "family": e.family,
                    "mode": e.mode,
                    "score": float(e.score),
                    "level_after": e.level_after,
                    "action": e.action,
                    "hc_rule": (e.gates or {}).get("hc_rule"),
                }
            )
    if "restriction" in want:
        for r in (
            await session.execute(
                select(AccountRestriction).where(
                    AccountRestriction.user_id == user_id, AccountRestriction.starts_at.between(since, until)
                )
            )
        ).scalars():
            ev.append(
                {
                    "at": to_rfc3339(r.starts_at),
                    "type": "restriction",
                    "level": r.level,
                    "family": r.family,
                    "source": r.source,
                    "hc_rule": r.hc_rule,
                    "evaluation_id": str(r.evaluation_id) if r.evaluation_id else None,
                    "end_reason": r.end_reason,
                }
            )
    if "otp" in want:
        from app.modules.identity import public as identity_public

        for t in _between(
            await identity_public.verification_tokens_of(
                session, user_id, created_after=since - _US, created_before=until + _US
            ),
            "created_at",
            since,
            until,
        ):
            outcome = (
                "completed"
                if t.consumed_at
                else (
                    "failed"
                    if t.attempts >= t.max_attempts
                    else ("abandoned" if t.expires_at < until else "pending")
                )
            )
            ev.append(
                {
                    "at": to_rfc3339(t.created_at),
                    "type": "otp",
                    "purpose": t.purpose,
                    "channel": t.channel,
                    "outcome": outcome,
                }
            )
    if "case" in want:
        cases = (
            (await session.execute(select(SecurityCase).where(SecurityCase.user_id == user_id)))
            .scalars()
            .all()
        )
        for c in cases:
            ev.append(
                {
                    "at": to_rfc3339(c.created_at),
                    "type": "case",
                    "event": "opened",
                    "case_ref": c.case_ref,
                    "opened_reason": c.opened_reason,
                }
            )
            for n in (await session.execute(select(CaseNote).where(CaseNote.case_id == c.id))).scalars():
                ev.append(
                    {
                        "at": to_rfc3339(n.created_at),
                        "type": "case",
                        "event": "note",
                        "case_ref": c.case_ref,
                        "visibility": n.visibility,
                    }
                )
            for d in (
                await session.execute(select(CaseDecision).where(CaseDecision.case_id == c.id))
            ).scalars():
                ev.append(
                    {
                        "at": to_rfc3339(d.created_at),
                        "type": "case",
                        "event": "decision",
                        "case_ref": c.case_ref,
                        "outcome": d.outcome,
                    }
                )
    ev.sort(key=lambda e: e["at"], reverse=True)
    return ev


async def _timeline_fs(
    session: AsyncSession, user_id: uuid.UUID, since: datetime, until: datetime, want: set[str]
) -> list[dict[str, Any]]:
    """``timeline`` on Firestore: the same events and fields; other modules' rows through their
    ``public.py``, security rows through the engine repository (``BETWEEN`` is inclusive)."""
    from app.modules.identity import public as idp
    from app.modules.sessions import public as sp

    ev: list[dict[str, Any]] = []
    labels: dict[uuid.UUID, str] = {}
    after = since - fx.ONE_US  # public.py bounds are ``> after``; BETWEEN includes ``since``
    r = fx.repo("security.timeline")

    async def label(dev_id: uuid.UUID | None) -> str | None:
        if dev_id is None:
            return None
        if dev_id not in labels:
            d = await sp.get_device(session, dev_id)
            labels[dev_id] = (d.label_hint if d else None) or "Unknown device"
        return labels[dev_id]

    if "login" in want:
        for la in await sp.list_login_attempts(session, since=after, until=until, user_id=user_id):
            ev.append(
                {
                    "at": to_rfc3339(la.attempted_at),
                    "type": "login",
                    "outcome": la.outcome,
                    "method": la.method,
                    "mfa_method": la.mfa_method,
                    "device_label": await label(la.device_id),
                    "net": mask_ip(la.ip),
                    "evidence_ref": f"la_{la.id}",
                }
            )
    if "session" in want:
        for s in await sp.list_sessions(session, user_id=user_id, created_after=after, created_until=until):
            ev.append(
                {
                    "at": to_rfc3339(s.created_at),
                    "type": "session",
                    "session_id": str(s.id),
                    "device_label": await label(s.device_id),
                    "net": mask_ip(s.ip_first),
                    "asn": s.asn,
                    "network_type": s.network_type,
                    "region": s.geo_region,
                    "status": s.status,
                    "auth_method": s.created_via,
                    "last_active_at": to_rfc3339(s.last_seen_at),
                    "ended_at": to_rfc3339(s.ended_at) if s.ended_at else None,
                    "end_reason": s.end_reason,
                    "evidence_ref": f"as_{s.id}",
                }
            )
    if "network" in want:
        for o in await sp.list_observations(session, user_id=user_id, since=after, until=until):
            ev.append(
                {
                    "at": to_rfc3339(o.first_seen_at),
                    "type": "network",
                    "session_id": str(o.auth_session_id),
                    "net_cluster": o.net_cluster,
                    "network_type": o.network_type,
                    "region": o.geo_region,
                }
            )
    if "signal" in want or "cap" in want:
        for sg in await r.user_signals(user_id):
            if not fx.window_between(sg.occurred_at, since, until):
                continue
            ev.append(
                {
                    "at": to_rfc3339(sg.occurred_at),
                    "type": "cap" if sg.family == "cap" else "signal",
                    "rule": sg.rule_key,
                    "rule_version": sg.rule_version,
                    "category": sg.category,
                    "base_points": float(sg.base_points),
                    "multipliers": sg.multipliers,
                    "evidence": sg.evidence,
                    "suppressed": sg.suppressed_by_decision_id is not None,
                }
            )
    if "evaluation" in want:
        evals = [e for e in await r.evaluations(user_id) if fx.window_between(e.evaluated_at, since, until)]
        for e in sorted(evals, key=lambda e: (e.evaluated_at, str(e.id))):
            ev.append(
                {
                    "at": to_rfc3339(e.evaluated_at),
                    "type": "evaluation",
                    "evaluation_id": str(e.id),
                    "family": e.family,
                    "mode": e.mode,
                    "score": float(e.score),
                    "level_after": e.level_after,
                    "action": e.action,
                    "hc_rule": (e.gates or {}).get("hc_rule"),
                }
            )
    if "restriction" in want:
        rows = [x for x in await r.restrictions_of(user_id) if fx.window_between(x.starts_at, since, until)]
        for x in sorted(rows, key=lambda x: (x.starts_at, str(x.id))):
            ev.append(
                {
                    "at": to_rfc3339(x.starts_at),
                    "type": "restriction",
                    "level": x.level,
                    "family": x.family,
                    "source": x.source,
                    "hc_rule": x.hc_rule,
                    "evaluation_id": str(x.evaluation_id) if x.evaluation_id else None,
                    "end_reason": x.end_reason,
                }
            )
    if "otp" in want:
        for t in await idp.verification_tokens_of(
            session, user_id, created_after=after, created_before=until
        ):
            outcome = (
                "completed"
                if t.consumed_at
                else (
                    "failed"
                    if t.attempts >= t.max_attempts
                    else ("abandoned" if t.expires_at < until else "pending")
                )
            )
            ev.append(
                {
                    "at": to_rfc3339(t.created_at),
                    "type": "otp",
                    "purpose": t.purpose,
                    "channel": t.channel,
                    "outcome": outcome,
                }
            )
    if "case" in want:
        cases = sorted(await r.cases_of(user_id), key=lambda c: (c.created_at, str(c.id)))
        decisions = await r.decisions_for_cases([c.id for c in cases]) if cases else []
        for c in cases:
            ev.append(
                {
                    "at": to_rfc3339(c.created_at),
                    "type": "case",
                    "event": "opened",
                    "case_ref": c.case_ref,
                    "opened_reason": c.opened_reason,
                }
            )
            for n in sorted(await r.notes_for_case(c.id), key=lambda n: (n.created_at, str(n.id))):
                ev.append(
                    {
                        "at": to_rfc3339(n.created_at),
                        "type": "case",
                        "event": "note",
                        "case_ref": c.case_ref,
                        "visibility": n.visibility,
                    }
                )
            for d in sorted(
                (d for d in decisions if d.case_id == c.id), key=lambda d: (d.created_at, str(d.id))
            ):
                ev.append(
                    {
                        "at": to_rfc3339(d.created_at),
                        "type": "case",
                        "event": "decision",
                        "case_ref": c.case_ref,
                        "outcome": d.outcome,
                    }
                )
    ev.sort(key=lambda e: e["at"], reverse=True)
    return ev


async def device_graph(session: AsyncSession, user_id: uuid.UUID, days: int, hops: int) -> dict[str, Any]:
    from app.modules.identity import clock
    from app.modules.security.models import AccountRestriction as AR

    since = clock.now() - timedelta(days=days)
    if fx.fs():
        return await _device_graph_fs(session, user_id, since, hops)
    mine = [d.device_id for d in await sessions_public.list_user_devices(session, user_id=user_id)]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_users: set[uuid.UUID] = {user_id}
    frontier = set(mine)
    for hop in range(max(1, min(hops, 2))):
        next_devices: set[uuid.UUID] = set()
        for dev_id in frontier:
            d = await sessions_public.get_device(session, dev_id)
            nodes.append(
                {
                    "type": "device",
                    "id": str(dev_id),
                    "label": d.label_hint if d else None,
                    "hop": hop,
                }
            )
            users = [
                d.user_id
                for d in await sessions_public.list_user_devices(
                    session, device_id=dev_id, created_after=since
                )
            ]
            for u in users:
                edges.append({"device": str(dev_id), "account": f"acct_{str(u)[:8]}"})
                if u in seen_users:
                    continue
                seen_users.add(u)
                lvl = (
                    await session.execute(
                        select(AR.level)
                        .where(AR.user_id == u, AR.ended_at.is_(None))
                        .order_by(AR.level.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                nodes.append(
                    {
                        "type": "account",
                        "id": f"acct_{str(u)[:8]}",
                        "restricted": bool(lvl and lvl >= 3),
                        "hop": hop + 1,
                    }
                )
                if hop == 0 and hops > 1:
                    next_devices.update(
                        d.device_id for d in await sessions_public.list_user_devices(session, user_id=u)
                    )
        frontier = next_devices - set(mine)
    return {"subject": str(user_id), "nodes": nodes, "edges": edges}


async def _device_graph_fs(
    session: AsyncSession, user_id: uuid.UUID, since: datetime, hops: int
) -> dict[str, Any]:
    """``device_graph`` on Firestore (devices through ``sessions.public``, restrictions through
    the security repository); same nodes, edges and hop numbering."""
    from app.modules.sessions import public as sp

    r = fx.repo("security.device_graph")
    mine = [d.device_id for d in await sp.list_user_devices(session, user_id=user_id)]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_users: set[uuid.UUID] = {user_id}
    frontier = set(mine)
    for hop in range(max(1, min(hops, 2))):
        next_devices: set[uuid.UUID] = set()
        for dev_id in frontier:
            d = await sp.get_device(session, dev_id)
            nodes.append(
                {"type": "device", "id": str(dev_id), "label": d.label_hint if d else None, "hop": hop}
            )
            users = [
                u.user_id for u in await sp.list_user_devices(session, device_id=dev_id, created_after=since)
            ]
            for u in users:
                edges.append({"device": str(dev_id), "account": f"acct_{str(u)[:8]}"})
                if u in seen_users:
                    continue
                seen_users.add(u)
                lvl = max(
                    (int(x.level) for x in await r.restrictions_of(u) if x.ended_at is None), default=None
                )
                nodes.append(
                    {
                        "type": "account",
                        "id": f"acct_{str(u)[:8]}",
                        "restricted": bool(lvl and lvl >= 3),
                        "hop": hop + 1,
                    }
                )
                if hop == 0 and hops > 1:
                    next_devices.update(d2.device_id for d2 in await sp.list_user_devices(session, user_id=u))
        frontier = next_devices - set(mine)
    return {"subject": str(user_id), "nodes": nodes, "edges": edges}
