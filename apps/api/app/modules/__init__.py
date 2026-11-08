"""Business modules (one package per brief §2 module).

Each package may expose:
* ``models.py``  — SQLAlchemy models (auto-imported by ``app.core.models_registry``);
* ``router.py``  — ``router: APIRouter`` (auto-included under ``/api/v1`` by ``app.main``);
  build it with ``app.core.routing.authenticated_router()`` / ``public_router()``.
"""
