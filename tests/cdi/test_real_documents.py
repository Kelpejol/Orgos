# =============================================================================
# tests/cdi/test_real_documents.py — the parser against Dragnet's documents
#
# Golden tests on the real CDI Standard, CDI Procedure and BCDR Procedure. The
# documents live in docs/ and are not committed, so each test skips where its
# file is absent; the synthetic tests in test_parser.py always run.
# =============================================================================

from collections import Counter
from functools import lru_cache
from pathlib import Path

import pytest

from cdi.library import LibraryIndex
from cdi.model import DocumentRole, FindingKind
from cdi.parser import parse_document

DOCS = Path(__file__).resolve().parents[2] / "docs"
STANDARD = DOCS / "Control of Documented Information Standard.docx"
PROCEDURE = DOCS / "Control of Documented Information Procedure.docx"
BCDR = DOCS / "BCDR Impact, Register and Process Continuity procedure.pdf"


@lru_cache(maxsize=None)
def _parse(path: Path):
    return parse_document(path.read_bytes(), path.name)


def load(path: Path):
    if not path.exists():
        pytest.skip(f"{path.name} is not present")
    return _parse(path)


def test_cdi_standard_defines_all_45_controls_with_all_eight_fields():
    doc = load(STANDARD)
    assert doc.role is DocumentRole.DEFINING
    assert len(doc.controls) == 45
    assert Counter(c.control_id.split("-")[0] for c in doc.controls) == {"CDI": 21, "IRG": 24}
    assert all(not c.missing_fields for c in doc.controls)
    assert not [f for f in doc.findings if f.kind is FindingKind.MAPPING_UNREADABLE]


def test_cdi_001_reads_exactly_as_written():
    c = load(STANDARD).controls[0]
    assert (c.control_id, c.title) == ("CDI-001", "Approved parent, no orphans")
    assert c.trigger == "Creation, submission, reclassification."
    assert (c.responsibility.accountable, c.responsibility.executing) == (
        "Compliance Executive (QMS & NDPA)", "platform check V03")
    assert [r.record_id for r in c.evidence] == ["REC-0623", "REC-0635"]
    assert [m.key for m in c.mapping] == ["ISO 9001 7.5.2", "ISO 27001 7.5.2", "ISO 27001 A.5.1"]


def test_cdi_standard_child_documents_survive_a_tracked_insertion():
    """The Child Documents row is a tracked change; python-docx alone returns it empty."""
    doc = load(STANDARD)
    assert doc.header.child_codes == ["DRG-QI-PRO-IRG", "DRG-QI-REG-RRS", "DRG-QI-REG-RSR"]
    assert doc.findings[0].kind is FindingKind.TRACKED_CHANGES


def test_cdi_procedure_carries_out_twenty_of_the_twenty_one_cdi_controls():
    doc = load(PROCEDURE)
    assert doc.role is DocumentRole.IMPLEMENTING
    assert doc.header.parent_codes == ["DRG-QI-STD-CDI"]
    assert doc.controls == []
    cdi = sorted(i for i in doc.implemented_ids if i.startswith("CDI-"))
    assert len(cdi) == 20 and "CDI-007" not in cdi


def test_bcdr_procedure_from_pdf():
    doc = load(BCDR)
    h = doc.header
    assert doc.role is DocumentRole.IMPLEMENTING
    assert (h.code, h.version, h.effective_date) == ("DRG-ISMS-PRO-BCI", "01", "October 2026")
    assert h.controls_implemented == ["BCDR-01", "BCDR-02", "BCDR-04", "BCDR-05", "BCDR-06"]
    assert [s.key for s in h.standards] == [
        "ISO 27001 A.5.29", "ISO 27001 A.5.30", "ISO 27001 A.5.19", "ISO 27001 A.5.20",
        "ISO 22301 8.2", "ISO 22301 8.3"]
    assert [s.section_number for s in doc.implementations] == ["4.0", "5.0", "6.0", "7.0", "8.0"]
    assert all(s.risk_statements for s in doc.implementations)


def test_bcdr_clause_4_1_is_an_implementation_step_not_a_control():
    """The clause that was extracted as a control, with an owner that didn't resolve."""
    doc = load(BCDR)
    step = doc.implementations[0]
    assert step.control_ids == ["BCDR-01"]
    assert step.clauses[0].number == "4.1"
    assert step.clauses[0].text.startswith("The Accountable Department Head records")
    assert "Accountable Department Head" in [r.role for r in doc.roles]


def test_bcdr_records_link_to_the_controls_that_create_them():
    doc = load(BCDR)
    links = {r.record_id: r.control_ids for r in doc.records}
    assert links["REC-0676"] == ["BCDR-01"]
    assert links["REC-0688"] == ["BCDR-04", "BCDR-05"]   # created at steps 6.8 and 7.4
    assert len(doc.open_parameters) == 7 and all(p.value is None for p in doc.open_parameters)
    assert set(Counter(f.kind for f in doc.findings)) == {FindingKind.OPEN_PARAMETER}


def test_the_cdi_standard_and_procedure_read_together():
    lib = LibraryIndex([load(STANDARD), load(PROCEDURE)])
    assert lib.definition("CDI-001")[0].header.code == "DRG-QI-STD-CDI"
    assert [d.header.code for d, _ in lib.implementations("CDI-001")] == ["DRG-QI-PRO-CDI"]
    unimplemented = {f.finding.location.item for f in lib.findings()
                     if f.finding.kind is FindingKind.DEFINED_NOT_IMPLEMENTED}
    assert "CDI-007" in unimplemented
