# DB-11: demo/dev seeds are an allowlist, not a production denylist — a task launched in
# staging or with an unexpected APP_ENV must not load synthetic users with a known password.
SEEDABLE_ENVS = frozenset({"local", "dev", "test"})


def seeds_allowed() -> bool:
    from app.core.config import get_settings

    return get_settings().APP_ENV in SEEDABLE_ENVS
