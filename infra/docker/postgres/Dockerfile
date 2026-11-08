# Local/CI Postgres 16 image for Tech Drona LMS.
# Adds pg_partman (docs/database-schema.md §1: extensions pgcrypto, citext, pg_partman,
# pg_stat_statements, btree_gist). pgcrypto/citext/btree_gist/pg_stat_statements ship with
# the official image (contrib); pg_partman comes from the PGDG apt repo already configured
# in the official postgres image. LOCAL / CI ONLY — AWS uses RDS PostgreSQL 16.
# Pinned by tag + multi-arch index digest (COM-23); Renovate/Dependabot bumps it.
FROM postgres:16-bookworm@sha256:e8a07d2c7579b038938cdba6c539e580e5001caf9ea203d397b5cc83e76bd938

RUN apt-get update \
    && apt-get install -y --no-install-recommends "postgresql-${PG_MAJOR}-partman" \
    && rm -rf /var/lib/apt/lists/*
