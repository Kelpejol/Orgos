

def test_a_missing_control_owner_blocks_with_a_message_that_names_it():
    from control_register.definitions import decide_status
    status, why = decide_status({"accountable": "", "control_owner": True}, lambda r: {})
    assert status == "Blocked" and "Control owner" in why


def test_a_field_name_in_the_role_slot_says_so_instead_of_blaming_org_roles():
    from control_register.definitions import decide_status
    for placeholder in ("Control Owner", "Document Owner", "Custodian Role"):
        status, why = decide_status({"accountable": placeholder, "control_owner": True}, lambda r: {})
        assert status == "Blocked" and "name of a field" in why and "Org Roles" in why
