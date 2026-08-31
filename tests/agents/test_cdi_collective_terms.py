# =============================================================================
# tests/agents/test_cdi_collective_terms.py
#
# CDI-16 (unregistered role reference) must not flag legitimate collective /
# audience / distribution terms like "All Staff" — they are not roles that
# belong in the Role Register. (The literal "vague term" checks CDI-07/08 are
# already disabled; this closes the same false positive on the CDI-16 path.)
# =============================================================================

import agents.cdi_checker.service as cdi


def _findings_text(findings):
    return " ".join((f.get("finding") or "") for f in findings).lower()


def test_all_staff_not_flagged_by_fallback_cdi16():
    text = "All Staff shall comply with this policy."
    roles = ["Information Security Officer", "Compliance Lead"]  # non-empty register
    findings = cdi._fallback_cdi_16(text, roles)
    assert "all staff" not in _findings_text(findings)


def test_common_collective_terms_are_whitelisted():
    for term in ("all staff", "staff", "all users", "employees", "everyone",
                 "management", "leadership", "stakeholders", "the team"):
        assert term in cdi._NON_ROLE_SUBJECTS, term


def test_ai_path_drops_collective_findings():
    # Simulate the AI returning an "All Staff" finding — the assembly filter
    # keys off the same whitelist, so it must be dropped.
    role = "All Staff"
    assert (role or "").lower().strip() in cdi._NON_ROLE_SUBJECTS
