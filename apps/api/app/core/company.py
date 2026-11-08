"""The single company organization (single-company LMS, ADR-0004 / REMOVAL-PLAN §2.2).

Tech Drona is the only tenant. Exactly one ``organizations`` row exists, inserted by migration
``orgs_0002`` with the fixed id below. It is an internal tenancy key only: no API lists,
creates, edits or suspends organizations, and users never pick one. Batches, batch members,
org-owned content (structured assignments, paths, engage activities, trainer tests and banks)
carry ``organization_id = COMPANY_ORG_ID``. Nullable ``organization_id`` columns keep meaning
"platform content" when NULL.

Import ``COMPANY_ORG_ID`` instead of resolving an organization from a request.
"""

from __future__ import annotations

import uuid
from typing import Final

COMPANY_ORG_ID: Final[uuid.UUID] = uuid.UUID("01930000-0000-7000-8000-00000000c001")
COMPANY_ORG_SLUG: Final[str] = "techdrona"
COMPANY_ORG_NAME: Final[str] = "Tech Drona"
COMPANY_ORG_TYPE: Final[str] = "internal"


def is_company_org(org_id: uuid.UUID | None) -> bool:
    return org_id == COMPANY_ORG_ID
