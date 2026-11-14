"""Certificate PDF renderer (server side, fpdf2): the company website's "royal diploma" look
(``tech drona/src/lib/docrender.js`` renderCertificate) redrawn with vectors.

A4 landscape, cream parchment, thick gold frame + navy hairline + inner gold rule with corner
diamonds; the "TECH DRONA" lockup in Cinzel, "Certificate" in Cinzel Decorative, "of Completion"
in gold EB Garamond italic, the learner's name in Pinyon Script over a gold flourish, the course
title, a Cinzel facts line, the date of issue and signatory columns, a red wax seal with navy
ribbons, and the QR code (to the public verify page) with the certificate number.

Fonts: the OFL fonts in ``certfonts/`` (same files as the website, licences alongside). When a
font file is missing the renderer falls back to the PDF core fonts (Latin-1 only), so issuing a
certificate never fails because of an asset.

QR: ``segno`` (pure Python). Without it the verify URL is printed instead of the QR.

Deterministic: the same ``CertificateArt`` always renders byte-identical PDFs (fixed creation
date = issue date, content-derived document /ID), so ``sha256(pdf)`` is a stable content hash.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

FONT_DIR = Path(__file__).with_name("certfonts")
TEMPLATE_VERSION = "cert-v2"  # v2 = this PDF design (v1 had no PDF)

# palette (docrender.js C)
NAVY = (16, 34, 79)
INK = (31, 38, 64)
BODY = (42, 51, 85)
LEAD = (59, 69, 102)
SLATE = (74, 83, 112)
BROWN = (107, 90, 51)
GOLD = (168, 128, 47)
GOLD_TEXT = (125, 95, 34)
GOLD_LIGHT = (201, 165, 90)
CREAM = (251, 246, 234)
PARCHMENT_EDGE = (243, 233, 207)
WHITE = (255, 255, 255)
WAX = (155, 28, 28)
WAX_DARK = (118, 18, 18)
WAX_TEXT = (243, 201, 198)

W, H = 841.89, 595.28  # A4 landscape in points
CX = W / 2

_FONTS = {
    "gar": ("EBGaramond-Regular.ttf", ("Times", "")),
    "garIt": ("EBGaramond-Italic.ttf", ("Times", "I")),
    "garSemi": ("EBGaramond-SemiBold.ttf", ("Times", "B")),
    "cin": ("Cinzel-SemiBold.ttf", ("Helvetica", "")),
    "cinBold": ("Cinzel-Bold.ttf", ("Helvetica", "B")),
    "deco": ("CinzelDecorative-Black.ttf", ("Times", "B")),
    "script": ("PinyonScript-Regular.ttf", ("Times", "I")),
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


_DEFAULT_CITATION = "for successfully completing all the requirements of the course"


@dataclass(frozen=True)
class CertificateArt:
    """Everything printed on the certificate (and nothing else: the PDF hash covers exactly this)."""

    name: str
    course_title: str
    public_code: str
    issued_on: date
    verify_url: str
    issuer: str = "Tech Drona"
    kind: str = "Course Completion"
    signatory: str = "Authorised Signatory"
    signatory_title: str = "Tech Drona"
    # Extra certificate types (issued documents, ``docpdf``). The defaults draw the course
    # completion certificate exactly as before, so existing certificates keep their hash.
    subtitle: str = "of Completion"
    lead: str = "This is proudly presented to"
    citation: str = _DEFAULT_CITATION
    number_label: str = "CERTIFICATE NO."
    note: str = ""  # one italic line under the title (project / specific citation)
    skills: tuple[str, ...] = ()
    facts: tuple[tuple[str, str], ...] = ()  # extra "LABEL value" cells after the number
    signature_image: bytes | None = None  # PNG/JPEG drawn above the signatory line


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
        if self.ttf.get("gar") and self._has_glyphs("gar", text):  # e.g. a name Pinyon can't draw
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
        color: tuple[int, int, int],
        align: str = "center",
        spacing: float = 0.0,
    ) -> float:
        """Draw at baseline ``y``; ``x`` is the centre / left / right edge per ``align``. Returns width."""
        t = self.font(key, size, text)
        self.pdf.set_char_spacing(spacing)
        w = self.pdf.get_string_width(t) + spacing * max(len(t) - 1, 0)
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
    def line(self, x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int], w: float) -> None:
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

    def diamond(
        self, x: float, y: float, r: float, color: tuple[int, int, int], outline: bool = False
    ) -> None:
        pts = [(x, y - r), (x + r * 0.72, y), (x, y + r), (x - r * 0.72, y)]
        if outline:
            self.pdf.set_draw_color(*color)
            self.pdf.set_line_width(0.6)
            self.pdf.polygon(pts, style="D")
        else:
            self.pdf.set_fill_color(*color)
            self.pdf.polygon(pts, style="F")

    def curve(self, pts: list[tuple[float, float]], color: tuple[int, int, int], w: float) -> None:
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


# --------------------------------------------------------------------------- pieces


def _frame(d: _Doc) -> None:
    d.rect(0, 0, W, H, fill=PARCHMENT_EDGE)
    d.rect(14, 14, W - 28, H - 28, fill=CREAM)
    d.rect(20, 20, W - 40, H - 40, stroke=GOLD, lw=5.5)
    d.rect(28.5, 28.5, W - 57, H - 57, stroke=NAVY, lw=0.8)
    # gold/navy wave band between the frames
    band_y = (33.0, H - 33.0)
    for yy in band_y:
        x = 60.0
        while x < W - 70:
            d.curve([(x, yy), (x + 9, yy - 3.2), (x + 18, yy + 3.2), (x + 27, yy)], GOLD_LIGHT, 0.55)
            x += 27
    inner = 49.8
    d.rect(inner, inner, W - 2 * inner, H - 2 * inner, stroke=GOLD, lw=1.3)
    d.rect(inner + 3.4, inner + 3.4, W - 2 * inner - 6.8, H - 2 * inner - 6.8, stroke=GOLD, lw=0.35)
    for cx, cy, sx, sy in ((inner, inner, 1, 1), (W - inner, inner, -1, 1), (inner, H - inner, 1, -1),
                           (W - inner, H - inner, -1, -1)):  # fmt: skip
        d.diamond(cx, cy, 6.5, NAVY)
        d.diamond(cx, cy, 10, GOLD, outline=True)
        # corner flourish: two gold scrolls running along the rules
        d.curve([(cx + sx * 14, cy + sy * 8), (cx + sx * 30, cy + sy * 20), (cx + sx * 46, cy + sy * 2),
                 (cx + sx * 72, cy + sy * 10)], GOLD, 0.7)  # fmt: skip
        d.curve([(cx + sx * 8, cy + sy * 14), (cx + sx * 20, cy + sy * 30), (cx + sx * 2, cy + sy * 46),
                 (cx + sx * 10, cy + sy * 72)], GOLD, 0.7)  # fmt: skip


def _lens_rule(d: _Doc, x: float, y: float, length: float, direction: int) -> None:
    k = length / 100

    def px(u: float) -> float:
        return x + direction * u * k

    d.line(px(0), y, px(80), y, GOLD, 0.75)
    d.curve([(px(80), y), (px(84), y - 2.4), (px(88), y - 2.4), (px(92), y)], GOLD, 0.75)
    d.curve([(px(80), y), (px(84), y + 2.4), (px(88), y + 2.4), (px(92), y)], GOLD, 0.75)
    d.line(px(94), y, px(100), y, GOLD, 0.75)


def _flourish(d: _Doc, cx: float, y: float, w: float) -> None:
    k = w / 380

    def px(u: float) -> float:
        return cx + (u - 200) * k

    def py(v: float) -> float:
        return y - (10 - v) * k

    d.curve([(px(10), py(10)), (px(80), py(-2)), (px(140), py(22)), (px(200), py(10))], GOLD, 0.9)
    d.curve([(px(200), py(10)), (px(260), py(-2)), (px(320), py(22)), (px(390), py(10))], GOLD, 0.9)
    r = max(4.2, 7.5 * k)
    d.pdf.set_fill_color(*NAVY)
    d.pdf.polygon([(cx - r * 1.4, y), (cx, y - r * 0.85), (cx + r * 1.4, y), (cx, y + r * 0.85)], style="F")


def _wax_seal(d: _Doc, cx: float, cy: float, year: int) -> None:
    # navy ribbons behind the seal
    d.pdf.set_fill_color(*NAVY)
    for s in (-1, 1):
        ribbon = [(14, 14), (2, 18), (16, 62), (23, 52), (33, 58)]
        d.pdf.polygon([(cx + s * dx, cy + dy) for dx, dy in ribbon], style="F")
    # scalloped wax body
    pts = []
    for i in range(48):
        a = 2 * math.pi * i / 48
        r = 37 + (2.2 if i % 2 == 0 else 0)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.pdf.set_fill_color(*WAX_DARK)
    d.pdf.polygon(pts, style="F")
    d.circle(cx, cy, 33.5, fill=WAX)
    d.circle(cx, cy, 27.5, stroke=WAX_TEXT, lw=0.6)
    d.circle(cx, cy, 25.8, stroke=WAX_TEXT, lw=0.3)
    d.text("cinBold", 11, "TD", x=cx, y=cy + 2.5, color=WAX_TEXT, spacing=1.2)
    d.text("cin", 4.0, "TECH DRONA", x=cx, y=cy - 12, color=WAX_TEXT, spacing=0.6)
    d.text("cinBold", 5.2, roman(year), x=cx, y=cy + 15, color=WAX_TEXT, spacing=1.2)
    d.diamond(cx - 17, cy - 0.5, 1.6, WAX_TEXT)
    d.diamond(cx + 17, cy - 0.5, 1.6, WAX_TEXT)


def _qr(d: _Doc, url: str, x: float, y: float, size: float) -> bool:
    try:
        import segno
    except ImportError:  # dependency not installed: the verify line below still carries the URL
        return False
    qr = segno.make(url, error="m", micro=False)
    rows = [list(r) for r in qr.matrix]
    n = len(rows)
    d.rect(x, y, size, size, stroke=GOLD, fill=WHITE, lw=0.5)
    m = size / (n + 6)
    ox, oy = x + 3 * m, y + 3 * m
    d.pdf.set_fill_color(*NAVY)
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


def draw_image(d: _Doc, data: bytes, cx: float, bottom: float, max_w: float, max_h: float) -> bool:
    """Draw a PNG/JPEG (signature / seal) centred on ``cx`` with its foot at ``bottom``, scaled
    into ``max_w`` x ``max_h``. Returns False (nothing drawn) for an unreadable image."""
    import io

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


# --------------------------------------------------------------------------- public API


def render_certificate_pdf(art: CertificateArt) -> bytes:
    """Render one certificate; deterministic for equal ``art``."""
    d = _Doc()
    pdf = d.pdf
    pdf.set_title(f"Certificate {art.public_code}")
    pdf.set_author(art.issuer)
    pdf.set_subject(f"{art.kind}: {art.course_title}")
    pdf.set_creator("Tech Drona LMS")
    pdf.set_producer("Tech Drona LMS")
    pdf.set_creation_date(datetime.combine(art.issued_on, time(0, 0)))
    pdf.add_page()
    _frame(d)

    # micro line just inside the inner rule at the foot
    micro = (f"{art.issuer} · {art.kind} · verified certificate · " * 8).upper()
    d.font("cin", 2.8, micro)
    while d.width("cin", 2.8, micro, 0.4) > W - 300 and len(micro) > 10:
        micro = micro[:-1]
    d.text("cin", 2.8, micro, x=CX, y=H - 49.8 - 5.5, color=GOLD_TEXT, spacing=0.4)

    # header
    d.text("cinBold", 19, art.issuer.upper(), x=CX, y=88, color=NAVY, spacing=4)
    d.line(CX - 70, 96, CX - 10, 96, GOLD, 0.6)
    d.line(CX + 10, 96, CX + 70, 96, GOLD, 0.6)
    d.diamond(CX, 96, 2.4, GOLD)
    d.text(
        "cin",
        7.6,
        f"{art.kind} · {roman(art.issued_on.year)}".upper(),
        x=CX,
        y=112,
        color=GOLD_TEXT,
        spacing=3,
    )
    d.text("deco", 40, "Certificate", x=CX, y=154, color=NAVY, spacing=2.25)
    sw = d.text("garIt", 20, art.subtitle, x=CX, y=182, color=GOLD_TEXT)
    _lens_rule(d, CX - sw / 2 - 11 - 62, 176.5, 62, 1)
    _lens_rule(d, CX + sw / 2 + 11 + 62, 176.5, 62, -1)

    # lead, name, flourish
    d.text("garIt", 13.5, art.lead, x=CX, y=222, color=LEAD)
    name = " ".join(art.name.split()) or "Learner"
    ns = d.fit_size("script", name, 56, 600, 30)
    d.text("script", ns, name, x=CX, y=272, color=NAVY)
    nw = d.width("script", ns, name)
    _flourish(d, CX, 292, min(max(nw + 40, 300), 400))

    # citation + course title
    cit = " ".join(art.citation.split())
    cs = 13.5 if cit == _DEFAULT_CITATION else d.fit_size("gar", cit, 13.5, 640, 9.5)
    d.text("gar", cs, cit, x=CX, y=322, color=BODY)
    title = " ".join(art.course_title.split()) or "Course"
    ts = 21.0
    lines = d.wrap("garSemi", ts, title, 600)
    while len(lines) > 2 and ts > 14:
        ts -= 1
        lines = d.wrap("garSemi", ts, title, 600)
    lines = lines[:2]
    ty = 350.0
    for i, ln in enumerate(lines):
        d.text("garSemi", ts, ln, x=CX, y=ty + i * ts * 1.15, color=NAVY)
    after = ty + (len(lines) - 1) * ts * 1.15

    # optional note (project / specific citation) and skills line (issued documents only)
    if art.note:
        note = " ".join(art.note.split())
        after += 18
        d.text("garIt", d.fit_size("garIt", note, 11.5, 600, 8.0), note, x=CX, y=after, color=LEAD)
    if art.skills:
        sk = "  ·  ".join(" ".join(s.split()) for s in art.skills).upper()
        after += 15
        d.text(
            "cin", d.fit_size("cin", sk, 7.2, 600, 5.0, 0.8), sk, x=CX, y=after, color=GOLD_TEXT, spacing=0.8
        )

    # facts line (kept clear of the seal when the extra lines above push it down)
    facts_y = after + (20 if (art.note or art.skills) else 26)
    cells = [("ISSUED", long_date(art.issued_on).upper()), (art.number_label, art.public_code)]
    cells += [(lab.upper(), val) for lab, val in art.facts[:1]]
    fs, sp, sep = 8.0, 1.4, 22.0

    def _facts_width() -> float:
        w = sum(
            d.width("cin", fs, lab, sp) + fs * 0.6 + d.width("cinBold", fs, val, sp) for lab, val in cells
        )
        return w + sep * (len(cells) - 1)

    total = _facts_width()
    while art.facts and total > 540 and fs > 5.5:
        fs -= 0.5
        total = _facts_width()
    x = CX - total / 2
    for i, (lab, val) in enumerate(cells):
        if i:
            d.diamond(x + sep / 2, facts_y - 2.6, 2, GOLD)
            x += sep
        x += d.text("cin", fs, lab, x=x, y=facts_y, color=GOLD_TEXT, align="left", spacing=sp) + fs * 0.6
        x += d.text("cinBold", fs, val, x=x, y=facts_y, color=NAVY, align="left", spacing=sp)

    # signature columns (date of issue left, signatory right) and the seal between
    sig_y = H - 112
    lx, rx, col = 246.0, W - 246.0, 174.0
    d.text("garSemi", 14, long_date(art.issued_on), x=lx, y=sig_y - 8, color=NAVY)
    d.line(lx - col / 2, sig_y, lx + col / 2, sig_y, NAVY, 0.7)
    d.text("cinBold", 8.4, "DATE OF ISSUE", x=lx, y=sig_y + 15, color=NAVY, spacing=1.2)
    if not (art.signature_image and draw_image(d, art.signature_image, rx, sig_y - 2, 150, 40)):
        d.curve(
            [(rx - 60, sig_y - 8), (rx - 30, sig_y - 26), (rx - 5, sig_y + 2), (rx + 20, sig_y - 14)],
            NAVY,
            0.9,
        )
        d.curve(
            [(rx + 20, sig_y - 14), (rx + 34, sig_y - 22), (rx + 46, sig_y - 6), (rx + 58, sig_y - 12)],
            NAVY,
            0.9,
        )
    d.line(rx - col / 2, sig_y, rx + col / 2, sig_y, NAVY, 0.7)
    sname = art.signatory.upper()
    ss = d.fit_size("cinBold", sname, 9.4, col + 30, 7.0, 1)
    d.text("cinBold", ss, sname, x=rx, y=sig_y + 15, color=NAVY, spacing=1)
    d.text("garIt", 10, art.signatory_title, x=rx, y=sig_y + 28, color=SLATE)
    _wax_seal(d, CX, H - 146, art.issued_on.year)

    # verification: QR + number bottom left, issue / verify lines flanking the ribbons
    qx, qs = 74.0, 49.0
    qy = H - 99 - qs
    has_qr = _qr(d, art.verify_url, qx, qy, qs)
    d.text("cin", 5.8, art.public_code, x=qx + qs / 2, y=qy + qs + 9, color=BROWN, spacing=0.8)
    if not has_qr:
        d.text("cin", 5.2, "VERIFY ONLINE", x=qx + qs / 2, y=qy + qs / 2, color=GOLD_TEXT, spacing=0.8)
    d.text("garIt", 7.8, art.issuer, x=CX - 74, y=H - 68, color=BROWN, align="right")
    verify = f"Verify at {_host(art.verify_url)}"
    vs = d.fit_size("garIt", verify, 7.8, 230, 5.5)
    d.text("garIt", vs, verify, x=CX + 74, y=H - 68, color=BROWN, align="left")

    return bytes(pdf.output())


def pdf_sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def art_fields(art: CertificateArt) -> dict[str, Any]:
    return {
        "name": art.name,
        "course_title": art.course_title,
        "public_code": art.public_code,
        "issued_on": art.issued_on.isoformat(),
        "verify_url": art.verify_url,
    }
