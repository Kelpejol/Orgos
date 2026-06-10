# =============================================================================
# grc/schemas.py — GRC module Pydantic v2 schemas
# These are the data contracts for all 4 Tier 1 registers.
# WARNING: Downstream modules (Incident, L&D, Performance, Audit) depend on
# these field names and types. Do NOT rename fields without a schema review.
# Depends on: pydantic v2
# =============================================================================

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
#  Shared
# =============================================================================

class PersonRef(BaseModel):
    """
    Represents a person resolved from Entra ID.
    All person fields in all registers use this shape.
    The oid is the Entra ID object ID — the stable, unique identifier.
    Display name and email are resolved at query time — never stored directly.
    """

    model_config = ConfigDict(from_attributes=True)

    oid: str = Field(description="Entra ID object ID")
    display_name: str = Field(description="Full display name")
    email: str = Field(description="UPN / email address")


# =============================================================================
#  Document Register
# =============================================================================

class DocumentType(str, Enum):
    POLICY = "Policy"
    PROCEDURE = "Procedure"
    SOP = "SOP"
    FORM = "Form"
    GUIDELINES = "Guidelines"


class DocumentStatus(str, Enum):
    ACTIVE = "Active"
    UNDER_REVIEW = "Under Review"
    SUPERSEDED = "Superseded"
    WITHDRAWN = "Withdrawn"


class DocumentBase(BaseModel):
    """Fields shared between create and read operations."""

    document_code: str = Field(
        description="Format: DRG-[DEPT]-[TYPE]-[REF]-[YY]",
        examples=["DRG-ISMS-POL-ACP-01-25"],
    )
    title: str = Field(description="Full document title")
    type: DocumentType
    department: str = Field(description="Owning department")
    current_version: str = Field(
        description="Version string e.g. R03", examples=["R01", "R03"]
    )
    effective_date: date = Field(description="Date approved and published")
    next_review_date: Optional[date] = Field(
        default=None, description="Calculated: effective_date + review period"
    )
    applicable_standards: list[str] = Field(
        default_factory=list,
        description="ISO 9001 / ISO 27001 / NDPA / Internal",
    )
    status: DocumentStatus = Field(default=DocumentStatus.ACTIVE)

    @field_validator("document_code")
    @classmethod
    def validate_doc_code_format(cls, v: str) -> str:
        """Enforce DRG-[DEPT]-[TYPE]-[REF]-[YY] format."""
        parts = v.split("-")
        if len(parts) < 4 or parts[0] != "DRG":
            raise ValueError(
                f"Document code '{v}' must follow format: DRG-[DEPT]-[TYPE]-[REF]-[YY]"
            )
        return v.upper()


class DocumentCreate(DocumentBase):
    """Used for POST /grc/documents — owner_id is the Entra ID object ID."""

    owner_id: str = Field(description="Entra ID object ID of the document owner")


class DocumentUpdate(BaseModel):
    """Used for PATCH /grc/documents/{id} — all fields optional."""

    title: Optional[str] = None
    type: Optional[DocumentType] = None
    department: Optional[str] = None
    current_version: Optional[str] = None
    effective_date: Optional[date] = None
    next_review_date: Optional[date] = None
    applicable_standards: Optional[list[str]] = None
    status: Optional[DocumentStatus] = None
    owner_id: Optional[str] = None


class DocumentRead(DocumentBase):
    """Returned by GET endpoints — includes resolved owner and system fields."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="SharePoint item ID")
    owner: Optional[PersonRef] = None
    linked_controls_count: int = Field(default=0)
    created: Optional[datetime] = None
    modified: Optional[datetime] = None


# =============================================================================
#  Role Register
# =============================================================================

class RoleSourceSystem(str, Enum):
    ENTRA_ID = "Entra ID"
    SEAMLESS_HR = "SeamlessHR"
    BITWISEFLOW = "BitWiseFlow"
    MANUAL = "Manual"

class AssignmentStatus(str, Enum):
    ASSIGNED   = "Assigned"
    UNASSIGNED = "Unassigned"


class RoleBase(BaseModel):
    role_title: str = Field(description="Canonical role name after harmonisation")
    department: str
    jd_reference: str = Field(
        description="JD document code e.g. DRG-JD-ISMS-IL-01"
    )
    assignment_status: AssignmentStatus = Field(
    default=AssignmentStatus.UNASSIGNED,
    description="Assigned = has a current holder. Unassigned = role confirmed but no person mapped."
)
    source_system: RoleSourceSystem = Field(default=RoleSourceSystem.ENTRA_ID)
    variant_terms: Optional[str] = Field(
        default=None,
        description="Original terms before harmonisation (comma-separated)",
    )


class RoleAssign(BaseModel):
    """Used for PATCH /grc/roles/{id}/assign — assigns a person to an unassigned role."""
    current_holder_id: str = Field(
        description="Entra ID OID of the person being assigned to this role"
    )



class RoleCreate(RoleBase):
    current_holder_id: Optional[str] = Field(
        default=None,
        description="Entra ID OID of current holder. None = role is Unassigned."
    )


class RoleUpdate(BaseModel):
    role_title: Optional[str] = None
    department: Optional[str] = None
    jd_reference: Optional[str] = None
    current_holder_id: Optional[str] = None
    source_system: Optional[RoleSourceSystem] = None
    variant_terms: Optional[str] = None


class RoleRead(RoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    current_holder: Optional[PersonRef] = None
    created: Optional[datetime] = None
    modified: Optional[datetime] = None


# =============================================================================
#  Compliance Calendar
# =============================================================================

class ObligationType(str, Enum):
    STATUTORY     = "Statutory"
    LICENSING     = "Licensing"
    CERTIFICATION = "Certification"
    REGULATORY    = "Regulatory"


class ObligationRecurrence(str, Enum):
    MONTHLY   = "Monthly"
    QUARTERLY = "Quarterly"
    ANNUAL    = "Annual"
    ONCE      = "Once"


class ObligationStatus(str, Enum):
    OVERDUE   = "Overdue"
    DUE_SOON  = "Due Soon"
    UPCOMING  = "Upcoming"
    COMPLETED = "Completed"


class ObligationBase(BaseModel):
    obligation_name: str = Field(
        description="e.g. PAYE Remittance, ISO Surveillance Audit"
    )
    type: ObligationType
    authority: str = Field(
        description="e.g. LIRS, PenCom, FIRS, FML, NDPC, Cert Body"
    )
    due_date: date
    recurrence: ObligationRecurrence
    source_document_code: Optional[str] = Field(
        default=None,
        description="Document Register code or external reference that created this obligation",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Freeform notes, context, or penalty information",
    )


class ObligationCreate(ObligationBase):
    owner_id: str = Field(description="Entra ID object ID of responsible person")
    linked_contract_id: Optional[str] = Field(
        default=None,
        description="SharePoint item ID of the contract that created this obligation",
    )


class ObligationUpdate(BaseModel):
    """PATCH — all fields optional."""
    obligation_name:      Optional[str]                  = None
    type:                 Optional[ObligationType]        = None
    authority:            Optional[str]                  = None
    due_date:             Optional[date]                 = None
    recurrence:           Optional[ObligationRecurrence] = None
    owner_id:             Optional[str]                  = None
    source_document_code: Optional[str]                  = None
    notes:                Optional[str]                  = None


class CompleteObligation(BaseModel):
    """Body for PATCH /compliance/{id}/complete."""
    completion_notes: Optional[str] = Field(
        default=None,
        description="Evidence, reference, or confirmation note for this completion",
    )


class EscalateObligation(BaseModel):
    """Body for POST /compliance/{id}/escalate — creates a Gap Analysis item."""
    escalation_notes: Optional[str] = Field(
        default=None,
        description="Reason for escalation / expected impact",
    )


class ObligationRead(ObligationBase):
    model_config = ConfigDict(from_attributes=True)

    id:                  str
    owner:               Optional[PersonRef]   = None
    status:              ObligationStatus       # Calculated — never manually set
    completed_date:      Optional[date]        = None
    completed_by_name:   Optional[str]         = None
    completion_notes:    Optional[str]         = None
    linked_contract_id:  Optional[str]        = None
    escalated_gap_id:    Optional[str]        = None
    created:             Optional[datetime]    = None
    modified:            Optional[datetime]    = None


# =============================================================================
#  Contract Register
# =============================================================================

class ContractType(str, Enum):
    CLIENT     = "Client"
    VENDOR     = "Vendor"
    PARTNER    = "Partner"
    EMPLOYMENT = "Employment"
    NDA        = "NDA"
    OTHER      = "Other"


class ContractStatus(str, Enum):
    ACTIVE        = "Active"
    EXPIRED       = "Expired"
    UNDER_REVIEW  = "Under Review"
    TERMINATED    = "Terminated"
    EXPIRING_SOON = "Expiring Soon"
    SUPERSEDED    = "Superseded"


class ContractLifecycleStatus(str, Enum):
    """Manual lifecycle state that overrides date-based expiry calculation."""
    ACTIVE       = "Active"
    UNDER_REVIEW = "Under Review"
    TERMINATED   = "Terminated"
    SUPERSEDED   = "Superseded"


class ContractBase(BaseModel):
    contract_reference:   str                           = Field(description="Internal reference code")
    title:                str                           = Field(description="Contract title / description")
    counterparty:         str                           = Field(description="Other party name")
    contract_type:        ContractType
    start_date:           Optional[date]               = None
    end_date:             Optional[date]               = Field(default=None, description="Contract expiry date")
    renewal_notice_date:  Optional[date]               = Field(
        default=None,
        description="Last date by which renewal notice must be sent",
    )
    review_date:          Optional[date]               = None
    auto_renewal:         bool                         = Field(
        default=False,
        description="True if contract auto-renews unless cancelled",
    )
    notice_period_days:   Optional[int]                = Field(
        default=None,
        description="Days of notice required before expiry to prevent auto-renewal or to terminate",
    )
    lifecycle_status:     ContractLifecycleStatus      = Field(
        default=ContractLifecycleStatus.ACTIVE,
        description="Manual lifecycle status — overrides date-based expiry calculation",
    )
    applicable_standards: list[str]                   = Field(default_factory=list)
    sharepoint_url:       Optional[str]               = Field(
        default=None,
        description="URL to signed contract file in SharePoint",
    )
    source_document_code: Optional[str]               = Field(
        default=None,
        description="Document Register code if this contract is linked to a registered document",
    )
    notes:                Optional[str]               = None


class ContractCreate(ContractBase):
    owner_id: str = Field(description="Entra ID object ID of contract owner")


class ContractUpdate(BaseModel):
    """PATCH — all fields optional."""
    title:                Optional[str]                      = None
    counterparty:         Optional[str]                      = None
    contract_type:        Optional[ContractType]             = None
    owner_id:             Optional[str]                      = None
    start_date:           Optional[date]                     = None
    end_date:             Optional[date]                     = None
    renewal_notice_date:  Optional[date]                     = None
    review_date:          Optional[date]                     = None
    auto_renewal:         Optional[bool]                     = None
    notice_period_days:   Optional[int]                      = None
    lifecycle_status:     Optional[ContractLifecycleStatus]  = None
    applicable_standards: Optional[list[str]]                = None
    sharepoint_url:       Optional[str]                      = None
    source_document_code: Optional[str]                      = None
    notes:                Optional[str]                      = None


class ContractAddObligation(BaseModel):
    """Body for POST /contracts/{id}/add-obligation — creates a Calendar item from a contract."""
    obligation_name: str
    type:            ObligationType
    authority:       str
    due_date:        date
    recurrence:      ObligationRecurrence
    owner_id:        str = Field(description="Entra ID OID of the obligation owner")
    notes:           Optional[str] = None


class ContractRead(ContractBase):
    model_config = ConfigDict(from_attributes=True)

    id:                   str
    owner:                Optional[PersonRef] = None
    status:               ContractStatus       # Effective combined status (lifecycle + expiry)
    linked_controls_count: int                 = Field(default=0)
    renewal_notice_overdue: bool               = Field(
        default=False,
        description="True if renewal_notice_date has passed and contract is still active",
    )
    created:              Optional[datetime]   = None
    modified:             Optional[datetime]   = None


# =============================================================================
#  Health check schemas
# =============================================================================

class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str = "1.0.0"


class GraphHealthResponse(BaseModel):
    status: str
    site: Optional[str] = None
    token_acquired: Optional[bool] = None
    detail: Optional[str] = None
