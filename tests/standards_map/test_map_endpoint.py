# =============================================================================
# tests/standards_map/test_map_endpoint.py — the Standards Map from registers
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest

import standards_map.router as sm
from auth.validator import CurrentUser

USER = CurrentUser(oid="u", name="U", email="u@x", tenant_id="t", roles=["OrgOS.Admin"])


class _Owners:
    def has_owner(self, role):
        return bool(role)


def _controls(*rows):
    return [{"id": str(i), "fields": f} for i, f in enumerate(rows, start=1)]


@pytest.fixture(autouse=True)
def _fresh_cache():
    sm._map_cache.clear()
    yield
    sm._map_cache.clear()


async def _map(controls, records=(), standard=None):
    async def lists(list_id, name, *a, **k):
        return controls if name == "Control Register" else list(records)
    with patch("standards_map.router.get_list_items", side_effect=lists), \
         patch("ownership.resolver.get_ownership_index", new=AsyncMock(return_value=_Owners())):
        return await sm.get_standards_map(standard=standard, user=USER)


def row(result, standard, clause):
    return next(r for r in result if r["standard"] == standard and r["clause"] == clause)


async def test_a_control_on_a_5_18_does_not_light_up_a_5_1():
    result = await _map(_controls({"ISOClause": "A.5.18", "OwnerRole": "CISO", "Status": "Active"}))
    assert row(result, "ISO 27001", "A.5.18")["controls_count"] == 1
    assert row(result, "ISO 27001", "A.5.1")["controls_count"] == 0


async def test_a_parsed_mapping_lands_on_every_clause_it_names():
    mapping = [{"standard": "ISO 9001", "clause": "7.5.2"}, {"standard": "ISO 27001", "clause": "A.5.1"}]
    result = await _map(_controls({"MappingJson": json.dumps(mapping), "OwnerRole": "CCO"}))
    assert row(result, "ISO 9001", "7.5")["controls_count"] == 1          # via its sub-clause
    assert row(result, "ISO 27001", "A.5.1")["controls_count"] == 1
    assert row(result, "ISO 27001", "A.5.1")["applicable"] is True


async def test_clauses_beyond_the_applicable_list_appear_once_mapped():
    mapping = [{"standard": "ISO 22301", "clause": "8.2"}]
    result = await _map(_controls({"MappingJson": json.dumps(mapping), "OwnerRole": "CTO"}))
    r = row(result, "ISO 22301", "8.2")
    assert (r["title"], r["applicable"], r["controls_count"]) == (
        "Business impact analysis and risk assessment", False, 1)


async def test_every_record_of_a_control_counts():
    controls = _controls({"ISOClause": "A.5.18", "OwnerRole": "CISO"})
    records = [{"id": "10", "fields": {"LinkedControlId": "1", "Status": "Accepted"}},
               {"id": "11", "fields": {"LinkedControlId": "1", "Status": "Accepted"}}]
    assert row(await _map(controls, records), "ISO 27001", "A.5.18")["records_accepted"] == 2


async def test_a_clause_number_shared_by_standards_must_name_its_standard():
    with pytest.raises(Exception) as exc:
        await sm.get_clause_detail("7.5", standard=None, user=USER)
    assert getattr(exc.value, "status_code", None) == 400
