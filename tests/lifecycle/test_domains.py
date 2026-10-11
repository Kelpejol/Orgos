# =============================================================================
# tests/lifecycle/test_domains.py — CDI Annex B reference data
#
# These guard the tables themselves as much as the lookups: a domain with no
# approval route, or a family mapped to something that isn't a real domain,
# would surface as a runtime failure of validation check V05 ("Domain is from
# reference data and the approval route resolves to role holders" — BLOCK)
# rather than as an obvious error, so it's checked here instead.
# =============================================================================

import pytest

from lifecycle.domains import (
    APPROVAL_ROUTES,
    FAMILIES_NEEDING_CONFIRMATION,
    FAMILY_TO_DOMAIN,
    FUNCTION_TO_DOMAIN,
    PARENT_TYPE_OF,
    RETIRED_FUNCTION_CODES,
    TYPE_LAYERS,
    Domain,
    domain_for_family,
    domain_for_function,
    layer_for_type,
    parse_domain,
    route_for,
)


# -----------------------------------------------------------------------------
#  Table completeness — the tables must stay internally consistent
# -----------------------------------------------------------------------------

def test_every_domain_has_an_approval_route():
    """V05 blocks approval if a domain's route doesn't resolve — so every
    domain in the enum must have one, with both roles named."""
    for domain in Domain:
        route = APPROVAL_ROUTES.get(domain)
        assert route is not None, f"{domain.value} has no approval route"
        assert route.first_pass.strip(), f"{domain.value} has a blank First Pass role"
        assert route.final_approval.strip(), f"{domain.value} has a blank Final Approval role"


def test_annex_b_has_exactly_fourteen_domains():
    """Annex B states 'The table is exhaustive'. If this count changes, the
    change must come from controlled change of Annex B, not a code edit."""
    assert len(Domain) == 14


def test_first_pass_and_final_approval_are_different_roles():
    """CDI-010 / V06: 'First Pass and Final Approval MUST be held by different
    roles and different people.' A route that names the same role twice would
    make every document on it unapprovable."""
    for domain, route in APPROVAL_ROUTES.items():
        assert route.first_pass != route.final_approval, (
            f"{domain.value} routes both passes to {route.first_pass}"
        )


def test_chief_technology_officer_is_not_an_approval_role():
    """Annex B says so explicitly, and deliberately — 'this is so its absence
    is not read as an omission' (Procedure 11.12)."""
    named = {r.first_pass for r in APPROVAL_ROUTES.values()} | {
        r.final_approval for r in APPROVAL_ROUTES.values()
    }
    assert not any("technology officer" in role.lower() for role in named)


def test_every_family_maps_to_a_real_domain():
    for family, domain in FAMILY_TO_DOMAIN.items():
        assert isinstance(domain, Domain), f"{family} maps to a non-Domain value"


def test_every_function_code_maps_to_a_real_domain():
    for code, domain in FUNCTION_TO_DOMAIN.items():
        assert isinstance(domain, Domain), f"{code} maps to a non-Domain value"


def test_retired_function_codes_resolve_to_current_ones():
    """A retired code must map to a code that still exists, or recoding a
    legacy document (CDI-016) would produce another invalid code."""
    for retired, current in RETIRED_FUNCTION_CODES.items():
        assert current in FUNCTION_TO_DOMAIN, (
            f"retired {retired} maps to {current}, which is not a current function code"
        )


def test_flagged_families_are_real_and_match_their_provisional_choice():
    """The 'needs confirmation' list must stay in step with the mapping it
    annotates — otherwise a reviewer is warned about the wrong value."""
    for family, (provisional, alternative, reason) in FAMILIES_NEEDING_CONFIRMATION.items():
        assert family in FAMILY_TO_DOMAIN, f"{family} is flagged but not mapped"
        assert FAMILY_TO_DOMAIN[family] == provisional, (
            f"{family} is mapped to {FAMILY_TO_DOMAIN[family].value} but flagged as {provisional.value}"
        )
        assert provisional != alternative
        assert reason.strip(), f"{family} is flagged with no stated reason"


def test_parent_types_reference_real_document_types():
    for child, parents in PARENT_TYPE_OF.items():
        assert child in TYPE_LAYERS
        for parent in parents:
            assert parent in TYPE_LAYERS


# -----------------------------------------------------------------------------
#  parse_domain — tolerant on input, never guesses
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "Information Security",
    "information security",
    "  INFORMATION   SECURITY  ",
])
def test_parse_domain_is_case_and_space_tolerant(raw):
    assert parse_domain(raw) is Domain.INFORMATION_SECURITY


def test_parse_domain_accepts_and_for_ampersand():
    """Existing documents carry hand-typed domains from before this was a
    controlled field, and people type 'and' as often as '&'."""
    assert parse_domain("Quality and Compliance") is Domain.QUALITY_COMPLIANCE
    assert parse_domain("Quality & Compliance") is Domain.QUALITY_COMPLIANCE


@pytest.mark.parametrize("raw", ["", None, "   ", "Something Invented", "ISMS"])
def test_parse_domain_returns_none_rather_than_guessing(raw):
    """Procedure 11.2: a document that cannot be placed in an Annex B domain
    'is not approved until its domain is assigned'. Silently defaulting would
    route it to the wrong approver. Note 'ISMS' is a FUNCTION code, not a
    domain — it must not resolve here."""
    assert parse_domain(raw) is None


# -----------------------------------------------------------------------------
#  route_for
# -----------------------------------------------------------------------------

def test_route_for_accepts_enum_or_text():
    by_enum = route_for(Domain.INFORMATION_SECURITY)
    by_text = route_for("Information Security")
    assert by_enum == by_text
    assert by_enum.first_pass == "Information Security Officer"
    assert by_enum.final_approval == "Chief Compliance Officer"


def test_route_for_unresolvable_domain_is_none():
    assert route_for("Not A Domain") is None
    assert route_for(None) is None


def test_revenue_and_sales_routes_to_cro_then_cco():
    """Procedure 11.1.1 singles this route out explicitly."""
    route = route_for(Domain.REVENUE_SALES)
    assert route.first_pass == "Chief Revenue Officer"
    assert route.final_approval == "Chief Compliance Officer"


# -----------------------------------------------------------------------------
#  Function code → domain
# -----------------------------------------------------------------------------

def test_function_code_maps_to_default_domain():
    assert domain_for_function("ISMS") is Domain.INFORMATION_SECURITY
    assert domain_for_function("hr") is Domain.HUMAN_RESOURCES


def test_retired_function_code_maps_through_to_successor_domain():
    """TES/VER/REC/CX all collapsed into OPS → Service Delivery & Operations."""
    assert domain_for_function("TES") is Domain.SERVICE_DELIVERY_OPERATIONS
    assert domain_for_function("CLE") is Domain.SERVICE_DELIVERY_OPERATIONS
    assert domain_for_function("QMS") is Domain.QUALITY_COMPLIANCE


def test_unknown_function_code_is_none():
    assert domain_for_function("ZZZ") is None
    assert domain_for_function("") is None


def test_devops_is_deliberately_unmapped():
    """Annex B splits DEVOPS by subject matter ('ISMS where the subject is
    cloud operation; SD where it is the software delivery pipeline'), so it
    cannot be resolved mechanically and must not be guessed."""
    assert "DEVOPS" not in RETIRED_FUNCTION_CODES
    assert domain_for_function("DEVOPS") is None


# -----------------------------------------------------------------------------
#  Family folder → domain
# -----------------------------------------------------------------------------

def test_several_families_share_one_domain():
    """Procedure 5.2: 'Several families may share one Primary Domain.' This is
    the reason a folder path can never BE the domain."""
    shared = [
        "Access Control",
        "Cryptography & Key Management",
        "Vulnerability Management",
        "Business Continuity & Disaster Recovery",
    ]
    assert all(domain_for_family(f) is Domain.INFORMATION_SECURITY for f in shared)


def test_cdi_family_folder_maps_to_quality_and_compliance():
    """Checked against the real documents: the CDI Policy/Standard/Procedure
    live in the 'Control of Documented Information & Records Governance'
    folder but their control blocks all state Domain: Quality & Compliance."""
    folder = "Control of Documented Information & Records Governance"
    assert domain_for_family(folder) is Domain.QUALITY_COMPLIANCE


def test_unknown_family_is_none():
    assert domain_for_family("00 WORK IN PROGRESS") is None
    assert domain_for_family(None) is None


# -----------------------------------------------------------------------------
#  Document type → layer
# -----------------------------------------------------------------------------

def test_layer_for_type():
    assert layer_for_type("PRO") == "Procedure (Layer 4)"
    assert layer_for_type("std") == "Standard (Layer 3)"
    assert layer_for_type("MAN") == "Manual (Companion to Layer 1)"


def test_policy_layer_is_left_unresolved():
    """Annex B gives POL as 'Layer 1 or 2' — Master vs Domain Policy. The
    distinction is real and must be confirmed, not guessed."""
    assert layer_for_type("POL") == "Policy"
    assert "Layer" not in layer_for_type("POL")


def test_unknown_type_is_none():
    assert layer_for_type("XXX") is None
    assert layer_for_type(None) is None
