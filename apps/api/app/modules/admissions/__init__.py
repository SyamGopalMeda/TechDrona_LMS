"""Admissions: course registration, instalment fees and manual UPI payment verification.

Ported from the company website (``tech drona/src/lib/feeplan.js`` + ``fees.js``). Students
register on the website without an account; the website calls the LMS public endpoints through
the BFF route ``/api/public/admissions/*`` (apps/web). Staff verify each payment claim against
the bank account here; when the verified total reaches the course's access threshold the learner
gets an LMS account (password-set link), an ``admin_grant`` entitlement for the linked course and
an enrolment (plus batch membership when the fee plan names a batch).

Pure money/status rules live in ``rules.py`` (no database), persistence + workflow in
``service.py``, routes in ``public.py`` / ``admin.py``.
"""
