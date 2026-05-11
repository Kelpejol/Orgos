# # =============================================================================
# # agents/extractor/schemas.py — Extractor agent Pydantic v2 schemas
# # Input: a policy document (file upload or raw text) + source document code.
# # Output: structured list of {risk, control, evidence} triplets.
# # These are the shapes written to the Control Register in SharePoint.
# # Depends on: pydantic v2
# # =============================================================================

# from enum import Enum
# from typing import Optional

# from pydantic import BaseModel, Field


# class ControlType(str, Enum):
#     PREVENTIVE = "Preventive"
#     DETECTIVE = "Detective"
#     CORRECTIVE = "Corrective"
#     DIRECTIVE = "Directive"


# class EvidenceFrequency(str, Enum):
#     CONTINUOUS = "Continuous"
#     MONTHLY = "Monthly"
#     QUARTERLY = "Quarterly"
#     ANNUAL = "Annual"
#     PER_OCCURRENCE = "Per occurrence"


# class CompletenessFlag(str, Enum):
#     COMPLETE = "COMPLETE"
#     DEFICIENT = "DEFICIENT"


# class ExtractionItem(BaseModel):
#     """
#     A single extracted {risk, control, evidence} triplet from a policy document.
#     This is the atomic unit written to the AI Review Queue staging list,
#     and after human confirmation, to the Control Register.

#     Every field maps directly to a Control Register column in SharePoint.
#     """

#     risk_statement: str = Field(
#         description="The risk or threat this control addresses"
#     )
#     control_statement: str = Field(
#         description="The control requirement as stated or implied in the document"
#     )
#     control_type: ControlType = Field(
#         description="Preventive / Detective / Corrective / Directive"
#     )
#     evidence_required: str = Field(
#         description="What evidence proves this control is working"
#     )
#     evidence_frequency: EvidenceFrequency = Field(
#         description="How often the evidence must be collected"
#     )
#     proposed_owner_role: str = Field(
#         description="Role title responsible for this control (resolved against Role Register)"
#     )
#     iso_clause: str = Field(
#         description="ISO 9001 / ISO 27001 / NDPA clause this maps to e.g. 'A.5.18'"
#     )
#     source_clause: Optional[str] = Field(
#         default=None,
#         description="Section/clause reference within the source document e.g. '§7.3'"
#     )
#     confidence_score: float = Field(
#         ge=0.0, le=1.0,
#         description="LLM confidence in this extraction (0.0 to 1.0)"
#     )
#     completeness_flag: CompletenessFlag = Field(
#         description="COMPLETE if risk+control+evidence all present, DEFICIENT if any missing"
#     )
#     deficiency_reason: Optional[str] = Field(
#         default=None,
#         description="Populated when completeness_flag = DEFICIENT — explains what is missing"
#     )


# class ExtractionRequest(BaseModel):
#     """
#     Request body for POST /api/v1/agents/extract/text
#     Use when submitting raw document text for extraction.
#     """

#     text: str = Field(
#         min_length=50,
#         description="Full text of the policy document to extract from"
#     )
#     source_document_code: str = Field(
#         description="Document Register code e.g. DRG-ISMS-POL-ACP-01-25"
#     )
#     write_to_sharepoint: bool = Field(
#         default=False,
#         description=(
#             "If True, writes COMPLETE items directly to the Control Register staging list. "
#             "If False (default), returns results only — for review before committing."
#         )
#     )


# class ExtractionResponse(BaseModel):
#     """
#     Response body for both extraction endpoints.
#     Returns all extracted items plus a summary.
#     """

#     source_document_code: str
#     total_extracted: int
#     complete_count: int
#     deficient_count: int
#     written_to_sharepoint: bool
#     items: list[ExtractionItem]


# class OllamaGenerateRequest(BaseModel):
#     """Internal schema — request body sent to Ollama API."""

#     model: str
#     prompt: str
#     stream: bool = False
#     format: str = "json"
#     options: dict = Field(default_factory=lambda: {"temperature": 0.1})


# class OllamaGenerateResponse(BaseModel):
#     """Internal schema — response body from Ollama API."""

#     model: str
#     response: str
#     done: bool




# =============================================================================
# agents/extractor/schemas.py — Extraction input/output schemas
# Updated for multi-type extraction per DRG-QI-REF-EXRL-01-26.
# Different document types produce different item shapes — all share a base.
# =============================================================================

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ControlType(str, Enum):
    PREVENTIVE = "Preventive"
    DETECTIVE  = "Detective"
    CORRECTIVE = "Corrective"
    DIRECTIVE  = "Directive"


class EvidenceFrequency(str, Enum):
    CONTINUOUS     = "Continuous"
    MONTHLY        = "Monthly"
    QUARTERLY      = "Quarterly"
    BI_ANNUALLY    = "Bi-annually"
    ANNUAL         = "Annual"
    PER_OCCURRENCE = "Per occurrence"
    PER_EVENT      = "Per event"
    ON_DEMAND      = "On-demand"


class EvidenceCollectionMethod(str, Enum):
    AUTOMATED  = "Automated"
    TRIGGERED  = "Triggered"
    SCHEDULED  = "Scheduled"
    ON_DEMAND  = "On-demand"


class EvidenceType(str, Enum):
    """16 evidence types from DRG-QI-REF-EVTX-01-26. No free-text types permitted."""
    LOG = "LOG"  # System log export
    CFG = "CFG"  # Configuration evidence
    APR = "APR"  # Signed approval record
    FRM = "FRM"  # Completed form/record
    TRN = "TRN"  # Training record
    ACK = "ACK"  # Policy acknowledgement
    TST = "TST"  # Test/drill/verification
    CRT = "CRT"  # Certificate/external attestation
    MTG = "MTG"  # Meeting/governance record
    REV = "REV"  # Review record
    CHK = "CHK"  # Checklist completion
    CNT = "CNT"  # Contract/agreement
    INV = "INV"  # Inventory/register extract
    CHG = "CHG"  # Change record
    INC = "INC"  # Incident record
    RPT = "RPT"  # Report/assessment


class CompletenessFlag(str, Enum):
    COMPLETE  = "COMPLETE"
    DEFICIENT = "DEFICIENT"


class ExtractionCategory(str, Enum):
    EXTRACTION    = "Extraction"
    ORPHAN        = "Orphan"
    HARMONISATION = "Harmonisation"


class ItemDocumentType(str, Enum):
    POLICY       = "Policy"
    JD           = "JobDescription"
    CONTRACT     = "Contract"
    REGULATORY   = "Regulatory"
    AUDIT        = "Audit"
    UNCLASSIFIED = "Unclassified"


# =============================================================================
#  Base extraction item — fields shared across all document types
# =============================================================================

class BaseExtractionItem(BaseModel):
    document_type:       ItemDocumentType
    extraction_category: ExtractionCategory
    source_clause:       Optional[str] = None
    confidence_score:    float = Field(ge=0.0, le=1.0)


# =============================================================================
#  Policy / Contract extraction item
# =============================================================================

class ExtractionItem(BaseExtractionItem):
    """
    Control extracted from a policy or contract document.
    Every field is mandatory or the item is DEFICIENT.
    Evidence fields enforce DRG-QI-REF-EVTX-01-26.
    """
    # Control fields
    risk_statement:    str
    control_statement: str
    control_type:      ControlType
    proposed_owner_role: str
    iso_clause:        str
    completeness_flag: CompletenessFlag
    deficiency_reason: Optional[str] = None

    # Contract-specific
    source_type:    Optional[str] = None  # "Policy" or "Contract"
    counterparty:   Optional[str] = None
    contract_clause:Optional[str] = None
    expiry_date:    Optional[str] = None
    renewal_date:   Optional[str] = None
    ndpa_section:   Optional[str] = None

    # Evidence fields — per Evidence Taxonomy
    evidence_type:                Optional[EvidenceType] = None
    evidence_description:         str = ""
    source_system:                str = ""
    evidence_format:              str = ""
    evidence_frequency:           str = ""
    evidence_collection_method:   str = ""
    evidence_owner_role:          str = ""
    evidence_validation_criteria: str = ""
    evidence_undefined:           bool = False
    evidence_undefined_reason:    Optional[str] = None


# =============================================================================
#  JD orphan item
# =============================================================================

class OrphanItem(BaseExtractionItem):
    """Orphan found during JD processing."""
    orphan_direction:     str  # "JD_to_Doc" or "Doc_to_JD"
    role_title:           str
    department:           str = ""
    reports_to:           Optional[str] = None
    responsibility_statement: str
    orphan_classification: str  # "POTENTIAL_ORPHAN" or "ROLE_REFERENCE"
    orphan_reason:        str


# =============================================================================
#  Regulatory obligation item
# =============================================================================

class RegulatoryItem(BaseExtractionItem):
    """Compliance Calendar obligation from regulatory/statutory document."""
    obligation_statement: str
    authority:           str
    deadline:            str
    recurrence:          str
    standards_reference: Optional[str] = None
    applies_to_dragnet:  bool = True
    penalty_if_missed:   Optional[str] = None


# =============================================================================
#  Audit finding item
# =============================================================================

class AuditItem(BaseExtractionItem):
    """Gap Analysis candidate from audit report or risk assessment."""
    finding_type:              str  # NonConformity|Finding|Observation|Risk
    severity:                  str  # Critical|Major|Minor
    finding_statement:         str
    standard_reference:        Optional[str] = None
    gap_type:                  str  # EvidenceGap|ControlGap|ProcessGap|Unknown
    remediation_required:      str
    triggers_document_lifecycle: bool = False
    is_repeated_finding:       bool = False


# =============================================================================
#  Request / Response schemas
# =============================================================================

class ExtractionRequest(BaseModel):
    """POST /api/v1/agents/extract/text"""
    text:                 str = Field(min_length=50)
    source_document_code: str
    folder_path:          Optional[str] = None  # For document type classification
    write_to_sharepoint:  bool = False


class ExtractionResponse(BaseModel):
    """Returned by both extraction endpoints."""
    source_document_code: str
    document_type:        str
    total_extracted:      int
    complete_count:       int
    deficient_count:      int
    written_to_sharepoint: bool
    skipped_reason:       Optional[str] = None  # Set when document is a non-extraction target
    items:                list[dict]             # Mixed types depending on document_type