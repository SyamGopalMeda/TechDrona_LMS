"""Import every ``app.modules.<name>.models`` so ``Base.metadata`` is complete
(Alembic autogenerate drafts, tests). Modules never edit this file."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

import app.modules as modules_pkg
from app.core.db import Base


def module_names() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(modules_pkg.__path__) if m.ispkg)


def _optional_import(dotted: str) -> ModuleType | None:
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError as e:
        if e.name == dotted:  # the submodule itself is absent -> fine
            return None
        raise  # a real missing dependency inside the module must surface


def import_all_models() -> type[Base]:
    importlib.import_module("app.core.models")
    for name in module_names():
        _optional_import(f"app.modules.{name}.models")
    return Base
