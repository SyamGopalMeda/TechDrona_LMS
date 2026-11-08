"""paths: single company — drop the article audience 'org'

Revision ID: paths_0002
Revises: paths_0001
Create Date: 2026-11-07

docs/single-company/REMOVAL-PLAN.md §1.2 (paths), §5 step 7, §6 WS4. The path-article publish
audience ``org`` ("everyone in the organization") is removed. Existing ``org`` articles are
remapped to the nearest remaining audience: ``batches`` with every non-archived batch of the
article's organization (the same learners an org-wide share reached). An ``org`` article whose
organization has no such batch is unpublished (``draft``, no audience). The audience CHECK then
allows only ``batches`` and ``people``.

No schema change for ``organization_id`` columns (they hold the company org; ``orgs_0003``
re-homes them).

Data step runs as the table owner; FORCE RLS on ``path_articles`` and ``batches`` is lifted for the statements
and restored in the same transaction.

Downgrade restores the wider CHECK, **not** the data: restore it from
``backups/techdrona-dev-before-college-removal-20261106.dump``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "paths_0002"
down_revision: str | Sequence[str] | None = "paths_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FORCED = ("path_articles", "batches")


def upgrade() -> None:
    conn = op.get_bind()
    forced = list(
        conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relname = ANY (:t) AND relkind IN ('r','p') "
                "AND relforcerowsecurity AND relnamespace = 'public'::regnamespace"
            ),
            {"t": list(_FORCED)},
        ).scalars()
    )
    for t in forced:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE path_articles pa
           SET audience = 'batches',
               batch_ids = b.ids,
               user_ids = '{}',
               updated_at = now()
          FROM (
                SELECT organization_id, array_agg(id ORDER BY id) AS ids
                  FROM batches
                 WHERE status <> 'archived'
                 GROUP BY organization_id
               ) b
         WHERE pa.audience = 'org' AND b.organization_id = pa.organization_id;

        UPDATE path_articles
           SET status = 'draft', audience = NULL, batch_ids = '{}', user_ids = '{}', updated_at = now()
         WHERE audience = 'org';

        ALTER TABLE path_articles DROP CONSTRAINT IF EXISTS path_articles_audience_check;
        ALTER TABLE path_articles DROP CONSTRAINT IF EXISTS ck_pa_audience;
        ALTER TABLE path_articles ADD CONSTRAINT ck_pa_audience
          CHECK (audience IS NULL OR audience IN ('batches','people'));
        """
    )
    for t in forced:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE path_articles DROP CONSTRAINT IF EXISTS ck_pa_audience;
        ALTER TABLE path_articles ADD CONSTRAINT path_articles_audience_check
          CHECK (audience IS NULL OR audience IN ('org','batches','people'));
        """
    )
