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


# ── the other layouts in the real library ────────────────────────────────────
#
# Each test is one layout found in Dragnet's Control Library, built small.

def test_a_row_per_control_table_defines_controls():
    """APPSEC, ENDSEC, INFRA, MONSEC: 'ID | Mandatory control requirement | …'."""
    b = DocBuilder()
    b.control_block(title="App Security Standard", code="DRG-ISMS-STD-APPSEC", owner="CTO", layer="Layer 3")
    b.heading("3.0 Control requirements")
    b.table([["ID", "Mandatory control requirement", "Required evidence / monitoring", "Risk statement"],
             ["APPSEC-01", "Applications MUST be onboarded.", "Onboarding record; inventory.", "A weakness is missed."],
             ["APPSEC-02", "Source code MUST be analysed.", "CI evidence REC-0700.", "Code weaknesses persist."]])
    doc = parse(b)
    assert doc.role is DocumentRole.DEFINING
    c1, c2 = doc.controls
    assert (c1.control_id, c1.layout, c1.requirement) == ("APPSEC-01", "row", "Applications MUST be onboarded.")
    assert [r.name for r in c1.evidence] == ["Onboarding record", "inventory"]   # named, no ID: a gap
    assert c2.evidence[0].record_id == "REC-0700"
    assert c1.risk == "A weakness is missed."


def test_a_table_combining_the_id_and_requirement_in_one_cell():
    b = DocBuilder()
    b.control_block(title="CIP Procedure", code="DRG-QI-PRO-CIP", owner="CCO", layer="Layer 4")
    b.table([["ID and requirement", "Role", "Evidence and risk link", "Trigger / monitor"],
             ["CIP-001 The context MUST be reviewed annually.", "Compliance Executive", "REC-0640", "Annual"]])
    [c] = parse(b).controls
    assert (c.control_id, c.requirement, c.trigger) == ("CIP-001", "The context MUST be reviewed annually.", "Annual")
    assert c.responsibility.accountable == "Compliance Executive"


def test_form_and_parameter_tables_with_id_shaped_refs_are_not_controls():
    b = DocBuilder()
    b.table([["Ref", "Field", "Default or note", "Value"], ["AF-01", "Requester", "Name", ""],
             ["AF-02", "Date", "Today", ""]])
    b.table([["ID", "Parameter", "Value"], ["PR-01", "Review month", "January"]])
    assert parse(b).controls == []


def test_access_control_block_style():
    """An unlabelled requirement, then several labels in one paragraph."""
    b = DocBuilder()
    b.heading("ACS-L3-01 Identity and account inventory", level=2)
    b.para("The Information Security Officer shall maintain a complete account population.")
    b.para("Trigger and monitoring: Creation; authoritative HR event.")
    b.para("Governing authority: DRG-ISMS-POL-ACCESS Access Control Policy. Responsible role: "
           "Information Security Officer. Required evidence: Account inventory entry. "
           "Record IDs: REC-0691; REC-0692.")
    b.para("Failure route: Quarantine an unowned identity.")
    b.para("Exception route: Recorded in REC-0696.")
    b.para("Risk treated: An account could remain unidentified.")
    [c] = parse(b).controls
    assert c.control_id == "ACS-L3-01"
    assert c.requirement.startswith("The Information Security Officer shall maintain")
    assert c.trigger == "Creation; authoritative HR event."
    assert c.authority == "DRG-ISMS-POL-ACCESS Access Control Policy."
    assert c.responsibility.accountable == "Information Security Officer"
    assert [r.record_id for r in c.evidence] == ["REC-0691", "REC-0692"]   # the IDs are authoritative
    assert "Account inventory entry" in c.evidence_as_written              # the names are kept
    assert c.risk == "An account could remain unidentified."


def test_it_style_per_control_field_table():
    b = DocBuilder()
    b.heading("IT-01 Technology service requests", level=1)
    b.para("The IT service owner shall log technology requests.")
    b.table([["Element", "Canonical declaration"],
             ["Responsible role", "IT Executive"],
             ["Governing authority", "IT Support Policy"],
             ["Required evidence", "Request ticket REC-0800"],
             ["Trigger and monitoring", "Each request"]])
    b.para("Risk statement: A request could be delayed.")
    [c] = parse(b).controls
    assert (c.requirement, c.trigger, c.authority) == (
        "The IT service owner shall log technology requests.", "Each request", "IT Support Policy")
    assert c.evidence[0].record_id == "REC-0800"
    assert c.risk == "A request could be delayed."


def test_change_management_sub_headings_label_their_paragraphs():
    """A deeper heading inside a control labels what follows; it does not end it."""
    b = DocBuilder()
    b.heading("CM-01 Intake and classification", level=1)
    b.para("Risk statement: A change may enter the wrong route.")
    b.heading("Control requirement", level=2)
    b.para("Every IT change is identified and classified.")
    b.heading("Procedure", level=2)
    b.para("The Change Lead records the CRF before action.")
    b.para("Owner: the Change Manager. Trigger: a change request. Evidence: the CRF REC-0820.")
    b.heading("CM-02 Approval", level=1)
    doc = parse(b)
    c = next(c for c in doc.controls if c.control_id == "CM-01")
    assert c.requirement == "Every IT change is identified and classified."
    assert c.other_fields["Procedure"] == "The Change Lead records the CRF before action."
    assert c.responsibility.accountable == "the Change Manager."[:-1]
    assert (c.trigger, c.evidence[0].record_id) == ("a change request.", "REC-0820")


def test_incident_style_id_only_heading_and_separate_accountable_and_executor():
    b = DocBuilder()
    b.heading("EVT-C01", level=2)
    b.para("Compliance Executive (QMS & NDPA) MUST ensure reportable incidents are captured.")
    b.para("Risk treated: An event could remain undisclosed.")
    b.para("Accountable: Compliance Executive (QMS & NDPA)")
    b.para("Executor: Case Handler")
    b.para("Trigger: On detection")
    b.para("Evidence Record ID: REC-0711")
    [c] = parse(b).controls
    assert (c.control_id, c.title) == ("EVT-C01", "")
    r = c.responsibility
    assert (r.accountable, r.executing, r.ambiguous) == (
        "Compliance Executive (QMS & NDPA)", "Case Handler", False)
    assert [e.record_id for e in c.evidence] == ["REC-0711"]


# ── the other citation styles ────────────────────────────────────────────────

def test_an_implements_line_under_a_section_heading():
    """Records Governance: '4.0 Record Admission' then 'Implements IRG-001, IRG-002 and IRG-009.'"""
    b = DocBuilder()
    b.control_block(title="Records Procedure", code="DRG-QI-PRO-IRG", owner="CCO", layer="Layer 4")
    b.heading("4.0 Record Admission and Taxonomy")
    b.para("Implements IRG-001, IRG-002 and IRG-009.")
    b.para("4.1 Search first.")
    [step] = parse(b).implementations
    assert step.control_ids == ["IRG-001", "IRG-002", "IRG-009"]
    assert [c.number for c in step.clauses] == ["4.1"]      # the citation line is not a clause


def test_a_range_in_a_citation_is_expanded_and_hides_nothing():
    b = DocBuilder()
    b.control_block(title="P", code="DRG-QI-PRO-CDI", owner="CCO", layer="Layer 4")
    b.heading("9.0 Evidence and Records (implements CDI-005, CDI-007, IRG-013 to IRG-015)")
    b.para("9.1 Name the evidence.")
    [step] = parse(b).implementations
    assert step.control_ids == ["CDI-005", "CDI-007", "IRG-013", "IRG-014", "IRG-015"]


def test_a_procedure_section_headed_by_the_control_it_carries_out():
    """BCDR / IT Operating Procedure style, and Access's 'AP-01 ACS-L3-01'."""
    b = DocBuilder()
    b.control_block(title="Access Procedure", code="DRG-ISMS-PRO-ACCESS", owner="ISO", layer="Layer 4")
    b.heading("AP-01 ACS-L3-01", level=2)
    b.para("1. The requester raises an access request.")
    b.para("Responsible handoff: Information Security Officer. Evidence: Access log REC-0691.")
    doc = parse(b)
    assert doc.role is DocumentRole.IMPLEMENTING and doc.controls == []
    [step] = doc.implementations
    assert step.control_ids == ["ACS-L3-01"]                 # the control, not the step number
    assert step.fields["Responsible handoff"] == "Information Security Officer."
    assert step.record_ids == ["REC-0691"]


def test_a_standard_with_an_id_led_heading_and_few_fields_is_not_an_implementation():
    b = DocBuilder()
    b.control_block(title="S", code="DRG-ISMS-STD-XYZ", owner="CTO", layer="Layer 3")
    b.heading("XYZ-01 Overview", level=2).para("Introductory text.")
    assert parse(b).implementations == []


def test_controls_declared_in_the_body_in_strict_forms_only():
    b = DocBuilder()
    b.control_block(title="ICH Procedure", code="DRG-ISMS-PRO-ICH", owner="CTO", layer="Layer 4")
    b.para("This Procedure implements IUHC-001 to IUHC-003. It creates no additional Control IDs.")
    b.para("Inherited controls: APPSEC-01 to APPSEC-02")
    b.para("Working Draft | Layer 4 | Implements DP-001 to DP-002")
    b.para("1.2 It implements the records governance controls IRG-001 to IRG-024 in the Standard.")
    doc = parse(b)
    assert doc.header.controls_declared_in_body == [
        "IUHC-001", "IUHC-002", "IUHC-003", "APPSEC-01", "APPSEC-02", "DP-001", "DP-002"]
    assert not any(i.startswith("IRG") for i in doc.implemented_ids)   # prose is not read
    assert doc.role is DocumentRole.IMPLEMENTING
    assert FindingKind.IMPLEMENTED_NOT_CITED not in kinds(doc)          # body lists are not cross-checked


# ── headers and classification ───────────────────────────────────────────────

def test_a_field_value_header_table_and_display_code():
    b = DocBuilder()
    b.table([["Field", "Value"], ["Display code", "DRG-QI-STD-INC"], ["Layer", "Layer 3"],
             ["Primary domain", "Quality & Compliance"], ["Owner", "Compliance Executive"]])
    h = parse(b).header
    assert (h.code, h.type_code, h.domain) == ("DRG-QI-STD-INC", "STD", "Quality & Compliance")


def test_type_comes_from_the_title_when_there_is_no_code_or_layer():
    b = DocBuilder()
    b.table([["Document Title", "IT and Infrastructure Control Standard"], ["Owner", "CTO"],
             ["Domain", "IT"], ["Classification", "Internal"]])
    h = parse(b).header
    assert (h.code, h.type_code, h.sources["type_code"]) == ("", "STD", "title")


def test_a_policy_listing_controls_authorises_them():
    b = DocBuilder()
    b.control_block(title="Change Policy", code="DRG-ISMS-POL-CHG", owner="CTO", layer="Layer 2",
                    implemented="CM-01 to CM-03")
    doc = parse(b)
    assert doc.role is DocumentRole.AUTHORITY
    assert doc.header.controls_implemented == ["CM-01", "CM-02", "CM-03"]


def test_a_header_row_labelled_with_the_standard_is_read_as_the_standards_the_document_states():
    from tests.cdi.builders import DocBuilder
    from cdi.parser import parse_document
    b = DocBuilder()
    b.table([["Document Code", "DRG-ISMS-STD-NET"], ["Document Title", "Net Standard"],
             ["Document Type / Layer", "Standard (Layer 3)"], ["Domain", "d"], ["Owner", "Head of IT"],
             ["ISO 27001:2022 Annex A", "A.8.20, A.8.21"]])
    h = parse_document(b.bytes(), "Net Standard.docx").header
    assert {(r.standard, r.clause) for r in h.standards} == {("ISO 27001", "A.8.20"), ("ISO 27001", "A.8.21")}
