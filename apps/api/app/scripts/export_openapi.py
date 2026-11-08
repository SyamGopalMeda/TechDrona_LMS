"""Write the OpenAPI document of the full API (user + webhook routers) to a JSON file.

    python -m app.scripts.export_openapi [--out openapi.json]

Builds the app with ``TD_ROUTER_SET=all`` and API docs enabled; no database or Redis
connection is opened. Used by the web app to reconcile its API types (openapi-typescript).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "openapi.json"


def build_document() -> dict[str, object]:
    os.environ["TD_ROUTER_SET"] = "all"
    os.environ["TD_DISABLE_API_DOCS"] = "false"
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    return create_app().openapi()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    doc = build_document()
    args.out.write_text(
        json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out} ({len(doc.get('paths', {}))} paths)")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
