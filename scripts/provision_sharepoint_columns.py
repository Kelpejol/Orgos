#!/usr/bin/env python3
# =============================================================================
# scripts/provision_sharepoint_columns.py
#
# Check and create missing SharePoint list columns across all 11 OrgOS lists.
#
# DRY-RUN by default — shows what WOULD be created without touching anything.
# Pass --apply to actually create the missing columns.
#
# Usage:
#   python scripts/provision_sharepoint_columns.py           # dry-run
#   python scripts/provision_sharepoint_columns.py --apply   # create missing cols
#   python scripts/provision_sharepoint_columns.py --list "Gap Analysis" --apply
#
# Re-running is safe — existing columns are never modified or duplicated.
# =============================================================================

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from config import settings
from graph.auth import get_graph_access_token

# =============================================================================
#  Column schema: every field the application reads or writes
#  Format: { "InternalName": ("type_key", extra_params_dict) }
#
#  type_key → Graph API column body:
#    "text"       → {"text": {}}
#    "note"       → {"text": {"allowMultipleLines": True, "linesForEditing": 6}}
#    "datetime"   → {"dateTime": {"displayAs": "default"}}
#    "number"     → {"number": {}}
#    "boolean"    → {"boolean": {}}
#    "choice"     → {"choice": {"choices": [...], "displayAs": "dropDownMenu"}}
# =============================================================================

TEXT    = "text"
NOTE    = "note"
DATE    = "datetime"
NUM     = "number"
BOOL    = "boolean"
CHOICE  = "choice"


def _col(type_key: str, choices: list[str] | None = None) -> dict:
    """Build the column definition dict."""
    if type_key == TEXT:
        return {"text": {}}
    if type_key == NOTE:
        return {"text": {"allowMultipleLines": True, "linesForEditing": 6}}
    if type_key == DATE:
        return {"dateTime": {"displayAs": "default"}}
    if type_key == NUM:
        return {"number": {"decimalPlaces": "two"}}
    if type_key == BOOL:
        return {"boolean": {}}
    if type_key == CHOICE:
        return {"choice": {"choices": choices or [], "displayAs": "dropDownMenu"}}
    raise ValueError(f"Unknown column type: {type_key}")


# =============================================================================
#  Per-list column definitions  (Title is built-in — always skip)
# =============================================================================

LISTS: dict[str, dict] = {

    # ─── 1. Document Register ────────────────────────────────────────────────
    "document_register": {
        "list_id_attr": "document_register_list_id",
        "display_name": "Document Register",
        "columns": {
            "DocumentCode":        (TEXT,   None),
            "DocumentType":        (CHOICE, ["Policy", "Procedure", "SOP", "Form", "Guidelines"]),
            "Department":          (TEXT,   None),
            "Owner":               (TEXT,   None),
            "OwnerId":             (TEXT,   None),
            "CurrentVersion":      (TEXT,   None),
            "EffectiveDate":       (DATE,   None),
            "NextReviewDate":      (DATE,   None),
            "ApplicableStandards": (TEXT,   None),
            "LinkedControlsCount": (NUM,    None),
            "Status":              (CHOICE, ["Active", "Under Review", "Superseded", "Withdrawn"]),
            "SharePointUrl":       (TEXT,   None),
        },
    },

    # ─── 2. Role Register ────────────────────────────────────────────────────
    "role_register": {
        "list_id_attr": "role_register_list_id",
        "display_name": "Role Register",
        "columns": {
            "Department":        (TEXT,   None),
            "JDReference":       (TEXT,   None),
            "CurrentHolder":     (TEXT,   None),
            "CurrentHolderId":   (TEXT,   None),
            "SourceSystem":      (CHOICE, ["Entra ID", "SeamlessHR", "BitWiseFlow", "Manual"]),
            "VariantTerms":      (NOTE,   None),
            "AssignmentStatus":  (CHOICE, ["Assigned", "Unassigned"]),
        },
    },

    # ─── 3. Compliance Calendar ──────────────────────────────────────────────
    "compliance_calendar": {
        "list_id_attr": "compliance_calendar_list_id",
        "display_name": "Compliance Calendar",
        "columns": {
            "ObligationType":    (CHOICE, ["Statutory", "Licensing", "Certification", "Regulatory"]),
            "Authority":         (TEXT,   None),
            "DueDate":           (DATE,   None),
            "Recurrence":        (CHOICE, ["Monthly", "Quarterly", "Annual", "Once"]),
            "Owner":             (TEXT,   None),
            "OwnerId":           (TEXT,   None),
            "Status":            (CHOICE, ["Overdue", "Due Soon", "Upcoming", "Completed"]),
            "SourceDocumentCode":(TEXT,   None),
            "ObligationNotes":   (NOTE,   None),
            "LinkedContractId":  (TEXT,   None),
            "CompletedDate":     (DATE,   None),
            "CompletedByName":   (TEXT,   None),
            "CompletedByEntraId":(TEXT,   None),
            "CompletionNotes":   (NOTE,   None),
            "EscalatedGapId":    (TEXT,   None),
        },
    },

    # ─── 4. Contract Register ────────────────────────────────────────────────
    "contract_register": {
        "list_id_attr": "contract_register_list_id",
        "display_name": "Contract Register",
        "columns": {
            "ContractTitle":       (TEXT,   None),
            "Counterparty":        (TEXT,   None),
            "ContractType":        (CHOICE, ["Client", "Vendor", "Partner", "Employment", "NDA", "Other"]),
            "Owner":               (TEXT,   None),
            "OwnerId":             (TEXT,   None),
            "StartDate":           (DATE,   None),
            "EndDate":             (DATE,   None),
            "ReviewDate":          (DATE,   None),
            "ApplicableStandards": (TEXT,   None),
            "Status":              (CHOICE, ["Active", "Expired", "Under Review", "Terminated", "Expiring Soon", "Superseded"]),
            "LinkedControlsCount": (NUM,    None),
            "RenewalNoticeDate":   (DATE,   None),
            "AutoRenewal":         (BOOL,   None),
            "NoticePeriodDays":    (NUM,    None),
            "LifecycleStatus":     (CHOICE, ["Active", "Under Review", "Terminated", "Superseded"]),
            "SharePointUrl":       (TEXT,   None),
            "SourceDocumentCode":  (TEXT,   None),
            "ContractNotes":       (NOTE,   None),
        },
    },

    # ─── 5. AI Review Queue ──────────────────────────────────────────────────
    "ai_review_queue": {
        "list_id_attr": "ai_review_queue_list_id",
        "display_name": "AI Review Queue",
        "columns": {
            "ItemType":                  (TEXT,   None),
            "DocumentType":              (TEXT,   None),
            "SourceDocumentCode":        (TEXT,   None),
            "SourceDocumentCode2":       (TEXT,   None),
            "SourceDocumentUrl":         (TEXT,   None),
            "SourceClause":              (TEXT,   None),
            "ControlStatement":          (NOTE,   None),
            "ControlType":               (TEXT,   None),
            "RiskStatement":             (NOTE,   None),
            "ProposedOwnerRole":         (TEXT,   None),
            "ISOClause":                 (TEXT,   None),
            "EvidenceType":              (TEXT,   None),
            "EvidenceDescription":       (NOTE,   None),
            "EvidenceSourceSystem":      (TEXT,   None),
            "EvidenceFormat":            (TEXT,   None),
            "EvidenceFrequency":         (TEXT,   None),
            "EvidenceCollectionMethod":  (TEXT,   None),
            "EvidenceOwnerRole":         (TEXT,   None),
            "EvidenceValidationCriteria":(NOTE,   None),
            "EvidenceUndefined":         (BOOL,   None),
            "EvidenceUndefinedReason":   (TEXT,   None),
            "CompletenessFlag":          (TEXT,   None),
            "DeficiencyReason":          (NOTE,   None),
            "ConfidenceScore":           (NUM,    None),
            "ReviewStatus":              (CHOICE, [
                "Pending Review", "Accepted", "Rejected",
                "False Positive", "Routed to Owner",
                "Second Review Requested",
            ]),
            "Decision":                  (TEXT,   None),
            "DecisionRationale":         (NOTE,   None),
            "ReviewedByEntraId":         (TEXT,   None),
            "CascadeResult":             (NOTE,   None),
            # Orphan fields
            "ResponsibilityStatement":   (NOTE,   None),
            "OrphanDirection":           (TEXT,   None),
            "OrphanClassification":      (TEXT,   None),
            "OrphanReason":              (NOTE,   None),
            # Harmonisation fields
            "VariantTerms":              (NOTE,   None),
            "CanonicalName":             (TEXT,   None),
            "VariantFrequency":          (TEXT,   None),
        },
    },

    # ─── 6. Document Lifecycle ───────────────────────────────────────────────
    "document_lifecycle": {
        "list_id_attr": "document_lifecycle_list_id",
        "display_name": "Document Lifecycle",
        "columns": {
            "DocumentCode":              (TEXT,   None),
            "DocumentType":              (TEXT,   None),
            "Department":                (TEXT,   None),
            "Stage":                     (CHOICE, ["Review", "Sensitisation", "Approval"]),
            "Trigger":                   (TEXT,   None),
            "AIGenerated":               (BOOL,   None),
            "Revised":                   (BOOL,   None),
            "CDIStatus":                 (CHOICE, ["Pending", "Passed", "Failed", "Error"]),
            "OwnerEntraId":              (TEXT,   None),
            "Owner":                     (TEXT,   None),
            "Notes":                     (NOTE,   None),
            "ApprovalStatus":            (TEXT,   None),
            "ApproverEntraId":           (TEXT,   None),
            "Approver":                  (TEXT,   None),
            "SubmittedForApproval":      (DATE,   None),
            "ApprovedDate":              (DATE,   None),
            "RejectionReason":           (NOTE,   None),
            "SharePointFileUrl":         (TEXT,   None),
            "CDIFailures":               (NOTE,   None),
            "LinkedGapId":               (TEXT,   None),
            "LinkedNCId":                (TEXT,   None),
            "StandardsMapping":          (TEXT,   None),
            "LinkedDocumentRegisterItem":(TEXT,   None),
            "SensitisationFeedback":     (NOTE,   None),
            "Stakeholders":              (NOTE,   None),
        },
    },

    # ─── 7. Control Register ─────────────────────────────────────────────────
    "control_register": {
        "list_id_attr": "control_register_list_id",
        "display_name": "Control Register",
        "columns": {
            "ControlStatement": (NOTE,   None),
            "ControlType":      (TEXT,   None),
            "SourceDocument":   (TEXT,   None),
            "SourceClause":     (TEXT,   None),
            "ISOClause":        (TEXT,   None),
            "OwnerRole":        (TEXT,   None),
            "OwnerEntraId":     (TEXT,   None),
            "RiskImplication":  (NOTE,   None),
            "EscalationNote":   (NOTE,   None),
            "Status":           (CHOICE, ["Active", "Blocked", "Superseded", "Withdrawn"]),
            "ConfidenceScore":  (NUM,    None),
            "QueueItemId":      (TEXT,   None),
        },
    },

    # ─── 8. Evidence Tracker ─────────────────────────────────────────────────
    "evidence_tracker": {
        "list_id_attr": "evidence_tracker_list_id",
        "display_name": "Evidence Tracker",
        "columns": {
            "EvidenceDescription": (NOTE,   None),
            "EvidenceType":        (TEXT,   None),
            "SourceSystem":        (TEXT,   None),
            "EvidenceFormat":      (TEXT,   None),
            "Frequency":           (TEXT,   None),
            "CollectionMethod":    (TEXT,   None),
            "OwnerRole":           (TEXT,   None),
            "OwnerEntraId":        (TEXT,   None),
            "ValidationCriteria":  (NOTE,   None),
            "EvidenceLink":        (TEXT,   None),
            "Status":              (CHOICE, ["Pending", "Submitted", "Accepted", "Rejected"]),
            "LinkedControlId":     (TEXT,   None),
            "NextDue":             (DATE,   None),
            "LastCollected":       (DATE,   None),
            "SubmissionNotes":     (NOTE,   None),
            "RejectionNote":       (NOTE,   None),
            "VerifiedBy":          (TEXT,   None),
        },
    },

    # ─── 9. Audit Log ────────────────────────────────────────────────────────
    "audit_log": {
        "list_id_attr": "audit_log_list_id",
        "display_name": "Audit Log",
        "columns": {
            "ReviewerOID":   (TEXT, None),
            "ReviewerName":  (TEXT, None),
            "ItemId":        (TEXT, None),
            "ItemType":      (TEXT, None),
            "Zone":          (TEXT, None),
            "AIConfidence":  (NUM,  None),
            "Decision":      (TEXT, None),
            "Rationale":     (NOTE, None),
            "CascadeResult": (NOTE, None),
            "StateFrom":     (TEXT, None),
            "StateTo":       (TEXT, None),
        },
    },

    # ─── 10. Strategic Risk Register ─────────────────────────────────────────
    "strategic_risk_register": {
        "list_id_attr": "strategic_risk_register_list_id",
        "display_name": "Strategic Risk Register",
        "columns": {
            "RiskId":           (TEXT,   None),
            "Description":      (NOTE,   None),
            "Category":         (TEXT,   None),
            "Source":           (TEXT,   None),
            "Likelihood":       (CHOICE, ["Low", "Medium", "High"]),
            "Impact":           (CHOICE, ["Low", "Medium", "High", "Critical"]),
            "RiskScore":        (NUM,    None),
            "OwnerEntraId":     (TEXT,   None),
            "Owner":            (TEXT,   None),
            "Treatment":        (CHOICE, ["Mitigate", "Accept", "Transfer", "Avoid"]),
            "TreatmentActions": (NOTE,   None),
            "Status":           (CHOICE, ["Open", "In Progress", "Accepted", "Closed"]),
            "DateIdentified":   (DATE,   None),
            "ReviewDate":       (DATE,   None),
            "LastReviewed":     (DATE,   None),
            "AcceptedBy":       (TEXT,   None),
            "AcceptedDate":     (DATE,   None),
            "RelatedGapId":     (TEXT,   None),
            "RelatedIncidentId":(TEXT,   None),
            "EscalationNote":   (NOTE,   None),
            "Notes":            (NOTE,   None),
        },
    },

    # ─── 11. Gap Analysis ────────────────────────────────────────────────────
    "gap_analysis": {
        "list_id_attr": "gap_analysis_list_id",
        "display_name": "Gap Analysis",
        "columns": {
            "GapId":               (TEXT,   None),
            "GapKey":              (TEXT,   None),
            "Standard":            (TEXT,   None),
            "Clause":              (TEXT,   None),
            "ClauseTitle":         (TEXT,   None),
            "GapCategory":         (TEXT,   None),
            "Severity":            (CHOICE, ["Critical", "Major", "Minor"]),
            "Finding":             (NOTE,   None),
            "Impact":              (NOTE,   None),
            "RemediationHint":     (NOTE,   None),
            "ProposedRemediation": (NOTE,   None),
            "Status":              (CHOICE, ["Open", "In progress", "Accepted risk", "Closed"]),
            "AssignedTo":          (TEXT,   None),
            "AssignedToEntraId":   (TEXT,   None),
            "TargetDate":          (DATE,   None),
            "VerificationMethod":  (TEXT,   None),
            "ResolutionNotes":     (NOTE,   None),
            "LinkedRiskId":        (TEXT,   None),
            "LinkedLifecycleId":   (TEXT,   None),
            "AcceptedBy":          (TEXT,   None),
            "AcceptedDate":        (DATE,   None),
        },
    },
}

# =============================================================================
#  ANSI colours (auto-disabled on non-TTY)
# =============================================================================

def _c(code: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

GREEN  = lambda t: _c("32", t)
YELLOW = lambda t: _c("33", t)
CYAN   = lambda t: _c("36", t)
RED    = lambda t: _c("31", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)


# =============================================================================
#  Graph API helpers
# =============================================================================

async def _auth_header() -> dict[str, str]:
    token = await get_graph_access_token()
    return {"Authorization": f"Bearer {token}"}


async def _get_existing_columns(
    client: httpx.AsyncClient, list_id: str
) -> set[str]:
    """Return the set of internal column names already on a list."""
    url = f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}/lists/{list_id}/columns"
    headers = await _auth_header()
    resp = await client.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {col["name"] for col in data.get("value", [])}


class PermissionError403(Exception):
    pass


async def _create_column(
    client: httpx.AsyncClient,
    list_id: str,
    col_name: str,
    type_key: str,
    choices: list[str] | None,
) -> None:
    """Create a single column on a SharePoint list."""
    url = (
        f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
        f"/lists/{list_id}/columns"
    )
    body = {
        "name":        col_name,
        "displayName": col_name,
        **_col(type_key, choices),
    }
    headers = {**(await _auth_header()), "Content-Type": "application/json"}
    resp = await client.post(url, json=body, headers=headers, timeout=30)
    if resp.status_code == 403:
        raise PermissionError403("403 Forbidden")
    resp.raise_for_status()


# =============================================================================
#  Core logic
# =============================================================================

async def provision(
    apply: bool,
    only_list: str | None,
) -> int:
    """
    Check each list and (if apply=True) create missing columns.
    Returns total count of missing columns found.
    """
    mode_label = BOLD(GREEN("APPLY MODE")) if apply else BOLD(YELLOW("DRY-RUN MODE"))
    print(f"\n{BOLD('OrgOS SharePoint Column Provisioner')}  [{mode_label}]\n")

    if not apply:
        print(
            YELLOW(
                "  Nothing will be created. Pass --apply to write to SharePoint.\n"
            )
        )

    total_existing        = 0
    total_missing         = 0
    total_created         = 0
    total_failed          = 0
    _permission_error_seen = False

    async with httpx.AsyncClient() as client:
        for key, spec in LISTS.items():
            display_name = spec["display_name"]

            if only_list and only_list.lower() not in display_name.lower():
                continue

            list_id: str = getattr(settings, spec["list_id_attr"], "")
            if not settings.is_list_configured(list_id):
                print(f"  {YELLOW('SKIP')}  {display_name}  {DIM('(list ID not configured)')}")
                continue

            print(f"  {BOLD(CYAN(display_name))}")

            try:
                existing = await _get_existing_columns(client, list_id)
            except Exception as exc:
                print(f"    {RED('ERROR')} fetching existing columns: {exc}\n")
                continue

            required: dict[str, tuple] = spec["columns"]
            missing  = {n: v for n, v in required.items() if n not in existing}
            present  = [n for n in required if n in existing]

            total_existing += len(present)
            total_missing  += len(missing)

            if present:
                print(f"    {GREEN('OK')}  {len(present)} column(s) already exist")

            if not missing:
                print(f"    {GREEN('✓')}  All required columns present\n")
                continue

            print(f"    {YELLOW('MISSING')}  {len(missing)} column(s):")

            for col_name, (type_key, choices) in sorted(missing.items()):
                type_label = {
                    TEXT: "Text",
                    NOTE: "Note (multiline)",
                    DATE: "DateTime",
                    NUM:  "Number",
                    BOOL: "Boolean (Yes/No)",
                    CHOICE: f"Choice {choices}",
                }[type_key]

                if not apply:
                    print(f"      {YELLOW('→')}  {col_name:45s}  {DIM(type_label)}")
                else:
                    try:
                        await _create_column(client, list_id, col_name, type_key, choices)
                        print(f"      {GREEN('✓ CREATED')}  {col_name:45s}  {DIM(type_label)}")
                        total_created += 1
                    except PermissionError403:
                        print(f"      {RED('✗ FAILED')}   {col_name:45s}  {RED('403 — missing Sites.Manage.All permission')}")
                        total_failed += 1
                        _permission_error_seen = True
                    except Exception as exc:
                        print(f"      {RED('✗ FAILED')}   {col_name:45s}  {RED(str(exc))}")
                        total_failed += 1

            print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(BOLD("─" * 60))
    print(BOLD("Summary"))
    print(f"  Columns already present : {GREEN(str(total_existing))}")
    print(f"  Columns missing         : {YELLOW(str(total_missing))}")

    if apply:
        print(f"  Columns created         : {GREEN(str(total_created))}")
        if total_failed:
            print(f"  Columns failed          : {RED(str(total_failed))}")
        if total_failed == 0 and total_missing > 0:
            print(f"\n  {GREEN('All missing columns have been created.')}")
        elif total_failed and _permission_error_seen:
            print(f"\n  {RED('403 permission errors detected.')}")
            print(f"  {YELLOW('Fix: add Sites.Manage.All to your Azure app registration.')}")
            print(f"  {YELLOW('Azure Portal → Entra ID → App registrations → OrgOS')}")
            print(f"  {YELLOW('→ API permissions → Add → Microsoft Graph → Application')}")
            print(f"  {YELLOW('→ Sites.Manage.All → Grant admin consent → re-run --apply')}")
        elif total_failed:
            print(f"\n  {RED('Some columns failed — re-run --apply after fixing the errors above.')}")
    else:
        if total_missing:
            print(
                f"\n  {YELLOW('Run with --apply to create the')} "
                f"{YELLOW(str(total_missing))} "
                f"{YELLOW('missing column(s).')}"
            )
        else:
            print(f"\n  {GREEN('No columns are missing. SharePoint lists are fully provisioned.')}")

    print()
    return total_missing


# =============================================================================
#  Entry point
# =============================================================================

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Check and provision missing SharePoint columns for all OrgOS lists.\n"
            "DRY-RUN by default — pass --apply to create missing columns."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually create the missing columns (default: dry-run only)",
    )
    p.add_argument(
        "--list",
        metavar="LIST_NAME",
        default=None,
        help='Only check/provision one list, e.g. --list "Gap Analysis"',
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    missing = asyncio.run(provision(apply=args.apply, only_list=args.list))
    sys.exit(0 if (not args.apply or missing == 0) else 1)
