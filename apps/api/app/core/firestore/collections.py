"""Collection registry: every collection the store touches declares its access family.

Families replace the Postgres RLS predicate families (MIGRATION-PLAN §1.4):

* ``owned``  (RLS ``O``/``U``/``US``): every document has ``owner_field`` (default ``user_id``).
  Read: the owner, or a principal holding ``read_permission``. Write: the owner when
  ``owner_writes``, else / additionally a principal holding ``write_permission``.
* ``shared`` (RLS ``T``/``TN``, single company): read by any authenticated principal unless
  ``read_permission`` is set; write needs ``write_permission``.
* ``system``: named system jobs only (``ScopedStore.system(job)``), e.g. relay/sealer state.

``append_only`` (``revoke_app_writes``): no update; delete only by a system job (retention/erasure).
A permission of ``None`` means "nobody but a system job".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from app.core.firestore.ids import validate_id

Family = Literal["owned", "shared", "system"]

# Firebase project billing-f4fe3 has ONE Firestore database shared by three modules, each owning the
# collections with its prefix: lms_* (this API), web_* (company website, browser SDK + rules in the
# website repo), col_* (Colleges Management portal). Code keeps the logical names used below
# ("courses", "uniq_email", "counters", ...); ScopedStore turns them into physical names with
# physical_name() at the single point where a reference is built, so nothing outside lms_* is reachable.
LMS_PREFIX = "lms_"


def physical_name(name: str) -> str:
    """Logical collection name -> the collection that actually exists in Firestore."""
    return name if name.startswith(LMS_PREFIX) else LMS_PREFIX + name


# Internal collections written only through store helpers (reserve_unique, next_sequence, leases).
UNIQUE_PREFIX = "uniq_"
COUNTERS = "counters"
LOCKS = "locks"
INTERNAL = frozenset({COUNTERS, LOCKS})


@dataclass(frozen=True, slots=True)
class CollectionSpec:
    name: str
    family: Family
    owner_field: str = "user_id"
    owner_writes: bool = True
    read_permission: str | None = None
    write_permission: str | None = None
    append_only: bool = False
    ttl: timedelta | None = None  # sets ``expire_at`` on create (Firestore TTL policy field)
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.name)
        if self.name in INTERNAL or self.name.startswith(UNIQUE_PREFIX):
            raise ValueError(f"{self.name!r} is reserved for store internals")
        if self.family == "owned" and not self.owner_field:
            raise ValueError("owned collections need an owner_field")


_registry: dict[str, CollectionSpec] = {}


def register_collection(spec: CollectionSpec) -> CollectionSpec:
    existing = _registry.get(spec.name)
    if existing is not None and existing != spec:
        raise ValueError(f"collection {spec.name!r} already registered with a different spec")
    _registry[spec.name] = spec
    return spec


def get_spec(name: str) -> CollectionSpec:
    try:
        return _registry[name]
    except KeyError:
        raise KeyError(
            f"collection {name!r} is not registered (app.core.firestore.register_collection)"
        ) from None


def registered() -> dict[str, CollectionSpec]:
    return dict(_registry)


def unregister_collection(name: str) -> None:
    """For tests."""
    _registry.pop(name, None)
