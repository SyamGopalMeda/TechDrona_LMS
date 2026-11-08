"""media: playback_sessions (partitioned monthly on started_at)

Revision ID: media_0001
Revises:
Create Date: 2026-11-03

database-schema §4 ``playback_sessions`` (created with the media module, see sessions_0001).
RLS family O on the parent and the DEFAULT partition; app roles reach the partition only
through the parent. pg_partman premake / 180-day drops are registered by the maintenance job
(Planned), like the other partitioned tables.

Addition: ``tab_id`` (MED-04 request; same-auth-session tab takeover is silent) and
``organization_id`` is deliberately absent (O family: no college visibility, privacy D11).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import enable_rls

revision: str = "media_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("media",)
depends_on: str | Sequence[str] | None = ("core_base", "catalog_0001")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE playback_sessions (
          id                    uuid        NOT NULL,
          started_at            timestamptz NOT NULL DEFAULT now(),
          user_id               uuid        NOT NULL,
          auth_session_id       uuid        NOT NULL,
          device_id             uuid        NULL,
          tab_id                uuid        NULL,
          lesson_asset_id       uuid        NOT NULL,
          provider              text        NOT NULL DEFAULT 'vdocipher',
          provider_otp_ref_hash bytea       NULL CHECK (provider_otp_ref_hash IS NULL OR octet_length(provider_otp_ref_hash) = 32),
          status                text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended')),
          otp_expires_at        timestamptz NOT NULL,
          last_heartbeat_at     timestamptz NOT NULL DEFAULT now(),
          last_position_s       integer     NULL,
          ended_at              timestamptz NULL,
          end_reason            text        NULL CHECK (end_reason IN ('stopped','stale','taken_over','revoked')),
          PRIMARY KEY (id, started_at),
          CONSTRAINT ck_ps_end CHECK ((status = 'ended') = (ended_at IS NOT NULL AND end_reason IS NOT NULL))
        ) PARTITION BY RANGE (started_at);
        CREATE TABLE playback_sessions_default PARTITION OF playback_sessions DEFAULT;
        CREATE INDEX ix_ps_user_active ON playback_sessions (user_id, last_heartbeat_at) WHERE status = 'active';
        CREATE INDEX ix_ps_asset ON playback_sessions (lesson_asset_id, started_at);
        CREATE INDEX ix_ps_user_started ON playback_sessions (user_id, started_at DESC);
        CREATE INDEX ix_ps_id ON playback_sessions (id);
        COMMENT ON TABLE playback_sessions IS 'Owner: media | RLS: O | partitioned | Retention: R-PLAY (180 d) | PII: P1/P3';
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON playback_sessions TO td_app")
    op.execute("GRANT SELECT ON playback_sessions TO td_readonly")
    op.execute("REVOKE ALL ON playback_sessions_default FROM td_app, td_readonly")
    enable_rls("playback_sessions", "O")
    enable_rls("playback_sessions_default", "O")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS playback_sessions CASCADE")
