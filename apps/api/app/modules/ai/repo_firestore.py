"""Firestore repository for the platform AI settings and app toggles (``TD_STORE_AI=firestore``).

``ai.store`` dispatches here; values come back as plain dicts that ``store`` turns into the
same ``PlatformAI`` / ``{app_key: bool}`` results as the Postgres path.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import ScopedStore, ScopedTransaction
from app.core.principal import Principal
from app.modules.ai.store_specs import AI_SETTINGS, APP_SETTINGS, PLATFORM_DOC, SETTINGS_PERM


class AISettingsRepo(FirestoreRepository):
    @platform_only(SETTINGS_PERM)
    async def settings(self) -> dict[str, Any] | None:
        d = await self.store.get(AI_SETTINGS, PLATFORM_DOC)
        return d.data if d else None

    @platform_only(SETTINGS_PERM)
    async def apps(self) -> dict[str, bool]:
        d = await self.store.get(APP_SETTINGS, PLATFORM_DOC)
        return {k: bool(v) for k, v in ((d.data.get("apps") or {}) if d else {}).items()}

    @platform_only(SETTINGS_PERM)
    async def write_settings(self, changes: dict[str, Any], by: uuid.UUID) -> None:
        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(AI_SETTINGS, PLATFORM_DOC)
            data = {**changes, "updated_by": str(by)}
            if cur is None:
                await tx.create(AI_SETTINGS, data, doc_id=PLATFORM_DOC)
            else:
                await tx.update(AI_SETTINGS, PLATFORM_DOC, data)

        await self.store.run_transaction(fn)

    @platform_only(SETTINGS_PERM)
    async def write_apps(self, apps: dict[str, bool], by: uuid.UUID) -> None:
        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(APP_SETTINGS, PLATFORM_DOC)
            base = cur.data if cur else {}
            merged = {
                "apps": {**(base.get("apps") or {}), **{k: bool(v) for k, v in apps.items()}},
                "updated_by": {**(base.get("updated_by") or {}), **dict.fromkeys(apps, str(by))},
            }
            if cur is None:
                await tx.create(APP_SETTINGS, merged, doc_id=PLATFORM_DOC)
            else:
                await tx.update(APP_SETTINGS, PLATFORM_DOC, merged)

        await self.store.run_transaction(fn)


def repo(principal: Principal | None = None) -> AISettingsRepo:
    """Principal-scoped for admin routes; the ``ai.settings`` system job otherwise."""
    return AISettingsRepo(ScopedStore(principal) if principal else ScopedStore.system("ai.settings"))
