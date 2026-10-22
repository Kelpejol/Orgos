# =============================================================================
# tests/doc_standards/test_checks.py — the CDI validation checks
#
# The properties that matter most: a check that could not look never passes; a
# check that is not built says so; an enforcement level comes from the CDI
# document; a check that crashes neither passes nor takes the others down.
# =============================================================================

from collections import Counter
from types import SimpleNamespace

import pytest

import doc_standards.checks as checks
from cdi.library import LibraryIndex
from cdi.parser import parse_document
from doc_standards.checks import Context, reference, run_checks
from tests.cdi.builders import DocBuilder
from tests.doc_standards.helpers import v06_document

NAME = "Test Standard.docx"


def run(data=None, filename=NAME, ctx=None, others=()):
    data = data or v06_document()
    parsed = parse_document(data, filename)
    if ctx is None and others is not None:
        ctx = Context(index=LibraryIndex([*others, parsed]))
    return run_checks(parsed, filename, data, ctx), parsed


def status(report, check_id):
    return next(r for r in report["results"] if r["id"] == check_id)


# ── the standard itself ─────────────────────────────────────────────────────

def test_the_enforcement_levels_are_the_cdi_documents_own():
    levels = Counter(c["enforcement"] for c in reference()["checks"])
    assert levels == {"BLOCK": 18, "FLAG": 5, "REPORT": 1}
    assert [c["id"] for c in reference()["checks"]] == [f"V{n:02d}" for n in range(1, 25)]


def test_every_check_is_accounted_for_nothing_is_silently_missing():
    report, _ = run()
    assert len(report["results"]) == 24
    assert sum(report["counts"].values()) == 24


def test_a_check_that_is_not_built_says_so_and_says_what_it_needs():
    report, _ = run()
    v05 = status(report, "V05")
    assert v05["status"] == "not_built" and "Role Register" in v05["summary"]


def test_a_clean_result_is_never_presented_as_a_full_clearance():
    report, _ = run(v06_document(ids=("TST-01",)), filename="Test Standard.docx")
    if report["verdict"] != "blocked":
        assert "not a full clearance" in report["headline"]


# ── V22 mapping, V08 completeness, V10 risk ─────────────────────────────────

def test_v22_fails_a_control_with_no_mapping_and_passes_one_that_has_it():
    assert status(run(v06_document(mapping=""))[0], "V22")["status"] == "fail"
    assert status(run(v06_document(mapping="ISO 27001 A.5.16"))[0], "V22")["status"] == "pass"


def test_v22_does_not_apply_outside_qms_and_isms_scope():
    r = status(run(v06_document(code="DRG-IT-STD-TST", mapping=""))[0], "V22")
    assert r["status"] == "not_applicable" and "outside QMS/ISMS scope" in r["summary"]


def test_v08_lists_each_incomplete_control():
    b = DocBuilder()
    b.control_block(title="Test Standard", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="o", classification="c")
    b.control("TST-01", "Thin", requirement="The ISO shall do it.", trigger="Creation.", responsibility="ISO.",
              evidence="REC-0001 log.", mapping="ISO 27001 A.5.1")
    report, _ = run(b.bytes())
    v08 = status(report, "V08")
    assert v08["status"] == "fail" and v08["findings"][0]["where"] == "TST-01"
    assert "Risk" in v08["findings"][0]["message"]


def test_v10_catches_a_risk_register_reference():
    b = DocBuilder()
    b.control_block(title="Test Standard", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="o", classification="c")
    b.control("TST-01", "Risky", requirement="The ISO shall.", trigger="t.", responsibility="ISO.",
              evidence="REC-0001.", risk="See RISK-014 in the register.", failure_route="f.",
              exception_route="e.", mapping="ISO 27001 A.5.1")
    assert status(run(b.bytes())[0], "V10")["status"] == "fail"


# ── restatements are not definitions ────────────────────────────────────────

def _procedure_restating() -> bytes:
    b = DocBuilder()
    b.control_block(title="Test Procedure", code="DRG-ISMS-PRO-TST", layer="Layer 4 Procedure", domain="d",
                    owner="o", classification="c")
    b.control("TST-01", "Copy", requirement="The Information Security Officer shall maintain TST-01.",
              evidence="REC-0691.", risk="Unlogged.")
    return b.bytes()


def test_a_procedures_short_copy_of_a_standards_control_is_not_held_to_the_definition_rules():
    standard = parse_document(v06_document(), NAME)
    report, _ = run(_procedure_restating(), "Test Procedure.docx", others=[standard])
    for cid in ("V08", "V10", "V22"):
        assert status(report, cid)["status"] == "not_applicable", cid


def test_without_the_library_it_says_it_cannot_tell_rather_than_judging_the_copy():
    report, _ = run(_procedure_restating(), "Test Procedure.docx", ctx=Context())
    assert status(report, "V08")["status"] == "could_not_check"


def test_a_reworded_copy_is_a_v11_failure():
    standard = parse_document(v06_document(), NAME)
    b = DocBuilder()
    b.control_block(title="Test Procedure", code="DRG-ISMS-PRO-TST", layer="Layer 4 Procedure", domain="d",
                    owner="o", classification="c")
    b.control("TST-01", "Copy", requirement="The Information Security Officer maintains TST-01.",
              trigger="Creation.", evidence="REC-0691.")           # three fields: enough to be read as a control
    report, _ = run(b.bytes(), "Test Procedure.docx", others=[standard])
    assert status(report, "V11")["status"] == "fail"


# ── V09, V03: they need context, and say so without it ──────────────────────

def test_v09_without_the_catalogue_cannot_check_it_does_not_pass():
    assert status(run(ctx=Context())[0], "V09")["status"] == "could_not_check"


def test_v09_fails_a_record_the_catalogue_does_not_hold_and_passes_one_it_does():
    other = SimpleNamespace(withdrawn=False, name="x")
    assert status(run(ctx=Context(catalogue={}))[0], "V09")["status"] == "fail"
    assert status(run(ctx=Context(catalogue={"REC-0691": other}))[0], "V09")["status"] == "pass"


def test_v09_fails_a_withdrawn_record():
    gone = SimpleNamespace(withdrawn=True, name="x")
    assert status(run(ctx=Context(catalogue={"REC-0691": gone}))[0], "V09")["status"] == "fail"


def test_v03_needs_the_register_and_an_approved_parent():
    assert status(run(ctx=Context())[0], "V03")["status"] == "could_not_check"
    approved = [{"fields": {"DocumentCode": "DRG-ISMS-POL-ACCESS", "Status": "Active"}}]
    draft = [{"fields": {"DocumentCode": "DRG-ISMS-POL-ACCESS", "Status": "Withdrawn"}}]
    assert status(run(ctx=Context(register=approved))[0], "V03")["status"] == "pass"
    assert status(run(ctx=Context(register=draft))[0], "V03")["status"] == "fail"
    assert status(run(ctx=Context(register=[]))[0], "V03")["status"] == "fail"


# ── V02, V23, V15, V14, V12 ─────────────────────────────────────────────────

def test_v02_rejects_a_retired_function_code_and_a_duplicate_code():
    assert status(run(v06_document(code="DRG-TES-PRO-X"))[0], "V02")["status"] == "fail"
    twin = parse_document(v06_document(title="A Different Document"), "A Different Document.docx")
    report, _ = run(others=[twin])
    assert status(report, "V02")["status"] == "fail"           # same code, different document


def test_v23_the_file_name_must_be_the_title_without_status():
    assert status(run(filename="Test Standard Draft.docx")[0], "V23")["status"] == "fail"
    assert status(run(filename="Something Else.docx")[0], "V23")["status"] == "fail"
    assert status(run(filename="Test Standard.docx")[0], "V23")["status"] == "pass"


def test_v15_flags_missing_required_sections_without_blocking():
    r = status(run()[0], "V15")
    assert r["status"] == "flag" and r["enforcement"] == "FLAG"
    assert {f["where"] for f in r["findings"]} == {"section Purpose", "section Roles and Responsibilities"}


def test_v14_is_a_report_not_a_failure():
    b = DocBuilder()
    b.control_block(title="Test Standard", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="o", classification="c")
    b.control("TST-01", "Soft", requirement="Staff should review it.", trigger="t.", responsibility="ISO.",
              evidence="REC-0001.", risk="r.", failure_route="f.", exception_route="e.", mapping="ISO 27001 A.5.1")
    assert status(run(b.bytes())[0], "V14")["status"] == "report"


def test_v12_flags_a_vague_qualifier():
    b = DocBuilder()
    b.control_block(title="Test Standard", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="o", classification="c")
    b.control("TST-01", "Vague", requirement="The ISO shall review access regularly.", trigger="t.",
              responsibility="ISO.", evidence="REC-0001.", risk="r.", failure_route="f.", exception_route="e.",
              mapping="ISO 27001 A.5.1")
    assert status(run(b.bytes())[0], "V12")["status"] == "flag"


# ── robustness ──────────────────────────────────────────────────────────────

def test_a_check_that_crashes_does_not_pass_and_does_not_stop_the_others(monkeypatch):
    def boom(subject):
        raise RuntimeError("kaput")
    monkeypatch.setitem(checks.CHECKS, "V10", boom)
    report, _ = run()
    crashed = status(report, "V10")
    assert crashed["status"] == "could_not_check" and "kaput" in crashed["summary"]
    assert status(report, "V23")["status"] in ("pass", "fail")            # the rest still ran


def test_the_verdict_follows_the_worst_result():
    blocked, _ = run(v06_document(mapping=""))
    assert blocked["verdict"] == "blocked" and "V22" in blocked["headline"]
