"""Analytics module: event ingest, time-on-task model ``tm-1.0``, aggregates, reports, topic
mastery, the security activity feed and retention (docs/analytics-event-schema.md).

Public service interfaces for other modules:

* ``app.modules.analytics.feeds``     — security: ``get_activity_summary``, ``get_engaged_buckets``
* ``app.modules.analytics.evidence``  — learning: ``lesson_time_evidence``, ``video_coverage``
* ``app.modules.analytics.mastery``   — placement: ``get_topic_mastery``; outbox handlers
* ``app.modules.analytics.jobs``      — scheduled jobs (``python -m app.modules.analytics.jobs``)
"""
