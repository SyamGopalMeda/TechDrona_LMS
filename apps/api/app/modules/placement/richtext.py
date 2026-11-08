"""Allow-list HTML sanitiser for authored rich text (question stems, options, explanations).

Stored rich text is ``{"html": "<p>…</p>"}``. Only formatting tags survive; every attribute
except a small per-tag allow-list is dropped, so ``<script>``, event handlers and
``javascript:`` URLs can never reach a learner's browser. Content inside dropped dangerous
elements (``script``/``style``/``iframe``…) is removed entirely; other unknown tags are
unwrapped (their text is kept, escaped).
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
from typing import Any

ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "b",
        "strong",
        "i",
        "em",
        "u",
        "s",
        "sub",
        "sup",
        "code",
        "pre",
        "kbd",
        "ul",
        "ol",
        "li",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
        "span",
        "div",
        "h3",
        "h4",
        "hr",
        "img",
    }
)
VOID_TAGS = frozenset({"br", "hr", "img"})
DROP_CONTENT_TAGS = frozenset({"script", "style", "iframe", "object", "embed", "svg", "math", "template"})
ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "img": frozenset({"data-s3-key", "alt"}),  # images by S3 key only; the web app resolves URLs
    "span": frozenset({"class"}),
    "code": frozenset({"class"}),
    "pre": frozenset({"class"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan"}),
}
MAX_HTML_CHARS = 20_000


class _Sanitiser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.drop_depth = 0
        self.open: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_CONTENT_TAGS:
            if tag not in VOID_TAGS:
                self.drop_depth += 1
            return
        if self.drop_depth or tag not in ALLOWED_TAGS:
            return
        allowed = ALLOWED_ATTRS.get(tag, frozenset())
        parts = [tag]
        for name, value in attrs:
            if name in allowed and value is not None and "javascript:" not in value.lower():
                parts.append(f'{name}="{html.escape(value, quote=True)}"')
        self.out.append("<" + " ".join(parts) + ">")
        if tag not in VOID_TAGS:
            self.open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.open and self.open[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth or tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag in self.open:
            while self.open:
                t = self.open.pop()
                self.out.append(f"</{t}>")
                if t == tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.drop_depth:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitize_html(raw: str) -> str:
    p = _Sanitiser()
    p.feed(raw[:MAX_HTML_CHARS])
    p.close()
    return p.result().strip()


def rich(raw: str | None) -> dict[str, Any] | None:
    """Authoring input -> stored rich-text JSON (None stays None)."""
    if raw is None:
        return None
    return {"html": sanitize_html(raw)}


def html_of(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    h = value.get("html")
    return h if isinstance(h, str) else None
