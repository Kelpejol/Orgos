# =============================================================================
# tests/cdi/test_parser.py — reading what a controlled document states
# =============================================================================

from collections import Counter

from cdi.model import DocumentRole, FindingKind, Severity
from cdi.parser import parse_document
from tests.cdi.builders import DocBuilder, defining_standard, implementing_procedure


def parse(builder, filename="t.docx", **kw):
    return parse_document(builder.bytes(), filename, **kw)


def kinds(doc):
    return Counter(f.kind for f in doc.findings)


# ── the document's control block ─────────────────────────────────────────────

def test_header_reads_identity_and_splits_combined_cells():
    h = parse(defining_standard()).header
    assert (h.code, h.type_code, h.layer_as_written) == ("DRG-QI-STD-TST", "STD", "Layer 3 Standard")
    assert h.parent_codes == ["DRG-QI-POL-TST"]
    assert (h.first_pass_approval, h.final_approval) == ("Chief Compliance Officer", "Managing Director / CEO")
    assert (h.classification, h.distribution) == ("Internal Use Only", "All Staff")
    assert [s.key for s in h.standards] == ["ISO 27001 7.5", "ISO 27001 A.5.1"]
    assert h.sources["code"] == "control block"


def test_a_cover_and_control_block_that_disagree_are_reported():
    b = DocBuilder()
    b.table([["Document Title", "Policy A"], ["Document Code", "DRG-QI-POL-AAA"],
             ["Version", "02"], ["Owner", "CCO"]])
    b.control_block(title="Policy B", code="DRG-QI-POL-AAA", owner="CCO", layer="Layer 2")
    doc = parse(b)
    assert doc.header.title == "Policy B"          # the control block wins
    [conflict] = [f for f in doc.findings if f.kind is FindingKind.HEADER_CONFLICT]
    assert "Policy A" in conflict.message and "Policy B" in conflict.message


def test_a_table_describing_the_fields_is_not_mistaken_for_a_control_block():
    """A Standard has a "Field | Rule" table whose rows say what Domain means."""
    b = defining_standard()
    b.table([["Field", "Rule"], ["Document Title", "Names the document"],
             ["Domain", "The area of organisational accountability"],
             ["Owner", "The role that owns it"], ["Version", "Two digits"]])
    doc = parse(b)
    assert doc.header.domain == "Quality & Compliance"
    assert FindingKind.HEADER_CONFLICT not in kinds(doc)


def test_the_code_falls_back_to_the_file_name():
    doc = parse(DocBuilder().para("No control block here."), filename="DRG-QI-GDL-ABC Guideline.docx")
    assert doc.header.code == "DRG-QI-GDL-ABC"
    assert doc.header.sources["code"] == "filename"


# ── defining documents ───────────────────────────────────────────────────────

def test_a_standard_defines_its_controls_with_every_field():
    doc = parse(defining_standard())
    assert doc.role is DocumentRole.DEFINING
    assert doc.defined_ids == ["TST-001", "TST-002"]
    c = doc.controls[0]
    assert c.requirement.startswith("Every document MUST link")
    assert c.trigger == "Creation, submission."
    assert (c.responsibility.accountable, c.responsibility.executing) == (
        "Compliance Executive (QMS & NDPA)", "platform check V03")
    assert [(r.record_id, r.name) for r in c.evidence] == [
        ("REC-0623", "Controlled Document Register"), ("REC-0635", "validation result")]
    assert all(r.control_ids == ["TST-001"] for r in c.evidence)
    assert [m.key for m in c.mapping] == ["ISO 9001 7.5.2", "ISO 27001 7.5.2", "ISO 27001 A.5.1"]
    assert c.missing_fields == []
    assert c.location.item == "TST-001"


def test_a_field_continued_on_the_next_paragraph_is_kept_whole():
    b = DocBuilder()
    b.control("TST-009", "Long requirement",
              requirement="Every document MUST do this,", trigger="Issue.",
              responsibility="Document Owner.", evidence="REC-0001 Log.")
    b.para("and it MUST also do that.")
    b.para("Risk: Something goes wrong.")
    [c] = parse(b).controls
    assert c.evidence_as_written == "REC-0001 Log.\nand it MUST also do that."
    assert c.risk == "Something goes wrong."


def test_missing_fields_are_reported_and_a_missing_requirement_is_an_error():
    b = DocBuilder()
    b.control("TST-010", "Partial", trigger="Issue.", responsibility="Document Owner.",
              evidence="REC-0001 Log.")
    doc = parse(b)
    [f] = [f for f in doc.findings if f.kind is FindingKind.CONTROL_MISSING_FIELD]
    assert f.severity is Severity.ERROR
    assert "Requirement" in f.message and "Mapping" in f.message


def test_an_id_led_line_without_labelled_fields_is_not_a_control():
    b = DocBuilder()
    b.para("CDI-019 is implemented throughout this Standard.")
    b.para("RR-26 Retention rule for operational records.")
    assert parse(b).controls == []


def test_unknown_labels_inside_a_control_are_kept_not_dropped():
    b = DocBuilder()
    b.control("TST-011", "Extra", requirement="MUST.", trigger="Issue.",
              responsibility="Document Owner.", evidence="REC-0001 Log.")
    b.para("Evidence freshness: 90 days.")
    [c] = parse(b).controls
    assert c.other_fields == {"Evidence freshness": "90 days."}


def test_a_duplicate_control_id_is_an_error_and_only_the_first_is_kept():
    b = defining_standard()
    b.control("TST-001", "Again", requirement="Different.", trigger="x.",
              responsibility="Document Owner.", evidence="REC-0001 Log.")
    doc = parse(b)
    assert doc.defined_ids.count("TST-001") == 1
    assert kinds(doc)[FindingKind.CONTROL_DUPLICATE_ID] == 1


def test_the_documents_roles_table_settles_a_slash_in_a_role_name():
    b = defining_standard()
    b.control("TST-003", "Approval", requirement="MUST.", trigger="Issue.",
              responsibility="Managing Director / CEO", evidence="REC-0001 Log.")
    doc = parse(b)
    c = next(c for c in doc.controls if c.control_id == "TST-003")
    assert c.responsibility.single_role and not c.responsibility.ambiguous
    assert FindingKind.RESPONSIBILITY_AMBIGUOUS not in kinds(doc)


# ── implementing documents ───────────────────────────────────────────────────

def test_a_procedure_carries_out_controls_through_citing_sections():
    doc = parse(implementing_procedure())
    assert doc.role is DocumentRole.IMPLEMENTING
    assert doc.controls == []                       # implementing creates no controls
    assert doc.implemented_ids == ["TST-01", "TST-02"]
    first, second = doc.implementations
    assert (first.section_number, first.section_title, first.control_ids) == (
        "4.0", "Business impact assessment", ["TST-01"])
    assert [c.number for c in first.clauses] == ["4.1", "4.2"]
    assert first.risk_statements == {"TST-01": "A process could stay down too long."}
    assert first.record_ids == ["REC-0676"]
    assert second.control_ids == ["TST-02"]         # "(implements TST-02)" syntax


def test_records_are_tied_to_controls_through_the_step_that_creates_them():
    doc = parse(implementing_procedure())
    by_id = {r.record_id: r for r in doc.records}
    assert by_id["REC-0676"].control_ids == ["TST-01"]
    assert by_id["REC-0676"].created_by == "Accountable Department Head"
    assert by_id["REC-0676"].at_step == "4.1"
    assert by_id["REC-0675"].control_ids == ["TST-02"]


def test_open_parameters_stay_visible_gaps():
    doc = parse(implementing_procedure())
    assert [(p.parameter, p.value) for p in doc.open_parameters] == [
        ("Maximum tolerable downtime", None), ("Review month", "January")]
    [gap] = [f for f in doc.findings if f.kind is FindingKind.OPEN_PARAMETER]
    assert gap.severity is Severity.INFO and "Maximum tolerable downtime" in gap.message


def test_a_consistent_procedure_raises_no_cross_check_findings():
    doc = parse(implementing_procedure())
    assert set(kinds(doc)) == {FindingKind.OPEN_PARAMETER}


def test_a_control_map_that_disagrees_with_the_headings_is_an_error():
    b = implementing_procedure()
    b.table([["Standard control", "Clause in this Procedure"], ["TST-01 Wrong place", "5.0"]])
    doc = parse(b)
    mismatches = [f for f in doc.findings if f.kind is FindingKind.CONTROL_MAP_MISMATCH]
    assert any(f.severity is Severity.ERROR and "TST-01" in f.message for f in mismatches)


def test_a_listed_control_no_section_carries_out_is_reported():
    b = DocBuilder()
    b.control_block(title="P", code="DRG-ISMS-PRO-XYZ", owner="CTO", layer="Layer 4",
                    implemented="TST-01; TST-02")
    b.heading("4.0 Assessment (TST-01)").para("4.1 Do the thing.")
    doc = parse(b)
    [f] = [f for f in doc.findings if f.kind is FindingKind.IMPLEMENTED_NOT_CITED]
    assert "TST-02" in f.message


def test_a_heading_that_merely_mentions_an_id_is_not_an_implementation():
    b = DocBuilder()
    b.heading("4.0 Records (see REC-0676)")
    b.heading("5.0 Escalation (CTO)")
    b.para("1.2 It implements BCDR-01 and BCDR-02.")    # prose, not structure
    assert parse(b).implementations == []


# ── classification ───────────────────────────────────────────────────────────

def test_a_forms_set_supports_the_controls_it_lists_without_warnings():
    b = DocBuilder()
    b.control_block(title="Forms", code="DRG-QI-FM-CDR", owner="CCO", layer="Supporting",
                    implemented="CDI-003, CDI-018")
    doc = parse(b)
    assert doc.role is DocumentRole.SUPPORTING
    assert doc.implemented_ids == ["CDI-003", "CDI-018"]
    assert FindingKind.IMPLEMENTED_NOT_CITED not in kinds(doc)


def test_a_policy_is_authority_and_a_policy_with_controls_is_flagged():
    b = DocBuilder()
    b.control_block(title="Policy", code="DRG-QI-POL-AAA", owner="CCO", layer="Layer 2")
    assert parse(b).role is DocumentRole.AUTHORITY

    b.control("AAA-001", "Rule", requirement="MUST.", trigger="Issue.",
              responsibility="CCO.", evidence="REC-0001 Log.")
    doc = parse(b)
    assert doc.role is DocumentRole.DEFINING
    assert FindingKind.POLICY_DEFINES_CONTROLS in kinds(doc)


def test_a_standard_written_as_prose_is_unstructured_and_says_so():
    b = DocBuilder()
    b.control_block(title="Old Standard", code="DRG-ISMS-STD-AU", owner="CTO", layer="Layer 3")
    b.heading("3.0 Rules").para("3.1 Staff must lock their screens.")
    doc = parse(b)
    assert doc.role is DocumentRole.UNSTRUCTURED
    assert FindingKind.NO_STRUCTURE in kinds(doc)


def test_tracked_changes_are_reported_first():
    b = defining_standard()
    b.para_with_changes("Note: ", inserted="pending wording")
    doc = parse(b)
    assert doc.findings[0].kind is FindingKind.TRACKED_CHANGES
    assert doc.tracked_changes == 1


def test_the_result_serialises_to_json_safe_data():
    import json
    data = parse(implementing_procedure()).to_dict()
    json.dumps(data)
    assert data["role"] == "Implementing"
    assert data["findings"][0]["kind"] == "open_parameter"


def test_a_pdf_records_row_that_lost_a_cell_keeps_only_its_record_id():
    """Guessing which column went missing would put a role in the wrong field."""
    from cdi.parser import parse_content
    from cdi.reader import DocumentContent, Table
    table = Table((
        ("Record", "Created by", "At step", "Kept in", "Retention"),
        ("REC-0675 Continuity Register", "Head of IT", "5.1", "Annex C"),   # one cell lost
    ), positional=False)
    doc = parse_content(DocumentContent([table], "pdf"), "t.pdf")
    [ref] = doc.records
    assert ref.record_id == "REC-0675" and ref.created_by == ""
    assert FindingKind.TABLE_ROW_UNALIGNED in kinds(doc)
