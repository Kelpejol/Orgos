# =============================================================================
# tests/control_register/test_resolutions.py — Zone 2: references that don't
# resolve. One item per problem; closed by the sync once fixed; never raised
# twice while a person is dealing with it.
# =============================================================================

from cdi.library import LibraryIndex
from cdi.parser import parse_document
from control_register.sync import plan_resolutions, plan_sync, queue_fields
from records_catalogue.model import RecordEntry
from tests.cdi.builders import DocBuilder

GOVERNED = RecordEntry("REC-0001", "Change log", admission_status="Governed Record")
WITHDRAWN = RecordEntry("REC-0670", "Old proposal", admission_status="Withdrawn duplicate proposal")


def standard(code, evidence="REC-0001 Change log.", cid="TST-01"):
    b = DocBuilder()
    b.control_block(title="Test Standard", code=code, owner="CTO", layer="Layer 3")
    b.control(cid, "Change logging", requirement="The CTO shall log.", trigger="A change.",
              responsibility="CTO.", evidence=evidence)
    return parse_document(b.bytes(), f"{code}.docx")


def as_queue(actions, status="Pending Review"):
    return [{"id": str(n), "fields": {**queue_fields(a), "ReviewStatus": status}}
            for n, a in enumerate(actions, start=10)]


def test_a_record_missing_from_the_catalogue_is_one_item_listing_every_citing_document():
    index = LibraryIndex([standard("DRG-ISMS-STD-AAA", "REC-0999 Lost log."),
                          standard("DRG-ISMS-STD-BBB", "REC-0999 Lost log.", cid="TST-02")])
    [action] = plan_resolutions(index, [], {"REC-0001": GOVERNED})
    f = action.fields
    assert (f["ResolutionKey"], f["OrphanClassification"]) == ("RECORD:REC-0999", "RECORD_NOT_IN_CATALOGUE")
    assert f["ItemType"] == "Orphan"
    assert f["OrphanReason"] == "Cited in: DRG-ISMS-STD-AAA; DRG-ISMS-STD-BBB"


def test_citing_a_withdrawn_duplicate_is_raised():
    index = LibraryIndex([standard("DRG-ISMS-STD-AAA", "REC-0670 Old.")])
    [action] = plan_resolutions(index, [], {"REC-0670": WITHDRAWN})
    assert action.fields["OrphanClassification"] == "WITHDRAWN_RECORD_CITED"


def test_governed_records_raise_nothing_and_no_catalogue_skips_the_check():
    index = LibraryIndex([standard("DRG-ISMS-STD-AAA")])
    assert plan_resolutions(index, [], {"REC-0001": GOVERNED}) == []
    assert plan_resolutions(LibraryIndex([standard("DRG-ISMS-STD-AAA", "REC-0999 X.")]), [], None) == []


def test_an_item_is_not_raised_again_while_waiting_or_after_a_decision():
    index = LibraryIndex([standard("DRG-ISMS-STD-AAA", "REC-0999 Lost log.")])
    first = plan_resolutions(index, [], {})
    for status in ("Pending Review", "Accepted", "Rejected", "Intentional"):
        assert plan_resolutions(index, as_queue(first, status), {}) == [], status


def test_the_item_closes_itself_once_the_record_is_admitted():
    index = LibraryIndex([standard("DRG-ISMS-STD-AAA", "REC-0999 Lost log.")])
    queue = as_queue(plan_resolutions(index, [], {}))
    admitted = {"REC-0999": RecordEntry("REC-0999", "Lost log", admission_status="Governed Record")}
    [close] = plan_resolutions(index, queue, admitted)
    assert (close.kind, close.queue_item_id) == ("close_item", "10")


def test_a_control_defined_twice_is_raised_and_kept_apart_from_its_definition_item():
    index = LibraryIndex([standard("DRG-ISMS-STD-AAA"), standard("DRG-ISMS-STD-BBB")])
    [action] = plan_resolutions(index, [], {"REC-0001": GOVERNED})
    assert action.fields["OrphanClassification"] == "CONTROL_DEFINED_TWICE"
    assert "DRG-ISMS-STD-AAA and DRG-ISMS-STD-BBB" in action.fields["ResponsibilityStatement"]

    # Once one document drops it, the definition is synced as a NEW Zone 1
    # item — the waiting conflict item is closed, not overwritten.
    resolved = LibraryIndex([standard("DRG-ISMS-STD-AAA")])
    queue = as_queue([action])
    assert [(a.kind, a.control_id) for a in plan_sync(resolved, [], queue).actions] == [
        ("create_item", "TST-01")]
    assert [a.kind for a in plan_resolutions(resolved, queue, {"REC-0001": GOVERNED})] == ["close_item"]


def test_a_procedure_citing_a_control_nobody_defines_is_raised_for_revision():
    from tests.cdi.builders import implementing_procedure
    index = LibraryIndex([parse_document(implementing_procedure().bytes(), "pro.docx")])
    keys = sorted(a.fields["ResolutionKey"] for a in plan_resolutions(index, [], None))
    assert keys == ["CITES-UNDEFINED:DRG-ISMS-PRO-TST:TST-01", "CITES-UNDEFINED:DRG-ISMS-PRO-TST:TST-02"]
    assert {a.fields["OrphanClassification"] for a in plan_resolutions(index, [], None)} == {
        "CITES_UNDEFINED_CONTROL"}
