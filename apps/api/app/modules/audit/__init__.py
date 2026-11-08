"""Audit module: append-only, hash-chained ``audit_log`` (ADR-0011).

Writers use ``app.core.audit.audit()`` (inserts ``audit_outbox``); the sealer
(``app.modules.audit.sealer``) chains rows into ``audit_log``.
"""
