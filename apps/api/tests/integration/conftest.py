"""Cross-module integration fixtures: reuse the commerce, coding and placement fixtures."""

from tests.coding.conftest import fake_judge, testcase_key  # noqa: F401
from tests.commerce.conftest import _clean_registries, api, fake_gw  # noqa: F401
from tests.placement.conftest import allow_access, rbac, world  # noqa: F401
