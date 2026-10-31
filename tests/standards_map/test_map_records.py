# =============================================================================
# tests/standards_map/test_map_records.py — the map counts the right records, by their real state
#
# A defined control's records are linked by its Control ID; the light follows each
# record's computed state (Late, Missing… turn it Red); a withdrawn control covers nothing.
# =============================================================================

from datetime import date, timedelta

from standards_map.router import _calculate_traffic_light, _controls_for, _records_for, record_state


class Owners:
    def has_owner(self, role):
        return True


CONTROL = {"id": "41", "ControlId": "ACS-L3-01", "Status": "Active", "OwnerRole": "ISO"}


def obligation(**kw):
    today = date.today()
    return {"ObligationKey": "ACS-L3-01|REC-0691", "LinkedControlId": "ACS-L3-01", "Status": "Pending",
            "CheckFrequencyDays": 30, "ScheduledFrom": (today - timedelta(days=10)).isoformat(), **kw}


def test_a_defined_controls_records_are_found_by_its_control_id():
    by_control = {"ACS-L3-01": [obligation()], "41": [{"Status": "Accepted"}]}
    assert len(_records_for(CONTROL, by_control)) == 2


def test_a_late_record_turns_the_clause_red():
    late = obligation(ScheduledFrom=(date.today() - timedelta(days=90)).isoformat())
    assert record_state(late) == "Missing"
    assert _calculate_traffic_light([CONTROL], [late], Owners()) == "Red"


def test_a_record_awaiting_its_first_copy_is_amber_and_a_current_one_green():
    assert _calculate_traffic_light([CONTROL], [obligation()], Owners()) == "Amber"
    current = obligation(Status="Accepted", LastRecordDate=date.today().isoformat())
    assert record_state(current) == "Current"
    assert _calculate_traffic_light([CONTROL], [current], Owners()) == "Green"


def test_an_older_record_past_its_due_date_is_late():
    assert record_state({"Status": "Pending", "DueDate": "2020-01-01"}) == "Late"


def test_a_withdrawn_control_covers_nothing():
    class Row:
        pass
    withdrawn = {**CONTROL, "Status": "Withdrawn", "_refs": ["x"]}
    import standards_map.router as m
    orig = m.catalogue.covers
    m.catalogue.covers = lambda row, ref: True
    try:
        assert _controls_for(Row(), [withdrawn]) == []
    finally:
        m.catalogue.covers = orig
    assert _calculate_traffic_light([withdrawn], [], Owners()) == "Red"
