"""Server-side sanitising of authored path articles (markdown) + table of contents.

Articles are stored as markdown in a small, documented block dialect that the web renders with
React elements only (never as HTML):

* ``#``/``##``/``###`` headings (``##``/``###`` feed the "On this page" TOC);
* fenced code blocks ```` ```lang ```` (a following ```` ```output ```` fence is the output panel);
* callouts ``:::key-idea`` / ``:::watch-out`` / ``:::note`` / ``:::tip`` … ``:::``;
* exercises ``:::exercise Title`` … ``:::answer`` … ``:::``;
* GFM pipe tables, lists, ``**bold**``, ``*italic*``, `` `code` ``, links.

Sanitising follows the allow-list idea of ``placement.richtext`` (no shared import: module
ownership): outside code fences every raw HTML tag is removed (the content of dangerous elements
such as ``script``/``style``/``iframe`` is dropped entirely), links/images may only point to
``https://`` or a site-relative path (``javascript:``/``data:``/``http:`` targets are replaced by
``#``), unknown ``:::`` directives become ``:::note`` and an unclosed fence is closed. Content
inside code fences is kept verbatim — it is code, rendered as text.
"""

from __future__ import annotations

import re
from typing import Any

MAX_BODY_CHARS = 200_000
CALLOUTS = frozenset({"key-idea", "watch-out", "note", "tip"})
_DROP_CONTENT = ("script", "style", "iframe", "object", "embed", "svg", "math", "template", "noscript")
_DROP_RE = re.compile(
    r"<\s*(" + "|".join(_DROP_CONTENT) + r")\b[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL
)
_DROP_OPEN_RE = re.compile(r"<\s*(" + "|".join(_DROP_CONTENT) + r")\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>|<!--.*?-->", re.DOTALL)
_LINK_RE = re.compile(r"(!?\[[^\]\n]*\]\()([^)\s]*)((?:\s+\"[^\"\n]*\")?\))")
_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
_DIRECTIVE_RE = re.compile(r"^\s{0,3}:::\s*([A-Za-z-]*)(.*)$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")


def _safe_target(target: str) -> str:
    t = target.strip()
    if t.lower().startswith("https://"):
        return t
    if t.startswith("/") and not t.startswith("//") and "\\" not in t:
        return t
    if t.startswith("#"):
        return t
    return "#"


def _clean_text(chunk: str) -> str:
    chunk = _DROP_RE.sub("", chunk)
    chunk = _DROP_OPEN_RE.sub("", chunk)
    chunk = _TAG_RE.sub("", chunk)
    return _LINK_RE.sub(lambda m: m.group(1) + _safe_target(m.group(2)) + m.group(3), chunk)


def sanitize_markdown(raw: str) -> str:
    """Authoring input -> stored markdown (see module docstring)."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")[:MAX_BODY_CHARS]
    out: list[str] = []
    prose: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if prose:
            out.append(_clean_text("\n".join(prose)))
            prose.clear()

    for line in text.split("\n"):
        if fence is not None:
            out.append(line)
            if line.strip().startswith(fence):
                fence = None
            continue
        m = _FENCE_RE.match(line)
        if m:
            flush()
            fence = m.group(1)
            out.append(line)
            continue
        d = _DIRECTIVE_RE.match(line)
        if d:
            name, rest = d.group(1).lower(), d.group(2)
            if name in ("", "answer"):
                prose.append(f":::{name}".rstrip() if name else ":::")
            elif name == "exercise":
                prose.append(f":::exercise {rest.strip()}".rstrip())
            else:
                prose.append(f":::{name if name in CALLOUTS else 'note'}")
            continue
        prose.append(line)
    flush()
    if fence is not None:
        out.append(fence)
    return "\n".join(out).strip()


def slugify(text: str) -> str:
    s = re.sub(r"[`*_\[\]()]", "", text.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "section"


def table_of_contents(md: str) -> list[dict[str, Any]]:
    """``[{id, text, level}]`` for ``##``/``###`` headings outside code fences. Ids match the web
    renderer (slug, de-duplicated with ``-2``, ``-3`` … over every heading level)."""
    used: dict[str, int] = {}
    toc: list[dict[str, Any]] = []
    fence: str | None = None
    for line in md.split("\n"):
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        m = _FENCE_RE.match(line)
        if m:
            fence = m.group(1)
            continue
        h = _HEADING_RE.match(line)
        if not h:
            continue
        level, label = len(h.group(1)), re.sub(r"[`*_]", "", h.group(2)).strip()
        base = slugify(h.group(2))
        used[base] = used.get(base, 0) + 1
        slug = base if used[base] == 1 else f"{base}-{used[base]}"
        if level in (2, 3):
            toc.append({"id": slug, "text": label, "level": level})
    return toc
