"""Issued-document PDFs (server side, fpdf2) in the Tech Drona certificate template family.

* Certificates (completion outside an LMS enrolment, internship, appreciation, participation):
  the course certificate renderer (``certpdf.render_certificate_pdf``) with the type's ribbon,
  lead line, citation, emphasised line (programme / role / achievement / event), a details
  sentence built from the saved fields (dates, hours, grade; missing parts are left out), merit /
  project note, evidence and skills lines, ONE Authorised Signatory and the optional logo slots.
* Letters (internship / employment offer, admission letter, recommendation; A4 portrait): cream
  paper with thin gold + navy rules and small corner flourishes; the letterhead repeats the
  certificate's top row (optional logo slots + the Tech Drona lockup), reference number and
  date, the navy heading, the recipient block, the "at a glance" panel, the paragraphs, the
  letter sections (what you'll gain, next steps, terms), one Authorised Signatory block, the
  acceptance slip, and a footer on every page: QR to the public verify page + reference on the
  left, the company's name, address, contact and registration lines on the right.
* Watermarks (both families): the faint Tech Drona mark centred behind every page
  (``watermark``); previews (``preview``) print "DRAFT" for the reference, no QR / verify link
  and a diagonal "PREVIEW · NOT VALID" over every page.

Deterministic like ``certpdf``: the same ``LetterArt`` always renders the same bytes (creation
date = issue date), so ``sha256(pdf)`` is a stable fingerprint that the verify page can check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from app.modules.learning import certpdf as cp
from app.modules.learning.certpdf import (
    BODY,
    DEFAULT_COMPANY,
    DEFAULT_TAGLINE,
    GOLD,
    GOLD_LIGHT,
    GOLD_TEXT,
    INK,
    LEAD,
    NAVY,
    PREVIEW_RED,
    SLATE,
    CertificateArt,
    _Doc,
    _host,
    draw_image,
    long_date,
)

LETTER_TEMPLATE_VERSION = "doc-letter-v3"  # v3 = brand watermark (v2: Tech Drona letterhead)
CERT_TEMPLATE_VERSION = "doc-cert-v3"  # v3 = brand watermark (v2: Tech Drona certificate template)

PW, PH = 595.28, 841.89  # A4 portrait (points)
PCX = PW / 2
MARGIN_X = 68.0
TEXT_W = PW - 2 * MARGIN_X
TOP_CONT = 104.0  # body top on continuation pages
FOOT_Y = PH - 100.0  # footer rule
BOTTOM = FOOT_Y - 14.0  # body must end above the footer

PAPER = (253, 250, 243)
PAPER_EDGE = (246, 238, 220)
PANEL = (248, 241, 225)
PANEL_LINE = (228, 208, 160)
SLIP = (255, 252, 245)
PANEL_OPACITY = 0.8  # panel / slip fills: near-identical on the paper, the brand mark shows through


@dataclass(frozen=True)
class LetterArt:
    """Everything printed on a letter (and nothing else: the PDF hash covers exactly this)."""

    heading: str  # "Admission Letter"
    ref_no: str
    issued_on: date
    verify_url: str
    recipient_name: str
    recipient_lines: tuple[str, ...] = ()
    paragraphs: tuple[str, ...] = ()
    hero: str = ""
    highlights: tuple[tuple[str, str], ...] = ()
    lists: tuple[tuple[str, tuple[str, ...]], ...] = ()
    benefits: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    accept: bool = False
    guardian: bool = False
    company: str = DEFAULT_COMPANY
    legal_name: str = ""
    tagline: str = DEFAULT_TAGLINE
    address: str = ""
    contact_line: str = ""
    reg_lines: tuple[str, ...] = ()
    signatory: str = ""
    designation: str = ""
    signatory_contact: str = ""
    signature_image: bytes | None = field(default=None, repr=False)
    seal_image: bytes | None = field(default=None, repr=False)  # company stamp, beside the signature
    logo_left: bytes | None = field(default=None, repr=False)
    logo_right: bytes | None = field(default=None, repr=False)
    watermark: bool = True  # faint Tech Drona mark behind every page
    preview: bool = False  # draft: "DRAFT" reference, no QR / verify link, PREVIEW watermark

    @property
    def ref_shown(self) -> str:
        return cp.PREVIEW_REF if self.preview else self.ref_no


class _Letter:
    """Flow layout over fpdf2 pages: frame + footer on every page, ``ensure`` breaks pages."""

    def __init__(self, art: LetterArt) -> None:
        self.art = art
        self.d = _Doc("P")
        self.pdf = self.d.pdf
        self.page_no = 0
        self.y = 0.0

    # ----------------------------------------------------------------- page furniture
    def finish_page(self) -> None:
        """Over the finished page: the PREVIEW watermark (previews only)."""
        if self.page_no and self.art.preview:
            cp.preview_watermark(self.d, PW, PH)

    def new_page(self) -> None:
        d, a = self.d, self.art
        self.finish_page()
        self.pdf.add_page()
        self.page_no += 1
        d.rect(0, 0, PW, PH, fill=PAPER_EDGE)
        with d.radial(PCX, PH * 0.45, PH * 0.75, PAPER, PAPER_EDGE):
            self.pdf.rect(0, 0, PW, PH, style="F")
        d.rect(16, 16, PW - 32, PH - 32, stroke=GOLD, lw=1.3)
        d.rect(19.5, 19.5, PW - 39, PH - 39, stroke=NAVY, lw=0.4)
        d.rect(23, 23, PW - 46, PH - 46, stroke=GOLD_LIGHT, lw=0.35)
        for cx, cy, sx, sy in (
            (23, 23, 1, 1),
            (PW - 23, 23, -1, 1),
            (23, PH - 23, 1, -1),
            (PW - 23, PH - 23, -1, -1),
        ):
            cp._corner(d, cx, cy, sx, sy, 0.55)
        if a.watermark:  # behind everything drawn on this page from here on
            cp.brand_watermark(d, PCX, PH * 0.5, PW * 0.6)
        self._footer()
        if self.page_no == 1:
            self._letterhead()
        else:
            cp.draw_lockup(d, PCX, 40, 118)
            y = 40 + 118 * cp.LOGO_RATIO + 10
            d.line(MARGIN_X - 14, y, PW - MARGIN_X + 14, y, GOLD, 0.7)
            d.line(MARGIN_X - 14, y + 2.4, PW - MARGIN_X + 14, y + 2.4, NAVY, 0.3)
            d.text("gar", 7.6, f"Ref. {a.ref_shown}  ·  continued", x=PW - MARGIN_X + 14, y=y + 14,
                   color=SLATE, align="right")  # fmt: skip
            self.y = TOP_CONT

    def _letterhead(self) -> None:
        d, a = self.d, self.art
        y = cp.logo_row(d, cx=PCX, top=40, lockup_w=184, slot_dx=192, slot_w=86, slot_h=46, left=a.logo_left,
                        right=a.logo_right)  # fmt: skip
        y += 6
        if a.legal_name and a.legal_name != a.company:
            org = " ".join(a.legal_name.split()).upper()
            y += 11
            d.text(
                "pfBold",
                d.fit_size("pfBold", org, 9.5, TEXT_W, 7, 1.4),
                org,
                x=PCX,
                y=y,
                color=NAVY,
                spacing=1.4,
            )
        tag = cp.tagline_shown(a.tagline)
        if tag:
            y += 11
            tg = tag.upper()
            d.text(
                "gar", d.fit_size("gar", tg, 7, TEXT_W, 5.5, 2.4), tg, x=PCX, y=y, color=SLATE, spacing=2.4
            )
        y += 9
        d.line(MARGIN_X - 14, y, PW - MARGIN_X + 14, y, GOLD, 1.0)
        d.line(MARGIN_X - 14, y + 2.8, PW - MARGIN_X + 14, y + 2.8, NAVY, 0.35)
        d.diamond(PCX, y + 1.4, 3.6, GOLD)
        y += 24
        lw = d.text("garSemi", 10, "Ref. No.:", x=MARGIN_X, y=y, color=NAVY, align="left")
        d.text("gar", 10, a.ref_shown, x=MARGIN_X + lw + 5, y=y, color=PREVIEW_RED if a.preview else INK,
               align="left")  # fmt: skip
        dt = long_date(a.issued_on)
        dw = d.text("gar", 10, dt, x=PW - MARGIN_X, y=y, color=INK, align="right")
        d.text("garSemi", 10, "Date:", x=PW - MARGIN_X - dw - 5, y=y, color=NAVY, align="right")
        y += 34
        hd = " ".join(a.heading.split()).upper()
        hs = d.fit_size("pfBold", hd, 17, TEXT_W, 11, 1.6)
        hw = d.text("pfBold", hs, hd, x=PCX, y=y, color=NAVY, spacing=1.6)
        for s in (-1, 1):
            x_in = PCX + s * (hw / 2 + 12)
            d.line(x_in, y - hs * 0.32, x_in + s * 46, y - hs * 0.32, GOLD, 0.8)
            d.diamond(x_in + s * 49, y - hs * 0.32, 1.7, GOLD)
        self.y = y + 26

    def _footer(self) -> None:
        d, a = self.d, self.art
        fy = FOOT_Y
        d.line(MARGIN_X - 14, fy, PW - MARGIN_X + 14, fy, GOLD, 0.9)
        d.line(MARGIN_X - 14, fy + 2.6, PW - MARGIN_X + 14, fy + 2.6, NAVY, 0.3)
        # left: verification (a preview has no QR / verify link: its reference does not exist)
        qx, qs = MARGIN_X - 14, 42.0
        if a.preview:
            tx = qx
            d.text("gar", 6.4, "PREVIEW  ·  NOT ISSUED", x=tx, y=fy + 19, color=PREVIEW_RED, align="left",
                   spacing=1.6)  # fmt: skip
            d.text("garSemi", 8.4, a.ref_shown, x=tx, y=fy + 31, color=NAVY, align="left")
            cp.preview_note(d, tx, fy + 41.5, size=7.4, align="left", max_w=190)
        else:
            has_qr = cp.qr(d, a.verify_url, qx, fy + 11, qs)
            tx = qx + (qs + 9 if has_qr else 0)
            d.text("gar", 6.4, "SCAN TO VERIFY" if has_qr else "VERIFY ONLINE", x=tx, y=fy + 19, color=SLATE,
                   align="left", spacing=1.6)  # fmt: skip
            d.text("garSemi", 8.4, a.ref_no, x=tx, y=fy + 31, color=NAVY, align="left")
            host = _host(a.verify_url)
            d.text("garIt", d.fit_size("garIt", host, 7.4, 150, 5), host, x=tx, y=fy + 41.5, color=SLATE,
                   align="left")  # fmt: skip
        d.text(
            "gar", 6.4, f"PAGE {self.page_no}", x=tx, y=fy + 52.5, color=GOLD_TEXT, align="left", spacing=1.4
        )
        # right: company details
        rx, max_w = PW - MARGIN_X + 14, 250.0
        ry = fy + 18
        org = " ".join((a.legal_name or a.company).split()).upper()
        d.text(
            "pfBold",
            d.fit_size("pfBold", org, 8.4, max_w, 6, 1),
            org,
            x=rx,
            y=ry,
            color=NAVY,
            align="right",
            spacing=1,
        )
        lines: list[tuple[str, str, Any]] = []
        if a.address:
            for ln in d.wrap("gar", 7.8, " ".join(a.address.split()), max_w)[:2]:
                lines.append(("gar", ln, LEAD))
        if a.contact_line:
            lines.append(("gar", a.contact_line, LEAD))
        if a.reg_lines:
            reg = "  ·  ".join(" ".join(x.split()) for x in a.reg_lines[:4])
            lines.append(("garIt", reg, SLATE))
        for key, ln, col in lines[:4]:
            ry += 10
            d.text(key, d.fit_size(key, ln, 7.8, max_w, 5.2), ln, x=rx, y=ry, color=col, align="right")

    # ----------------------------------------------------------------- flow
    def ensure(self, h: float) -> None:
        if self.y + h > BOTTOM:
            self.new_page()

    def para(self, text: str, *, key: str = "gar", size: float = 11.0, color=BODY, indent: float = 0.0,
             lead: float = 1.45, gap: float = 7.0, align: str = "left") -> None:  # fmt: skip
        lines = self.d.wrap(key, size, " ".join(text.split()), TEXT_W - indent)
        lh = size * lead
        for ln in lines:
            self.ensure(lh)
            x = PCX if align == "center" else MARGIN_X + indent
            self.d.text(key, size, ln, x=x, y=self.y + size, color=color, align=align)
            self.y += lh
        self.y += gap

    def section_title(self, title: str) -> None:
        self.ensure(40)
        self.y += 5
        w = self.d.text(
            "pfBold", 9.6, title.upper(), x=MARGIN_X, y=self.y + 9, color=NAVY, align="left", spacing=1.1
        )
        self.d.line(MARGIN_X + w + 9, self.y + 5.8, PW - MARGIN_X, self.y + 5.8, GOLD, 0.6)
        self.d.diamond(PW - MARGIN_X + 3, self.y + 5.8, 1.6, GOLD)
        self.y += 19

    def bullets(self, items: tuple[str, ...] | list[str], *, numbered: bool = False) -> None:
        for i, item in enumerate(items, 1):
            lines = self.d.wrap("gar", 10.5, " ".join(item.split()), TEXT_W - 18)
            lh = 14.8
            self.ensure(lh * min(len(lines), 2))
            if numbered:
                self.d.text(
                    "garSemi", 10.5, f"{i}.", x=MARGIN_X + 12, y=self.y + 10.5, color=GOLD_TEXT, align="right"
                )
            else:
                self.d.diamond(MARGIN_X + 6, self.y + 7, 2.4, GOLD)
            for ln in lines:
                self.ensure(lh)
                self.d.text("gar", 10.5, ln, x=MARGIN_X + 18, y=self.y + 10.5, color=BODY, align="left")
                self.y += lh
            self.y += 2.5
        self.y += 5

    def highlights(self, pairs: tuple[tuple[str, str], ...]) -> None:
        if not pairs:
            return
        d = self.d
        col_w = (TEXT_W - 30) / 2
        rows = [pairs[i : i + 2] for i in range(0, len(pairs), 2)]
        heights = []
        for row in rows:
            h = 0.0
            for _lab, val in row:
                h = max(h, 11 + 12.5 * len(d.wrap("garSemi", 10, val, col_w - 6)))
            heights.append(h + 6)
        total = 26 + sum(heights)
        self.ensure(total + 8)
        top = self.y
        with self.pdf.local_context(fill_opacity=PANEL_OPACITY):  # the brand watermark shows through
            d.rect(MARGIN_X, top, TEXT_W, total, fill=PANEL)
        d.rect(MARGIN_X, top, TEXT_W, total, stroke=PANEL_LINE, lw=0.6)
        d.rect(MARGIN_X, top, 3, total, fill=NAVY)
        d.text(
            "pfBold", 8.2, "AT A GLANCE", x=MARGIN_X + 15, y=top + 16, color=NAVY, align="left", spacing=1.4
        )
        d.line(MARGIN_X + 15, top + 20.5, MARGIN_X + 60, top + 20.5, GOLD, 0.6)
        y = top + 26
        for row, h in zip(rows, heights, strict=True):
            for j, (lab, val) in enumerate(row):
                x = MARGIN_X + 15 + j * (col_w + 6)
                d.text("gar", 6.6, lab.upper(), x=x, y=y + 7, color=GOLD_TEXT, align="left", spacing=1.0)
                for k, ln in enumerate(d.wrap("garSemi", 10, val, col_w - 6)):
                    d.text("garSemi", 10, ln, x=x, y=y + 19 + 12.5 * k, color=NAVY, align="left")
            y += h
        self.y = top + total + 14

    def signature_block(self) -> None:
        d, a = self.d, self.art
        # keep the whole block together: greeting, signature space, name, designation, caption
        self.ensure(
            6
            + 58
            + 15
            + 13 * bool(a.signatory)
            + 13 * bool(a.designation)
            + 12
            + 11 * bool(a.signatory_contact)
        )
        y = self.y + 6
        d.text("gar", 10.5, f"For {a.company},", x=MARGIN_X, y=y + 10, color=BODY, align="left")
        sig_base = y + 58
        cx = MARGIN_X + 85
        if a.signature_image:
            draw_image(d, a.signature_image, cx, sig_base - 2, 150, 42)
        d.line(MARGIN_X, sig_base, MARGIN_X + 170, sig_base, NAVY, 0.6)
        yy = sig_base + 15
        if a.signatory:
            d.text("pfBold", d.fit_size("pfBold", a.signatory, 11.5, 240, 8), a.signatory, x=MARGIN_X, y=yy,
                   color=NAVY, align="left")  # fmt: skip
            yy += 13
        if a.designation:
            d.text("garIt", 10.5, a.designation, x=MARGIN_X, y=yy, color=SLATE, align="left")
            yy += 13
        d.text("gar", 7.2, "AUTHORISED SIGNATORY", x=MARGIN_X, y=yy, color=SLATE, align="left", spacing=2.2)
        yy += 12
        if a.signatory_contact:
            d.text("gar", 8.8, a.signatory_contact, x=MARGIN_X, y=yy, color=LEAD, align="left")
            yy += 11
        bottom = yy
        if a.seal_image and draw_image(d, a.seal_image, PW - MARGIN_X - 60, sig_base + 20, 100, 90):
            bottom = max(bottom, sig_base + 22)
        self.y = bottom + 10

    def acceptance(self) -> None:
        d, a = self.d, self.art
        rows = 4 if a.guardian else 3
        h = 96 + rows * 26
        self.ensure(h + 10)
        top = self.y + 6
        with self.pdf.local_context(fill_opacity=PANEL_OPACITY):
            d.rect(MARGIN_X, top, TEXT_W, h, fill=SLIP)
        d.rect(MARGIN_X, top, TEXT_W, h, stroke=GOLD, lw=0.7)
        d.rect(MARGIN_X + 3, top + 3, TEXT_W - 6, h - 6, stroke=GOLD_LIGHT, lw=0.3)
        d.text("pfBold", 10.5, "ACCEPTANCE OF OFFER", x=PCX, y=top + 21, color=NAVY, spacing=1.4)
        d.text("gar", 7, f"PLEASE SIGN AND RETURN  ·  REF. {a.ref_shown}", x=PCX, y=top + 33, color=GOLD_TEXT,
               spacing=1.0)  # fmt: skip
        txt = (
            f"I, {a.recipient_name}, have read and understood the terms of this letter and accept the offer "
            f"made by {a.company}."
        )
        y = top + 51
        for ln in d.wrap("gar", 10.5, txt, TEXT_W - 28):
            d.text("gar", 10.5, ln, x=MARGIN_X + 14, y=y, color=BODY, align="left")
            y += 14
        labels = ["Candidate's signature", "Name", "Date"] + (
            ["Parent / guardian's signature"] if a.guardian else []
        )
        y += 18
        for lab in labels:
            d.text("gar", 7, lab.upper(), x=MARGIN_X + 14, y=y, color=GOLD_TEXT, align="left", spacing=1.0)
            d.line(MARGIN_X + 170, y + 1, PW - MARGIN_X - 14, y + 1, INK, 0.4)
            y += 26
        self.y = top + h + 10


def render_letter_pdf(art: LetterArt) -> bytes:
    """Render one letter; deterministic for equal ``art``."""
    lt = _Letter(art)
    pdf = lt.pdf
    pdf.set_title(f"{art.heading} {art.ref_shown}" + (" (preview, not valid)" if art.preview else ""))
    pdf.set_author(art.company)
    pdf.set_subject(f"{art.heading}: {art.recipient_name}")
    pdf.set_creator("Tech Drona LMS")
    pdf.set_producer("Tech Drona LMS")
    pdf.set_creation_date(datetime.combine(art.issued_on, time(0, 0)))
    lt.new_page()
    d = lt.d

    # recipient block
    d.text("garSemi", 10, "To,", x=MARGIN_X, y=lt.y, color=NAVY, align="left")
    lt.y += 15
    d.text("pfBold", 12, art.recipient_name, x=MARGIN_X, y=lt.y, color=NAVY, align="left")
    lt.y += 3
    for line in art.recipient_lines:
        lt.y += 12.5
        d.text("gar", 10, line, x=MARGIN_X, y=lt.y, color=LEAD, align="left")
    lt.y += 22

    if art.hero:
        lt.para(art.hero, key="pfIt", size=13, color=NAVY, align="center", gap=10)
    lt.highlights(art.highlights)
    for i, p in enumerate(art.paragraphs):
        lt.para(p, gap=4 if i == 0 else 8)
    for title, items in art.lists:
        if items:
            lt.section_title(title)
            lt.bullets(items)
    if art.benefits:
        lt.section_title("What you'll gain")
        lt.bullets(art.benefits)
    if art.next_steps:
        lt.section_title("Next steps")
        lt.bullets(art.next_steps)
    lt.signature_block()
    if art.terms:  # printed after the signature, like the website's annexure
        lt.section_title("Terms and conditions")
        lt.bullets(art.terms, numbered=True)
    if art.accept:
        lt.acceptance()
    lt.finish_page()
    return bytes(pdf.output())


# --------------------------------------------------------------------------- certificates

_NUMERIC = re.compile(r"^\d+(?:\.\d+)?$")


def _hours(h: str) -> str:
    h = " ".join((h or "").split())
    return f"{h} hours" if _NUMERIC.match(h) else h


def _grade(g: str) -> str:
    g = " ".join((g or "").split()).rstrip(".")
    if not g:
        return ""
    if re.match(r"^with\b", g, re.I):
        return g
    if re.match(r"^grade\b", g, re.I) or re.search(
        r"\b(distinction|merit|honou?rs|first class|second class|credit)\b", g, re.I
    ):
        return f"with {g}"
    return f"with grade {g}"


def _sentence(*parts: str) -> str:
    s = ", ".join(p for p in parts if p).strip()
    return f"{s}." if s and not s.endswith(".") else s


def _period(start: str, end: str) -> str:
    if start and end:
        return f"from {start} to {end}"
    return f"from {start}" if start else ""


def certificate_art(
    *,
    doc_type: str,
    name: str,
    ref_no: str,
    issued_on: date,
    verify_url: str,
    extras: dict[str, Any],
    settings: dict[str, Any],
    signature_image: bytes | None = None,
    logo_left: bytes | None = None,
    logo_right: bytes | None = None,
    lead: str = "",
    watermark: bool = True,
    preview: bool = False,
) -> CertificateArt:
    """The certificate template with the document type's wording.

    ``extras`` is the frozen ``render_extras`` output. Documents issued before the details keys
    existed (``start``, ``end``, ``hours``, ``grade``, ``held_on``) fall back to the evidence cells."""
    from app.modules.learning.docdefs import DOC_TYPES, article

    t = DOC_TYPES[doc_type]
    company = settings.get("company") or DEFAULT_COMPANY
    ev = {c["label"]: c["value"] for c in extras.get("evidence") or ()}
    start, end = extras.get("start") or "", extras.get("end") or ""
    if not start and ev.get("Period"):  # older content: "1 Jun 2026 - 31 Aug 2026" (en dash)
        start, _, end = (x.strip() for x in ev["Period"].partition(chr(0x2013)))
    hours = _hours(extras.get("hours") or ev.get("Hours") or "")
    grade = _grade(extras.get("grade") or ev.get("Grade") or "")
    emphasis = " ".join(str(extras.get("emphasis") or "").split()) or t["short"]
    hours_part = f"comprising {hours}" if hours else ""
    if doc_type == "cert_internship":
        art_word = article(emphasis)
        citation = f"has successfully completed an internship as {art_word}"
        details = _sentence(
            " ".join(x for x in (f"at {company}", _period(start, end)) if x), hours_part, grade
        )
    elif doc_type == "cert_appreciation":
        citation = "in appreciation of"
        ctx = extras.get("context") or ""
        details = _sentence(f"during {ctx}" if ctx else "")
    elif doc_type == "cert_participation":
        citation = "has participated in"
        held = extras.get("held_on") or ev.get("Held on") or ""
        details = _sentence(f"held on {held}" if held else "")
    else:  # cert_completion
        citation = "has successfully completed" + ("" if emphasis.lower().startswith("the ") else " the")
        details = _sentence(_period(start, end), hours_part, grade)
    note = extras.get("citation") or (
        f"Capstone project: {extras['project']}" if extras.get("project") else ""
    )
    if extras.get("merit"):
        note = f"{extras['merit']}" + (f"  ·  {note}" if note else "")
    covered = {"Period", "Hours", "Grade", "Held on"}
    facts = tuple((lab, val) for lab, val in ev.items() if lab not in covered)
    first = " ".join(str(lead or "").split())
    return CertificateArt(
        name=name,
        course_title=emphasis,
        public_code=ref_no,
        issued_on=issued_on,
        verify_url=verify_url,
        issuer=settings.get("legal_name") or company,
        kind=t["kind"],
        signatory=settings.get("signatory") or "",
        signatory_title=settings.get("designation") or "",
        subtitle=t["subtitle"],
        lead=first if first and len(first) <= 80 else "This is to certify that",
        citation=citation,
        details=details,
        number_label="Certificate No.",
        note=note,
        skills=tuple(extras.get("skills") or ()),
        facts=facts,
        tagline=settings.get("tagline") or DEFAULT_TAGLINE,
        signature_image=signature_image,
        logo_left=logo_left,
        logo_right=logo_right,
        watermark=watermark,
        preview=preview,
    )


def render_document_certificate(art: CertificateArt) -> bytes:
    return cp.render_certificate_pdf(art)
