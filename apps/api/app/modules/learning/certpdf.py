"""Certificate PDF renderer (server side, fpdf2): the Tech Drona certificate template
(``docs/design/certificates/completion-certificate-reference.png``) redrawn with vectors.

A4 landscape on cream parchment: an ornate gold double border with corner flourishes and diamond
ornaments; a top row with the Tech Drona lockup in the centre and two optional logo slots (owner
uploads in Documents -> Settings, empty by default); the issuing organisation with gold rules and
its tagline; "CERTIFICATE" over a navy ribbon ("of Completion"); the recipient's name between
laurel sprigs over a gold rule; the citation, the emphasised course / role / event and a details
sentence; then the verification column (small QR to the verify page + certificate number), a
gold-and-navy award seal and ONE signature block (Authorised Signatory) with the date of issue.

Fonts: the OFL fonts in ``certfonts/`` (licences alongside). When a font file is missing the
renderer falls back to the PDF core fonts (Latin-1 only), so issuing never fails on an asset.
The lockup is the official brand SVG (``certart/logo-lockup-navy.svg``, a copy of the website's
``public/brand`` file), drawn as vectors. Third-party logos are never bundled: the two side slots
are images the owner uploads (and has the right to use).

QR: ``segno`` (pure Python). Without it the verify URL is printed instead of the QR.

Watermarks: every page carries the Tech Drona mark (``certart/logo-mark-navy.svg``, the archer
symbol) very faintly behind everything (``watermark=False`` leaves it out; Documents -> Settings).
A preview (``preview=True``: nothing is stored, the number does not exist) prints "DRAFT" for the
number, no QR and no verify link, and a large diagonal "PREVIEW · NOT VALID" over the page.

Deterministic: the same ``CertificateArt`` always renders byte-identical PDFs (fixed creation
date = issue date, content-derived document /ID), so ``sha256(pdf)`` is a stable content hash.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

FONT_DIR = Path(__file__).with_name("certfonts")
LOGO_SVG = Path(__file__).with_name("certart") / "logo-lockup-navy.svg"
LOGO_RATIO = 200 / 922  # lockup viewBox height / width
LOGO_MARK_SVG = Path(__file__).with_name("certart") / "logo-mark-navy.svg"  # square icon mark
TEMPLATE_VERSION = "cert-v4"  # v4 = brand watermark (v3: Tech Drona template, v2: royal diploma)

WATERMARK_OPACITY = 0.05  # brand mark behind the content
PREVIEW_OPACITY = 0.2  # "PREVIEW · NOT VALID" over the content
PREVIEW_MARK = "PREVIEW · NOT VALID"
PREVIEW_REF = "DRAFT"  # printed instead of the reference / certificate number
PREVIEW_NOTE = "Verification code appears when the document is issued"
PREVIEW_RED = (196, 30, 36)

DEFAULT_COMPANY = "Tech Drona"
DEFAULT_TAGLINE = "Debug your career. Deploy your dreams."

# palette (sampled from the reference template)
NAVY = (15, 33, 82)
NAVY_DARK = (8, 20, 54)
NAVY_LIGHT = (36, 62, 128)
INK = (31, 38, 64)
BODY = (42, 51, 85)
LEAD = (59, 69, 102)
SLATE = (74, 83, 112)
BROWN = (107, 90, 51)
GOLD = (190, 145, 58)
GOLD_DARK = (140, 100, 32)
GOLD_LIGHT = (226, 192, 116)
GOLD_PALE = (246, 222, 160)
GOLD_TEXT = (125, 95, 34)
CREAM = (253, 249, 239)
PARCHMENT = (248, 240, 222)
PARCHMENT_EDGE = (238, 224, 190)
RIBBON_TEXT = (253, 246, 226)
WHITE = (255, 255, 255)

W, H = 841.89, 595.28  # A4 landscape in points
CX = W / 2

_FONTS = {
    "gar": ("EBGaramond-Regular.ttf", ("Times", "")),
    "garIt": ("EBGaramond-Italic.ttf", ("Times", "I")),
    "garSemi": ("EBGaramond-SemiBold.ttf", ("Times", "B")),
    "cin": ("Cinzel-SemiBold.ttf", ("Helvetica", "")),
    "cinBold": ("Cinzel-Bold.ttf", ("Helvetica", "B")),
    "pfBold": ("PlayfairDisplay-Bold.ttf", ("Times", "B")),
    "pfIt": ("PlayfairDisplay-Italic.ttf", ("Times", "I")),
    "pfSemiIt": ("PlayfairDisplay-SemiBoldItalic.ttf", ("Times", "BI")),
    "pfBoldIt": ("PlayfairDisplay-BoldItalic.ttf", ("Times", "BI")),
}

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

Color = tuple[int, int, int]
Point = tuple[float, float]


@dataclass(frozen=True)
class CertificateArt:
    """Everything printed on the certificate (and nothing else: the PDF hash covers exactly this)."""

    name: str
    course_title: str  # the emphasised line: course / programme, internship role, event, ...
    public_code: str
    issued_on: date
    verify_url: str
    issuer: str = DEFAULT_COMPANY  # issuing organisation (header line)
    kind: str = "Course Completion"
    signatory: str = ""  # name; empty = only the "Authorised Signatory" caption
    signatory_title: str = ""  # designation
    subtitle: str = "of Completion"  # on the ribbon
    lead: str = "This is to certify that"
    citation: str = "has successfully completed the"
    details: str = ""  # sentence under the emphasis ("from ... to ..., comprising ..., with grade A.")
    number_label: str = "Certificate No."
    note: str = ""  # one italic line (merit / project / specific citation)
    skills: tuple[str, ...] = ()
    facts: tuple[tuple[str, str], ...] = ()  # extra "LABEL value" cells (scores, cohort)
    tagline: str = DEFAULT_TAGLINE  # under the organisation name (skipped when the lockup says it)
    signature_image: bytes | None = field(default=None, repr=False)  # PNG/JPEG over the line
    logo_left: bytes | None = field(default=None, repr=False)  # optional top-row logo slots
    logo_right: bytes | None = field(default=None, repr=False)
    watermark: bool = True  # faint Tech Drona mark behind the content
    preview: bool = False  # draft: "DRAFT" number, no QR / verify link, PREVIEW watermark


def long_date(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def roman(n: int) -> str:
    out = []
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
                 (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):  # fmt: skip
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def _host(url: str) -> str:
    return url.split("://", 1)[-1].rstrip("/")


def _norm(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


def tagline_shown(tagline: str) -> str:
    """The tagline line under the organisation name; empty when it only repeats the lockup's own
    tagline ("Debug your career. Deploy your dreams.")."""
    t = " ".join((tagline or "").split())
    return "" if not t or _norm(t) == _norm(DEFAULT_TAGLINE) else t


class _Doc:
    """fpdf2 wrapper: font registry with core-font fallback, tracked/centred text, vector bits."""

    def __init__(self, orientation: str = "L") -> None:
        from fpdf import FPDF

        self.pdf = FPDF(orientation=orientation, unit="pt", format="A4")
        self.pdf.set_auto_page_break(False)
        self.pdf.set_margins(0, 0, 0)
        self.ttf: dict[str, bool] = {}
        for key, (fname, _core) in _FONTS.items():
            path = FONT_DIR / fname
            ok = False
            if path.is_file():
                try:
                    self.pdf.add_font(key, "", str(path))
                    ok = True
                except Exception:  # broken font file -> core fallback
                    ok = False
            self.ttf[key] = ok

    # ----------------------------------------------------------------- text
    def _has_glyphs(self, key: str, text: str) -> bool:
        font = self.pdf.fonts.get(key)
        cmap = getattr(font, "cmap", None)
        if not cmap:
            return True
        return all(ord(c) in cmap or c.isspace() for c in text)

    def font(self, key: str, size: float, text: str = "") -> str:
        """Select ``key`` (or a fallback that can draw ``text``); returns the text to draw."""
        if self.ttf.get(key) and self._has_glyphs(key, text):
            self.pdf.set_font(key, "", size)
            return text
        if self.ttf.get("gar") and self._has_glyphs("gar", text):  # e.g. a name Playfair can't draw
            self.pdf.set_font("gar", "", size)
            return text
        family, style = _FONTS[key][1]
        self.pdf.set_font(family, style, size)
        return text.encode("latin-1", "replace").decode("latin-1")

    def width(self, key: str, size: float, text: str, spacing: float = 0.0) -> float:
        t = self.font(key, size, text)
        return self.pdf.get_string_width(t) + spacing * max(len(t) - 1, 0)

    def text(
        self,
        key: str,
        size: float,
        text: str,
        *,
        x: float,
        y: float,
        color: Color,
        align: str = "center",
        spacing: float = 0.0,
    ) -> float:
        """Draw at baseline ``y``; ``x`` is the centre / left / right edge per ``align``. Returns width."""
        t = self.font(key, size, text)
        self.pdf.set_char_spacing(spacing)
        # fpdf2's width already includes the spacing after every character (drop the last one)
        w = self.pdf.get_string_width(t) - (spacing if t else 0.0)
        x0 = x - w / 2 if align == "center" else (x - w if align == "right" else x)
        self.pdf.set_text_color(*color)
        self.pdf.text(x0, y, t)
        self.pdf.set_char_spacing(0)
        return w

    def fit_size(
        self, key: str, text: str, size: float, max_w: float, min_size: float, spacing: float = 0.0
    ) -> float:
        while size > min_size and self.width(key, size, text, spacing) > max_w:
            size -= 0.5
        return size

    def wrap(self, key: str, size: float, text: str, max_w: float) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if cur and self.width(key, size, cand) > max_w:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            lines.append(cur)
        return lines

    # ----------------------------------------------------------------- vectors
    def line(self, x1: float, y1: float, x2: float, y2: float, color: Color, w: float) -> None:
        self.pdf.set_draw_color(*color)
        self.pdf.set_line_width(w)
        self.pdf.line(x1, y1, x2, y2)

    def rect(
        self, x: float, y: float, w: float, h: float, *, stroke=None, fill=None, lw: float = 0.5
    ) -> None:
        style = ("D" if stroke else "") + ("F" if fill else "")
        if stroke:
            self.pdf.set_draw_color(*stroke)
            self.pdf.set_line_width(lw)
        if fill:
            self.pdf.set_fill_color(*fill)
        self.pdf.rect(x, y, w, h, style=style or "D")

    def poly(self, pts: list[Point], *, fill=None, stroke=None, lw: float = 0.5) -> None:
        style = ("D" if stroke else "") + ("F" if fill else "")
        if fill:
            self.pdf.set_fill_color(*fill)
        if stroke:
            self.pdf.set_draw_color(*stroke)
            self.pdf.set_line_width(lw)
        self.pdf.polygon(pts, style=style or "D")

    def polyline(self, pts: list[Point], color: Color, w: float) -> None:
        self.pdf.set_draw_color(*color)
        self.pdf.set_line_width(w)
        self.pdf.polyline(pts)

    def diamond(self, x: float, y: float, r: float, color: Color, outline: bool = False) -> None:
        pts = [(x, y - r), (x + r * 0.72, y), (x, y + r), (x - r * 0.72, y)]
        if outline:
            self.poly(pts, stroke=color, lw=0.6)
        else:
            self.poly(pts, fill=color)

    def curve(self, pts: list[Point], color: Color, w: float) -> None:
        self.pdf.set_draw_color(*color)
        self.pdf.set_line_width(w)
        self.pdf.bezier(pts, style="D")

    def circle(self, x: float, y: float, r: float, *, fill=None, stroke=None, lw: float = 0.6) -> None:
        style = ("D" if stroke else "") + ("F" if fill else "")
        if fill:
            self.pdf.set_fill_color(*fill)
        if stroke:
            self.pdf.set_draw_color(*stroke)
            self.pdf.set_line_width(lw)
        self.pdf.circle(x=x, y=y, radius=r, style=style or "D")

    @contextmanager
    def _shading(self, make: Callable[[], object], flat: Color) -> Iterator[None]:
        """Fill with a gradient (fpdf2 >= 2.8); a flat colour when gradients are unavailable."""
        self.pdf.set_fill_color(*flat)
        try:
            shading = make()
        except Exception:  # older fpdf2: flat fill
            yield
            return
        with self.pdf.use_pattern(shading):  # type: ignore[arg-type]
            yield

    def radial(self, cx: float, cy: float, r: float, inner: Color, outer: Color):
        """Radial-gradient fill context: ``with d.radial(...): d.pdf.circle(..., style="F")``."""

        def make() -> object:
            from fpdf.pattern import RadialGradient

            return RadialGradient(cx, cy, 0, cx, cy, r, [inner, outer], extend_before=True, extend_after=True)

        return self._shading(make, outer)

    def linear(self, x1: float, y1: float, x2: float, y2: float, colors: list[Color]):
        def make() -> object:
            from fpdf.pattern import LinearGradient

            return LinearGradient(x1, y1, x2, y2, colors, extend_before=True, extend_after=True)

        return self._shading(make, colors[len(colors) // 2])


# --------------------------------------------------------------------------- geometry


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, n: int = 18) -> list[Point]:
    out = []
    for i in range(n + 1):
        t = i / n
        m = 1 - t
        a, b, c, e = m * m * m, 3 * m * m * t, 3 * m * t * t, t * t * t
        out.append(
            (a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1])
        )
    return out


def _leaf_pts(x: float, y: float, ang: float, length: float, width: float, n: int = 9) -> list[Point]:
    """A pointed leaf from (x, y) towards angle ``ang`` (radians, y down)."""
    ux, uy = math.cos(ang), math.sin(ang)
    nx, ny = -uy, ux
    left, right = [], []
    for i in range(n + 1):
        t = i / n
        hw = width / 2 * math.sin(math.pi * t) ** 0.85 * (1 - 0.3 * t)
        px, py = x + ux * length * t, y + uy * length * t
        left.append((px + nx * hw, py + ny * hw))
        right.append((px - nx * hw, py - ny * hw))
    return left + right[::-1]


def _spiral(cx: float, cy: float, r0: float, r1: float, a0: float, turns: float, sense: int) -> list[Point]:
    n = max(12, int(28 * turns))
    pts = []
    for i in range(n + 1):
        t = i / n
        r = r0 + (r1 - r0) * t
        a = a0 + sense * 2 * math.pi * turns * t
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# --------------------------------------------------------------------------- ornaments


def _corner(d: _Doc, cx: float, cy: float, sx: int, sy: int, k: float = 1.0) -> None:
    """Gold corner flourish anchored at the inner border corner (cx, cy), growing inwards."""

    def tf(u: float, v: float) -> Point:
        return (cx + sx * u * k, cy + sy * v * k)

    for swap in (False, True):

        def p(u: float, v: float, swap: bool = swap) -> Point:
            return tf(v, u) if swap else tf(u, v)

        # arm along the edge: a wave ending in a small curl
        d.curve([p(16, 8), p(34, 1), p(50, 19), p(70, 11)], GOLD, 1.1 * k)
        d.curve([p(70, 11), p(80, 7), p(90, 5), p(99, 9)], GOLD, 0.8 * k)
        sp = _spiral(0, 0, 4.6, 0.8, -math.pi / 2, 1.05, 1)
        d.polyline([p(97 + x, 13.4 + y) for x, y in sp], GOLD, 0.7 * k)
        # thin echo line inside the wave
        d.curve([p(22, 14), p(36, 9), p(46, 24), p(60, 19)], GOLD_LIGHT, 0.55 * k)
        # leaves on the arm
        for u, v, a, ln, wd in (
            (30, 5.5, -0.42, 13, 5.2),
            (45, 14.5, 0.62, 12, 4.6),
            (63, 12.5, -0.5, 10, 4.0),
            (80, 8.5, 0.45, 8, 3.2),
        ):
            pts = _leaf_pts(u, v, a, ln, wd)
            d.poly([p(x, y) for x, y in pts], fill=GOLD)
        # a dot at the end of each leaf row
        bx, by = p(88, 15)
        d.circle(bx, by, 1.1 * k, fill=GOLD)
    # central curl in the corner, joining both arms
    sp = _spiral(0, 0, 11.5, 2.2, math.pi * 0.25, 1.35, 1)
    d.polyline([tf(22 + x, 22 + y) for x, y in sp], GOLD, 1.1 * k)
    x0, y0 = tf(22, 22)
    d.circle(x0, y0, 1.8 * k, fill=GOLD)
    d.diamond(*tf(8, 8), 3.4 * k, GOLD)


def _side_ornament(d: _Doc, x: float, y: float, horizontal: bool, k: float = 1.0) -> None:
    """Diamond with two tiny scrolls, centred on a border (top / bottom / left / right)."""
    for rad, col in ((6.2, GOLD), (2.6, CREAM)):
        r = rad * k
        if horizontal:
            d.diamond(x, y, r, col)
        else:
            d.poly([(x - r, y), (x, y - r * 0.72), (x + r, y), (x, y + r * 0.72)], fill=col)
    for s in (-1, 1):
        if horizontal:
            d.curve([(x + s * 7 * k, y), (x + s * 12 * k, y - 4 * k), (x + s * 17 * k, y + 3 * k),
                     (x + s * 22 * k, y)], GOLD, 0.7 * k)  # fmt: skip
            d.circle(x + s * 23.5 * k, y, 1.1 * k, fill=GOLD)
        else:
            d.curve([(x, y + s * 7 * k), (x - 4 * k, y + s * 12 * k), (x + 3 * k, y + s * 17 * k),
                     (x, y + s * 22 * k)], GOLD, 0.7 * k)  # fmt: skip
            d.circle(x, y + s * 23.5 * k, 1.1 * k, fill=GOLD)


def _beads(d: _Doc, x0: float, y0: float, x1: float, y1: float, step: float, r: float) -> None:
    """A row of small gold diamonds and dots between two points (the outer border band)."""
    n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
    for i in range(n + 1):
        t = i / n
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        if i % 2:
            d.circle(x, y, r * 0.45, fill=GOLD)
        else:
            d.poly([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=GOLD_LIGHT)


def _frame(
    d: _Doc,
    w: float,
    h: float,
    *,
    inset: float = 15.0,
    k: float = 1.0,
    corner: float = 1.3,
    beads: bool = True,
) -> float:
    """Parchment + gold double border with corner flourishes. Returns the inner border inset."""
    d.rect(0, 0, w, h, fill=PARCHMENT_EDGE)
    with d.radial(w / 2, h / 2, math.hypot(w, h) * 0.55, CREAM, PARCHMENT_EDGE):
        d.pdf.rect(0, 0, w, h, style="F")
    o = inset
    d.rect(o, o, w - 2 * o, h - 2 * o, stroke=GOLD, lw=2.2 * k)
    d.rect(o + 3.4 * k, o + 3.4 * k, w - 2 * o - 6.8 * k, h - 2 * o - 6.8 * k, stroke=GOLD_DARK, lw=0.45 * k)
    band = o + 8.6 * k
    if beads:
        _beads(d, o + 30 * k, band, w - o - 30 * k, band, 7.2 * k, 1.6 * k)
        _beads(d, o + 30 * k, h - band, w - o - 30 * k, h - band, 7.2 * k, 1.6 * k)
        _beads(d, band, o + 30 * k, band, h - o - 30 * k, 7.2 * k, 1.6 * k)
        _beads(d, w - band, o + 30 * k, w - band, h - o - 30 * k, 7.2 * k, 1.6 * k)
    i = o + 14 * k
    d.rect(i, i, w - 2 * i, h - 2 * i, stroke=GOLD_DARK, lw=0.45 * k)
    i2 = i + 3 * k
    d.rect(i2, i2, w - 2 * i2, h - 2 * i2, stroke=GOLD, lw=1.6 * k)
    i3 = i2 + 3.6 * k
    d.rect(i3, i3, w - 2 * i3, h - 2 * i3, stroke=GOLD_LIGHT, lw=0.5 * k)
    for cx, cy, sx, sy in (
        (i3, i3, 1, 1),
        (w - i3, i3, -1, 1),
        (i3, h - i3, 1, -1),
        (w - i3, h - i3, -1, -1),
    ):
        _corner(d, cx, cy, sx, sy, k * corner)
        # outer corner: a gold square knot over the border band
        ox, oy = (o if sx > 0 else w - o), (o if sy > 0 else h - o)
        d.poly(
            [
                (ox + sx * 2, oy + sy * 2),
                (ox + sx * 12 * k, oy + sy * 2),
                (ox + sx * 12 * k, oy + sy * 12 * k),
                (ox + sx * 2, oy + sy * 12 * k),
            ],
            fill=GOLD,
        )
        d.diamond(ox + sx * 7 * k, oy + sy * 7 * k, 3.2 * k, CREAM)
    _side_ornament(d, w / 2, i2, True, k)
    _side_ornament(d, w / 2, h - i2, True, k)
    _side_ornament(d, i2, h / 2, False, k)
    _side_ornament(d, w - i2, h / 2, False, k)
    return i3


def draw_image(d: _Doc, data: bytes, cx: float, bottom: float, max_w: float, max_h: float) -> bool:
    """Draw a PNG/JPEG (signature / seal / logo) centred on ``cx`` with its foot at ``bottom``,
    scaled into ``max_w`` x ``max_h``. Returns False (nothing drawn) for an unreadable image."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            iw, ih = im.size
        if not iw or not ih:
            return False
        k = min(max_w / iw, max_h / ih)
        w, h = iw * k, ih * k
        d.pdf.image(io.BytesIO(data), x=cx - w / 2, y=bottom - h, w=w, h=h)
        return True
    except Exception:  # a broken upload never blocks a document
        return False


def draw_image_mid(d: _Doc, data: bytes, cx: float, cy: float, max_w: float, max_h: float) -> bool:
    """Like ``draw_image`` but vertically centred on ``cy`` (logo slots)."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            iw, ih = im.size
        if not iw or not ih:
            return False
        k = min(max_w / iw, max_h / ih)
        return draw_image(d, data, cx, cy + ih * k / 2, max_w, max_h)
    except Exception:
        return False


def draw_lockup(d: _Doc, cx: float, top: float, width: float) -> bool:
    """The official Tech Drona lockup (vector). Falls back to a typeset name when missing."""
    if LOGO_SVG.is_file():
        with contextlib.suppress(Exception):  # unreadable SVG: typeset lockup below
            d.pdf.image(str(LOGO_SVG), x=cx - width / 2, y=top, w=width, h=width * LOGO_RATIO)
            return True
    h = width * LOGO_RATIO
    d.text("cinBold", h * 0.42, "TECH DRONA", x=cx, y=top + h * 0.6, color=NAVY, spacing=h * 0.06)
    d.text("cin", h * 0.12, DEFAULT_TAGLINE.upper(), x=cx, y=top + h * 0.86, color=NAVY, spacing=h * 0.02)
    return False


def logo_row(
    d: _Doc,
    *,
    cx: float,
    top: float,
    lockup_w: float,
    slot_dx: float,
    slot_w: float,
    slot_h: float,
    left: bytes | None,
    right: bytes | None,
) -> float:
    """Centre lockup + optional side logos with thin gold dividers. Returns the row's bottom."""
    lh = lockup_w * LOGO_RATIO
    draw_lockup(d, cx, top, lockup_w)
    mid = top + lh / 2
    div = lockup_w / 2 + (slot_dx - lockup_w / 2 - slot_w / 2) / 2
    for s, img in ((-1, left), (1, right)):
        if img and draw_image_mid(d, img, cx + s * slot_dx, mid, slot_w, slot_h):
            dx = cx + s * div
            d.line(dx, mid - lh * 0.55, dx, mid + lh * 0.55, GOLD, 0.7)
    return top + max(lh, slot_h if (left or right) else 0)


def brand_watermark(d: _Doc, cx: float, cy: float, size: float) -> bool:
    """The Tech Drona mark centred on (``cx``, ``cy``), ``size`` wide, very faint. Draw it before
    the page's content so everything (signature, seal, text) sits on top. False when unavailable."""
    if not LOGO_MARK_SVG.is_file():
        return False
    try:
        with d.pdf.local_context(fill_opacity=WATERMARK_OPACITY, stroke_opacity=WATERMARK_OPACITY):
            d.pdf.image(str(LOGO_MARK_SVG), x=cx - size / 2, y=cy - size / 2, w=size, h=size)
        return True
    except Exception:  # unreadable SVG / old fpdf2: no watermark, never a failed document
        return False


def preview_watermark(d: _Doc, w: float, h: float) -> None:
    """A large diagonal "PREVIEW · NOT VALID" across the page (bottom-left to top-right), drawn
    over the content and translucent so the text below stays readable."""
    ang = math.degrees(math.atan2(h, w))
    size = d.fit_size("cinBold", PREVIEW_MARK, 96, math.hypot(w, h) * 0.66, 30, 4)
    with d.pdf.local_context(fill_opacity=PREVIEW_OPACITY), d.pdf.rotation(ang, x=w / 2, y=h / 2):
        d.text("cinBold", size, PREVIEW_MARK, x=w / 2, y=h / 2 + size * 0.34, color=PREVIEW_RED, spacing=4)


def preview_note(d: _Doc, x: float, y: float, *, size: float = 8.5, align: str = "center",
                 max_w: float = 150) -> float:  # fmt: skip
    """The small italic "Verification code appears when the document is issued" (in place of the
    QR / verify link). Returns the last baseline."""
    lines = d.wrap("garIt", size, PREVIEW_NOTE, max_w)
    for i, ln in enumerate(lines):
        d.text("garIt", size, ln, x=x, y=y + i * size * 1.2, color=SLATE, align=align)
    return y + (len(lines) - 1) * size * 1.2


def ribbon(d: _Doc, cx: float, top: float, width: float, height: float, label: str, size: float) -> None:
    """Navy ribbon banner with gold edges and folded swallow-tail ends."""
    x0, x1 = cx - width / 2, cx + width / 2
    drop, tail = height * 0.32, height * 1.05
    for s, xe in ((-1, x0), (1, x1)):
        ty0, ty1 = top + drop, top + height + drop
        outer = xe + s * tail
        pts = [(xe - s * 4, ty0), (outer, ty0), (outer - s * height * 0.32, (ty0 + ty1) / 2), (outer, ty1),
               (xe - s * 4, ty1)]  # fmt: skip
        d.poly(pts, fill=NAVY_DARK)
        d.polyline([(xe, ty0 + 1.6), (outer - s * 1.5, ty0 + 1.6)], GOLD, 0.9)
        d.polyline([(xe, ty1 - 1.6), (outer - s * 1.5, ty1 - 1.6)], GOLD, 0.9)
        d.poly([(xe, top + height), (xe - s * 0.01, top + height + drop), (xe - s * 9, top + height + drop)],
               fill=(4, 12, 34))  # fmt: skip
    with d.linear(0, top, 0, top + height, [NAVY_LIGHT, NAVY, NAVY_DARK]):
        d.pdf.rect(x0, top, width, height, style="F")
    d.line(x0, top + 1.2, x1, top + 1.2, GOLD_LIGHT, 1.6)
    d.line(x0, top + 3.6, x1, top + 3.6, GOLD, 0.5)
    d.line(x0, top + height - 1.2, x1, top + height - 1.2, GOLD_LIGHT, 1.6)
    d.line(x0, top + height - 3.6, x1, top + height - 3.6, GOLD, 0.5)
    fs = d.fit_size("pfSemiIt", label, size, width - 30, size * 0.6)
    d.text("pfSemiIt", fs, label, x=cx, y=top + height / 2 + fs * 0.33, color=RIBBON_TEXT)


def side_scroll(d: _Doc, x: float, y: float, length: float, direction: int) -> None:
    """Gold filigree running outwards from ``x`` (direction -1 = to the left)."""
    k = length / 100

    def p(u: float, v: float) -> Point:
        return (x + direction * u * k, y + v * k)

    d.curve([p(0, 0), p(22, -9), p(38, 9), p(58, 0)], GOLD, 1.0)
    d.curve([p(58, 0), p(72, -6), p(84, -4), p(92, -1)], GOLD, 0.8)
    sp = _spiral(0, 0, 5.5, 1.0, math.pi / 2, 1.1, -direction)
    d.polyline([p(92 + u, 5.5 + v) for u, v in sp], GOLD, 0.75)
    sp = _spiral(0, 0, 4.5, 0.8, -math.pi / 2, 1.1, direction)
    d.polyline([p(20 + u, -9 + v) for u, v in sp], GOLD, 0.7)
    for u, v, a, ln, wd in ((36, 4, 0.55, 10, 4), (48, 3.5, -0.75, 10, 4), (70, -5, -0.5, 8, 3.2)):
        ang = a if direction > 0 else math.pi - a
        d.poly(_leaf_pts(*p(u, v), ang, ln * k, wd * k), fill=GOLD)
    d.circle(*p(100, 0), 1.3, fill=GOLD)


def laurel(d: _Doc, cx: float, cy: float, height: float, side: int) -> None:
    """A laurel sprig curving like "(" (side -1, left of the name) or ")" (side 1, mirrored)."""
    r = height * 0.8

    def at(a: float) -> Point:  # stem point for angle a (left sprig: centre of curvature to the right)
        x = r * math.cos(a) + r * 0.9
        return (cx + x if side < 0 else cx - x, cy + r * math.sin(a))

    def ang(a: float) -> float:  # a direction in the left sprig, mirrored for the right one
        return a if side < 0 else math.pi - a

    a0, a1 = math.radians(142), math.radians(220)
    d.polyline([at(a0 + (a1 - a0) * i / 24) for i in range(25)], GOLD_DARK, 1.0)
    n = 7
    for i in range(n):
        t = 0.1 + 0.82 * i / (n - 1)
        a = a0 + (a1 - a0) * t
        tang = math.atan2(math.cos(a), -math.sin(a))  # towards the tip
        ln = height * (0.24 - 0.09 * t)
        for s in (-1, 1):
            d.poly(_leaf_pts(*at(a), ang(tang + s * 0.66), ln, ln * 0.42), fill=GOLD)
    tang = math.atan2(math.cos(a1), -math.sin(a1))
    d.poly(_leaf_pts(*at(a1), ang(tang), height * 0.16, height * 0.065), fill=GOLD)
    d.circle(*at(a0), 1.3, fill=GOLD_DARK)


def name_rule(d: _Doc, cx: float, y: float, half: float) -> None:
    d.line(cx - half, y, cx - 9, y, GOLD, 0.9)
    d.line(cx + 9, y, cx + half, y, GOLD, 0.9)
    d.line(cx - half * 0.8, y + 2.4, cx - 14, y + 2.4, GOLD_LIGHT, 0.4)
    d.line(cx + 14, y + 2.4, cx + half * 0.8, y + 2.4, GOLD_LIGHT, 0.4)
    d.diamond(cx, y, 5.2, GOLD)
    d.diamond(cx, y, 2.0, GOLD_PALE)
    d.diamond(cx - half - 4, y, 1.8, GOLD)
    d.diamond(cx + half + 4, y, 1.8, GOLD)


def award_seal(d: _Doc, cx: float, cy: float, r: float) -> None:
    """Gold rosette with a navy centre: three stars, a graduation cap and a small wreath, on
    two navy ribbon tails."""
    # ribbon tails behind the seal
    for s in (-1, 1):
        top = (cx + s * r * 0.22, cy + r * 0.25)
        bot = (cx + s * r * 0.78, cy + r * 1.6)
        dx, dy = bot[0] - top[0], bot[1] - top[1]
        ln = math.hypot(dx, dy)
        nx, ny = -dy / ln * r * 0.27, dx / ln * r * 0.27
        notch = (bot[0] - dx / ln * r * 0.28, bot[1] - dy / ln * r * 0.28)
        pts = [(top[0] + nx, top[1] + ny), (bot[0] + nx, bot[1] + ny), notch, (bot[0] - nx, bot[1] - ny),
               (top[0] - nx, top[1] - ny)]  # fmt: skip
        d.poly(pts, fill=NAVY)
        d.polyline([pts[0], pts[1]], GOLD, 0.8)
        d.polyline([pts[4], pts[3]], GOLD, 0.8)
        d.polyline([pts[1], notch, pts[3]], GOLD, 0.6)
    # scalloped rosette
    ros = []
    for i in range(240):
        a = 2 * math.pi * i / 240
        rr = r * (0.93 + 0.07 * abs(math.cos(14 * a)))
        ros.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    with d.radial(cx - r * 0.35, cy - r * 0.4, r * 1.4, GOLD_PALE, GOLD_DARK):
        d.pdf.polygon(ros, style="F")
    d.poly(ros, stroke=GOLD_DARK, lw=0.4)
    d.circle(cx, cy, r * 0.83, fill=GOLD_DARK)
    with d.radial(cx + r * 0.3, cy + r * 0.3, r * 1.1, GOLD_PALE, GOLD):
        d.pdf.circle(x=cx, y=cy, radius=r * 0.8, style="F")
    with d.radial(cx - r * 0.2, cy - r * 0.25, r * 0.8, NAVY_LIGHT, NAVY_DARK):
        d.pdf.circle(x=cx, y=cy, radius=r * 0.7, style="F")
    d.circle(cx, cy, r * 0.64, stroke=GOLD_LIGHT, lw=0.6)
    # stars
    for a, sz in ((-112, 0.07), (-90, 0.085), (-68, 0.07)):
        x, y = cx + r * 0.49 * math.cos(math.radians(a)), cy + r * 0.49 * math.sin(math.radians(a))
        d.pdf.set_fill_color(*GOLD_PALE)
        d.pdf.star(x, y, r * sz * 0.42, r * sz, 5, rotate_degrees=-90, style="F")
    # graduation cap
    c = (cx, cy - r * 0.02)
    base = [
        (c[0] - r * 0.2, c[1] + r * 0.02),
        (c[0] + r * 0.2, c[1] + r * 0.02),
        (c[0] + r * 0.2, c[1] + r * 0.17),
    ]
    base += _cubic((c[0] + r * 0.2, c[1] + r * 0.17), (c[0] + r * 0.1, c[1] + r * 0.25),
                   (c[0] - r * 0.1, c[1] + r * 0.25), (c[0] - r * 0.2, c[1] + r * 0.17), 10)  # fmt: skip
    d.poly(base, fill=GOLD)
    top_pts = [(c[0] - r * 0.4, c[1] - r * 0.04), (c[0], c[1] - r * 0.2), (c[0] + r * 0.4, c[1] - r * 0.04),
               (c[0], c[1] + r * 0.11)]  # fmt: skip
    d.poly(top_pts, fill=GOLD_PALE, stroke=GOLD_DARK, lw=0.5)
    d.circle(c[0], c[1] - r * 0.045, r * 0.025, fill=GOLD_DARK)
    d.polyline(
        [(c[0], c[1] - r * 0.045), (c[0] + r * 0.3, c[1] + r * 0.02), (c[0] + r * 0.3, c[1] + r * 0.2)],
        GOLD_PALE,
        0.7,
    )
    d.poly(
        [
            (c[0] + r * 0.27, c[1] + r * 0.2),
            (c[0] + r * 0.33, c[1] + r * 0.2),
            (c[0] + r * 0.34, c[1] + r * 0.28),
            (c[0] + r * 0.26, c[1] + r * 0.28),
        ],
        fill=GOLD_PALE,
    )
    # wreath around the lower half of the navy disc: two branches rising from the bottom
    rr = r * 0.52
    for side in (-1, 1):
        angs = [math.radians(90 - side * (14 + 9.5 * i)) for i in range(12)]
        d.polyline([(cx + rr * math.cos(a), cy + rr * math.sin(a)) for a in angs], GOLD_LIGHT, 0.5)
        for i, a in enumerate(angs[1::2]):
            px, py = cx + rr * math.cos(a), cy + rr * math.sin(a)
            tang = math.atan2(-side * math.cos(a), side * math.sin(a))  # along the arc, upwards
            ln = r * (0.14 - 0.012 * i)
            for t in (-1, 1):
                d.poly(_leaf_pts(px, py, tang + t * 0.6, ln, ln * 0.45, 7), fill=GOLD_LIGHT)


def calendar_icon(d: _Doc, x: float, y: float, s: float, color: Color) -> None:
    """A small calendar outline (top-left at x, y; size s)."""
    d.rect(x, y + s * 0.12, s, s * 0.88, stroke=color, lw=0.7)
    d.rect(x, y + s * 0.12, s, s * 0.22, fill=color)
    for fx in (0.28, 0.72):
        d.line(x + s * fx, y, x + s * fx, y + s * 0.2, color, 0.9)
    for row in range(3):
        for col in range(4):
            d.rect(x + s * (0.12 + col * 0.21), y + s * (0.44 + row * 0.17), s * 0.11, s * 0.09, fill=color)


def card_icon(d: _Doc, x: float, y: float, s: float, color: Color) -> None:
    """A small ID-card outline (certificate number)."""
    h = s * 0.74
    d.rect(x, y + (s - h) / 2, s, h, stroke=color, lw=0.7)
    d.circle(x + s * 0.28, y + s * 0.42, s * 0.1, fill=color)
    d.poly([(x + s * 0.13, y + s * 0.7), (x + s * 0.43, y + s * 0.7), (x + s * 0.4, y + s * 0.56),
            (x + s * 0.16, y + s * 0.56)], fill=color)  # fmt: skip
    for i in range(3):
        d.line(x + s * 0.54, y + s * (0.38 + i * 0.13), x + s * 0.88, y + s * (0.38 + i * 0.13), color, 0.7)


def qr(d: _Doc, url: str, x: float, y: float, size: float, *, frame: Color = GOLD) -> bool:
    try:
        import segno
    except ImportError:  # dependency not installed: the verify line carries the URL
        return False
    code = segno.make(url, error="m", micro=False)
    rows = [list(r) for r in code.matrix]
    n = len(rows)
    d.rect(x, y, size, size, stroke=frame, fill=WHITE, lw=0.5)
    m = size / (n + 4)
    ox, oy = x + 2 * m, y + 2 * m
    d.pdf.set_fill_color(*NAVY_DARK)
    for r, row in enumerate(rows):
        c = 0
        while c < n:
            if row[c]:
                start = c
                while c < n and row[c]:
                    c += 1
                d.pdf.rect(ox + start * m, oy + r * m, (c - start) * m + 0.02, m + 0.02, style="F")
            else:
                c += 1
    return True


def signature_block(
    d: _Doc,
    *,
    cx: float,
    line_y: float,
    width: float,
    signatory: str,
    designation: str,
    image: bytes | None,
    img_h: float = 40.0,
) -> float:
    """One signature: image (or nothing) over a navy line, "Name, Designation" and the
    "AUTHORISED SIGNATORY" caption. Returns the caption's baseline."""
    if image:
        draw_image(d, image, cx, line_y - 2, width * 0.9, img_h)
    d.line(cx - width / 2, line_y, cx + width / 2, line_y, NAVY, 0.7)
    d.diamond(cx - width / 2 - 3, line_y, 1.6, GOLD)
    d.diamond(cx + width / 2 + 3, line_y, 1.6, GOLD)
    name = ", ".join(x for x in (" ".join(signatory.split()), " ".join(designation.split())) if x)
    y = line_y + 15
    if name:
        d.text("pfBold", d.fit_size("pfBold", name, 12, width + 50, 8), name, x=cx, y=y, color=NAVY)
        y += 14
    else:
        y += 2
    cap = "AUTHORISED SIGNATORY"
    d.text("gar", 7.6, cap, x=cx, y=y, color=SLATE, spacing=2.6)
    return y


# --------------------------------------------------------------------------- public API


def _optional_lines(art: CertificateArt) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if art.note:
        out.append(("note", " ".join(art.note.split())))
    if art.facts:
        out.append(("caps", "  ·  ".join(f"{a.upper()} {' '.join(b.split())}" for a, b in art.facts)))
    if art.skills:
        out.append(("caps", "  ·  ".join(" ".join(s.split()) for s in art.skills).upper()))
    return out


def render_certificate_pdf(art: CertificateArt) -> bytes:
    """Render one certificate; deterministic for equal ``art``."""
    d = _Doc()
    pdf = d.pdf
    number = PREVIEW_REF if art.preview else art.public_code
    pdf.set_title(f"Certificate {number}" + (" (preview, not valid)" if art.preview else ""))
    pdf.set_author(art.issuer)
    pdf.set_subject(f"{art.kind}: {art.course_title}")
    pdf.set_creator("Tech Drona LMS")
    pdf.set_producer("Tech Drona LMS")
    pdf.set_creation_date(datetime.combine(art.issued_on, time(0, 0)))
    pdf.add_page()
    _frame(d, W, H)
    if art.watermark:  # behind the body; the seal and signature (y > 420) stay clear of it
        brand_watermark(d, CX, 268, 268)

    # top row: [logo] | TECH DRONA lockup | [logo]
    logo_row(d, cx=CX, top=50, lockup_w=206, slot_dx=228, slot_w=100, slot_h=54, left=art.logo_left,
             right=art.logo_right)  # fmt: skip

    # issuing organisation + tagline
    org = " ".join((art.issuer or DEFAULT_COMPANY).split()).upper()
    os_ = d.fit_size("pfBold", org, 15, 430, 10, 1.4)
    ow = d.text("pfBold", os_, org, x=CX, y=122, color=NAVY, spacing=1.4)
    for s in (-1, 1):
        x_in = CX + s * (ow / 2 + 12)
        d.line(x_in, 117.2, x_in + s * 70, 117.2, GOLD, 0.9)
        d.diamond(x_in + s * 73, 117.2, 1.7, GOLD)
    tag = tagline_shown(art.tagline)
    if tag:
        tg = tag.upper()
        d.text("gar", d.fit_size("gar", tg, 7.6, 420, 5.5, 3.2), tg, x=CX, y=135, color=SLATE, spacing=3.2)

    # CERTIFICATE + ribbon
    d.text("pfBold", 52, "CERTIFICATE", x=CX, y=188, color=NAVY, spacing=3.5)
    rw = max(230.0, d.width("pfSemiIt", 20, art.subtitle) + 90)
    ribbon(d, CX, 195, rw, 29, art.subtitle, 20)
    side_scroll(d, CX - rw / 2 - 46, 212, 92, -1)
    side_scroll(d, CX + rw / 2 + 46, 212, 92, 1)

    # body: lead, name (laurels + rule), citation, emphasis, details, optional lines
    name = " ".join(art.name.split()) or "Learner"
    title = " ".join(art.course_title.split()) or "Course"
    extra = _optional_lines(art)
    limit = 410.0  # last body baseline (the seal and signature start below)
    for k in (1.0, 0.94, 0.88, 0.82, 0.76):
        ts = 21.0 * min(1.0, k + 0.06)
        lines = d.wrap("pfBoldIt", ts, title, 580)
        while len(lines) > 2 and ts > 13:
            ts -= 0.5
            lines = d.wrap("pfBoldIt", ts, title, 580)
        lines = lines[:2]
        y_name = 252 + 44 * k
        y_cit = y_name + 40 * k
        y_title = y_cit + 26 * k
        y_det = y_title + (len(lines) - 1) * ts * 1.12 + 22 * k
        y_end = (y_det if art.details else y_det - 22 * k) + 16 * k * len(extra)
        if y_end <= limit:
            break
    if y_end > limit and extra:  # still too tall: keep the most important optional lines
        extra = extra[: max(0, len(extra) - math.ceil((y_end - limit) / (16 * k)))]

    d.text("garIt", 15.5, " ".join(art.lead.split()), x=CX, y=252, color=LEAD)
    ns = d.fit_size("pfBoldIt", name, 36 * min(1.0, k + 0.1), 500, 20)
    nw = d.text("pfBoldIt", ns, name, x=CX, y=y_name, color=NAVY)
    lx = min(max(nw / 2 + 44, 150), 280)
    for s in (-1, 1):
        laurel(d, CX + s * lx, y_name - ns * 0.36, ns * 1.7, s)
    name_rule(d, CX, y_name + 13 * k, max(min(nw / 2 + 40, 300), 190))
    cit = " ".join(art.citation.split())
    d.text("garIt", d.fit_size("garIt", cit, 14, 620, 10), cit, x=CX, y=y_cit, color=BODY)
    for i, ln in enumerate(lines):
        d.text("pfBoldIt", ts, ln, x=CX, y=y_title + i * ts * 1.12, color=NAVY)
    y = y_title + (len(lines) - 1) * ts * 1.12
    if art.details:
        det = " ".join(art.details.split())
        y += 22 * k
        dlines = d.wrap("garIt", 13, det, 640)
        if len(dlines) > 1:
            ds = d.fit_size("garIt", det, 13, 640, 9.5)
            det_lines = [det] if d.width("garIt", ds, det) <= 640 else d.wrap("garIt", 11, det, 640)[:2]
            for j, dl in enumerate(det_lines):
                d.text("garIt", ds if len(det_lines) == 1 else 11, dl, x=CX, y=y + j * 13, color=BODY)
            y += (len(det_lines) - 1) * 13
        else:
            d.text("garIt", 13, det, x=CX, y=y, color=BODY)
    for kind, txt in extra:
        y += 16 * k
        if kind == "note":
            d.text("garIt", d.fit_size("garIt", txt, 11.5, 600, 8), txt, x=CX, y=y, color=LEAD)
        else:
            d.text(
                "gar", d.fit_size("gar", txt, 7.6, 600, 5, 1.2), txt, x=CX, y=y, color=GOLD_TEXT, spacing=1.2
            )

    # bottom: verification (left) | seal (centre) | signature (right); number + date below
    line_y = 476.0
    lcx, rcx = 212.0, W - 212.0
    award_seal(d, CX, 468, 48)
    signature_block(
        d,
        cx=rcx,
        line_y=line_y,
        width=200,
        signatory=art.signatory,
        designation=art.signatory_title,
        image=art.signature_image,
        img_h=42,
    )
    if art.preview:  # no QR / verify link: the number does not exist yet
        d.text("gar", 7.6, "PREVIEW  ·  NOT ISSUED", x=lcx, y=line_y - 22, color=PREVIEW_RED, spacing=2.2)
        preview_note(d, lcx, line_y - 6, size=9.5, max_w=200)
    else:
        qs = 48.0
        has_qr = qr(d, art.verify_url, lcx - qs / 2, line_y - qs + 4, qs)
        if not has_qr:
            d.text("gar", 7, "VERIFY ONLINE", x=lcx, y=line_y - 18, color=GOLD_TEXT, spacing=1.5)
        d.text("gar", 7.6, "SCAN TO VERIFY", x=lcx, y=line_y + 16, color=SLATE, spacing=2.6)
        host = _host(art.verify_url)
        d.text("garIt", d.fit_size("garIt", host, 8.5, 230, 5.5), host, x=lcx, y=line_y + 29, color=SLATE)

    row_y = 531.0
    _bottom_item(d, lcx, row_y, f"{art.number_label} :", number, card_icon)
    _bottom_item(d, rcx, row_y, "Date of Issue :", long_date(art.issued_on), calendar_icon)
    if art.preview:
        preview_watermark(d, W, H)
    return bytes(pdf.output())


def _bottom_item(d: _Doc, cx: float, y: float, label: str, value: str, icon) -> None:
    lw = d.width("garSemi", 11, label)
    vs = d.fit_size("pfIt", value, 11, 190, 7.5)
    vw = d.width("pfIt", vs, value)
    total = 16 + 6 + lw + 5 + vw
    x = cx - total / 2
    icon(d, x, y - 11.5, 14, NAVY)
    x += 20
    d.text("garSemi", 11, label, x=x, y=y, color=NAVY, align="left")
    d.text("pfIt", vs, value, x=x + lw + 5, y=y, color=NAVY, align="left")


def pdf_sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
