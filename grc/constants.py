# =============================================================================
# grc/constants.py — GRC module constants
# Single source of truth for SharePoint field names, choice values, and list IDs.
# Change SharePoint column names here — not scattered across service/router files.
# Depends on: config.py
# =============================================================================

from config import settings

# =============================================================================
#  SharePoint List IDs (from settings — populated from .env)
# =============================================================================

LIST_IDS = {
    "document_register": settings.document_register_list_id,
    "role_register":     settings.role_register_list_id,
    "compliance_calendar": settings.compliance_calendar_list_id,
    "contract_register": settings.contract_register_list_id,
}

LIST_NAMES = {
    "document_register":   "Document Register",
    "role_register":       "Role Register",
    "compliance_calendar": "Compliance Calendar",
    "contract_register":   "Contract Register",
}

# =============================================================================
#  Document Register — SharePoint field names
# =============================================================================

DOC_FIELDS = {
    "document_code":       "DocumentCode",
    "title":               "Title",
    "type":                "DocumentType",
    "department":          "Department",
    "owner":               "Owner",
    "owner_id":            "OwnerId",
    "current_version":     "CurrentVersion",
    "effective_date":      "EffectiveDate",
    "next_review_date":    "NextReviewDate",
    "applicable_standards":"ApplicableStandards",
    "linked_controls_count":"LinkedControlsCount",
    "status":              "Status",
    "sharepoint_url":      "SharePointUrl",
    # Withdrawal provenance — new SharePoint columns required on Document Register list
    "withdrawal_reason":   "WithdrawalReason",
    "withdrawn_date":      "WithdrawnDate",
    "withdrawn_by_oid":    "WithdrawnByEntraId",
    "withdrawn_by_name":   "WithdrawnByName",
    "replaced_by_code":    "ReplacedByCode",
    "withdrawal_note":     "WithdrawalNote",
}

DOC_TYPE_CHOICES    = ["Policy", "Procedure", "SOP", "Form", "Guidelines"]
DOC_STATUS_CHOICES  = ["Active", "Under Review", "Superseded", "Withdrawn"]
DOC_STANDARDS_CHOICES = ["ISO 9001", "ISO 27001", "NDPA", "Internal"]

# =============================================================================
#  Role Register — SharePoint field names
# =============================================================================

ROLE_FIELDS = {
    "role_title":        "Title",
    "department":        "Department",
    "jd_reference":      "JDReference",
    "current_holder":    "CurrentHolder",
    "current_holder_id": "CurrentHolderId",
    "source_system":     "SourceSystem",
    "variant_terms":     "VariantTerms",
    "assignment_status": "AssignmentStatus",
}

ROLE_ASSIGNMENT_CHOICES = ["Assigned", "Unassigned"]
ROLE_SOURCE_CHOICES     = ["Entra ID", "SeamlessHR", "BitWiseFlow", "Manual"]

# =============================================================================
#  Compliance Calendar — SharePoint field names
# =============================================================================

CAL_FIELDS = {
    # Core fields
    "obligation_name":    "Title",
    "type":               "ObligationType",
    "authority":          "Authority",
    "due_date":           "DueDate",
    "recurrence":         "Recurrence",
    "owner":              "Owner",
    "owner_id":           "OwnerId",
    "status":             "Status",
    # Source / context
    "source_document_code": "SourceDocumentCode",
    "notes":              "ObligationNotes",
    "linked_contract_id": "LinkedContractId",
    # Completion workflow
    "completed_date":     "CompletedDate",
    "completed_by_name":  "CompletedByName",
    "completed_by_oid":   "CompletedByEntraId",
    "completion_notes":   "CompletionNotes",
    # Escalation
    "escalated_gap_id":   "EscalatedGapId",
}

CAL_TYPE_CHOICES       = ["Statutory", "Licensing", "Certification", "Regulatory"]
CAL_RECURRENCE_CHOICES = ["Monthly", "Quarterly", "Annual", "Once"]
CAL_STATUS_CHOICES     = ["Overdue", "Due Soon", "Upcoming", "Completed"]

# Status calculation thresholds (days)
CAL_DUE_SOON_THRESHOLD_DAYS = 30

# =============================================================================
#  Contract Register — SharePoint field names
# =============================================================================

CONTRACT_FIELDS = {
    # Core fields
    "contract_reference":   "Title",
    "title":                "ContractTitle",
    "counterparty":         "Counterparty",
    "contract_type":        "ContractType",
    "owner":                "Owner",
    "owner_id":             "OwnerId",
    "start_date":           "StartDate",
    "end_date":             "EndDate",
    "review_date":          "ReviewDate",
    "applicable_standards": "ApplicableStandards",
    "status":               "Status",
    "linked_controls_count":"LinkedControlsCount",
    # Renewal / notice
    "renewal_notice_date":  "RenewalNoticeDate",
    "auto_renewal":         "AutoRenewal",
    "notice_period_days":   "NoticePeriodDays",
    # Lifecycle
    "lifecycle_status":     "LifecycleStatus",
    # Source / traceability
    "sharepoint_url":       "SharePointUrl",
    "source_document_code": "SourceDocumentCode",
    "notes":                "ContractNotes",
}

CONTRACT_TYPE_CHOICES   = ["Client", "Vendor", "Partner", "Employment", "NDA", "Other"]
CONTRACT_STATUS_CHOICES = ["Active", "Expired", "Under Review", "Terminated", "Expiring Soon", "Superseded", "Withdrawn"]
CONTRACT_LIFECYCLE_CHOICES = ["Active", "Under Review", "Terminated", "Superseded"]

# Status calculation threshold (days before expiry = "Expiring Soon")
CONTRACT_EXPIRING_SOON_THRESHOLD_DAYS = 60

# =============================================================================
#  Tier 2 list IDs — referenced by some Tier 1 cascades
# =============================================================================

LIST_IDS["ai_review_queue"]    = settings.ai_review_queue_list_id
LIST_IDS["document_lifecycle"] = settings.document_lifecycle_list_id
LIST_IDS["control_register"]   = settings.control_register_list_id
LIST_IDS["evidence_tracker"]   = settings.evidence_tracker_list_id
LIST_IDS["audit_log"]          = settings.audit_log_list_id
LIST_IDS["gap_analysis"]       = settings.gap_analysis_list_id

LIST_NAMES["ai_review_queue"]    = "AI Review Queue"
LIST_NAMES["document_lifecycle"] = "Document Lifecycle"
LIST_NAMES["control_register"]   = "Control Register"
LIST_NAMES["evidence_tracker"]   = "Evidence Tracker"
LIST_NAMES["audit_log"]          = "Audit Log"
LIST_NAMES["gap_analysis"]       = "Gap Analysis"
