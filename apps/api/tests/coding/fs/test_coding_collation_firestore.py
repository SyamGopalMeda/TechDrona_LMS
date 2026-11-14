"""Coding Firestore paths sort ``language_key`` like Postgres (glibc ``en_US.utf8``): judge
languages (``enabled_languages``) and reference solutions."""

from __future__ import annotations

from typing import Any

from app.core.firestore.collation import sort_key
from app.core.firestore.store import ScopedStore
from app.modules.coding import models as cm
from app.modules.coding import service
from app.modules.coding.store_specs import LANGUAGES, orm_doc
from tests.placement.fs.backfill_helper import sample_row

# '_' is ignorable at the first level in glibc: "c_cpp" sorts with "ccpp", after "c" + "b...":
KEYS = ["python3", "c_cpp", "cpp17", "Java", "c", "cbl"]


async def test_enabled_languages_follow_postgres_collation(coding_fs: Any) -> None:
    st = ScopedStore.system("test.seed")
    docs = []
    for k in KEYS:
        lang = cm.JudgeLanguage(**sample_row(cm.JudgeLanguage, language_key=k, is_enabled=True))
        docs.append((str(lang.id), orm_doc(lang)))
    await st.import_documents(LANGUAGES, docs)
    got = [x.language_key for x in await service.enabled_languages(None)]  # type: ignore[arg-type]
    assert got == sorted(KEYS, key=sort_key)
    assert got != sorted(KEYS)  # differs from code-point order
