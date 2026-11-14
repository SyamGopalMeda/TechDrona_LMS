"""Issued-document PDFs (server side, fpdf2) in the certificate's "royal diploma" family.

* Certificates (completion outside an LMS enrolment, internship, appreciation, participation):
  the course certificate renderer (``certpdf.render_certificate_pdf``) with the type's subtitle,
  citation, emphasis line, evidence cells, skills and the signatory from the document settings.
* Letters (internship / employment offer, admission letter, recommendation; A4 portrait): light
  parchment with a slimmer gold + navy frame, centred company lockup and gold rules, reference
  number and date, recipient block, the letter heading in Cinzel, the "at a glance" panel, the
  paragraphs in EB Garamond, the letter sections (what you'll gain, terms, next steps), the
  signature block with the wax seal, the acceptance slip, and a verification footer (QR to the
  public verify page, reference, statutory lines) on every page.

Deterministic like ``certpdf``: the same ``LetterArt`` always renders the same bytes (creation
date = issue date), so ``sha256(pdf)`` is a stable fingerprint that the verify page can check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from app.modules.learning import certpdf as cp
from app.modules.learning.certpdf import (
    BODY,
    BROWN,
    GOLD,
    GOLD_LIGHT,
    GOLD_TEXT,
    INK,
    LEAD,
    NAVY,
    SLATE,
    CertificateArt,
    _Doc,
    _host,
    _lens_rule,
    _qr,
    _wax_seal,
    draw_image,
    long_date,
)

LETTER_TEMPLATE_VERSION = "doc-letter-v1"
CERT_TEMPLATE_VERSION = "doc-cert-v1"

PW, PH = 595.28, 841.89  # A4 portrait (points)
PCX = PW / 2
MARGIN_X = 70.0
TEXT_W = PW - 2 * MARGIN_X
TOP_CONT = 92.0  # body top on continuation pages
BOTTOM = PH - 112.0  # body must end above the footer

PAPER = (253, 249, 239)
PAPER_EDGE = (246, 238, 218)
PANEL = (246, 234, 208)
PANEL_LINE = (227, 207, 159)
SLIP = (255, 251, 242)


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
    company: str = "Tech Drona"
    legal_name: str = ""
    address: str = ""
    contact_line: str = ""
    reg_lines: tuple[str, ...] = ()
    signatory: str = ""
    designation: str = ""
    signatory_contact: str = ""
    signature_image: bytes | None = field(default=None, repr=False)
    seal_image: bytes | None = field(default=None, repr=False)


class _Letter:
    """Flow layout over fpdf2 pages: frame + footer on every page, ``ensure`` breaks pages."""

    def __init__(self, art: LetterArt) -> None:
        self.art = art
        self.d = _Doc("P")
        self.pdf = self.d.pdf
        self.page_no = 0
        self.y = 0.0

    # ----------------------------------------------------------------- page furniture
    def new_page(self) -> None:
        d, a = self.d, self.art
        self.pdf.add_page()
        self.page_no += 1
        d.rect(0, 0, PW, PH, fill=PAPER_EDGE)
        d.rect(10, 10, PW - 20, PH - 20, fill=PAPER)
        d.rect(16, 16, PW - 32, PH - 32, stroke=GOLD, lw=2.4)
        d.rect(21.5, 21.5, PW - 43, PH - 43, stroke=NAVY, lw=0.6)
        d.rect(26, 26, PW - 52, PH - 52, stroke=GOLD_LIGHT, lw=0.35)
        for cx, cy in ((26, 26), (PW - 26, 26), (26, PH - 26), (PW - 26, PH - 26)):
            d.diamond(cx, cy, 4.5, NAVY)
            d.diamond(cx, cy, 7, GOLD, outline=True)
        self._footer()
        if self.page_no == 1:
            self._letterhead()
        else:
            d.text("cinBold", 10, a.company.upper(), x=PCX, y=58, color=NAVY, spacing=2.5)
            d.text("cin", 6.8, f"{a.ref_no}  ·  CONTINUED", x=PCX, y=72, color=GOLD_TEXT, spacing=1)
            self.y = TOP_CONT

    def _letterhead(self) -> None:
        d, a = self.d, self.art
        d.text("cinBold", 20, a.company.upper(), x=PCX, y=70, color=NAVY, spacing=4)
        d.line(PCX - 90, 79, PCX - 9, 79, GOLD, 0.6)
        d.line(PCX + 9, 79, PCX + 90, 79, GOLD, 0.6)
        d.diamond(PCX, 79, 2.4, GOLD)
        y = 93.0
        if a.legal_name and a.legal_name != a.company:
            d.text("garIt", 9, a.legal_name, x=PCX, y=y, color=SLATE)
            y += 11
        if a.address:
            addr = " ".join(a.address.split())
            d.text("gar", d.fit_size("gar", addr, 9, TEXT_W + 40, 6.5), addr, x=PCX, y=y, color=LEAD)
            y += 11
        if a.contact_line:
            d.text(
                "gar",
                d.fit_size("gar", a.contact_line, 8.6, TEXT_W + 40, 6.5),
                a.contact_line,
                x=PCX,
                y=y,
                color=LEAD,
            )
            y += 11
        d.line(MARGIN_X - 14, y + 2, PW - MARGIN_X + 14, y + 2, GOLD, 0.8)
        d.line(MARGIN_X - 14, y + 4.5, PW - MARGIN_X + 14, y + 4.5, GOLD, 0.3)
        y += 26
        d.text("cin", 7.6, "REF. NO.", x=MARGIN_X, y=y, color=GOLD_TEXT, align="left", spacing=1.2)
        w = d.width("cin", 7.6, "REF. NO.", 1.2)
        d.text("cinBold", 8.4, a.ref_no, x=MARGIN_X + w + 6, y=y, color=NAVY, align="left", spacing=1)
        d.text("garSemi", 10.5, long_date(a.issued_on), x=PW - MARGIN_X, y=y, color=NAVY, align="right")
        y += 30
        # heading with lens rules
        hd = a.heading.upper()
        hw = d.text("cinBold", 13, hd, x=PCX, y=y, color=NAVY, spacing=2.4)
        _lens_rule(d, PCX - hw / 2 - 10 - 46, y - 4.2, 46, 1)
        _lens_rule(d, PCX + hw / 2 + 10 + 46, y - 4.2, 46, -1)
        self.y = y + 26

    def _footer(self) -> None:
        d, a = self.d, self.art
        fy = PH - 92.0
        d.line(MARGIN_X - 14, fy, PW - MARGIN_X + 14, fy, GOLD, 0.5)
        qs = 42.0
        has_qr = _qr(d, a.verify_url, MARGIN_X - 14, fy + 8, qs)
        tx = MARGIN_X - 14 + qs + 10
        d.text("cin", 6.4, "REFERENCE", x=tx, y=fy + 16, color=GOLD_TEXT, align="left", spacing=1)
        d.text("cinBold", 7.6, a.ref_no, x=tx, y=fy + 27, color=NAVY, align="left", spacing=0.8)
        verify = f"Verify at {_host(a.verify_url)}"
        d.text(
            "garIt",
            d.fit_size("garIt", verify, 8, 220, 5.5),
            verify,
            x=tx,
            y=fy + 39,
            color=BROWN,
            align="left",
        )
        if not has_qr:
            d.text(
                "cin", 5, "SCAN / VERIFY ONLINE", x=tx, y=fy + 49, color=GOLD_TEXT, align="left", spacing=0.6
            )
        ry = fy + 16
        for line in a.reg_lines[:4]:
            d.text(
                "gar",
                d.fit_size("gar", line, 7.2, 200, 5.5),
                line,
                x=PW - MARGIN_X + 14,
                y=ry,
                color=SLATE,
                align="right",
            )
            ry += 9.5
        d.text(
            "cin",
            6,
            f"PAGE {self.page_no}",
            x=PW - MARGIN_X + 14,
            y=fy + 52,
            color=GOLD_TEXT,
            align="right",
            spacing=1,
        )

    # ----------------------------------------------------------------- flow
    def ensure(self, h: float) -> None:
        if self.y + h > BOTTOM:
            self.new_page()

    def para(self, text: str, *, key: str = "gar", size: float = 11.0, color=BODY, indent: float = 0.0,
             lead: float = 1.42, gap: float = 7.0, align: str = "left") -> None:  # fmt: skip
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
        self.y += 4
        w = self.d.text(
            "cinBold", 8.6, title.upper(), x=MARGIN_X, y=self.y + 8.6, color=NAVY, align="left", spacing=1.6
        )
        self.d.line(MARGIN_X + w + 8, self.y + 5.5, PW - MARGIN_X, self.y + 5.5, GOLD_LIGHT, 0.5)
        self.y += 18

    def bullets(self, items: tuple[str, ...] | list[str], *, numbered: bool = False) -> None:
        for i, item in enumerate(items, 1):
            lines = self.d.wrap("gar", 10.5, " ".join(item.split()), TEXT_W - 18)
            lh = 14.6
            self.ensure(lh * min(len(lines), 2))
            if numbered:
                self.d.text(
                    "garSemi", 10.5, f"{i}.", x=MARGIN_X + 12, y=self.y + 10.5, color=GOLD_TEXT, align="right"
                )
            else:
                self.d.diamond(MARGIN_X + 6, self.y + 7, 2.2, GOLD)
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
        col_w = (TEXT_W - 24) / 2
        rows = [pairs[i : i + 2] for i in range(0, len(pairs), 2)]
        heights = []
        for row in rows:
            h = 0.0
            for _lab, val in row:
                h = max(h, 11 + 12.5 * len(d.wrap("garSemi", 10, val, col_w - 6)))
            heights.append(h + 6)
        total = 24 + sum(heights)
        self.ensure(total + 8)
        top = self.y
        d.rect(MARGIN_X, top, TEXT_W, total, fill=PANEL, stroke=PANEL_LINE, lw=0.6)
        d.text(
            "cinBold",
            7.4,
            "AT A GLANCE",
            x=MARGIN_X + 12,
            y=top + 15,
            color=GOLD_TEXT,
            align="left",
            spacing=1.6,
        )
        y = top + 24
        for row, h in zip(rows, heights, strict=True):
            for j, (lab, val) in enumerate(row):
                x = MARGIN_X + 12 + j * (col_w + 6)
                d.text("cin", 6.4, lab.upper(), x=x, y=y + 7, color=GOLD_TEXT, align="left", spacing=0.9)
                for k, ln in enumerate(d.wrap("garSemi", 10, val, col_w - 6)):
                    d.text("garSemi", 10, ln, x=x, y=y + 19 + 12.5 * k, color=NAVY, align="left")
            y += h
        self.y = top + total + 14

    def signature_block(self) -> None:
        d, a = self.d, self.art
        self.ensure(118)
        y = self.y + 6
        d.text("gar", 10.5, f"For {a.company},", x=MARGIN_X, y=y + 10, color=BODY, align="left")
        sig_base = y + 62
        cx = MARGIN_X + 80
        if not (a.signature_image and draw_image(d, a.signature_image, cx, sig_base - 2, 140, 40)):
            d.curve(
                [
                    (cx - 52, sig_base - 8),
                    (cx - 26, sig_base - 26),
                    (cx - 4, sig_base + 1),
                    (cx + 18, sig_base - 13),
                ],
                NAVY,
                0.9,
            )
            d.curve(
                [
                    (cx + 18, sig_base - 13),
                    (cx + 30, sig_base - 21),
                    (cx + 40, sig_base - 6),
                    (cx + 50, sig_base - 11),
                ],
                NAVY,
                0.9,
            )
        d.line(MARGIN_X, sig_base, MARGIN_X + 170, sig_base, NAVY, 0.6)
        name = (a.signatory or "Authorised Signatory").upper()
        d.text(
            "cinBold",
            d.fit_size("cinBold", name, 9.2, 220, 6.5, 1),
            name,
            x=MARGIN_X,
            y=sig_base + 14,
            color=NAVY,
            align="left",
            spacing=1,
        )
        yy = sig_base + 27
        if a.designation:
            d.text("garIt", 10, a.designation, x=MARGIN_X, y=yy, color=SLATE, align="left")
            yy += 12
        d.text("garIt", 10, a.company, x=MARGIN_X, y=yy, color=SLATE, align="left")
        yy += 12
        if a.signatory_contact:
            d.text("gar", 8.6, a.signatory_contact, x=MARGIN_X, y=yy, color=LEAD, align="left")
            yy += 11
        sx, sy = PW - MARGIN_X - 62, y + 48
        if not (a.seal_image and draw_image(d, a.seal_image, sx, sy + 42, 92, 84)):
            _wax_seal(d, sx, sy, a.issued_on.year)
        self.y = max(yy, sy + 70) + 10

    def acceptance(self) -> None:
        d, a = self.d, self.art
        rows = 4 if a.guardian else 3
        h = 96 + rows * 26
        self.ensure(h + 10)
        top = self.y + 6
        d.rect(MARGIN_X, top, TEXT_W, h, fill=SLIP, stroke=GOLD, lw=0.6)
        d.text("cinBold", 9, "ACCEPTANCE OF OFFER", x=PCX, y=top + 20, color=NAVY, spacing=1.8)
        d.text(
            "cin",
            6.6,
            f"PLEASE SIGN AND RETURN  ·  REF. {a.ref_no}",
            x=PCX,
            y=top + 32,
            color=GOLD_TEXT,
            spacing=0.8,
        )
        txt = (
            f"I, {a.recipient_name}, have read and understood the terms of this letter and accept the offer "
            f"made by {a.company}."
        )
        y = top + 50
        for ln in d.wrap("gar", 10.5, txt, TEXT_W - 28):
            d.text("gar", 10.5, ln, x=MARGIN_X + 14, y=y, color=BODY, align="left")
            y += 14
        labels = ["Candidate's signature", "Name", "Date"] + (
            ["Parent / guardian's signature"] if a.guardian else []
        )
        y += 18
        for lab in labels:
            d.text("cin", 6.6, lab.upper(), x=MARGIN_X + 14, y=y, color=GOLD_TEXT, align="left", spacing=0.9)
            d.line(MARGIN_X + 170, y + 1, PW - MARGIN_X - 14, y + 1, INK, 0.4)
            y += 26
        self.y = top + h + 10


def render_letter_pdf(art: LetterArt) -> bytes:
    """Render one letter; deterministic for equal ``art``."""
    lt = _Letter(art)
    pdf = lt.pdf
    pdf.set_title(f"{art.heading} {art.ref_no}")
    pdf.set_author(art.company)
    pdf.set_subject(f"{art.heading}: {art.recipient_name}")
    pdf.set_creator("Tech Drona LMS")
    pdf.set_producer("Tech Drona LMS")
    pdf.set_creation_date(datetime.combine(art.issued_on, time(0, 0)))
    lt.new_page()
    d = lt.d

    # recipient block
    d.text("cin", 7, "TO", x=MARGIN_X, y=lt.y, color=GOLD_TEXT, align="left", spacing=1.2)
    lt.y += 14
    d.text("garSemi", 12, art.recipient_name, x=MARGIN_X, y=lt.y, color=NAVY, align="left")
    lt.y += 4
    for line in art.recipient_lines:
        lt.y += 12.5
        d.text("gar", 10, line, x=MARGIN_X, y=lt.y, color=LEAD, align="left")
    lt.y += 22

    if art.hero:
        lt.para(art.hero, key="garIt", size=13.5, color=GOLD_TEXT, align="center", gap=10)
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
    return bytes(pdf.output())


# --------------------------------------------------------------------------- certificates


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
) -> CertificateArt:
    """The course certificate design with the document type's wording."""
    from app.modules.learning.docdefs import DOC_TYPES

    t = DOC_TYPES[doc_type]
    emphasis = extras.get("emphasis") or ""
    citation = {
        "cert_completion": "for successfully completing all the requirements of",
        "cert_internship": "for successfully completing an internship as",
        "cert_appreciation": "in appreciation of",
        "cert_participation": "for participating in",
    }[doc_type]
    note = (
        extras.get("citation")
        or (f"Capstone project: {extras['project']}" if extras.get("project") else "")
        or (f"During {extras['context']}" if extras.get("context") else "")
    )
    if extras.get("merit"):
        note = f"{extras['merit']}" + (f"  ·  {note}" if note else "")
    facts = tuple((c["label"], c["value"]) for c in extras.get("evidence") or ())
    return CertificateArt(
        name=name,
        course_title=emphasis or t["short"],
        public_code=ref_no,
        issued_on=issued_on,
        verify_url=verify_url,
        issuer=settings.get("company") or "Tech Drona",
        kind=t["kind"],
        signatory=settings.get("signatory") or "Authorised Signatory",
        signatory_title=", ".join(x for x in (settings.get("designation"), settings.get("company")) if x)
        or "Tech Drona",
        subtitle=t["subtitle"],
        lead="This is proudly presented to",
        citation=citation,
        number_label="CERTIFICATE NO.",
        note=note,
        skills=tuple(extras.get("skills") or ()),
        facts=facts,
        signature_image=signature_image,
    )


def render_document_certificate(art: CertificateArt) -> bytes:
    return cp.render_certificate_pdf(art)
