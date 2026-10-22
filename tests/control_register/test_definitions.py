

def test_a_missing_control_owner_blocks_with_a_message_that_names_it():
    from control_register.definitions import decide_status
    status, why = decide_status({"accountable": "", "control_owner": True}, lambda r: {})
    assert status == "Blocked" and "Control owner" in why
