"""Firestore persistence foundation (MIGRATION-PLAN P0; usage in docs/firebase/p0.md).

Kept import-light on purpose: importing the package loads no google/grpc code. Use:

* ``app.core.firestore.backend``      — ``uses_firestore("catalog")`` (TD_STORE_<MODULE> switch)
* ``app.core.firestore.store``        — ``ScopedStore(principal)`` / ``ScopedStore.system(job)``
* ``app.core.firestore.collections``  — ``register_collection(CollectionSpec(...))``
* ``app.core.firestore.repository``   — ``FirestoreRepository``, ``@platform_only``
* ``app.core.firestore.ids``          — ``compose_id`` / ``hashed_id``

``app.core.firestore.client`` is private to this package (tests/firestore/test_store_boundary.py).
"""
