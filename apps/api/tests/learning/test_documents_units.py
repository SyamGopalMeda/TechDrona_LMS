"""Issued documents, pure units (no database): reference numbers, placeholder wording, issue /
revoke / supersede rules, verify-code resolution, PDF render smoke (stable hash) and email parts.

Runs without Postgres: ``pytest --noconftest tests/learning/test_documents_units.py``."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from datetime import date
from pathlib import Path

import pytest

from app.core.errors import ProblemError
from app.modules.learning import docdefs as dd
from app.modules.learning import documents as docs

SETTINGS = dd.clean_settings(
    {
        "company": "Tech Drona",
        "email": "hello@example.test",
        "signatory": "A Signatory",
        "designation": "Director",
    }
)
R = {"name": "Ananya Reddy", "email": "ananya@example.test", "college": "", "reg_no": ""}


class _NoTemplates:
    async def get(self, *a, **k):
        return None


# --------------------------------------------------------------------------- reference numbers


def test_ref_numbers_have_type_prefix_year_and_safe_alphabet() -> None:
    seq = iter(range(100))
    ref = dd.new_ref_no("offer_course", 2026, rnd=lambda n: next(seq) % n)
    assert ref == "TD-AL-2026-ABCDEF"
    for t in dd.DOC_KEYS:
        r = dd.new_ref_no(t, 2027)
        m = dd.REF_RE.match(r)
        assert m and m.group(1) == dd.DOC_TYPES[t]["prefix"] and m.group(2) == "2027"
        assert not set(m.group(3)) & set("IO01")
    assert len({dd.new_ref_no("lor", 2026) for _ in range(200)}) > 195  # 32^6 space


def test_prefixes_are_unique_and_match_the_migration_check() -> None:
    assert len(set(dd.PREFIXES.values())) == len(dd.PREFIXES)
    mig = (
        Path(__file__).resolve().parents[2] / "migrations" / "versions" / "learning_0006_issued_documents.py"
    ).read_text(encoding="utf-8")
    alternation = re.search(r"\^TD-\(([A-Z|]+)\)", mig)
    assert alternation and set(alternation.group(1).split("|")) == set(dd.PREFIXES.values())
    for t, p in dd.PREFIXES.items():
        assert f'("{t}", "{p}")' in mig


def test_verify_codes_resolve_documents_and_keep_certificate_codes() -> None:
    for spelled in ("TD-AL-2026-7K3QX9", "td/al/2026/7k3qx9", " TD AL 2026 7K3QX9 ", "TD_AL_2026_7K3QX9"):
        assert dd.is_doc_ref(spelled) and dd.normalise_ref(spelled) == "TD-AL-2026-7K3QX9"
    for cert_code in ("ABCDEFGH2345", "ABCDEFGHJK", "TDAL20267K3QX9"):
        assert not dd.is_doc_ref(cert_code)
    assert not dd.is_doc_ref("TD-XX-2026-7K3QX9") and not dd.is_doc_ref("TD-AL-2026-7K3QX0")


# --------------------------------------------------------------------------- wording


def _values(t: str, f: dict[str, str], **kw) -> dict[str, str]:
    return dd.placeholder_values(doc_type=t, recipient=R, fields=f, settings=SETTINGS, **kw)


def test_placeholder_phrases_read_naturally() -> None:
    v = _values(
        "cert_completion",
        {"program": "DSA", "start_date": "2026-01-05", "end_date": "2026-03-01", "grade": "A"},
    )
    assert dd.fill(dd.DOC_TYPES["cert_completion"]["paragraphs"][2], v) == (
        "has successfully completed DSA from 5 January 2026 to 1 March 2026, with grade A."
    )
    assert _values("cert_completion", {"grade": "Distinction"})["grade_phrase"] == ", with Distinction"
    assert _values("offer_internship", {"intern_stipend": "Unpaid"})["stipend_sentence"].startswith(
        "This is an unpaid"
    )
    assert (
        _values("offer_internship", {"role": "ML Engineer Intern"})["role_phrase"] == "an ML Engineer Intern"
    )
    assert _values("lor", {})["salutation"] == "To whom it may concern,"
    assert (
        _values("lor", {"addressee": "the Admissions Committee"})["salutation"]
        == "Dear Admissions Committee,"
    )
    assert (
        _values("offer_course", {"fee_total": "₹30,000", "fee_balance": "₹0"})["fee_sentence"]
        == "Total course fee: ₹30,000."
    )
    v = _values(
        "cert_participation",
        {},
        ref_no="TD-CP-2026-ABCDEF",
        cert_no="TD-CP-2026-ABCDEF",
        site_url="https://x.test",
    )
    assert v["verify_url"] == "https://x.test/verify/TD-CP-2026-ABCDEF"


def test_empty_paragraphs_dropped_and_overrides_used() -> None:
    v = _values(
        "offer_course",
        {"program": "Web", "batch_start": "2026-12-01", "duration": "16 weeks", "mode": "Online"},
    )
    paras = dd.doc_paragraphs("offer_course", v)
    assert "" not in paras and not any(p.startswith("Total course fee") for p in paras)
    assert dd.doc_paragraphs("offer_course", v, {"paragraphs": ["Hello {{first_name}}"]}) == ["Hello Ananya"]
    sec = dd.letter_sections("offer_course", v, {"sections": {"hero": "Welcome {{name}}"}})
    assert sec and sec["hero"] == "Welcome Ananya Reddy" and sec["accept"] is False and sec["terms"]
    assert dd.letter_sections("lor", v) is None


def test_missing_fields_and_clean_fields() -> None:
    assert dd.missing_fields("offer_course", {}, {"name": "", "email": "bad"})[:2] == [
        "Student name",
        "Valid student email",
    ]
    assert dd.missing_fields("offer_course", {}, {"name": "A", "email": ""})[0] == "Student email"
    assert "Batch start date" in dd.missing_fields("offer_course", {"program": "x"}, R)
    with pytest.raises(ValueError, match="date"):
        dd.clean_fields("offer_course", {"batch_start": "tomorrow"})
    with pytest.raises(ValueError, match="Mode"):
        dd.clean_fields("offer_course", {"mode": "Telepathy"})
    assert dd.clean_fields("lor", {"program": "  a   b ", "unknown": "x", "skills": "a\nb"}) == {
        "program": "a b",
        "skills": "a\nb",
    }


def test_leftover_template_tokens_are_detected() -> None:
    assert dd.leftover_tokens(["Dear {{name}}"], {"a": "[Student name] (COURSE_NAME)"}) == [
        "{{name}}",
        "[Student name]",
        "(COURSE_NAME)",
    ]
    assert dd.leftover_tokens(["All filled (as agreed)."]) == []


def test_email_parts_default_and_override() -> None:
    v = _values(
        "cert_internship", {"role": "Data Intern"}, cert_no="TD-IC-2026-ABCDEF", site_url="https://x.test"
    )
    p = dd.email_parts("cert_internship", v)
    assert p["attach"] == "cert_internship" and "Tech Drona" in p["subject"]
    assert any("TD-IC-2026-ABCDEF" in x for x in p["paragraphs"])
    o = dd.email_parts("cert_internship", v, {"subject": "Hi {{first_name}}", "body": "One\n\nTwo"})
    assert o["subject"] == "Hi Ananya" and o["paragraphs"] == ["One", "Two"]
    assert len(dd.EMAIL_TEMPLATES) == 12 and set(dd.DOC_KEYS) <= set(dd.EMAIL_TEMPLATES)


# --------------------------------------------------------------------------- rules


def test_revoke_and_supersede_rules() -> None:
    assert docs.check_revocable("valid") is True
    assert docs.check_revocable("revoked") is False  # idempotent
    with pytest.raises(ProblemError) as e:
        docs.check_revocable("superseded")
    assert e.value.code == "invalid_state_transition"
    docs.check_supersedable("valid", "lor", "lor")
    with pytest.raises(ProblemError) as e:
        docs.check_supersedable("valid", "lor", "offer_course")
    assert e.value.code == "validation_failed"
    for st in ("revoked", "superseded"):
        with pytest.raises(ProblemError) as e:
            docs.check_supersedable(st, "lor", "lor")
        assert e.value.code == "invalid_state_transition"


def test_completion_certificates_of_enrolments_stay_in_certificates() -> None:
    import uuid

    docs.validate_cert_completion_target("cert_completion", None)
    docs.validate_cert_completion_target("cert_internship", uuid.uuid4())
    with pytest.raises(ProblemError):
        docs.validate_cert_completion_target("cert_completion", uuid.uuid4())


def test_settings_problem_and_image_decoding() -> None:
    assert dd.settings_problem(dd.clean_settings({})) and not dd.settings_problem(SETTINGS)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    data, ctype = docs.decode_image("data:image/png;base64," + base64.b64encode(png).decode())
    assert data == png and ctype == "image/png"
    for bad in (
        "data:image/gif;base64,AAAA",
        "data:image/png;base64," + base64.b64encode(b"GIF89a").decode(),
    ):
        with pytest.raises(ProblemError):
            docs.decode_image(bad)
    with pytest.raises(ProblemError) as e:
        docs.decode_image("data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8" + b"0" * 300_001).decode())
    assert e.value.code == "payload_too_large"


def test_hash_matching() -> None:
    h = hashlib.sha256(b"pdf").hexdigest()
    assert docs.hash_matches(h, hashlib.sha256(b"pdf").digest(), None)
    assert docs.hash_matches(h.upper(), None, [h])
    assert not docs.hash_matches(h, None, []) and not docs.hash_matches("zz", None, ["zz"])


# --------------------------------------------------------------------------- PDF smoke

SAMPLES = {
    "offer_course": {
        "program": "Full Stack Web Development",
        "batch_start": "2026-12-01",
        "duration": "16 weeks",
        "mode": "Online",
        "fee_total": "₹30,000",
    },
    "offer_internship": {
        "role": "Data Intern",
        "start_date": "2026-12-01",
        "duration": "3 months",
        "mode": "Online",
        "intern_stipend": "Unpaid",
        "responsibilities": "Clean data\nBuild charts",
    },
    "lor": {
        "relationship": "an intern in our data team",
        "strengths": "Careful and quick.",
        "skills": "SQL\nPython",
    },
    "cert_internship": {
        "role": "Data Intern",
        "start_date": "2026-06-01",
        "end_date": "2026-08-31",
        "cert_skills": "SQL\nPython",
    },
    "cert_participation": {"event": "Cloud Workshop", "event_date": "12 December 2026"},
}


@pytest.mark.parametrize("doc_type", list(SAMPLES))
def test_document_pdf_renders_with_a_stable_hash(doc_type: str) -> None:
    async def run(name: str) -> bytes:
        f = dd.clean_fields(doc_type, SAMPLES[doc_type])
        ref = f"TD-{dd.PREFIXES[doc_type]}-2026-ABCDEF"
        rcp = {**R, "name": name}
        content = await docs.compose(
            _NoTemplates(), doc_type=doc_type, recipient=rcp, fields=f, issue_date=date(2026, 11, 11),
            ref_no=ref, settings=SETTINGS, site_url="https://lms.example.test",
        )  # fmt: skip
        return await docs.render_content(doc_type, ref, date(2026, 11, 11), rcp, content)

    a = asyncio.run(run("Ananya Reddy"))
    b = asyncio.run(run("Ananya Reddy"))
    assert a.startswith(b"%PDF-") and len(a) > 5000
    assert a == b  # deterministic: the SHA-256 recorded at issue matches every re-render
    assert hashlib.sha256(asyncio.run(run("Rahul Varma"))).digest() != hashlib.sha256(a).digest()


def test_compose_refuses_leftover_template_text() -> None:
    class Override:
        async def get(self, model, key):
            from app.modules.learning.doc_models import DocumentTemplate

            return DocumentTemplate(
                kind="document", template_key="lor", content={"paragraphs": ["Dear [Student name],"]}
            )

    with pytest.raises(ProblemError) as e:
        asyncio.run(
            docs.compose(
                Override(),
                doc_type="lor",
                recipient=R,
                fields={"relationship": "x", "strengths": "y"},
                issue_date=date(2026, 11, 11),
                ref_no="TD-LR-2026-ABCDEF",
                settings=SETTINGS,
                site_url="https://x.test",
            )
        )
    assert e.value.code == "validation_failed"


# --------------------------------------------------------------------------- certificate template


def _cert_art(doc_type: str, fields: dict[str, str], settings: dict | None = None, **kw):
    from app.modules.learning import docpdf

    f = dd.clean_fields(doc_type, fields)
    return docpdf.certificate_art(
        doc_type=doc_type, name="Ananya Reddy", ref_no="TD-CC-2026-ABCDEF", issued_on=date(2026, 11, 11),
        verify_url="https://lms.example.test/verify/TD-CC-2026-ABCDEF", extras=dd.render_extras(doc_type, f, R),
        settings=settings or SETTINGS, **kw,
    )  # fmt: skip


def test_certificate_wording_leaves_out_missing_details() -> None:
    full = _cert_art(
        "cert_completion",
        {
            "program": "Full Stack",
            "start_date": "2026-06-01",
            "end_date": "2026-08-31",
            "hours": "120",
            "grade": "A",
        },
    )
    assert full.subtitle == "of Completion" and full.citation == "has successfully completed the"
    assert full.course_title == "Full Stack"
    assert full.details == "from 1 June 2026 to 31 August 2026, comprising 120 hours, with grade A."
    assert _cert_art("cert_completion", {"program": "Full Stack", "hours": "45 hours"}).details == (
        "comprising 45 hours."
    )
    assert _cert_art("cert_completion", {"program": "Full Stack"}).details == ""
    intern = _cert_art(
        "cert_internship", {"role": "Data Intern", "start_date": "2026-06-01", "grade": "Distinction"}
    )
    assert intern.subtitle == "of Internship" and intern.citation.endswith("an internship as a")
    assert intern.details == "at Tech Drona from 1 June 2026, with Distinction."
    part = _cert_art("cert_participation", {"event": "Cloud Workshop", "event_date": "12 December 2026"})
    assert part.details == "held on 12 December 2026." and part.course_title == "Cloud Workshop"
    # one signatory from the settings; organisation and tagline default to Tech Drona's
    assert (full.signatory, full.signatory_title) == ("A Signatory", "Director")
    assert full.issuer == "Tech Drona" and full.tagline == dd.DEFAULT_TAGLINE


def test_logo_slots_are_empty_by_default_and_rendered_when_uploaded() -> None:
    from app.modules.learning.certpdf import render_certificate_pdf, tagline_shown

    st = dd.clean_settings({})
    assert {"logo_left", "logo_right"} <= set(dd.IMAGE_SLOTS)
    assert st["logo_left_key"] is None and st["logo_right_key"] is None
    assert st["tagline"] == dd.DEFAULT_TAGLINE and tagline_shown(st["tagline"]) == ""  # already in the lockup
    assert tagline_shown("Department of Training") == "Department of Training"
    from PIL import Image

    buf = __import__("io").BytesIO()
    Image.new("RGB", (40, 20), (200, 30, 30)).save(buf, "PNG")
    plain = render_certificate_pdf(_cert_art("cert_completion", {"program": "Full Stack"}))
    logos = render_certificate_pdf(
        _cert_art(
            "cert_completion",
            {"program": "Full Stack"},
            logo_left=buf.getvalue(),
            signature_image=buf.getvalue(),
        )
    )
    assert plain.startswith(b"%PDF-") and logos.startswith(b"%PDF-")
    assert plain.count(b"/Subtype /Image") == 0 and logos.count(b"/Subtype /Image") >= 1
