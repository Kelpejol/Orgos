# =============================================================================
# lifecycle/domains.py — CDI reference data: domains, approval routes, layers
#
# Source of truth: Control of Documented Information Procedure, Annex B
# ("Reference Data", owned by the Chief Compliance Officer and changed only by
# controlled change of that Annex). This module mirrors those tables so the
# platform can enforce them — it does not invent any value.
#
# WHY THIS EXISTS — the governing rule from CDI Procedure 11.1:
#   "Approval authority follows the domain, not the layer. Every governing
#    document has one Primary Domain... Domain, function code and approval
#    route are separate fields."
# and validation check V05: "Domain is from reference data and the approval
# route resolves to role holders" (enforcement: BLOCK).
#
# Before this module, `domain` was free text printed on the cover page and read
# by nothing. These tables make it a real, validated field that resolves an
# approval route.
#
# This module is pure data + pure functions. No I/O, no AI, no SharePoint.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Domain(str, Enum):
    """
    The 14 Primary Domains. CDI Procedure Annex B, "Domains and approval
    routes" — the Annex states "The table is exhaustive", so this enum is
    closed: a document that cannot be placed in one of these is not approved
    until its domain is assigned (Procedure 11.2).
    """

    MASTER_GOVERNANCE = "Master Governance"
    QUALITY_COMPLIANCE = "Quality & Compliance"
    INFORMATION_SECURITY = "Information Security"
    DATA_PROTECTION_PRIVACY = "Data Protection & Privacy"
    IT_INFRASTRUCTURE = "IT & Infrastructure"
    SOFTWARE_PRODUCT_DEVELOPMENT = "Software & Product Development"
    AI_GOVERNANCE = "AI Governance"
    SERVICE_DELIVERY_OPERATIONS = "Service Delivery & Operations"
    CLIENT_ENGAGEMENT = "Client Engagement"
    MARKETING_COMMUNICATIONS = "Marketing & Communications"
    REVENUE_SALES = "Revenue & Sales"
    FINANCE_ADMINISTRATION = "Finance & Administration"
    HUMAN_RESOURCES = "Human Resources"
    LEGAL_CORPORATE_GOVERNANCE = "Legal & Corporate Governance"


@dataclass(frozen=True)
class ApprovalRoute:
    """The two approval roles a domain resolves to. Both are ROLE titles."""

    first_pass: str
    final_approval: str


# CDI Procedure Annex B, "Domains and approval routes". Verbatim.
# Note the Annex's own closing qualifiers, enforced by callers, not here:
#   • "The Chief Technology Officer is not an approval-route role."
#   • "A route role must exist in the Role Register before a document can
#      pass V05."
APPROVAL_ROUTES: dict[Domain, ApprovalRoute] = {
    Domain.MASTER_GOVERNANCE:            ApprovalRoute("Chief Compliance Officer", "Managing Director / CEO"),
    Domain.QUALITY_COMPLIANCE:           ApprovalRoute("Chief Compliance Officer", "Managing Director / CEO"),
    Domain.INFORMATION_SECURITY:         ApprovalRoute("Information Security Officer", "Chief Compliance Officer"),
    Domain.DATA_PROTECTION_PRIVACY:      ApprovalRoute("Chief Compliance Officer", "Managing Director / CEO"),
    Domain.IT_INFRASTRUCTURE:            ApprovalRoute("Head of IT and Infrastructure", "Chief Compliance Officer"),
    Domain.SOFTWARE_PRODUCT_DEVELOPMENT: ApprovalRoute("Head of Products and Software Development", "Chief Compliance Officer"),
    Domain.AI_GOVERNANCE:                ApprovalRoute("Information Security Officer", "Chief Compliance Officer"),
    Domain.SERVICE_DELIVERY_OPERATIONS:  ApprovalRoute("Chief Operating Officer", "Chief Compliance Officer"),
    Domain.CLIENT_ENGAGEMENT:            ApprovalRoute("Chief Business Officer", "Chief Compliance Officer"),
    Domain.MARKETING_COMMUNICATIONS:     ApprovalRoute("Chief Business Officer", "Chief Compliance Officer"),
    Domain.REVENUE_SALES:                ApprovalRoute("Chief Revenue Officer", "Chief Compliance Officer"),
    Domain.FINANCE_ADMINISTRATION:       ApprovalRoute("Chief Compliance Officer", "Managing Director / CEO"),
    Domain.HUMAN_RESOURCES:              ApprovalRoute("Chief Compliance Officer", "Managing Director / CEO"),
    Domain.LEGAL_CORPORATE_GOVERNANCE:   ApprovalRoute("Chief Compliance Officer", "Managing Director / CEO"),
}


# =============================================================================
#  Function code → default domain
# =============================================================================
# CDI Procedure Annex B, "Function codes" (9 codes). These REPLACE the older
# 11-code department list the platform used (TES/VER/REC/CX/EX etc.), which the
# Annex retires — see RETIRED_FUNCTION_CODES below.
#
# IMPORTANT — this is a DEFAULT, not an authority. CDI-017: "Domain, function
# code and approval route are separate fields; the domain decides the route."
# Procedure 6.4 gives the explicit counter-example: a document whose functional
# origin is data protection takes function code QI but Primary Domain
# Data Protection & Privacy. So a suggestion built from the function code is
# always overridable by a stronger signal (parent, or regulated subject matter).

FUNCTION_CODES: dict[str, str] = {
    "ISMS": "Information security, including cloud, access, cryptography and continuity",
    "QI":   "Integrated quality and compliance, including governance, risk, incident, "
            "nonconformity, legal, context and data protection",
    "SD":   "Software and product development",
    "IT":   "IT and infrastructure",
    "FIN":  "Finance and administration",
    "HR":   "Human resources",
    "OPS":  "Service delivery operations: testing, verification, recruitment, scholarship, "
            "candidate experience, customer success and client engagement",
    "MKT":  "Marketing, brand and communications",
    "SAL":  "Revenue and Sales",
}

FUNCTION_TO_DOMAIN: dict[str, Domain] = {
    "ISMS": Domain.INFORMATION_SECURITY,
    "QI":   Domain.QUALITY_COMPLIANCE,
    "SD":   Domain.SOFTWARE_PRODUCT_DEVELOPMENT,
    "IT":   Domain.IT_INFRASTRUCTURE,
    "FIN":  Domain.FINANCE_ADMINISTRATION,
    "HR":   Domain.HUMAN_RESOURCES,
    "OPS":  Domain.SERVICE_DELIVERY_OPERATIONS,
    "MKT":  Domain.MARKETING_COMMUNICATIONS,
    "SAL":  Domain.REVENUE_SALES,
}

# CDI Procedure Annex B, "Function code map (retired to current)". A document
# carrying one of these is recoded at its next revision (CDI-016/CDI-017) and
# the old code kept in the Legacy Code field. DEVOPS is deliberately absent:
# the Annex splits it by subject ("ISMS where the subject is cloud operation;
# SD where it is the software delivery pipeline"), so it cannot be mapped
# mechanically and must be decided per document.
RETIRED_FUNCTION_CODES: dict[str, str] = {
    "TES": "OPS", "SCH": "OPS", "REC": "OPS", "CUS": "OPS",
    "VER": "OPS", "CAE": "OPS", "CLE": "OPS", "PROM": "OPS",
    "DPR": "QI",        # with Primary Domain Data Protection & Privacy
    "QMS": "QI", "QA": "QI",
    "ISM": "ISMS", "DCE": "ISMS",
    "PD": "SD", "TD": "SD", "SEC": "SD", "AI": "SD",
    "LEGAL": "QI", "POLICY": "QI",
}


# =============================================================================
#  Document type → layer
# =============================================================================
# CDI Procedure Annex B, "Document types" / CDI Standard 4.0 Table 3 (the two
# agree exactly). Fills the cover's "Document Type / Layer" cell.
#
# Note: POL is deliberately ambiguous in the source ("Layer 1 or 2") — a Master
# Policy is Layer 1, a Domain Policy is Layer 2 — so it is not resolved here.
# Callers treat POL as needing confirmation rather than guessing.

TYPE_LAYERS: dict[str, str] = {
    "POL":  "Policy",                 # Layer 1 (Master) or Layer 2 (Domain) — see note
    "STD":  "Standard (Layer 3)",
    "PRO":  "Procedure (Layer 4)",
    "SPEC": "Specification (Layer 4)",
    "MAN":  "Manual (Companion to Layer 1)",
    "GDL":  "Guideline (Supporting)",
    "PBK":  "Playbook (Supporting)",
    "CHK":  "Checklist (Supporting)",
    "FM":   "Form or Template (Supporting)",
    "REG":  "Register (Supporting)",
}

# The layer above each governing layer — used to find a document's parent.
# CDI Procedure 5.5: "Every Standard is authorised by a Domain Policy; every
# Domain Policy by the Master Policy; every Procedure and Specification names
# its parent Standard, or its parent Policy where no Standard is required."
PARENT_TYPE_OF: dict[str, tuple[str, ...]] = {
    "PRO":  ("STD", "POL"),   # Standard, falling back to Policy where no Standard exists
    "SPEC": ("STD", "POL"),
    "STD":  ("POL",),
    "POL":  ("POL",),         # a Domain Policy's parent is the Master Policy
}


# =============================================================================
#  SharePoint family folder → domain
# =============================================================================
# The compliance library is organised by CONTROL FAMILY, not by domain — there
# are 24 family folders against 14 domains, and several families share one
# domain (CDI Procedure 5.2: "Several families may share one Primary Domain and
# its approval route"; Annex B: "Business Continuity sits within Information
# Security"). So a folder path is a HINT, never the answer.
#
# ⚠ STATUS: DRAFT — awaiting Chief Compliance Officer confirmation.
# Annex B reference data is owned by the CCO and changed only by controlled
# change. This table was derived by mapping each family to the domain its
# subject matter is accountable to; the entries flagged below are genuinely
# ambiguous and were given a provisional value so the platform is usable, but
# they must be confirmed before this is treated as authoritative.

FAMILY_TO_DOMAIN: dict[str, Domain] = {
    # Unambiguous — the family maps to exactly one domain.
    "Access Control":                                        Domain.INFORMATION_SECURITY,
    "AI Governance":                                         Domain.AI_GOVERNANCE,
    "Assurance & Continual Improvement":                     Domain.QUALITY_COMPLIANCE,
    "Business Continuity & Disaster Recovery":               Domain.INFORMATION_SECURITY,
    "Context & Interested Parties":                          Domain.QUALITY_COMPLIANCE,
    "Control of Documented Information & Records Governance": Domain.QUALITY_COMPLIANCE,
    "Cryptography & Key Management":                          Domain.INFORMATION_SECURITY,
    "Data Protection & Privacy":                              Domain.DATA_PROTECTION_PRIVACY,
    "Finance & Administration":                               Domain.FINANCE_ADMINISTRATION,
    "HR People Governance":                                   Domain.HUMAN_RESOURCES,
    "Incident, Nonconformity & Corrective Action Management": Domain.QUALITY_COMPLIANCE,
    "Information Technology":                                 Domain.IT_INFRASTRUCTURE,
    "Information Use, Handling & Communication Governance":   Domain.INFORMATION_SECURITY,
    "Legal & Corporate Governance":                           Domain.LEGAL_CORPORATE_GOVERNANCE,
    "Marketing & Communications":                             Domain.MARKETING_COMMUNICATIONS,
    "Product & Software Development":                         Domain.SOFTWARE_PRODUCT_DEVELOPMENT,
    "Revenue & Sales":                                        Domain.REVENUE_SALES,
    "Risk & Opportunity Management":                          Domain.QUALITY_COMPLIANCE,
    "Vulnerability Management":                               Domain.INFORMATION_SECURITY,

    # ⚠ PROVISIONAL — see FAMILIES_NEEDING_CONFIRMATION for why each is open.
    "Cloud Governance":                                       Domain.INFORMATION_SECURITY,
    "Change Management":                                      Domain.IT_INFRASTRUCTURE,
    "Quality & Service Delivery":                             Domain.QUALITY_COMPLIANCE,
    "Statement of Applicability":                             Domain.INFORMATION_SECURITY,
    "Third Party & External Provider":                        Domain.LEGAL_CORPORATE_GOVERNANCE,
}

# Families whose mapping above is a provisional engineering judgement, not a
# governance decision. A suggestion resolved from one of these is returned with
# reduced confidence so the reviewer is told to check it rather than nodding it
# through. Each entry: (provisional choice, the credible alternative, why).
FAMILIES_NEEDING_CONFIRMATION: dict[str, tuple[Domain, Domain, str]] = {
    "Cloud Governance": (
        Domain.INFORMATION_SECURITY, Domain.IT_INFRASTRUCTURE,
        "Annex B retires DCE (cloud and access) to ISMS, which points at Information "
        "Security; but cloud platform operation could equally sit with IT & Infrastructure.",
    ),
    "Change Management": (
        Domain.IT_INFRASTRUCTURE, Domain.QUALITY_COMPLIANCE,
        "Technical change control points at IT & Infrastructure; management-system "
        "change control points at Quality & Compliance.",
    ),
    "Quality & Service Delivery": (
        Domain.QUALITY_COMPLIANCE, Domain.SERVICE_DELIVERY_OPERATIONS,
        "The family name spans two domains that have DIFFERENT approval routes "
        "(CCO→MD/CEO vs COO→CCO), so this choice changes who signs.",
    ),
    "Statement of Applicability": (
        Domain.INFORMATION_SECURITY, Domain.QUALITY_COMPLIANCE,
        "The SoA is an ISO 27001 artefact (Information Security) but is a management-"
        "system control document (Quality & Compliance).",
    ),
    "Third Party & External Provider": (
        Domain.LEGAL_CORPORATE_GOVERNANCE, Domain.QUALITY_COMPLIANCE,
        "Supplier contracts sit with Legal & Corporate Governance; supplier "
        "performance and assurance sit with Quality & Compliance.",
    ),
}


# =============================================================================
#  Lookups
# =============================================================================

def parse_domain(value: str | None) -> Domain | None:
    """
    Resolve free text to a canonical Domain, tolerantly (case and spacing
    insensitive, and accepting 'and' for '&'). Returns None when it does not
    resolve — callers treat that as "unassigned", never as a silent default.

    Tolerant because existing documents carry hand-typed domain text from
    before this was a controlled field.
    """
    if not value:
        return None
    normalised = " ".join(value.strip().lower().replace("&", "and").split())
    for domain in Domain:
        if " ".join(domain.value.lower().replace("&", "and").split()) == normalised:
            return domain
    return None


def route_for(domain: Domain | str | None) -> ApprovalRoute | None:
    """The approval route a domain resolves to, or None if it does not resolve."""
    resolved = domain if isinstance(domain, Domain) else parse_domain(domain)
    return APPROVAL_ROUTES.get(resolved) if resolved else None


def domain_for_function(function_code: str | None) -> Domain | None:
    """
    Default domain for a function code, mapping a retired code through to its
    successor first. A DEFAULT only — see FUNCTION_TO_DOMAIN's note.
    """
    if not function_code:
        return None
    code = function_code.strip().upper()
    code = RETIRED_FUNCTION_CODES.get(code, code)
    return FUNCTION_TO_DOMAIN.get(code)


def domain_for_family(family_folder: str | None) -> Domain | None:
    """Domain hinted by a SharePoint family folder name. A HINT only."""
    if not family_folder:
        return None
    target = " ".join(family_folder.strip().lower().replace("&", "and").split())
    for family, domain in FAMILY_TO_DOMAIN.items():
        if " ".join(family.lower().replace("&", "and").split()) == target:
            return domain
    return None


def layer_for_type(type_code: str | None) -> str | None:
    """The 'Document Type / Layer' cover value for a document type code."""
    if not type_code:
        return None
    return TYPE_LAYERS.get(type_code.strip().upper())
