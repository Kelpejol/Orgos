# =============================================================================
# tests/cdi/test_real_library.py — the parser against the whole Control Library
#
# Runs over the local copy that `scripts/cdi_library_census.py --save
# .cdi_corpus` makes, and pins what the real library says — so a change that
# breaks a real document fails here rather than in production. The copy is
# not committed (company documents); without it these tests skip.
# =============================================================================

from collections import Counter
from pathlib import Path

import pytest

from cdi.library import LibraryIndex
from cdi.model import DocumentRole, FindingKind, Severity
from cdi.parser import parse_document

CORPUS = Path(__file__).resolve().parents[2] / ".cdi_corpus"

pytestmark = pytest.mark.skipif(
    not CORPUS.exists(), reason="no local copy of the Control Library (.cdi_corpus)"
)


@pytest.fixture(scope="module")
def library():
    docs = [
        parse_document(p.read_bytes(), p.name)
        for p in sorted(CORPUS.rglob("*"))
        if p.suffix.lower() in {".docx", ".pdf"} and not p.name.startswith("~$")
    ]
    return docs, LibraryIndex(docs)


def defined_by(lib, cid):
    found = lib.definition(cid)
    return found[0].header.code if found else None


def test_nearly_all_of_the_library_reads_from_structure(library):
    docs, _ = library
    unstructured = [d.filename for d in docs if d.role is DocumentRole.UNSTRUCTURED]
    assert len(unstructured) <= 0.05 * len(docs), unstructured


def test_each_layout_resolves_to_its_standard(library):
    _, lib = library
    assert defined_by(lib, "CDI-001") == "DRG-QI-STD-CDI"      # labelled block
    assert defined_by(lib, "APPSEC-01") == "DRG-ISMS-STD-APPSEC"  # row table
    assert defined_by(lib, "ACS-L3-01") == "DRG-ISMS-STD-IDL"  # block, unlabelled requirement
    assert defined_by(lib, "BCDR-01") == "DRG-ISMS-STD-BCDR"
    assert defined_by(lib, "EVT-C01") == "DRG-QI-STD-INC"      # ID-only heading
    assert defined_by(lib, "CM-01") == "DRG-ISMS-STD-CHG"      # sub-headings inside the control


def test_no_two_standards_claim_the_same_control(library):
    _, lib = library
    errors = [f for f in lib.findings()
              if f.finding.kind is FindingKind.DEFINED_TWICE and f.finding.severity is Severity.ERROR]
    assert errors == []


def test_procedures_still_citing_the_retired_dp_002_are_reported(library):
    _, lib = library
    undefined = {f.document for f in lib.findings()
                 if f.finding.kind is FindingKind.IMPLEMENTS_UNDEFINED and "DP-002" in f.finding.message}
    # Two cite it directly; the Operations Procedure's "Implements DP-001 to
    # DP-046" covers it by range.
    assert undefined == {"DRG-QI-PRO-PDD", "DRG-QI-PRO-PGA",
                         "03 Data Protection Operations Procedure - Production Candidate.docx"}


def test_edited_copies_of_the_it_standard_are_reported_and_summaries_are_not(library):
    _, lib = library
    drift = Counter(f.finding.kind for f in lib.findings())[FindingKind.RESTATEMENT_DIFFERS]
    assert 1 <= drift <= 10      # the IT near-copies, not the Access Control summaries
    assert any(f.document == "DRG-IT-PRO-SRS" and "IT-01" in f.finding.message
               for f in lib.findings() if f.finding.kind is FindingKind.RESTATEMENT_DIFFERS)
