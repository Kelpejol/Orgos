# =============================================================================
# tests/doc_standards/test_amendments.py — agreed changes the Procedure does not yet carry
#
# OrgOS may carry a change Dragnet has agreed before the CDI Procedure is
# reissued — but must say so, must never rewrite the Procedure's own data, and
# must stop applying the change once the reissued Procedure already has it.
# =============================================================================

import copy
import json

import doc_standards.checks as checks


def base():
    with open(checks._REFERENCE) as f:
        return json.load(f)


def test_the_control_owner_amendment_replaces_accountable_and_executing_in_annex_c():
    fields = [r["field"] for r in checks.reference()["annex_c_control_fields"]]
    assert "Control owner" in fields
    assert "Accountable role" not in fields and "Executing role or system" not in fields


def test_the_new_row_sits_where_the_old_ones_were_and_is_tagged_as_amended():
    rows = checks.reference()["annex_c_control_fields"]
    original = [r["field"] for r in base()["annex_c_control_fields"]]
    assert [r["field"] for r in rows].index("Control owner") == original.index("Accountable role")
    assert next(r for r in rows if r["field"] == "Control owner")["amended"] == "A1"
    assert len(rows) == len(original) - 1                       # two rows became one


def test_v08_is_reworded_and_says_it_was_amended():
    v08 = next(c for c in checks.reference()["checks"] if c["id"] == "V08")
    assert "a Control owner" in v08["name"] and "accountable and executing" not in v08["name"]
    assert v08["amended"] == "A1" and v08["enforcement"] == "BLOCK"        # only the wording moves


def test_the_procedures_own_data_on_disk_is_never_rewritten():
    assert "Accountable role" in [r["field"] for r in base()["annex_c_control_fields"]]


def test_an_amendment_the_reissued_procedure_already_carries_is_not_applied():
    reissued = copy.deepcopy(base())
    reissued["annex_c_control_fields"] = [r for r in reissued["annex_c_control_fields"]
                                          if r["field"] not in ("Accountable role", "Executing role or system")]
    reissued["annex_c_control_fields"].append({"field": "Control owner", "rule": "(as reissued)", "mandatory": "Yes"})
    out = checks._apply_amendments(reissued)
    assert [a["status"] for a in out["amendments"]] == ["obsolete"]
    assert [r["field"] for r in out["annex_c_control_fields"]].count("Control owner") == 1   # not added twice
    assert next(r for r in out["annex_c_control_fields"] if r["field"] == "Control owner")["rule"] == "(as reissued)"


def test_the_page_is_told_about_applied_amendments_only():
    from doc_standards import service
    view = service.standard_view()
    assert [a["id"] for a in view["amendments"]] == ["A1"] and view["amendments"][0]["status"] == "applied"
