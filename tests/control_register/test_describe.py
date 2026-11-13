# A control is described by what it requires and the name of its document, not by codes.
import json

from control_register.describe import by_control_id, describe, for_record, short_name

REQ = ("Compliance runs the internal and external context analysis as a scheduled, owned activity. "
       "Results go to ExCo.")


def _row(**definition):
    base = {"control_id": "ICX-001", "title": "", "requirement": REQ, "trigger": "Every quarter",
            "defined_in": {"code": "DRG-QI-PRO-ICX", "title": "Internal and External Issues and Strategic Context Procedure"}}
    return {"fields": {"ControlId": "ICX-001", "DefinitionJson": json.dumps({**base, **definition})}}


def test_a_control_without_a_title_is_named_by_its_requirement_and_its_document_by_name():
    d = describe(_row()["fields"])
    assert d["ControlName"] == "Compliance runs the internal and external context analysis as a scheduled, owned activity"
    assert d["ControlSummary"] == REQ
    assert d["ControlDocument"] == "Internal and External Issues and Strategic Context Procedure"
    assert d["ControlId"] == "ICX-001" and d["ControlDocumentCode"] == "DRG-QI-PRO-ICX"
    assert d["ControlTrigger"] == "Every quarter"


def test_a_stated_title_is_the_name():
    assert describe(_row(title="Context analysis")["fields"])["ControlName"] == "Context analysis"


def test_a_long_requirement_is_cut_at_a_word():
    name = short_name("word " * 60)
    assert name.endswith("…") and len(name) <= 121 and not name.endswith(" …")


def test_an_older_control_without_a_definition_still_reads():
    d = describe({"ControlId": "X-1", "ControlStatement": "Backups are tested monthly.", "SourceDocument": "DRG-IT-PRO-BKP"})
    assert d["ControlName"] == "Backups are tested monthly" and d["ControlDocument"] == "DRG-IT-PRO-BKP"


def test_records_find_their_control():
    controls = by_control_id([_row()])
    assert for_record({"LinkedControlId": "ICX-001"}, controls)["ControlDocument"].startswith("Internal")
    assert for_record({"LinkedControlId": "NOPE"}, controls) is None


async def test_listed_records_carry_their_control_in_words():
    from unittest.mock import AsyncMock, patch
    from auth.validator import CurrentUser
    from config import settings
    import record_tracker.router as rt

    record = {"id": "5", "fields": {"ObligationKey": "ICX-001|REC-0001", "LinkedControlId": "ICX-001",
                                    "EvidenceDescription": "Context Analysis Record", "OwnerRole": "Compliance"}}

    async def items(list_id, name, *a, **k):
        return [_row()] if name == "Control Register" else [record]

    with patch.object(rt, "get_list_items", new=AsyncMock(side_effect=items)), \
         patch("ownership.resolver.get_ownership_index", new=AsyncMock(side_effect=RuntimeError("offline"))), \
         patch.object(type(settings), "is_list_configured", lambda self, v: True):
        out = await rt.list_records(user=CurrentUser(oid="o", name="n", email="e", tenant_id="t", roles=[]))
    assert out[0]["ControlName"].startswith("Compliance runs") and out[0]["ControlDocument"].startswith("Internal")
