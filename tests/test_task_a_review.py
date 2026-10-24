import io
import json
import re
from unittest.mock import AsyncMock, Mock

import pytest

from agents.extractor.ollama_client import DocumentType, _parse_response
from agents.extractor.service import _validate_items
from auth.validator import CurrentUser
from review_queue import router as queue


USER = CurrentUser(oid="reviewer", name="Reviewer", email="reviewer@example.test",
                   tenant_id="test", roles=["OrgOS.Admin"])


def test_audit_short_key_severity_is_not_an_owner():
    raw = _parse_response('[{"s":"Access reviews were not retained.","o":"Major"}]', "AUDIT")
    [item] = _validate_items(raw, DocumentType.AUDIT, "AUDIT")
    assert item["severity"] == "Major"
    assert item["proposed_owner_role"] == ""


@pytest.mark.parametrize("evidence,overrides", [
    ({"EvidenceType": "Review record", "EvidenceDescription": ""}, {}),
    ({"EvidenceType": "", "EvidenceUndefined": True}, {"evidence_type": "Review record"}),
    ({"EvidenceType": "", "EvidenceUndefined": "false"}, {"evidence_type": "Review record"}),
    ({"EvidenceType": "Review record", "EvidenceUndefined": "true"}, {}),
    ({"EvidenceType": "Review record"}, {"evidence_type": "Log", "evidence_frequency": "Weekly",
                                          "evidence_owner_role": "Records Lead"}),
])
async def test_evidence_preview_uses_the_execution_plan(monkeypatch, evidence, overrides):
    from agents.nl_search import vector_store
    monkeypatch.setattr(vector_store, "embed_and_store_control", AsyncMock())
    create = AsyncMock(return_value={"id": "created"})
    monkeypatch.setattr(queue, "create_list_item", create)
    item = {"ControlStatement": "Retain the access review.", "ProposedOwnerRole": "Review Lead", **evidence}
    impact = await queue._zone1_impact(item, "Edit and Accept", queue._impact_shell("1", "Edit and Accept"))
    await queue._zone1_accept_cascade(item, USER, overrides)
    records = [c.args[2] for c in create.await_args_list if c.args[1] == "Evidence Tracker"]
    preview = [r for r in impact["creates"] if r["register"] == "Record Tracker"]
    # For an unedited item the preview and execution must agree, even without a description.
    if not overrides:
        assert bool(preview) == bool(records)
    else:
        impact = await queue._zone1_impact(item, "Edit and Accept", queue._impact_shell("1", "Edit and Accept"), overrides)
        preview = [r for r in impact["creates"] if r["register"] == "Record Tracker"]
        assert bool(preview) == bool(records)
        if records:
            assert records[0]["EvidenceType"] in preview[0]["detail"]
            assert records[0]["Frequency"] in preview[0]["detail"]
            assert records[0]["OwnerRole"] in preview[0]["detail"]


def definition(owner, cid="TST-01", **candidate_fields):
    return {"id": cid, "fields": {
        "ItemType": "Extraction", "DocumentType": "Policy", "ControlId": cid,
        "SourceDocumentCode": "DRG-ISMS-STD-TST", "ReviewStatus": "Pending Review", "ChangeKind": "New",
        "CandidateJson": json.dumps({"control_id": cid, "accountable": owner, "executing": owner,
                                     "control_owner": True, "title": "Review retention", "requirement": "Retain the review.",
                                     "mapping": [], "mapping_as_written": "", "risk": "Missing review",
                                     "defined_in_label": "DRG-ISMS-STD-TST", "defined_in": {"section": "8.1"},
                                     **candidate_fields}),
    }}


@pytest.mark.parametrize("owner", ["Security Lead; Operations Lead", "Control Owner", "Custodian Role"])
async def test_single_accept_refuses_before_any_register_or_queue_write(monkeypatch, owner):
    from ownership import resolver
    get_owners = AsyncMock()
    monkeypatch.setattr(resolver, "get_ownership_index", get_owners)
    monkeypatch.setattr(queue, "get_list_item", AsyncMock(return_value=definition(owner)))
    create, update = AsyncMock(), AsyncMock()
    monkeypatch.setattr(queue, "create_list_item", create)
    monkeypatch.setattr(queue, "update_list_item", update)
    with pytest.raises(queue.HTTPException) as exc:
        await queue.zone1_decide("TST-01", queue.Zone1DecideBody(
            decision="Accept", rationale="Matches the approved document."), USER)
    assert exc.value.status_code == 422
    reason = exc.value.detail
    assert all(text in reason for text in ("TST-01", owner, "document author", "exactly one role"))
    mapped = queue._sp_to_item(definition(owner))
    assert mapped["AcceptanceRefusal"] == reason
    impact = await queue._definition_impact(mapped, "Accept", queue._impact_shell("1", "Accept"))
    assert impact["blocked"] and impact["blocked_reason"] == reason
    create.assert_not_awaited()
    update.assert_not_awaited()
    get_owners.assert_not_awaited()


async def test_bulk_refuses_invalid_owner_and_accepts_the_others(monkeypatch):
    from evidence import service as evidence
    from ownership import resolver
    from doc_standards.roles import Role, RoleBook

    # Even a registered combined spelling cannot override the one-role rule.
    book = RoleBook([Role("1", "Review Lead"), Role("2", "Security Lead; Operations Lead")])
    owners = Mock(resolve=lambda name: {"kind": "group"} if book.find(name) else {"kind": "unresolved"})
    monkeypatch.setattr(resolver, "get_ownership_index", AsyncMock(return_value=owners))
    rows = [definition("Security Lead; Operations Lead"), definition("Review Lead", "TST-02")]
    monkeypatch.setattr(queue, "get_list_items", AsyncMock(side_effect=[rows, []]))
    create, update = AsyncMock(return_value={"id": "created"}), AsyncMock()
    monkeypatch.setattr(queue, "create_list_item", create)
    monkeypatch.setattr(queue, "update_list_item", update)
    monkeypatch.setattr(evidence, "sync_obligations", AsyncMock(return_value={"create": 0}))
    result = await queue.accept_document_definitions(queue.AcceptDocumentBody(
        document="DRG-ISMS-STD-TST", rationale="Matches the approved document."), USER)
    assert result["accepted"] == ["TST-02"]
    assert not result["blocked"] and not result["failed"]
    assert result["refused"] == [{"control_id": "TST-01", "reason": queue._sp_to_item(rows[0])["AcceptanceRefusal"]}]
    assert "refused" in result["message"] and "document author" in result["message"]
    assert [c.args[2] for c in update.await_args_list] == ["TST-02"]
    assert [c.args[1] for c in create.await_args_list] == ["Control Register", "Audit Log"]


async def test_all_refused_bulk_leaves_queue_pending_and_does_not_sync_evidence(monkeypatch):
    from evidence import service as evidence
    from ownership import resolver
    get_owners, sync = AsyncMock(), AsyncMock()
    monkeypatch.setattr(resolver, "get_ownership_index", get_owners)
    monkeypatch.setattr(evidence, "sync_obligations", sync)
    reads = AsyncMock(return_value=[definition("Review Lead; Operations Lead")])
    monkeypatch.setattr(queue, "get_list_items", reads)
    result = await queue.accept_document_definitions(queue.AcceptDocumentBody(
        document="DRG-ISMS-STD-TST", rationale="Matches the approved document."), USER)
    assert not result["accepted"] and len(result["refused"]) == 1
    assert reads.await_count == 1
    get_owners.assert_not_awaited()
    sync.assert_not_awaited()


@pytest.mark.parametrize("owner", ["Managing Director / CEO", "Head of IT and Infrastructure", "Review Lead"])
async def test_single_role_and_older_accountable_executing_remain_acceptable(monkeypatch, owner):
    from ownership import resolver
    from evidence import service as evidence
    monkeypatch.setattr(resolver, "get_ownership_index", AsyncMock(return_value=Mock(resolve=lambda _: {"kind": "group"})))
    monkeypatch.setattr(queue, "get_list_items", AsyncMock(return_value=[]))
    monkeypatch.setattr(queue, "create_list_item", AsyncMock(return_value={"id": "new"}))
    monkeypatch.setattr(evidence, "sync_obligations", AsyncMock(return_value={"create": 0}))
    item = queue._sp_to_item(definition(owner, control_owner=False, executing="Different Executing Role",
                                       responsibility_as_written=f"{owner} / Different Executing Role"))
    assert not item["AcceptanceRefusal"]
    result = await queue._definition_accept_cascade(item, USER, "As approved.")
    assert "Status Active" in result


@pytest.mark.parametrize("invalid", ["Control Owner", "Document Owner", "Custodian Role", "Review Lead; Operations Lead"])
@pytest.mark.parametrize("alias", [False, True])
def test_v07_rejects_invalid_registered_names_and_aliases_before_lookup(invalid, alias):
    from doc_standards.roles import Role, RoleBook
    from tests.doc_standards.test_v07_roles import BOOK, standard, v07
    role = Role("bad", "Registered Lead" if alias else invalid, (invalid,) if alias else ())
    report = v07(standard(invalid), roles=RoleBook([*BOOK.roles, role]))
    assert report["status"] == "fail"
    [finding] = [f for f in report["findings"] if f["data"]["role"] == invalid]
    assert finding["data"]["placeholder"] or finding["data"]["several"]


@pytest.mark.parametrize("code", ["DRG-ISMS-POL-TST", "DRG-ISMS-STD-TST", "DRG-ISMS-PRO-TST", "DRG-ISMS-SOP-TST"])
async def test_controlled_text_and_sharepoint_entries_refuse_before_model_or_download(monkeypatch, code):
    from agents.extractor import router, schemas, service
    from sharepoint import router as sp
    llm, download = AsyncMock(), AsyncMock()
    monkeypatch.setattr(service, "run_extraction", llm)
    monkeypatch.setattr(sp.sp_service, "get_file_bytes", download)
    with pytest.raises(queue.HTTPException) as exc:
        await router.extract_from_text(schemas.ExtractionRequest(
            text="The role shall retain every access review. " * 10,
            source_document_code=code, write_to_sharepoint=True), USER)
    assert exc.value.status_code == 422
    assert "Document Lifecycle approval" in exc.value.detail and "approved-library" in exc.value.detail
    with pytest.raises(queue.HTTPException) as exc:
        await sp.extract_from_sharepoint("file", sp.SharePointExtractionRequest(
            source_document_code=code, write_to_sharepoint=True), USER)
    assert exc.value.status_code == 422
    llm.assert_not_awaited()
    download.assert_not_awaited()


@pytest.mark.parametrize("filename,code", [("Access Standard.pdf", "EXAMPLE"), ("Policy.docx", "EXAMPLE"),
                                           ("anything.txt", "DRG-STD-TST")])
async def test_controlled_upload_refuses_before_pdf_ocr_or_model(monkeypatch, filename, code):
    from fastapi import UploadFile
    from agents.extractor import router, service
    pdf, llm = AsyncMock(), AsyncMock()
    monkeypatch.setattr(service, "extract_text_from_pdf", pdf)
    monkeypatch.setattr(service, "run_extraction", llm)
    with pytest.raises(queue.HTTPException) as exc:
        await router.extract_from_file(UploadFile(io.BytesIO(b"not needed"), filename=filename), code, True, USER)
    assert exc.value.status_code == 422 and "approved-library" in exc.value.detail
    pdf.assert_not_awaited()
    llm.assert_not_awaited()


async def test_type_override_cannot_bypass_controlled_code_or_folder(monkeypatch):
    from agents.extractor import service
    llm = AsyncMock()
    monkeypatch.setattr(service, "run_extraction", llm)
    for code, folder in [("DRG-STD-TST", None), ("EXAMPLE", "Policies & SOPs")]:
        with pytest.raises(ValueError, match="Document Lifecycle approval"):
            await service.run_extraction_from_text("Document content", code, True, folder, "Contract")
    llm.assert_not_awaited()


@pytest.mark.parametrize("doc_type", [DocumentType.CONTRACT, DocumentType.JD, DocumentType.REGULATORY, DocumentType.AUDIT])
async def test_supported_legacy_types_keep_their_pipeline(monkeypatch, doc_type):
    from agents.extractor import ollama_client as oc, service
    from graph import client as graph
    from groups import service as groups
    monkeypatch.setattr(graph, "list_all_job_titles", AsyncMock(return_value=[]))
    monkeypatch.setattr(groups, "group_names", AsyncMock(return_value=[]))
    llm = AsyncMock(return_value='[{"s":"The reviewer shall retain every signed review.","o":"Review Lead"}]')
    monkeypatch.setattr(oc, "llm_generate", llm)
    write = AsyncMock(return_value=1)
    monkeypatch.setattr(service, "_write_to_queue", write)
    from agents.classifier import service as classifier
    monkeypatch.setattr(classifier, "run_classifier", AsyncMock())
    result = await service.run_extraction_from_file(b"Document content", "document.txt", "EXAMPLE", True,
                                                  document_type_override=doc_type.value)
    assert result.document_type == doc_type.value and result.total_extracted == 1
    assert result.written_to_sharepoint
    assert write.await_args.args[2] == doc_type
    llm.assert_awaited_once()


@pytest.mark.parametrize("dry_run", [True, False])
async def test_bulk_script_refuses_policy_and_standard_without_download_or_write(monkeypatch, respx_mock, capsys, dry_run):
    from scripts import bulk_extract as bulk
    import httpx
    monkeypatch.setattr(bulk, "startup", AsyncMock())
    monkeypatch.setattr(bulk, "shutdown", AsyncMock())
    monkeypatch.setattr(bulk, "load_checkpoint", lambda: {})
    monkeypatch.setattr(bulk, "save_checkpoint", Mock())
    monkeypatch.setattr(bulk, "resolve_compliance_drive", AsyncMock(return_value=("site", "drive")))
    monkeypatch.setattr(bulk, "get_headers", AsyncMock(return_value={}))
    respx_mock.get(re.compile(r".*/drives/drive/root:.*")).mock(return_value=httpx.Response(200, json={"id": "root"}))
    monkeypatch.setattr(bulk, "list_folder", AsyncMock(return_value=[
        {"id": "policy", "name": "DRG-ISMS-POL-TST.pdf"},
        {"id": "standard", "name": "Access Standard.pdf"},
    ]))
    download, write = AsyncMock(), AsyncMock()
    monkeypatch.setattr(bulk, "download_file", download)
    monkeypatch.setattr(bulk, "write_to_queue", write)
    await bulk.bulk_extract(dry_run=dry_run)
    output = capsys.readouterr().out
    assert output.count("REFUSED") == 2
    assert "Document Lifecycle approval" in output
    download.assert_not_awaited()
    write.assert_not_awaited()


async def test_existing_legacy_policy_proposal_cannot_create_a_control(monkeypatch):
    item = {"id": "old-policy", "DocumentType": "Policy", "ControlStatement": "Retain the review."}
    create = AsyncMock()
    monkeypatch.setattr(queue, "create_list_item", create)
    with pytest.raises(queue.HTTPException) as exc:
        await queue._zone1_accept_cascade(item, USER, {})
    assert exc.value.status_code == 422
    impact = await queue._zone1_impact(item, "Accept", queue._impact_shell("1", "Accept"))
    assert impact["blocked"] and impact["blocked_reason"] == exc.value.detail
    create.assert_not_awaited()


async def test_audit_severity_survives_actual_normalization_and_queue_write(monkeypatch):
    from agents.extractor import ollama_client as oc, service
    from graph import client as graph
    monkeypatch.setattr(oc, "llm_generate", AsyncMock(return_value='[{"s":"Access reviews were not retained.","o":"Major"}]'))
    raw = await oc.run_extraction("Audit finding text", "AUDIT", DocumentType.AUDIT)
    [item] = _validate_items(raw, DocumentType.AUDIT, "AUDIT")
    monkeypatch.setattr(service, "_get_queue_list_id", lambda: "test-queue")
    monkeypatch.setattr(type(service.settings), "is_list_configured", staticmethod(lambda _: True))
    monkeypatch.setattr(graph, "get_list_items", AsyncMock(return_value=[]))
    create = AsyncMock(return_value={"id": "finding"})
    monkeypatch.setattr(graph, "create_list_item", create)
    assert await service._write_to_queue([item], "AUDIT", DocumentType.AUDIT) == 1
    fields = create.await_args.args[2]
    assert fields["Severity"] == "Major" and not fields.get("ProposedOwnerRole")


async def test_http_edit_preview_and_accept_use_the_same_overrides(monkeypatch):
    from fastapi import FastAPI
    import httpx
    from agents.nl_search import vector_store
    from agents.classifier import service as classifier
    app = FastAPI()
    app.include_router(queue.router)
    app.dependency_overrides[queue.get_current_user] = lambda: USER
    app.dependency_overrides[queue.require_compliance_lead] = lambda: USER
    row = {"id": "legacy", "fields": {"ItemType": "Extraction", "DocumentType": "Contract",
           "ControlStatement": "Retain the signed review.", "EvidenceType": "Review record",
           "EvidenceDescription": "", "EvidenceFrequency": "Monthly", "EvidenceOwnerRole": "Records Lead"}}
    monkeypatch.setattr(queue, "get_list_item", AsyncMock(return_value=row))
    create = AsyncMock(return_value={"id": "created"})
    monkeypatch.setattr(queue, "create_list_item", create)
    monkeypatch.setattr(queue, "update_list_item", AsyncMock())
    monkeypatch.setattr(vector_store, "embed_and_store_control", AsyncMock())
    monkeypatch.setattr(classifier, "run_classifier", AsyncMock())
    edits = {"evidence_type": "Approval log", "evidence_frequency": "Weekly", "evidence_owner_role": "Archive Lead"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/queue/items/legacy/impact", params={
            "zone": "1", "decision": "Edit and Accept", **edits})
        assert response.status_code == 200
        [preview] = [r for r in response.json()["creates"] if r["register"] == "Record Tracker"]
        assert all(value in preview["detail"] for value in edits.values())
        response = await client.patch("/api/v1/queue/items/legacy/decide", json={
            "decision": "Edit and Accept", "rationale": "Use the agreed evidence fields.", **edits})
        assert response.status_code == 200
    [record] = [c.args[2] for c in create.await_args_list if c.args[1] == "Evidence Tracker"]
    assert record["EvidenceType"] == "Approval log" and record["Frequency"] == "Weekly"
    assert record["OwnerRole"] == "Archive Lead"


@pytest.mark.parametrize("filename,doc_type", [
    ("Employment agreement.pdf", DocumentType.CONTRACT), ("NDA.pdf", DocumentType.CONTRACT),
    ("Standard vendor contract.pdf", DocumentType.CONTRACT),
    ("Audit against the Standard.pdf", DocumentType.AUDIT),
    ("Job Description - Standards Lead.pdf", DocumentType.JD),
    ("Access Standard.pdf", DocumentType.POLICY),
])
def test_standard_detection_preserves_actual_contracts_jds_and_audits(filename, doc_type):
    from agents.extractor.ollama_client import classify_document
    assert classify_document(filename, "") == doc_type


def test_audit_long_format_preserves_an_explicit_owner_and_severity():
    raw = _parse_response(json.dumps([{
        "control_statement": "Access reviews were not retained.", "severity": "Critical",
        "proposed_owner_role": "Audit Lead",
    }]), "AUDIT", DocumentType.AUDIT)
    [item] = _validate_items(raw, DocumentType.AUDIT, "AUDIT")
    assert item["severity"] == "Critical" and item["proposed_owner_role"] == "Audit Lead"


def test_role_navigation_metadata_does_not_change_document_gap_items():
    item = queue._sp_to_item({"id": "gap", "fields": {
        "ItemType": "Orphan", "DocumentType": "Policy", "OrphanDirection": "Doc_to_JD",
        "OrphanClassification": "ROLE_REFERENCE", "ProposedOwnerRole": "Review Lead",
    }})
    assert not item["AcceptanceRefusal"] and "AcceptPreview" not in item
    assert item["OrphanDirection"] == "Doc_to_JD" and item["OrphanClassification"] == "ROLE_REFERENCE"
