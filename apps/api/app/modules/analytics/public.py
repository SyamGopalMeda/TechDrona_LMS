"""Public API of the analytics module (data-ops agent). Other modules import only this file.

Store-neutral on ``TD_STORE_ANALYTICS=firestore``: ``get_topic_mastery`` and the feeds
(``get_activity_summary``, ``get_engaged_buckets``, ``get_learning_activity``). The rest are
wiring/registration entry points (no table access of their own at import time).
"""

from __future__ import annotations

from app.modules.analytics.evidence import coverage_groups
from app.modules.analytics.feeds import (
    ActivityFeedDay,
    EngagedBucket,
    LearningActivityBucket,
    get_activity_summary,
    get_engaged_buckets,
    get_learning_activity,
)
from app.modules.analytics.mastery import TopicMasteryView, get_topic_mastery, rollup
from app.modules.analytics.params import K_MIN_ITEM

__all__ = [
    "K_MIN_ITEM",
    "ActivityFeedDay",
    "EngagedBucket",
    "LearningActivityBucket",
    "TopicMasteryView",
    "coverage_groups",
    "get_activity_summary",
    "get_engaged_buckets",
    "get_learning_activity",
    "get_topic_mastery",
    "rollup",
]
