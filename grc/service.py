# =============================================================================
# grc/service.py — GRC business logic layer
# All business logic for Tier 1 registers. Calls graph/client.py for data.
# Handles: status calculation, person field resolution, field mapping.
# Depends on: graph/client.py, grc/constants.py, grc/schemas.py
# =============================================================================

import calendar
import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from pydantic import ValidationError

from agents.cdi_checker.service import DOC_CODE_PATTERN
from graph.client import (
    create_list_item,
    get_list_item,
    get_list_items,
    resolve_user,
    soft_delete_list_item,
    update_list_item,
)
from graph.exceptions import GraphNotFoundError
from grc.constants import (
    CAL_DUE_SOON_THRESHOLD_DAYS,
    CAL_FIELDS,
    CONTRACT_EXPIRING_SOON_THRESHOLD_DAYS,
    CONTRACT_FIELDS,
    DOC_FIELDS,
    LIST_IDS,
    LIST_NAMES,
    ROLE_FIELDS,
)
from grc.schemas import (
    CompleteObligation,
    ContractAddObligation,
    ContractCreate,
    ContractLifecycleStatus,
    ContractRead,
    ContractStatus,
    ContractUpdate,
    DocumentCreate,
    DocumentRead,
    DocumentUpdate,
    ObligationCreate,
    ObligationRead,
    ObligationStatus,
    ObligationUpdate,
    PersonRef,
    RoleCreate,
    RoleRead,
    RoleUpdate,
)

logger = logging.getLogger(__name__)


# =============================================================================
#  Text helpers
# =============================================================================

def _normalise_variant_terms(value: Optional[str]) -> str:
    """Store Role Register variant terms as one term per line."""
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\n,]+", value or ""):
        term = raw.strip()
        key = term.lower()
        if term and key not in seen:
            terms.append(term)
            seen.add(key)
    return "\n".join(terms)


# =============================================================================
#  Date helpers
# =============================================================================

def _today() -> date:
    """Return today's date in UTC."""
    return datetime.now(timezone.utc).date()


def _next_due_date(current_due: date, recurrence: str) -> date:
    """
    Roll a due date forward by one recurrence period.
    Used when an obligation is completed: the next cycle starts.
    """
    if recurrence == "Monthly":
        month = current_due.month + 1
        year  = current_due.year
        if month > 12:
            month = 1
            year += 1
        max_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(current_due.day, max_day))

    elif recurrence == "Quarterly":
        month = current_due.month + 3
        year  = current_due.year
        while month > 12:
            month -= 12
            year  += 1
        max_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(current_due.day, max_day))

    elif recurrence == "Annual":
        try:
            return current_due.replace(year=current_due.year + 1)
        except ValueError:
            # Feb 29 on a non-leap year
            return date(current_due.year + 1, 3, 1)

    return current_due  # Once — no roll


# =============================================================================
#  Status calculation (pure functions — never stored in SharePoint)
# =============================================================================

def _calculate_obligation_status(
    due_date: date,
    completed_date: Optional[date] = None,
    recurrence: str = "Annual",
) -> ObligationStatus:
    """
    Calculate compliance obligation status.

    Rules (applied in order):
      1. If completed_date is set AND recurrence is Once  → Completed
         (recurring obligations roll their due_date forward on completion,
          so the completed_date only makes sense as a terminal state for Once)
      2. due_date < today                                → Overdue
      3. today <= due_date <= today + 30 days            → Due Soon
      4. due_date > today + 30 days                      → Upcoming
    """
    if completed_date and recurrence == "Once":
        return ObligationStatus.COMPLETED

    today = _today()
    delta = (due_date - today).days

    if delta < 0:
        return ObligationStatus.OVERDUE
    elif delta <= CAL_DUE_SOON_THRESHOLD_DAYS:
        return ObligationStatus.DUE_SOON
    else:
        return ObligationStatus.UPCOMING


def _calculate_contract_status(
    end_date: Optional[date],
    lifecycle_status: Optional[str] = None,
) -> ContractStatus:
    """
    Calculate effective contract status.

    Manual lifecycle_status overrides date-based calculation:
      Terminated  → ContractStatus.TERMINATED
      Under Review → ContractStatus.UNDER_REVIEW
      Superseded  → ContractStatus.SUPERSEDED

    Date-based rules (when lifecycle is Active or unset):
      end_date is None                         → Active (open-ended)
      end_date < today                         → Expired
      today <= end_date <= today + 60 days     → Expiring Soon
      end_date > today + 60 days               → Active
    """
    if lifecycle_status == ContractLifecycleStatus.TERMINATED:
        return ContractStatus.TERMINATED
    if lifecycle_status == ContractLifecycleStatus.UNDER_REVIEW:
        return ContractStatus.UNDER_REVIEW
    if lifecycle_status == ContractLifecycleStatus.SUPERSEDED:
        return ContractStatus.SUPERSEDED

    if end_date is None:
        return ContractStatus.ACTIVE

    today = _today()
    delta = (end_date - today).days

    if delta < 0:
        return ContractStatus.EXPIRED
    elif delta <= CONTRACT_EXPIRING_SOON_THRESHOLD_DAYS:
        return ContractStatus.EXPIRING_SOON
    else:
        return ContractStatus.ACTIVE


def _is_renewal_notice_overdue(
    renewal_notice_date: Optional[date],
    lifecycle_status: Optional[str],
    calculated_status: ContractStatus,
) -> bool:
    """
    True if the renewal notice deadline has passed and the contract is
    still active (not terminated/superseded/expired).
    """
    if not renewal_notice_date:
        return False
    if calculated_status in (
        ContractStatus.TERMINATED,
        ContractStatus.SUPERSEDED,
        ContractStatus.EXPIRED,
    ):
        return False
    return renewal_notice_date < _today()


# =============================================================================
#  Person field helpers
# =============================================================================

async def _build_person_ref(
    fields: dict, owner_field: str = "Owner"
) -> Optional[PersonRef]:
    """
    Build a PersonRef from SharePoint item fields.
    Resolves the Entra ID OID to display name and email via Graph API.
    """
    oid = (
        fields.get(f"{owner_field}EntraId", "")
        or fields.get(f"{owner_field}Id", "")
    )
    if not oid:
        return None

    resolved = await resolve_user(oid)
    return PersonRef(
        oid=oid,
        display_name=resolved["display_name"],
        email=resolved["email"],
    )


def _person_write_field(owner_field: str, entra_oid: str) -> dict:
    """
    Write person field to SharePoint.
    Stores the Entra ID OID in the companion text column only.
    """
    return {
        f"{owner_field}EntraId": entra_oid,
    }


def _document_owner_write_field(entra_oid: str) -> dict:
    """Document Register stores owner OID in OwnerId."""
    return {
        DOC_FIELDS["owner_id"]: entra_oid,
    }


# =============================================================================
#  SharePoint item → schema converters
# =============================================================================

async def _sp_item_to_doc(item: dict) -> DocumentRead:
    """Convert a SharePoint List item dict to a DocumentRead schema."""
    fields = item.get("fields", {})
    document_code = fields.get(DOC_FIELDS["document_code"]) or "DRG-MISSING-DOC-00"
    if not DOC_CODE_PATTERN.match(str(document_code).strip().upper()):
        raise ValueError(f"Invalid Document Register code '{document_code}' on item {item.get('id')}")
    title = fields.get(DOC_FIELDS["title"]) or document_code
    effective_date = _parse_date(fields.get(DOC_FIELDS["effective_date"])) or _today()
    return DocumentRead(
        id=str(item["id"]),
        document_code=document_code,
        title=title,
        type=fields.get(DOC_FIELDS["type"]) or "Policy",
        department=fields.get(DOC_FIELDS["department"]) or "",
        owner=await _build_person_ref(fields, "Owner"),
        current_version=fields.get(DOC_FIELDS["current_version"]) or "R01",
        effective_date=effective_date,
        next_review_date=_parse_date(fields.get(DOC_FIELDS["next_review_date"])),
        applicable_standards=_parse_multi_choice(
            fields.get(DOC_FIELDS["applicable_standards"])
        ),
        linked_controls_count=_parse_int(fields.get(DOC_FIELDS["linked_controls_count"])) or 0,
        sharepoint_url=fields.get(DOC_FIELDS["sharepoint_url"]) or None,
        status=fields.get(DOC_FIELDS["status"]) or "Active",
        created=_parse_datetime(item.get("createdDateTime")),
        modified=_parse_datetime(item.get("lastModifiedDateTime")),
    )


async def _sp_item_to_role(item: dict) -> RoleRead:
    fields = item.get("fields", {})

    holder_oid = (
        fields.get(ROLE_FIELDS["current_holder_id"], "")
        or fields.get("CurrentHolderEntraId", "")
    )
    raw_status = fields.get(ROLE_FIELDS["assignment_status"], "")
    assignment_status = raw_status if raw_status else ("Assigned" if holder_oid else "Unassigned")

    return RoleRead(
        id=str(item["id"]),
        role_title=fields.get(ROLE_FIELDS["role_title"], ""),
        department=fields.get(ROLE_FIELDS["department"], ""),
        jd_reference=fields.get(ROLE_FIELDS["jd_reference"], ""),
        current_holder=await _build_person_ref(fields, "CurrentHolder"),
        source_system=fields.get(ROLE_FIELDS["source_system"], "Entra ID"),
        variant_terms=fields.get(ROLE_FIELDS["variant_terms"]),
        assignment_status=assignment_status,
        created=_parse_datetime(item.get("createdDateTime")),
        modified=_parse_datetime(item.get("lastModifiedDateTime")),
    )


async def _sp_item_to_obligation(item: dict) -> ObligationRead:
    """Convert a SharePoint List item dict to an ObligationRead schema."""
    fields         = item.get("fields", {})
    due_date       = _parse_date(fields.get(CAL_FIELDS["due_date"])) or _today()
    recurrence     = fields.get(CAL_FIELDS["recurrence"], "Annual")
    completed_date = _parse_date(fields.get(CAL_FIELDS["completed_date"]))

    return ObligationRead(
        id=str(item["id"]),
        obligation_name=fields.get(CAL_FIELDS["obligation_name"], ""),
        type=fields.get(CAL_FIELDS["type"], "Statutory"),
        authority=fields.get(CAL_FIELDS["authority"], ""),
        due_date=due_date,
        recurrence=recurrence,
        owner=await _build_person_ref(fields, "Owner"),
        status=_calculate_obligation_status(due_date, completed_date, recurrence),
        source_document_code=fields.get(CAL_FIELDS["source_document_code"]) or None,
        notes=fields.get(CAL_FIELDS["notes"]) or None,
        linked_contract_id=fields.get(CAL_FIELDS["linked_contract_id"]) or None,
        completed_date=completed_date,
        completed_by_name=fields.get(CAL_FIELDS["completed_by_name"]) or None,
        completion_notes=fields.get(CAL_FIELDS["completion_notes"]) or None,
        escalated_gap_id=fields.get(CAL_FIELDS["escalated_gap_id"]) or None,
        created=_parse_datetime(item.get("createdDateTime")),
        modified=_parse_datetime(item.get("lastModifiedDateTime")),
    )


async def _sp_item_to_contract(item: dict) -> ContractRead:
    """Convert a SharePoint List item dict to a ContractRead schema."""
    fields           = item.get("fields", {})
    end_date         = _parse_date(fields.get(CONTRACT_FIELDS["end_date"]))
    lifecycle_status = fields.get(CONTRACT_FIELDS["lifecycle_status"], "Active") or "Active"
    renewal_notice   = _parse_date(fields.get(CONTRACT_FIELDS["renewal_notice_date"]))
    stored_status    = str(fields.get(CONTRACT_FIELDS["status"], "") or "").strip()

    calculated_status = (
        ContractStatus.WITHDRAWN
        if stored_status == ContractStatus.WITHDRAWN.value
        else _calculate_contract_status(end_date, lifecycle_status)
    )

    return ContractRead(
        id=str(item["id"]),
        contract_reference=fields.get(CONTRACT_FIELDS["contract_reference"], ""),
        title=fields.get(CONTRACT_FIELDS["title"], ""),
        counterparty=fields.get(CONTRACT_FIELDS["counterparty"], ""),
        contract_type=fields.get(CONTRACT_FIELDS["contract_type"], "Other"),
        owner=await _build_person_ref(fields, "Owner"),
        start_date=_parse_date(fields.get(CONTRACT_FIELDS["start_date"])),
        end_date=end_date,
        renewal_notice_date=renewal_notice,
        review_date=_parse_date(fields.get(CONTRACT_FIELDS["review_date"])),
        auto_renewal=bool(fields.get(CONTRACT_FIELDS["auto_renewal"], False)),
        notice_period_days=_parse_int(fields.get(CONTRACT_FIELDS["notice_period_days"])),
        lifecycle_status=lifecycle_status,
        applicable_standards=_parse_multi_choice(
            fields.get(CONTRACT_FIELDS["applicable_standards"])
        ),
        status=calculated_status,
        linked_controls_count=int(
            fields.get(CONTRACT_FIELDS["linked_controls_count"], 0) or 0
        ),
        sharepoint_url=fields.get(CONTRACT_FIELDS["sharepoint_url"]) or None,
        source_document_code=fields.get(CONTRACT_FIELDS["source_document_code"]) or None,
        notes=fields.get(CONTRACT_FIELDS["notes"]) or None,
        renewal_notice_overdue=_is_renewal_notice_overdue(
            renewal_notice, lifecycle_status, calculated_status
        ),
        created=_parse_datetime(item.get("createdDateTime")),
        modified=_parse_datetime(item.get("lastModifiedDateTime")),
    )


# =============================================================================
#  Parsing utilities
# =============================================================================

def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_multi_choice(value: Optional[str]) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r";#|[;,]", str(value))

    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = str(part).strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _parse_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# =============================================================================
#  Document Register
# =============================================================================

async def get_documents(
    status: Optional[str] = None,
    department: Optional[str] = None,
) -> list[DocumentRead]:
    filters = []
    if status:
        filters.append(f"fields/Status eq '{status}'")
    if department:
        filters.append(f"fields/Department eq '{department}'")

    odata_filter = " and ".join(filters) if filters else None
    items = await get_list_items(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        odata_filter=odata_filter,
    )
    docs: list[DocumentRead] = []
    for item in items:
        try:
            docs.append(await _sp_item_to_doc(item))
        except (ValueError, ValidationError) as exc:
            logger.error(
                "Skipping invalid Document Register item %s: %s",
                item.get("id", "?"),
                exc,
            )
    return docs


async def get_document(item_id: str) -> DocumentRead:
    item = await get_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        item_id,
    )
    return await _sp_item_to_doc(item)


async def create_document(doc: DocumentCreate) -> DocumentRead:
    fields: dict = {
        DOC_FIELDS["document_code"]:    doc.document_code,
        DOC_FIELDS["title"]:            doc.title,
        DOC_FIELDS["type"]:             doc.type.value,
        DOC_FIELDS["department"]:       doc.department,
        DOC_FIELDS["current_version"]:  doc.current_version,
        DOC_FIELDS["effective_date"]:   doc.effective_date.isoformat(),
        DOC_FIELDS["status"]:           doc.status.value,
        DOC_FIELDS["applicable_standards"]: ";".join(doc.applicable_standards),
    }
    if doc.next_review_date:
        fields[DOC_FIELDS["next_review_date"]] = doc.next_review_date.isoformat()
    fields.update(_document_owner_write_field(doc.owner_id))

    item = await create_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        fields,
    )
    return await _sp_item_to_doc(item)


async def update_document(item_id: str, doc: DocumentUpdate) -> DocumentRead:
    fields: dict = {}
    if doc.title is not None:
        fields[DOC_FIELDS["title"]] = doc.title
    if doc.type is not None:
        fields[DOC_FIELDS["type"]] = doc.type.value
    if doc.department is not None:
        fields[DOC_FIELDS["department"]] = doc.department
    if doc.current_version is not None:
        fields[DOC_FIELDS["current_version"]] = doc.current_version
    if doc.effective_date is not None:
        fields[DOC_FIELDS["effective_date"]] = doc.effective_date.isoformat()
    if doc.next_review_date is not None:
        fields[DOC_FIELDS["next_review_date"]] = doc.next_review_date.isoformat()
    if doc.applicable_standards is not None:
        fields[DOC_FIELDS["applicable_standards"]] = ";".join(doc.applicable_standards)
    if doc.status is not None:
        fields[DOC_FIELDS["status"]] = doc.status.value
    if doc.owner_id is not None:
        fields.update(_document_owner_write_field(doc.owner_id))

    await update_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        item_id,
        fields,
    )
    return await get_document(item_id)


async def soft_delete_document(item_id: str) -> None:
    await soft_delete_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        item_id,
    )


# =============================================================================
#  Role Register
# =============================================================================

async def get_roles(department: Optional[str] = None) -> list[RoleRead]:
    odata_filter = f"fields/Department eq '{department}'" if department else None
    items = await get_list_items(
        LIST_IDS["role_register"],
        LIST_NAMES["role_register"],
        odata_filter=odata_filter,
    )
    return [await _sp_item_to_role(item) for item in items]


async def get_role(item_id: str) -> RoleRead:
    item = await get_list_item(
        LIST_IDS["role_register"], LIST_NAMES["role_register"], item_id
    )
    return await _sp_item_to_role(item)


async def create_role(role: RoleCreate) -> RoleRead:
    assignment_status = "Assigned" if role.current_holder_id else "Unassigned"
    fields: dict = {
        ROLE_FIELDS["role_title"]:        role.role_title,
        ROLE_FIELDS["department"]:        role.department,
        ROLE_FIELDS["jd_reference"]:      role.jd_reference,
        ROLE_FIELDS["source_system"]:     role.source_system.value,
        ROLE_FIELDS["assignment_status"]: assignment_status,
    }
    if role.variant_terms:
        fields[ROLE_FIELDS["variant_terms"]] = _normalise_variant_terms(role.variant_terms)
    if role.current_holder_id:
        fields.update(_person_write_field("CurrentHolder", role.current_holder_id))

    item = await create_list_item(
        LIST_IDS["role_register"], LIST_NAMES["role_register"], fields
    )
    return await _sp_item_to_role(item)


async def update_role(item_id: str, role: RoleUpdate) -> RoleRead:
    fields: dict = {}
    if role.role_title is not None:
        fields[ROLE_FIELDS["role_title"]] = role.role_title
    if role.department is not None:
        fields[ROLE_FIELDS["department"]] = role.department
    if role.jd_reference is not None:
        fields[ROLE_FIELDS["jd_reference"]] = role.jd_reference
    if role.source_system is not None:
        fields[ROLE_FIELDS["source_system"]] = role.source_system.value
    if role.variant_terms is not None:
        fields[ROLE_FIELDS["variant_terms"]] = _normalise_variant_terms(role.variant_terms)
    if role.current_holder_id is not None:
        fields.update(_person_write_field("CurrentHolder", role.current_holder_id))

    await update_list_item(
        LIST_IDS["role_register"], LIST_NAMES["role_register"], item_id, fields
    )
    return await get_role(item_id)


async def assign_role_holder(item_id: str, holder_id: str) -> RoleRead:
    fields: dict = {ROLE_FIELDS["assignment_status"]: "Assigned"}
    fields.update(_person_write_field("CurrentHolder", holder_id))
    await update_list_item(
        LIST_IDS["role_register"], LIST_NAMES["role_register"], item_id, fields
    )
    return await get_role(item_id)


async def get_unassigned_roles() -> list[RoleRead]:
    all_roles = await get_roles()
    return [r for r in all_roles if r.assignment_status == "Unassigned"]


# =============================================================================
#  Compliance Calendar
# =============================================================================

async def get_obligations(
    obligation_type: Optional[str] = None,
    authority: Optional[str] = None,
) -> list[ObligationRead]:
    """Retrieve obligations. Status is calculated on every read."""
    filters = []
    if obligation_type:
        filters.append(f"fields/ObligationType eq '{obligation_type}'")
    if authority:
        filters.append(f"fields/Authority eq '{authority}'")

    odata_filter = " and ".join(filters) if filters else None
    items = await get_list_items(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        odata_filter=odata_filter,
    )
    return [await _sp_item_to_obligation(item) for item in items]


async def get_obligation(item_id: str) -> ObligationRead:
    item = await get_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
    )
    return await _sp_item_to_obligation(item)


async def get_overdue_obligations() -> list[ObligationRead]:
    all_items = await get_obligations()
    return [o for o in all_items if o.status == ObligationStatus.OVERDUE]


async def get_due_soon_obligations() -> list[ObligationRead]:
    all_items = await get_obligations()
    return [o for o in all_items if o.status == ObligationStatus.DUE_SOON]


async def create_obligation(obligation: ObligationCreate) -> ObligationRead:
    fields: dict = {
        CAL_FIELDS["obligation_name"]: obligation.obligation_name,
        CAL_FIELDS["type"]:            obligation.type.value,
        CAL_FIELDS["authority"]:       obligation.authority,
        CAL_FIELDS["due_date"]:        obligation.due_date.isoformat(),
        CAL_FIELDS["recurrence"]:      obligation.recurrence.value,
    }
    if obligation.source_document_code:
        fields[CAL_FIELDS["source_document_code"]] = obligation.source_document_code
    if obligation.notes:
        fields[CAL_FIELDS["notes"]] = obligation.notes
    if obligation.linked_contract_id:
        fields[CAL_FIELDS["linked_contract_id"]] = obligation.linked_contract_id
    fields.update(_person_write_field("Owner", obligation.owner_id))

    item = await create_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        fields,
    )
    return await _sp_item_to_obligation(item)


async def update_obligation(item_id: str, obligation: ObligationUpdate) -> ObligationRead:
    fields: dict = {}
    if obligation.obligation_name is not None:
        fields[CAL_FIELDS["obligation_name"]] = obligation.obligation_name
    if obligation.type is not None:
        fields[CAL_FIELDS["type"]] = obligation.type.value
    if obligation.authority is not None:
        fields[CAL_FIELDS["authority"]] = obligation.authority
    if obligation.due_date is not None:
        fields[CAL_FIELDS["due_date"]] = obligation.due_date.isoformat()
    if obligation.recurrence is not None:
        fields[CAL_FIELDS["recurrence"]] = obligation.recurrence.value
    if obligation.owner_id is not None:
        fields.update(_person_write_field("Owner", obligation.owner_id))
    if obligation.source_document_code is not None:
        fields[CAL_FIELDS["source_document_code"]] = obligation.source_document_code
    if obligation.notes is not None:
        fields[CAL_FIELDS["notes"]] = obligation.notes

    await update_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
        fields,
    )
    return await get_obligation(item_id)


async def complete_obligation(
    item_id: str,
    user_oid: str,
    user_name: str,
    body: CompleteObligation,
) -> ObligationRead:
    """
    Mark an obligation as completed.

    For Once obligations: stamps CompletedDate — status becomes Completed.
    For recurring obligations: rolls DueDate forward one period and records
    the completion date for audit history. The obligation re-enters the
    Upcoming/Due Soon cycle with the new date.
    """
    item      = await get_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
    )
    fields_sp = item.get("fields", {})
    recurrence = fields_sp.get(CAL_FIELDS["recurrence"], "Annual")
    due_date   = _parse_date(fields_sp.get(CAL_FIELDS["due_date"])) or _today()

    update: dict = {
        CAL_FIELDS["completed_date"]:    _today().isoformat(),
        CAL_FIELDS["completed_by_name"]: user_name,
        CAL_FIELDS["completed_by_oid"]:  user_oid,
    }
    if body.completion_notes:
        update[CAL_FIELDS["completion_notes"]] = body.completion_notes

    # Recurring obligations: roll the due date forward
    if recurrence != "Once":
        next_date = _next_due_date(due_date, recurrence)
        update[CAL_FIELDS["due_date"]] = next_date.isoformat()
        logger.info(
            f"Obligation {item_id} completed; next due date rolled to {next_date}"
        )

    await update_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
        update,
    )
    return await get_obligation(item_id)


async def escalate_obligation(
    item_id: str,
    user_oid: str,
    user_name: str,
    escalation_notes: Optional[str],
) -> dict:
    """
    Escalate an overdue obligation to the Gap Analysis register.

    Creates a Gap Analysis item with category "Obligation gap" and links
    the obligation to it via EscalatedGapId. Idempotent — if the obligation
    already has an EscalatedGapId the existing ID is returned without
    creating a duplicate.
    """
    from config import settings

    item      = await get_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
    )
    fields_sp = item.get("fields", {})

    # Idempotency guard
    existing_gap_id = fields_sp.get(CAL_FIELDS["escalated_gap_id"], "")
    if existing_gap_id:
        return {"gap_id": existing_gap_id, "message": "Already escalated. Existing gap returned."}

    obligation_name = fields_sp.get(CAL_FIELDS["obligation_name"], "")
    authority       = fields_sp.get(CAL_FIELDS["authority"], "")
    ob_type         = fields_sp.get(CAL_FIELDS["type"], "Statutory")
    due_date_str    = fields_sp.get(CAL_FIELDS["due_date"], "")
    notes_str       = fields_sp.get(CAL_FIELDS["notes"], "") or ""

    # Map obligation type to severity
    severity = "Critical" if ob_type in ("Statutory", "Regulatory") else "Major"

    # Generate a sequential GapId for the obligation namespace
    year_short = _today().strftime("%y")
    gap_prefix = f"GAP-OBL-{year_short}-"
    try:
        existing = await get_list_items(
            settings.gap_analysis_list_id, "Gap Analysis"
        )
        count = sum(
            1 for i in existing
            if i.get("fields", {}).get("GapId", "").startswith(gap_prefix)
        )
        gap_id = f"{gap_prefix}{count + 1:03d}"
    except Exception:
        import time
        gap_id = f"{gap_prefix}{int(time.time()) % 1000:03d}"

    finding = (
        f"Overdue {ob_type} obligation: '{obligation_name}' "
        f"(due {due_date_str}). Authority: {authority}."
    )
    if escalation_notes:
        finding += f" Escalation note: {escalation_notes}"

    target_days = 30 if severity == "Critical" else 60
    from datetime import timedelta
    target_date = (_today() + timedelta(days=target_days)).isoformat()

    gap_fields = {
        "Title":               finding[:255],
        "GapId":               gap_id,
        "Standard":            ob_type,
        "Clause":              ob_type,
        "ClauseTitle":         obligation_name,
        "GapCategory":         "Obligation gap",
        "GapKey":              f"{ob_type}|{authority}|Obligation gap|{item_id}",
        "Severity":            severity,
        "Finding":             finding,
        "Impact":              (
            f"This {ob_type} obligation is overdue. Failure to comply with "
            f"{authority} requirements may result in regulatory action or penalties."
        ),
        "Status":              "Open",
        "TargetDate":          target_date,
    }

    await create_list_item(settings.gap_analysis_list_id, "Gap Analysis", gap_fields)

    # Link back to obligation
    await update_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
        {CAL_FIELDS["escalated_gap_id"]: gap_id},
    )

    logger.info(f"Obligation {item_id} escalated to Gap Analysis as {gap_id}")
    return {
        "gap_id": gap_id,
        "severity": severity,
        "message": f"Gap Analysis item {gap_id} created from overdue obligation.",
    }


async def soft_delete_obligation(item_id: str) -> None:
    await soft_delete_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
    )


# =============================================================================
#  Contract Register
# =============================================================================

async def get_contracts(
    contract_type: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
) -> list[ContractRead]:
    """Retrieve contracts. Status (effective combined) is calculated on read."""
    filters = []
    if contract_type:
        filters.append(f"fields/ContractType eq '{contract_type}'")
    if lifecycle_status:
        filters.append(f"fields/LifecycleStatus eq '{lifecycle_status}'")

    odata_filter = " and ".join(filters) if filters else None
    items = await get_list_items(
        LIST_IDS["contract_register"],
        LIST_NAMES["contract_register"],
        odata_filter=odata_filter,
    )
    return [await _sp_item_to_contract(item) for item in items]


async def get_contract(item_id: str) -> ContractRead:
    item = await get_list_item(
        LIST_IDS["contract_register"], LIST_NAMES["contract_register"], item_id
    )
    return await _sp_item_to_contract(item)


async def get_expiring_contracts() -> list[ContractRead]:
    all_contracts = await get_contracts()
    return [c for c in all_contracts if c.status == ContractStatus.EXPIRING_SOON]


async def create_contract(contract: ContractCreate) -> ContractRead:
    fields: dict = {
        CONTRACT_FIELDS["contract_reference"]:   contract.contract_reference,
        CONTRACT_FIELDS["title"]:                contract.title,
        CONTRACT_FIELDS["counterparty"]:         contract.counterparty,
        CONTRACT_FIELDS["contract_type"]:        contract.contract_type.value,
        CONTRACT_FIELDS["applicable_standards"]: ";".join(contract.applicable_standards),
        CONTRACT_FIELDS["lifecycle_status"]:     contract.lifecycle_status.value,
        CONTRACT_FIELDS["auto_renewal"]:         contract.auto_renewal,
    }
    if contract.start_date:
        fields[CONTRACT_FIELDS["start_date"]] = contract.start_date.isoformat()
    if contract.end_date:
        fields[CONTRACT_FIELDS["end_date"]] = contract.end_date.isoformat()
    if contract.renewal_notice_date:
        fields[CONTRACT_FIELDS["renewal_notice_date"]] = contract.renewal_notice_date.isoformat()
    if contract.review_date:
        fields[CONTRACT_FIELDS["review_date"]] = contract.review_date.isoformat()
    if contract.notice_period_days is not None:
        fields[CONTRACT_FIELDS["notice_period_days"]] = contract.notice_period_days
    if contract.sharepoint_url:
        fields[CONTRACT_FIELDS["sharepoint_url"]] = contract.sharepoint_url
    if contract.source_document_code:
        fields[CONTRACT_FIELDS["source_document_code"]] = contract.source_document_code
    if contract.notes:
        fields[CONTRACT_FIELDS["notes"]] = contract.notes
    fields.update(_person_write_field("Owner", contract.owner_id))

    item = await create_list_item(
        LIST_IDS["contract_register"],
        LIST_NAMES["contract_register"],
        fields,
    )
    return await _sp_item_to_contract(item)


async def update_contract(item_id: str, contract: ContractUpdate) -> ContractRead:
    fields: dict = {}
    if contract.title is not None:
        fields[CONTRACT_FIELDS["title"]] = contract.title
    if contract.counterparty is not None:
        fields[CONTRACT_FIELDS["counterparty"]] = contract.counterparty
    if contract.contract_type is not None:
        fields[CONTRACT_FIELDS["contract_type"]] = contract.contract_type.value
    if contract.owner_id is not None:
        fields.update(_person_write_field("Owner", contract.owner_id))
    if contract.start_date is not None:
        fields[CONTRACT_FIELDS["start_date"]] = contract.start_date.isoformat()
    if contract.end_date is not None:
        fields[CONTRACT_FIELDS["end_date"]] = contract.end_date.isoformat()
    if contract.renewal_notice_date is not None:
        fields[CONTRACT_FIELDS["renewal_notice_date"]] = contract.renewal_notice_date.isoformat()
    if contract.review_date is not None:
        fields[CONTRACT_FIELDS["review_date"]] = contract.review_date.isoformat()
    if contract.auto_renewal is not None:
        fields[CONTRACT_FIELDS["auto_renewal"]] = contract.auto_renewal
    if contract.notice_period_days is not None:
        fields[CONTRACT_FIELDS["notice_period_days"]] = contract.notice_period_days
    if contract.lifecycle_status is not None:
        fields[CONTRACT_FIELDS["lifecycle_status"]] = contract.lifecycle_status.value
    if contract.applicable_standards is not None:
        fields[CONTRACT_FIELDS["applicable_standards"]] = ";".join(contract.applicable_standards)
    if contract.sharepoint_url is not None:
        fields[CONTRACT_FIELDS["sharepoint_url"]] = contract.sharepoint_url
    if contract.source_document_code is not None:
        fields[CONTRACT_FIELDS["source_document_code"]] = contract.source_document_code
    if contract.notes is not None:
        fields[CONTRACT_FIELDS["notes"]] = contract.notes

    await update_list_item(
        LIST_IDS["contract_register"],
        LIST_NAMES["contract_register"],
        item_id,
        fields,
    )
    return await get_contract(item_id)


async def add_contract_obligation(
    contract_id: str,
    body: ContractAddObligation,
) -> ObligationRead:
    """
    Create a Compliance Calendar entry linked to this contract.
    The contract reference is stored on the obligation as LinkedContractId.
    """
    from grc.schemas import ObligationCreate, ObligationRecurrence, ObligationType
    obligation = ObligationCreate(
        obligation_name=body.obligation_name,
        type=body.type,
        authority=body.authority,
        due_date=body.due_date,
        recurrence=body.recurrence,
        owner_id=body.owner_id,
        notes=body.notes,
        linked_contract_id=contract_id,
    )
    return await create_obligation(obligation)


async def soft_delete_contract(item_id: str) -> None:
    await soft_delete_list_item(
        LIST_IDS["contract_register"],
        LIST_NAMES["contract_register"],
        item_id,
    )
