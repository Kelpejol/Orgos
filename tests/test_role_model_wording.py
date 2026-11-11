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
    ("create", "Audit Lead", {"id": "other", "name": "Audit Lead"},
     "These names can't be used: “Audit Lead” is already in Org Roles as Audit Lead."),
    ("update", " ", None, "Role name cannot be empty."),
    ("update", "Audit Lead", {"id": "other", "name": "Audit Lead"},
     "These names can't be used: “Audit Lead” is already in Org Roles as Audit Lead."),
])
async def test_role_validation_errors_keep_their_checks_and_write_nothing(monkeypatch, action, name, found, expected):
    monkeypatch.setattr(groups_service, "get_groups_list_id", AsyncMock(return_value="example-list"))
    monkeypatch.setattr(groups_service, "list_groups",
                        AsyncMock(return_value=[{"aliases": [], "members": [], **found}] if found else []))
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


@pytest.mark.parametrize("owner,status", [("", "Blocked"), ("Unregistered Example Role", "Blocked"),
                                          ("Registered Role", "Active")])
async def test_an_older_extraction_is_active_only_when_its_owner_is_a_role_in_org_roles(owner, status, monkeypatch):
    from ownership import resolver
    owners = resolver.OwnershipIndex([{"name": "Registered Role", "members": [{"oid": "p"}]}],
                                     {"Unregistered Example Role": [{"oid": "q"}]})   # a job title is not a role
    monkeypatch.setattr(resolver, "get_ownership_index", AsyncMock(return_value=owners))
    item = {"ControlStatement": "The reviewer shall retain the signed review.", "ProposedOwnerRole": owner}
    impact = await queue._zone1_impact(item, "Accept", queue._impact_shell("1", "Accept"))
    detail = impact["creates"][0]["detail"]
    assert "Control owner:" in detail
    assert f"status: {status}" in detail
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


async def test_chat_answers_who_owns_a_control_by_its_id_with_the_role_and_its_holders(monkeypatch):
    from agents.nl_search import compliance_search as search
    from agents.nl_search.response_generator import _context_from_compliance
    from ownership import resolver
    monkeypatch.setattr(search.settings, "control_register_list_id", "example-controls")
    items = [{"id": str(i), "fields": {"ControlId": cid, "OwnerRole": role, "OwnerEntraId": "",
              "ControlStatement": statement, "Status": "Active"}}
             for i, (cid, role, statement) in enumerate([
                 ("SWEEP-01", "Review Lead", "Review access."),
                 ("OTHER-02", "Operations Lead", "Retain approvals."),
             ], 1)]
    monkeypatch.setattr(search, "get_list_items", AsyncMock(return_value=items))
    monkeypatch.setattr(search, "_graph_search_list", AsyncMock(return_value=[]))
    monkeypatch.setattr(search, "_extract_entities", AsyncMock(return_value={"keywords": ["owns"]}))
    for name in ("_search_compliance_calendar", "_search_gap_analysis", "_search_document_register",
                 "_search_strategic_risks", "_get_all_records"):
        monkeypatch.setattr(search, name, AsyncMock(return_value=[]))
    owners = resolver.OwnershipIndex([{"name": "Review Lead", "members": [{"oid": "p", "display_name": "Ada Okafor"}]}], {})
    monkeypatch.setattr(resolver, "get_ownership_index", AsyncMock(return_value=owners))
    result = await search.search_compliance("who owns control SWEEP-01")
    [row] = result["controls"]                                  # exactly the control asked about
    assert row["control_id"] == "SWEEP-01"
    assert row["owner"]["role"] == "Review Lead" and row["owner"]["holders"] == ["Ada Okafor"]
    context = _context_from_compliance(result)
    assert "SWEEP-01" in context and "Review Lead — held by Ada Okafor" in context


async def test_my_controls_finds_nothing_rather_than_everyones(monkeypatch):
    from agents.nl_search import compliance_search as search
    from ownership import resolver
    monkeypatch.setattr(search.settings, "control_register_list_id", "example-controls")
    items = [{"id": "1", "fields": {"ControlId": "A-01", "OwnerRole": "Review Lead", "Status": "Active",
                                    "ControlStatement": "x"}}]
    monkeypatch.setattr(search, "get_list_items", AsyncMock(return_value=items))
    monkeypatch.setattr(resolver, "get_ownership_index",
                        AsyncMock(return_value=resolver.OwnershipIndex([{"name": "Review Lead", "members": []}], {})))
    rows = await search._search_controls([], None, question="my controls", user_oid="me", is_personal_query=True)
    assert rows == []


async def test_a_spelling_of_an_existing_role_cannot_be_created_beside_it(monkeypatch):
    monkeypatch.setattr(groups_service, "list_groups", AsyncMock(return_value=[
        {"id": "1", "name": "IT and Security Lead", "aliases": [], "members": []}]))
    with pytest.raises(ValueError, match="already in Org Roles as IT and Security Lead"):
        await groups_service.create_group("IT & Security Lead", "", "", [], "", "")


async def test_an_alias_that_already_means_another_role_or_is_a_field_name_is_refused(monkeypatch):
    monkeypatch.setattr(groups_service, "list_groups", AsyncMock(return_value=[
        {"id": "1", "name": "Head of IT", "aliases": [], "members": []},
        {"id": "2", "name": "ISMS Lead", "aliases": [], "members": []}]))
    monkeypatch.setattr(groups_service, "get_groups_list_id", AsyncMock(return_value="l"))
    monkeypatch.setattr(groups_service, "_has_col", lambda c: True)
    update = AsyncMock()
    monkeypatch.setattr(groups_service, "update_list_item", update)
    with pytest.raises(ValueError, match="already in Org Roles as ISMS Lead.*field"):
        await groups_service.update_group("1", None, None, None, ["isms lead", "Control Owner"])
    update.assert_not_awaited()


async def test_an_alias_of_another_role_can_be_moved_to_a_new_role_by_choice(monkeypatch):
    """Creating "Department Heads" with alias "Team Leads", which Line Manager answers to today."""
    line = {"id": "1", "name": "Line Manager", "aliases": ["Team Leads", "Line Managers"], "members": []}
    monkeypatch.setattr(groups_service, "list_groups", AsyncMock(return_value=[line]))
    monkeypatch.setattr(groups_service, "get_group", AsyncMock(return_value=line))
    monkeypatch.setattr(groups_service, "get_groups_list_id", AsyncMock(return_value="l"))
    monkeypatch.setattr(groups_service, "_has_col", lambda c: True)
    update = AsyncMock()
    create = AsyncMock(return_value={"id": "9", "fields": {"Title": "Department Heads"}})
    monkeypatch.setattr(groups_service, "update_list_item", update)
    monkeypatch.setattr(groups_service, "create_list_item", create)

    with pytest.raises(groups_service.NameClash) as refused:                 # not chosen: refused, nothing written
        await groups_service.create_group("Department Heads", "", "", [], "", "", aliases=["Team Lead"])
    assert refused.value.clashes[0]["movable"] and refused.value.clashes[0]["role"] == "Line Manager"
    update.assert_not_awaited() and create.assert_not_awaited()

    out = await groups_service.create_group("Department Heads", "", "", [], "", "",
                                            aliases=["Team Lead"], move_aliases=["Team Lead"])
    assert json.loads(update.await_args.args[3]["Aliases"]) == ["Line Managers"]   # Line Manager lets it go
    assert out["moved"] == [{"text": "Team Lead", "from": "Line Manager"}]


async def test_another_role_s_own_name_can_never_be_moved(monkeypatch):
    monkeypatch.setattr(groups_service, "list_groups", AsyncMock(return_value=[
        {"id": "1", "name": "Line Manager", "aliases": [], "members": []}]))
    with pytest.raises(groups_service.NameClash) as refused:
        await groups_service.create_group("Line Managers", "", "", [], "", "", move_aliases=["Line Managers"])
    assert not refused.value.clashes[0]["movable"]
