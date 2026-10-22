# =============================================================================
# tests/doc_standards/test_v07_roles.py — every role a document names must exist (V07)
#
# Bobby, 22 Oct: a control has one Control owner, stated in the control; a role
# that is not in Org Roles is caught while the document is written, with the
# nearest existing roles suggested.
# =============================================================================

from cdi.library import LibraryIndex
from cdi.parser import parse_document
from doc_standards.checks import Context, run_checks
from doc_standards.roles import Role, RoleBook
from tests.cdi.builders import DocBuilder

BOOK = RoleBook([
    Role("1", "Information Security Officer", ("ISO",)),
    Role("2", "Chief Compliance Officer"),
    Role("3", "Head of IT and Infrastructure"),
])


def standard(*owners, owner="Information Security Officer", first="Chief Compliance Officer", final="Chief Compliance Officer"):
    b = DocBuilder()
    b.control_block(title="Test Standard", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="Information Security",
                    owner=owner, first_pass=first, final_approval=final, classification="Internal")
    for i, who in enumerate(owners, 1):
        b.control(f"TST-0{i}", f"Control {i}", requirement="The role shall act.", trigger="Creation.",
                  evidence="REC-0001.", risk="r.", failure_route="f.", exception_route="e.", mapping="ISO 27001 A.5.1",
                  **{"Control owner": who})
    data = b.bytes()
    return data


def v07(data, roles=BOOK, name="Test Standard.docx"):
    parsed = parse_document(data, name)
    ctx = Context(index=LibraryIndex([parsed]), roles=roles)
    report = run_checks(parsed, name, data, ctx)
    return next(r for r in report["results"] if r["id"] == "V07")


def test_roles_that_exist_pass():
    r = v07(standard("Information Security Officer", "Chief Compliance Officer"))
    assert r["status"] == "pass" and r["enforcement"] == "BLOCK"


def test_a_role_that_does_not_exist_fails_with_the_nearest_existing_role_suggested():
    r = v07(standard("Info Sec Officer"))
    assert r["status"] == "fail"
    finding = next(f for f in r["findings"] if f["data"]["role"] == "Info Sec Officer")
    top = finding["data"]["suggestions"][0]
    assert top["name"] == "Information Security Officer" and top["group_id"] == "1" and top["reason"]
    assert "Did you mean" in finding["fix"] and finding["where"] == "TST-01"


def test_the_same_wrong_role_in_several_controls_is_one_finding_listing_them_all():
    r = v07(standard("Infosec Lead", "Infosec Lead", "Infosec Lead"))
    wrong = [f for f in r["findings"] if f["data"]["role"] == "Infosec Lead"]
    assert len(wrong) == 1 and wrong[0]["data"]["locations"] == ["TST-01", "TST-02", "TST-03"]


def test_a_field_name_is_called_out_as_not_being_a_role():
    for placeholder in ("Control Owner", "Document Owner", "Custodian Role"):
        r = v07(standard(placeholder))
        f = next(f for f in r["findings"] if f["data"]["role"] == placeholder)
        assert f["data"]["placeholder"] and "name of a field" in f["message"] and f["data"]["suggestions"] == []


def test_two_roles_in_one_control_are_reported_because_a_control_has_exactly_one():
    r = v07(standard("Information Security Officer; Head of IT and Infrastructure"))
    f = next(f for f in r["findings"] if f["data"]["several"])
    assert "more than one role" in f["message"] and f["data"]["suggestions"] == []


def test_a_role_whose_name_contains_a_slash_or_and_is_one_role_not_two():
    book = RoleBook([Role("9", "Managing Director / CEO"), Role("3", "Head of IT and Infrastructure")])
    data = standard("Managing Director / CEO", "Head of IT and Infrastructure",
                    owner="Managing Director / CEO", first="Head of IT and Infrastructure", final="Managing Director / CEO")
    assert v07(data, roles=book)["status"] == "pass"


def test_the_cover_owner_and_approvers_are_checked_too():
    r = v07(standard("Information Security Officer", owner="Compliance Lead", first="Mr Smith", final="Chief Compliance Officer"))
    roles = {f["data"]["role"]: f["data"]["kinds"] for f in r["findings"]}
    assert roles["Compliance Lead"] == ["Document owner"] and roles["Mr Smith"] == ["First pass approval"]
    assert "Chief Compliance Officer" not in roles


def test_an_alias_already_agreed_counts_as_the_role():
    assert v07(standard("ISO"))["status"] == "pass"


def test_without_org_roles_the_check_says_it_could_not_run_it_does_not_pass():
    r = v07(standard("Information Security Officer"), roles=None)
    assert r["status"] == "could_not_check" and "Org Roles" in r["summary"]


def test_with_no_roles_created_yet_every_role_is_reported_and_the_note_says_why():
    r = v07(standard("Information Security Officer"), roles=RoleBook())
    assert r["status"] == "fail" and "no roles yet" in r["note"]


def test_a_job_title_is_not_a_role():
    # A title that happens to match a person's Entra title is still not in Org Roles.
    assert v07(standard("Chief Technology Officer"))["status"] == "fail"


def test_the_older_accountable_executing_line_still_names_its_accountable_role_and_is_told_to_move():
    b = DocBuilder()
    b.control_block(title="Test Standard", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="Information Security Officer", classification="c")
    b.control("TST-01", "Old", requirement="The ISO shall.", trigger="t.", responsibility="Information Security Officer; IT owners.",
              evidence="REC-0001.", risk="r.", failure_route="f.", exception_route="e.", mapping="ISO 27001 A.5.1")
    data = b.bytes()
    assert v07(data)["status"] == "pass"                                      # the accountable role is a real role
    parsed = parse_document(data, "Test Standard.docx")
    report = run_checks(parsed, "Test Standard.docx", data, Context(index=LibraryIndex([parsed]), roles=BOOK))
    v08 = next(r for r in report["results"] if r["id"] == "V08")
    assert v08["status"] == "pass" and "Control owner" in v08["note"] and "TST-01" in v08["note"]
