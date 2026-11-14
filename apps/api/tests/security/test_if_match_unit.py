"""If-Match on case / incident / unblock transitions: a compressing proxy (Caddy ``encode zstd gzip``)
rewrites the strong ETag ``"v3"`` to ``"v3-zstd"`` / ``"v3-gzip"``, and browsers echo that back.
No database."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.errors import ProblemError
from app.modules.security.policies import check_if_match


def _req(value: str | None) -> Request:
    headers = [] if value is None else [(b"if-match", value.encode())]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


@pytest.mark.parametrize("tag", ['"v3"', "v3", 'W/"v3"', '"v3-zstd"', '"v3-gzip"', 'W/"v3-gzip"', '"v3-br"'])
def test_matching_versions_pass(tag: str) -> None:
    check_if_match(_req(tag), 3)


@pytest.mark.parametrize("tag", ['"v2"', '"v2-zstd"', '"v33"', '"v3-zstdx"', '"x3"', '"v3-gzip-zstd"'])
def test_other_versions_conflict(tag: str) -> None:
    with pytest.raises(ProblemError) as e:
        check_if_match(_req(tag), 3)
    assert e.value.code == "version_conflict"


def test_missing_header() -> None:
    with pytest.raises(ProblemError) as e:
        check_if_match(_req(None), 3)
    assert e.value.code == "precondition_required"
    check_if_match(_req(None), 3, required=False)
