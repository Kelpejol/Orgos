import json
from unittest.mock import AsyncMock

import pytest

from agents.extractor.ollama_client import DocumentType
from agents.extractor.service import _validate_items
from control_register.definitions import decide_status
from groups import service as groups_service
from review_queue import router as queue


@pytest.mark.parametrize("candidate,words", [
    ({"accountable": "", "control_owner": True}, "The defining document names no Control owner"),
    ({"accountable": "", "control_owner": False}, "older responsibility line names no Control owner"),
    ({"accountable": "Audit Lead", "responsibility_ambiguous": True,
      "responsibility_as_written": "Audit Lead / Operations Lead"}, "one Control owner from Org Roles"),
])
def test_blocked_owner_messages_preserve_status_and_explain_the_document_fix(candidate, words):
    status, reason = decide_status(candidate, lambda role: {"kind": "group"})
    assert status == "Blocked" and words in reason


@pytest.mark.parametrize("action,name,found,expected", [
    ("create", " ", None, "Role name is required."),
    ("create", "Audit Lead", {"id": "other"}, "A role named 'Audit Lead' already exists."),
    ("update", " ", None, "Role name cannot be empty."),
    ("update", "Audit Lead", {"id": "other"}, "A role named 'Audit Lead' already exists."),
])
async def test_role_validation_errors_keep_their_checks_and_write_nothing(monkeypatch, action, name, found, expected):
    monkeypatch.setattr(groups_service, "get_groups_list_id", AsyncMock(return_value="example-list"))
    monkeypatch.setattr(groups_service, "find_group_by_name", AsyncMock(return_value=found))
    create, update = AsyncMock(), AsyncMock()
    monkeypatch.setattr(groups_service, "create_list_item", create)
    monkeypatch.setattr(groups_service, "update_list_item", update)
    with pytest.raises(ValueError) as error:
        if action == "create":
            await groups_service.create_group(name, "", "", [], "", "")
        else:
            await groups_service.update_group("example-role", None, None, name)
    assert str(error.value) == expected
    create.assert_not_awaited()
    update.assert_not_awaited()


async def test_definition_preview_names_org_roles_and_preserves_accept_as_blocked(monkeypatch):
    from ownership import resolver
    owners = resolver.OwnershipIndex([], {})
    monkeypatch.setattr(resolver, "get_ownership_index", AsyncMock(return_value=owners))
    monkeypatch.setattr(queue, "get_list_items", AsyncMock(return_value=[]))
    candidate = {"control_id": "SWEEP-01", "accountable": "Unregistered Role", "control_owner": True}
    item = {"ControlId": "SWEEP-01", "Candidate": candidate}
    impact = await queue._definition_impact(item, "Accept", queue._impact_shell("1", "Accept"))
    assert not impact["blocked"]  # the acceptance policy is a decision left to the report
    assert "status Blocked" in impact["creates"][0]["detail"]
    warnings = " ".join(impact["warnings"])
    assert "Control owner is recognised in Org Roles" in warnings and "status recheck" in warnings
    assert "Role Catalogue" not in warnings
    assert item["Candidate"] == candidate


@pytest.mark.parametrize("owner", ["", "Unregistered Example Role"])
async def test_legacy_preview_wording_does_not_change_its_status_policy(owner):
    item = {"ControlStatement": "The reviewer shall retain the signed review.", "ProposedOwnerRole": owner}
    impact = await queue._zone1_impact(item, "Accept", queue._impact_shell("1", "Accept"))
    detail = impact["creates"][0]["detail"]
    assert "Control owner:" in detail
    assert f"status: {'Active' if owner else 'Blocked'}" in detail
    if not owner:
        assert "No Control owner proposed" in " ".join(impact["warnings"])


def test_gap_remediation_uses_org_roles_without_assigning_a_placeholder_role():
    from agents.gap_analyzer.control_gaps import find_control_gaps
    control = {"control_id": "SWEEP-01", "status": "Blocked", "definition": {
        "control_id": "SWEEP-01", "accountable": "Unregistered Role", "defined_in_label": "Example Standard",
        "evidence": [{"record_id": "REC-0001"}], "implemented_in": [{"document": "Example Procedure"}],
    }}
    gap, = find_control_gaps([control])
    package = json.loads(gap["stated"]["remediation_json"])
    assert "Add each real role to Org Roles" in package["document"]
    assert "Role Catalogue" not in package["document"]
    assert package["roles"] == ["Document Owner", "Compliance Executive (QMS & NDPA)"]


@pytest.mark.parametrize("owner", ["", "Review Lead"])
def test_legacy_ownership_gap_wording_checks_roles_and_people(monkeypatch, owner):
    from agents.gap_analyzer import service
    from standards_map import catalogue
    clause = catalogue.Clause("ISO 27001", "A.5.1", "Policies")
    monkeypatch.setattr(catalogue, "applicable_clauses", lambda: [(clause, {"control"})])
    monkeypatch.setattr(catalogue, "covers", lambda row, ref: True)
    control = {"id": "example", "control_id": "", "refs": [{}], "owner_role": owner,
               "statement": "Retain the review.", "status": "Blocked"}
    gaps = service._find_gaps([control], [], type("Owners", (), {"has_owner": lambda self, role: False})())
    ownership, = [gap for gap in gaps if gap["gap_category"] == "Ownership gap"]
    assert "needs ownership review" in ownership["finding"]
    assert "Control owner" in ownership["finding"]
    assert "job title or group" not in ownership["finding"]
    if owner:
        assert "Org Roles" in ownership["finding"] and "people assigned" in ownership["finding"]


@pytest.mark.parametrize("doc_type,extra", [
    (DocumentType.CONTRACT, {"role": "Contract Review Lead"}),
    (DocumentType.JD, {"role": "Operations Coordinator"}),
    (DocumentType.AUDIT, {"o": "Major"}),
])
def test_legacy_contract_jd_and_audit_output_remains_readable(doc_type, extra):
    item, = _validate_items([{"statement": "The team shall review the signed approval record.",
                              "risk": "An unreviewed change may be issued.", **extra}], doc_type, "EXAMPLE")
    assert item["document_type"] == doc_type.value
    if doc_type == DocumentType.JD:
        assert item["extraction_category"] == "Orphan"
        assert item["responsibility_statement"] == item["control_statement"]
    else:
        assert item["extraction_category"] == "Extraction"
    if doc_type == DocumentType.AUDIT:
        assert item["finding_type"] == "Finding" and item["severity"] == "Major"


def test_chat_control_and_document_labels_preserve_their_distinct_existing_owners():
    from agents.nl_search.response_formatter import format_compliance_response
    from agents.nl_search.response_generator import _context_from_compliance
    result = {"found": True, "controls": [{"control_statement": "Review access.",
              "owner_role_title": "Review Lead", "owner": {"display_name": "Review Lead"}}],
              "documents": [{"title": "Example Standard", "document_code": "EXAMPLE-STD",
                             "owner": {"display_name": "Avery Example"}}]}
    context = _context_from_compliance(result)
    answer = format_compliance_response(result)["answer"]
    for text in (context, answer):
        assert "Control owner: Review Lead" in text and "Document owner: Avery Example" in text


async def test_chat_owner_question_records_current_retrieval_limitations_without_live_calls(monkeypatch):
    from agents.nl_search import compliance_search as search
    from agents.nl_search.response_generator import _context_from_compliance
    monkeypatch.setattr(search.settings, "control_register_list_id", "example-controls")
    items = [{"id": str(i), "fields": {"ControlId": cid, "OwnerRole": role, "OwnerEntraId": "",
              "ControlStatement": statement, "Status": "Active"}}
             for i, (cid, role, statement) in enumerate([
                 ("SWEEP-01", "Review Lead", "Review access."),
                 ("OTHER-02", "Operations Lead", "Retain approvals."),
             ], 1)]
    monkeypatch.setattr(search, "get_list_items", AsyncMock(return_value=items))
    monkeypatch.setattr(search, "_graph_search_list", AsyncMock(return_value=[]))
    monkeypatch.setattr(search, "_extract_entities", AsyncMock(return_value={"keywords": ["SWEEP-01"]}))
    for name in ("_search_compliance_calendar", "_search_gap_analysis", "_search_document_register",
                 "_search_strategic_risks", "_get_all_records"):
        monkeypatch.setattr(search, name, AsyncMock(return_value=[]))
    people_lookup = AsyncMock(side_effect=AssertionError("Role-owned rows have no person OID"))
    monkeypatch.setattr(search, "resolve_user", people_lookup)
    result = await search.search_compliance("who owns control SWEEP-01")
    # Characterization of D7, not a desired new contract: ID is not searched or carried through.
    assert len(result["controls"]) == 2 and all("control_id" not in row for row in result["controls"])
    assert result["controls"][0]["owner"]["display_name"] == "Review Lead"
    people_lookup.assert_not_awaited()
    context = _context_from_compliance(result)
    assert "Control owner: Review Lead" in context and "held by" not in context
