"""Commerce documents: GST invoice / credit note PDFs (COM-16) and the GST register CSV
(COM-37), stored in the private exports bucket and handed out as short-lived signed URLs.

* Rendering: ``fpdf2`` (pure Python). Core PDF fonts are Latin-1 only, so text outside
  Latin-1 (e.g. a buyer name in an Indic script) is transliterated to ``?`` — a Unicode TTF
  font is a follow-up. Amounts print as ``INR 1,234.56`` (no rupee glyph in core fonts).
* Seller identity (GSTIN, state, legal name, address) comes from env (``SELLER_*``); while the
  ``.env.example`` placeholder GSTIN is configured every PDF carries a "DEV PLACEHOLDER" banner.
* Storage: ``DocumentStore`` adapter. ``S3DocumentStore`` (boto3 ``put_object``, SeaweedFS
  locally via ``S3_ENDPOINT_URL``; downloads use the stdlib SigV4 presigner of the media
  module) or ``MemoryDocumentStore`` (tests; refused at startup in production).
"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.startup_checks import register_fake_adapter
from app.core.time import utcnow
from app.modules.commerce import datastore as ds
from app.modules.commerce import policy
from app.modules.commerce.models import Invoice, Order, OrderItem, Product

register_fake_adapter(
    "commerce documents (MemoryDocumentStore: COMMERCE_DOCUMENT_STORE=memory)",
    lambda _s: policy.commerce_settings().COMMERCE_DOCUMENT_STORE.lower() == "memory",
)


# --------------------------------------------------------------------------- storage


class DocumentStore(Protocol):
    name: str

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...

    def signed_url(self, bucket: str, key: str, *, filename: str, expires_s: int) -> tuple[str, datetime]: ...


class S3DocumentStore:
    name = "s3"

    def _client(self) -> Any:
        import boto3

        from app.modules.media.storage import storage_settings

        s = storage_settings()
        kw: dict[str, Any] = {"region_name": s.AWS_REGION}
        if s.S3_ENDPOINT_URL:
            kw["endpoint_url"] = s.S3_ENDPOINT_URL
        if s.AWS_ACCESS_KEY_ID:  # local only; ECS uses the task role (default chain)
            kw["aws_access_key_id"] = s.AWS_ACCESS_KEY_ID
            kw["aws_secret_access_key"] = s.AWS_SECRET_ACCESS_KEY
            if s.AWS_SESSION_TOKEN:
                kw["aws_session_token"] = s.AWS_SESSION_TOKEN
        # botocore >= 1.36 adds a streaming CRC trailer (aws-chunked) to every PutObject by default.
        # S3-compatible stores (SeaweedFS on the GCP demo) then keep the chunk framing INSIDE the
        # object, corrupting every stored PDF/image (found live 2026-11-11). Only send/verify
        # checksums when the operation requires them; real S3 behaves the same either way.
        from botocore.config import Config

        kw["config"] = Config(
            request_checksum_calculation="when_required", response_checksum_validation="when_required"
        )
        return boto3.client("s3", **kw)

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        extra: dict[str, Any] = {}
        from app.modules.media.storage import storage_settings

        if not storage_settings().S3_ENDPOINT_URL:
            extra["ServerSideEncryption"] = "aws:kms"  # bucket default key in AWS
        await asyncio.to_thread(
            self._client().put_object,
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            **extra,
        )

    def signed_url(self, bucket: str, key: str, *, filename: str, expires_s: int) -> tuple[str, datetime]:
        from app.modules.media.storage import presign_get

        return presign_get(bucket, key, expires_s=expires_s, filename=filename)


class MemoryDocumentStore:
    """Test/dev fake: objects live in process memory."""

    name = "memory"

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.objects[(bucket, key)] = (data, content_type)

    def signed_url(self, bucket: str, key: str, *, filename: str, expires_s: int) -> tuple[str, datetime]:
        exp = utcnow() + timedelta(seconds=expires_s)
        return f"memory://{bucket}/{key}?filename={filename}&expires={int(exp.timestamp())}", exp


_store: DocumentStore | None = None


def set_document_store(store: DocumentStore | None) -> None:
    global _store
    _store = store


def get_document_store() -> DocumentStore:
    global _store
    if _store is None:
        kind = policy.commerce_settings().COMMERCE_DOCUMENT_STORE.lower()
        _store = MemoryDocumentStore() if kind == "memory" else S3DocumentStore()
    return _store


def bucket() -> str:
    return policy.commerce_settings().S3_BUCKET_EXPORTS


# --------------------------------------------------------------------------- formatting


def inr(paise: int, *, grouping: bool = True) -> str:
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(int(paise)), 100)
    return f"{sign}{rupees:,}.{p:02d}" if grouping else f"{sign}{rupees}.{p:02d}"


def _latin1(s: str | None) -> str:
    return (s or "").encode("latin-1", "replace").decode("latin-1")


def invoice_filename(inv: Invoice) -> str:
    return inv.invoice_number.replace("/", "-") + ".pdf"


def invoice_key(inv: Invoice) -> str:
    fy_folder = inv.issue_date.strftime("%Y/%m")
    return f"invoices/{fy_folder}/{inv.id}.pdf"


async def _lines(session: AsyncSession, inv: Invoice) -> list[dict[str, Any]]:
    if inv.invoice_type == "credit_note":
        orig = (
            await ds.execute(
                session, select(Invoice.invoice_number).where(Invoice.id == inv.original_invoice_id)
            )
        ).scalar_one_or_none()
        return [
            {
                "description": f"Credit against invoice {orig or ''}".strip(),
                "sac": "9992",
                "qty": 1,
                "taxable": inv.taxable_paise,
                "rate": None,
                "cgst": inv.cgst_paise,
                "sgst": inv.sgst_paise,
                "igst": inv.igst_paise,
                "total": inv.total_paise,
            }
        ]
    rows = (
        await ds.execute(
            session,
            select(OrderItem, Product.name)
            .join(Product, Product.id == OrderItem.product_id)
            .where(OrderItem.order_id == inv.order_id),
        )
    ).all()
    out = []
    for it, name in rows:
        # ``description`` is set only on legacy offline-PO invoices (kept as GST records, D1).
        desc = inv.description or str(name)
        out.append(
            {
                "description": desc,
                "sac": it.sac_code,
                "qty": it.quantity,
                "taxable": it.taxable_paise,
                "rate": Decimal(it.gst_rate),
                "cgst": it.cgst_paise,
                "sgst": it.sgst_paise,
                "igst": it.igst_paise,
                "total": it.total_paise,
            }
        )
    return out


async def render_invoice_pdf(session: AsyncSession, inv: Invoice) -> bytes:
    from fpdf import FPDF

    s = policy.commerce_settings()
    lines = await _lines(session, inv)
    original_number = None
    if inv.original_invoice_id:
        original_number = (
            await ds.execute(
                session, select(Invoice.invoice_number).where(Invoice.id == inv.original_invoice_id)
            )
        ).scalar_one_or_none()
    order = (await ds.execute(session, select(Order).where(Order.id == inv.order_id))).scalar_one()

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_title(_latin1(f"{inv.invoice_number}"))
    pdf.set_author(_latin1(s.SELLER_LEGAL_NAME))
    pdf.set_creation_date(datetime.combine(inv.issue_date, datetime.min.time()))
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    placeholder = inv.seller_gstin == policy.PLACEHOLDER_GSTIN or "PLACEHOLDER" in s.SELLER_LEGAL_NAME
    if placeholder:
        pdf.set_fill_color(255, 235, 200)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(
            0,
            7,
            "DEV PLACEHOLDER - seller GSTIN/address are not real; not a valid tax document",
            border=1,
            align="C",
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(2)
    title = "TAX INVOICE" if inv.invoice_type == "tax_invoice" else "CREDIT NOTE"
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _latin1(s.SELLER_LEGAL_NAME), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _latin1(s.SELLER_ADDRESS), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0, 5, f"GSTIN: {inv.seller_gstin}    State code: {s.SELLER_STATE_CODE}", new_x="LMARGIN", new_y="NEXT"
    )
    pdf.ln(3)

    meta = [
        ("Number", inv.invoice_number),
        ("Date", inv.issue_date.isoformat()),
        ("Order", order.order_number),
        ("Place of supply (state code)", inv.place_of_supply),
        ("Supply type", "Intra-state (CGST+SGST)" if inv.igst_paise == 0 else "Inter-state (IGST)"),
    ]
    if original_number:
        meta.append(("Against invoice", original_number))
    if inv.due_on:
        meta.append(("Payment due", inv.due_on.isoformat()))
    pdf.set_font("Helvetica", "", 9)
    for k, v in meta:
        pdf.cell(55, 5, _latin1(k) + ":")
        pdf.cell(0, 5, _latin1(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Bill to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _latin1(inv.buyer_name), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"GSTIN: {inv.buyer_gstin or 'Unregistered (B2C)'}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    widths = (62, 14, 10, 24, 12, 22, 22, 22)
    heads = ("Description", "SAC", "Qty", "Taxable", "Rate", "CGST", "SGST", "IGST")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(235, 235, 235)
    for w, h in zip(widths, heads, strict=True):
        pdf.cell(w, 7, h, border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for ln in lines:
        rate = f"{ln['rate']:.0f}%" if ln["rate"] is not None else "-"
        cells = (
            _latin1(str(ln["description"]))[:48],
            str(ln["sac"]),
            str(ln["qty"]),
            inr(ln["taxable"]),
            rate,
            inr(ln["cgst"]),
            inr(ln["sgst"]),
            inr(ln["igst"]),
        )
        for i, (w, c) in enumerate(zip(widths, cells, strict=True)):
            pdf.cell(w, 7, c, border=1, align="L" if i == 0 else "R")
        pdf.ln()
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 9)
    for label, val in (
        ("Taxable value", inv.taxable_paise),
        ("CGST", inv.cgst_paise),
        ("SGST", inv.sgst_paise),
        ("IGST", inv.igst_paise),
    ):
        pdf.cell(150, 5, label, align="R")
        pdf.cell(38, 5, "INR " + inr(val), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(150, 7, "Total" if inv.invoice_type == "tax_invoice" else "Total credited", align="R")
    pdf.cell(38, 7, "INR " + inr(inv.total_paise), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(
        0,
        4,
        "This is a computer-generated document and needs no signature. Prices are inclusive of GST "
        "for online purchases. Retained for 72 months.",
    )
    return bytes(pdf.output())


async def ensure_invoice_pdf(session: AsyncSession, inv: Invoice) -> str:
    """Render + store once; the key is persisted in ``invoices.pdf_s3_key`` (caller provides a
    context that may update the row, e.g. ``as_system``)."""
    if inv.pdf_s3_key:
        return inv.pdf_s3_key
    data = await render_invoice_pdf(session, inv)
    key = invoice_key(inv)
    await ds.before_side_effect(session)
    await get_document_store().put(bucket(), key, data, "application/pdf")
    inv.pdf_s3_key = key
    await ds.flush(session)
    return key


def signed(key: str, filename: str) -> dict[str, Any]:
    url, exp = get_document_store().signed_url(
        bucket(), key, filename=filename, expires_s=policy.DOCUMENT_URL_SECONDS
    )
    return {"url": url, "expires_at": exp.isoformat(), "filename": filename}


# --------------------------------------------------------------------------- GST register CSV

GST_COLUMNS = (
    "document_type",
    "document_number",
    "issue_date",
    "original_invoice_number",
    "order_number",
    "buyer_name",
    "buyer_gstin",
    "supply_category",
    "place_of_supply",
    "supply_type",
    "sac_code",
    "gst_rate",
    "taxable_value_inr",
    "cgst_inr",
    "sgst_inr",
    "igst_inr",
    "total_inr",
    "status",
)


async def gst_rows(session: AsyncSession, period_from: date, period_to: date) -> list[dict[str, Any]]:
    """Invoices and credit notes issued in [from, to] (IST issue dates), oldest first."""
    invs = (
        await ds.execute(
            session,
            select(Invoice, Order.order_number)
            .join(Order, Order.id == Invoice.order_id)
            .where(Invoice.issue_date >= period_from, Invoice.issue_date <= period_to)
            .order_by(Invoice.issue_date, Invoice.invoice_number),
        )
    ).all()
    numbers = {i.id: i.invoice_number for i, _ in invs}
    missing = {
        i.original_invoice_id
        for i, _ in invs
        if i.original_invoice_id and i.original_invoice_id not in numbers
    }
    if missing:
        for iid, num in (
            await ds.execute(
                session, select(Invoice.id, Invoice.invoice_number).where(Invoice.id.in_(missing))
            )
        ).all():
            numbers[iid] = num
    order_ids = {i.order_id for i, _ in invs}
    sac_rate: dict[uuid.UUID, tuple[str, str]] = {}
    if order_ids:
        for oid, sac, rate in (
            await ds.execute(
                session,
                select(OrderItem.order_id, OrderItem.sac_code, OrderItem.gst_rate).where(
                    OrderItem.order_id.in_(order_ids)
                ),
            )
        ).all():
            sac_rate.setdefault(oid, (str(sac), f"{Decimal(rate):.2f}"))
    out = []
    for i, order_number in invs:
        sign = -1 if i.invoice_type == "credit_note" else 1
        sac, rate_s = sac_rate.get(i.order_id, ("9992", f"{policy.DEFAULT_GST_RATE:.2f}"))
        out.append(
            {
                "document_type": i.invoice_type,
                "document_number": i.invoice_number,
                "issue_date": i.issue_date.isoformat(),
                "original_invoice_number": numbers.get(i.original_invoice_id)
                if i.original_invoice_id
                else "",
                "order_number": order_number,
                "buyer_name": i.buyer_name,
                "buyer_gstin": i.buyer_gstin or "",
                "supply_category": "B2B" if i.buyer_gstin else "B2C",
                "place_of_supply": i.place_of_supply,
                "supply_type": "intra_state" if i.igst_paise == 0 else "inter_state",
                "sac_code": sac,
                "gst_rate": rate_s,
                "taxable_value_inr": inr(sign * i.taxable_paise, grouping=False),
                "cgst_inr": inr(sign * i.cgst_paise, grouping=False),
                "sgst_inr": inr(sign * i.sgst_paise, grouping=False),
                "igst_inr": inr(sign * i.igst_paise, grouping=False),
                "total_inr": inr(sign * i.total_paise, grouping=False),
                "status": i.status,
            }
        )
    return out


def _csv_safe(v: Any) -> str:
    """CSV/formula injection guard for spreadsheet consumers."""
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "@") or (s[:1] == "-" and not _is_number(s)) else s


def _is_number(s: str) -> bool:
    try:
        Decimal(s)
    except ArithmeticError:
        return False
    return True


def gst_csv(rows: list[dict[str, Any]], *, watermark: str) -> bytes:
    buf = io.StringIO()
    buf.write(f"# {watermark}\n")
    w = csv.DictWriter(buf, fieldnames=list(GST_COLUMNS), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: _csv_safe(r[k]) for k in GST_COLUMNS})
    return buf.getvalue().encode("utf-8")
