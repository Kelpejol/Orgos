# =============================================================================
# grc/service.py — GRC business logic layer
# All business logic for Tier 1 registers. Calls graph/client.py for data.
# Handles: status calculation, person field resolution, field mapping.
# Depends on: graph/client.py, grc/constants.py, grc/schemas.py
# =============================================================================

import logging
from datetime import date, datetime, timezone
from typing import Optional

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
    ContractCreate,
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
#  Helpers
# =============================================================================

def _today() -> date:
    """Return today's date in UTC."""
    return datetime.now(timezone.utc).date()


def _calculate_obligation_status(due_date: date) -> ObligationStatus:
    """
    Calculate compliance obligation status from due date.
    This is a pure function — never stored in SharePoint, always recalculated.

    Rules:
      due_date < today                        → Overdue
      today <= due_date <= today+30 days      → Due Soon
      due_date > today+30 days                → Upcoming
    """
    today = _today()
    delta = (due_date - today).days

    if delta < 0:
        return ObligationStatus.OVERDUE
    elif delta <= CAL_DUE_SOON_THRESHOLD_DAYS:
        return ObligationStatus.DUE_SOON
    else:
        return ObligationStatus.UPCOMING


def _calculate_contract_status(end_date: Optional[date]) -> ContractStatus:
    """
    Calculate contract status from end/expiry date.

    Rules:
      end_date is None                              → Active (open-ended)
      end_date < today                              → Expired
      today <= end_date <= today+60 days            → Expiring Soon
      end_date > today+60 days                      → Active
    """
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


async def _build_person_ref(
    fields: dict, owner_field: str = "Owner"
) -> Optional[PersonRef]:
    """
    Build a PersonRef from SharePoint item fields.
    Resolves the Entra ID OID to display name and email via Graph API.
    """
    oid = fields.get(f"{owner_field}EntraId", "")
    if not oid:
        return None

    resolved = await resolve_user(oid)
    return PersonRef(
        oid=oid,
        display_name=resolved["display_name"],
        email=resolved["email"],
    )

# def _person_write_field(owner_field: str, entra_oid: str) -> dict:
#     """
#     Build the field dict for writing a person column to SharePoint.
#     Stores the Entra ID OID in a companion text field alongside the
#     SharePoint person column for reliable resolution.
#     """
#     return {
#         f"{owner_field}@odata.type": (
#             "#Microsoft.Azure.Connectors.SharePoint.SPListExpandedUser"
#         ),
#         f"{owner_field}Id": entra_oid,
#         # Store raw OID in a separate text column for direct Entra ID lookup
#         f"{owner_field}EntraId": entra_oid,
#     }



def _person_write_field(owner_field: str, entra_oid: str) -> dict:
    """
    Write person field to SharePoint.
    Stores the Entra ID OID in the companion text column only.
    The Person column requires a SharePoint-specific user lookup ID
    which is resolved in a separate step after initial creation.
    """
    return {
        f"{owner_field}EntraId": entra_oid,
    }


async def _sp_item_to_doc(item: dict) -> DocumentRead:
    """Convert a SharePoint List item dict to a DocumentRead schema."""
    fields = item.get("fields", {})
    return DocumentRead(
        id=str(item["id"]),
        document_code=fields.get(DOC_FIELDS["document_code"], ""),
        title=fields.get(DOC_FIELDS["title"], ""),
        type=fields.get(DOC_FIELDS["type"], "Policy"),
        department=fields.get(DOC_FIELDS["department"], ""),
        owner=await _build_person_ref(fields, "Owner"),
        current_version=fields.get(DOC_FIELDS["current_version"], "R01"),
        effective_date=_parse_date(fields.get(DOC_FIELDS["effective_date"])),
        next_review_date=_parse_date(fields.get(DOC_FIELDS["next_review_date"])),
        applicable_standards=_parse_multi_choice(
            fields.get(DOC_FIELDS["applicable_standards"])
        ),
        linked_controls_count=int(
            fields.get(DOC_FIELDS["linked_controls_count"], 0) or 0
        ),
        status=fields.get(DOC_FIELDS["status"], "Active"),
        created=_parse_datetime(item.get("createdDateTime")),
        modified=_parse_datetime(item.get("lastModifiedDateTime")),
    )


async def _sp_item_to_role(item: dict) -> RoleRead:
    fields = item.get("fields", {})
    
    # Determine assignment status
    holder_oid = fields.get(ROLE_FIELDS["current_holder_id"], "") or \
                 fields.get("CurrentHolderEntraId", "")
    raw_status = fields.get(ROLE_FIELDS["assignment_status"], "")
    
    # Calculate from holder presence if not explicitly set
    if raw_status:
        assignment_status = raw_status
    else:
        assignment_status = "Assigned" if holder_oid else "Unassigned"

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
    fields = item.get("fields", {})
    due_date = _parse_date(fields.get(CAL_FIELDS["due_date"])) or _today()
    return ObligationRead(
        id=str(item["id"]),
        obligation_name=fields.get(CAL_FIELDS["obligation_name"], ""),
        type=fields.get(CAL_FIELDS["type"], "Statutory"),
        authority=fields.get(CAL_FIELDS["authority"], ""),
        due_date=due_date,
        recurrence=fields.get(CAL_FIELDS["recurrence"], "Annual"),
        owner=await _build_person_ref(fields, "Owner"),
        status=_calculate_obligation_status(due_date),
        created=_parse_datetime(item.get("createdDateTime")),
        modified=_parse_datetime(item.get("lastModifiedDateTime")),
    )


async def _sp_item_to_contract(item: dict) -> ContractRead:
    """Convert a SharePoint List item dict to a ContractRead schema."""
    fields = item.get("fields", {})
    end_date = _parse_date(fields.get(CONTRACT_FIELDS["end_date"]))
    return ContractRead(
        id=str(item["id"]),
        contract_reference=fields.get(CONTRACT_FIELDS["contract_reference"], ""),
        title=fields.get(CONTRACT_FIELDS["title"], ""),
        counterparty=fields.get(CONTRACT_FIELDS["counterparty"], ""),
        contract_type=fields.get(CONTRACT_FIELDS["contract_type"], "Other"),
        owner=await _build_person_ref(fields, "Owner"),
        start_date=_parse_date(fields.get(CONTRACT_FIELDS["start_date"])),
        end_date=end_date,
        review_date=_parse_date(fields.get(CONTRACT_FIELDS["review_date"])),
        applicable_standards=_parse_multi_choice(
            fields.get(CONTRACT_FIELDS["applicable_standards"])
        ),
        status=_calculate_contract_status(end_date),
        linked_controls_count=int(
            fields.get(CONTRACT_FIELDS["linked_controls_count"], 0) or 0
        ),
        created=_parse_datetime(item.get("createdDateTime")),
        modified=_parse_datetime(item.get("lastModifiedDateTime")),
    )


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse ISO date string from SharePoint. Returns None on failure."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string from SharePoint. Returns None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_multi_choice(value: Optional[str]) -> list[str]:
    """Parse a semicolon or comma-separated multi-choice SharePoint field."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [v.strip() for v in value.replace(";#", ";").split(";") if v.strip()]


# =============================================================================
#  Document Register
# =============================================================================

async def get_documents(
    status: Optional[str] = None,
    department: Optional[str] = None,
) -> list[DocumentRead]:
    """
    Retrieve all approved controlled documents from the Document Register.

    Args:
        status: Filter by status e.g. "Active"
        department: Filter by department e.g. "ISMS"
    """
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
    return [await _sp_item_to_doc(item) for item in items]


async def get_document(item_id: str) -> DocumentRead:
    """Retrieve a single document by SharePoint item ID."""
    item = await get_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        item_id,
    )
    return _sp_item_to_doc(item)


async def create_document(doc: DocumentCreate) -> DocumentRead:
    """
    Create a new entry in the Document Register.
    Rule: Only approved documents enter this register.
    The Document Lifecycle screen (Tier 2) enforces this upstream.
    """
    fields: dict = {
        DOC_FIELDS["document_code"]: doc.document_code,
        DOC_FIELDS["title"]: doc.title,
        DOC_FIELDS["type"]: doc.type.value,
        DOC_FIELDS["department"]: doc.department,
        DOC_FIELDS["current_version"]: doc.current_version,
        DOC_FIELDS["effective_date"]: doc.effective_date.isoformat(),
        DOC_FIELDS["status"]: doc.status.value,
        DOC_FIELDS["applicable_standards"]: ";".join(doc.applicable_standards),
    }

    if doc.next_review_date:
        fields[DOC_FIELDS["next_review_date"]] = doc.next_review_date.isoformat()

    # Person field
    fields.update(_person_write_field("Owner", doc.owner_id))

    item = await create_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        fields,
    )
    return await _sp_item_to_doc(item)


async def update_document(item_id: str, doc: DocumentUpdate) -> DocumentRead:
    """Partially update a Document Register entry."""
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
        fields.update(_person_write_field("Owner", doc.owner_id))

    await update_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        item_id,
        fields,
    )
    return await get_document(item_id)


async def soft_delete_document(item_id: str) -> None:
    """Soft-delete: sets Status = 'Withdrawn'. Preserves audit trail."""
    await soft_delete_list_item(
        LIST_IDS["document_register"],
        LIST_NAMES["document_register"],
        item_id,
    )


# =============================================================================
#  Role Register
# =============================================================================

async def get_roles(department: Optional[str] = None) -> list[RoleRead]:
    """Retrieve all roles, optionally filtered by department."""
    odata_filter = f"fields/Department eq '{department}'" if department else None
    items = await get_list_items(
        LIST_IDS["role_register"],
        LIST_NAMES["role_register"],
        odata_filter=odata_filter,
    )
    return [await _sp_item_to_role(item) for item in items]


async def get_role(item_id: str) -> RoleRead:
    """Retrieve a single role by SharePoint item ID."""
    item = await get_list_item(
        LIST_IDS["role_register"], LIST_NAMES["role_register"], item_id
    )
    return await _sp_item_to_role(item)


async def create_role(role: RoleCreate) -> RoleRead:
    """Create a new role. If no holder provided, status is Unassigned."""
    assignment_status = "Assigned" if role.current_holder_id else "Unassigned"
    
    fields: dict = {
        ROLE_FIELDS["role_title"]:        role.role_title,
        ROLE_FIELDS["department"]:        role.department,
        ROLE_FIELDS["jd_reference"]:      role.jd_reference,
        ROLE_FIELDS["source_system"]:     role.source_system.value,
        ROLE_FIELDS["assignment_status"]: assignment_status,
    }
    if role.variant_terms:
        fields[ROLE_FIELDS["variant_terms"]] = role.variant_terms
    if role.current_holder_id:
        fields.update(_person_write_field("CurrentHolder", role.current_holder_id))

    item = await create_list_item(
        LIST_IDS["role_register"], LIST_NAMES["role_register"], fields
    )
    return await _sp_item_to_role(item)

async def update_role(item_id: str, role: RoleUpdate) -> RoleRead:
    """Partially update a Role Register entry."""
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
        fields[ROLE_FIELDS["variant_terms"]] = role.variant_terms
    if role.current_holder_id is not None:
        fields.update(_person_write_field("CurrentHolder", role.current_holder_id))

    await update_list_item(
        LIST_IDS["role_register"], LIST_NAMES["role_register"], item_id, fields
    )
    return await get_role(item_id)



async def assign_role_holder(item_id: str, holder_id: str) -> RoleRead:
    """
    Assign a person to an Unassigned role.
    Sets assignment_status to Assigned and maps the Entra ID OID.
    This is the only way roles get holders — through human confirmation,
    not through the create flow.
    """
    fields: dict = {
        ROLE_FIELDS["assignment_status"]: "Assigned",
    }
    fields.update(_person_write_field("CurrentHolder", holder_id))

    await update_list_item(
        LIST_IDS["role_register"],
        LIST_NAMES["role_register"],
        item_id,
        fields,
    )
    return await get_role(item_id)


async def get_unassigned_roles() -> list[RoleRead]:
    """Return all roles with no current holder — used by Work Hub urgency stream."""
    all_roles = await get_roles()
    return [r for r in all_roles if r.assignment_status == "Unassigned"]   


# =============================================================================
#  Compliance Calendar
# =============================================================================

async def get_obligations(
    obligation_type: Optional[str] = None,
) -> list[ObligationRead]:
    """Retrieve all compliance obligations. Status is calculated on read."""
    odata_filter = (
        f"fields/ObligationType eq '{obligation_type}'" if obligation_type else None
    )
    items = await get_list_items(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        odata_filter=odata_filter,
    )
    return [await _sp_item_to_obligation(item) for item in items]


async def get_obligation(item_id: str) -> ObligationRead:
    """Retrieve a single obligation."""
    item = await get_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
    )
    return await _sp_item_to_obligation(item)


async def get_overdue_obligations() -> list[ObligationRead]:
    """Return obligations where due_date has passed."""
    all_items = await get_obligations()
    return [o for o in all_items if o.status == ObligationStatus.OVERDUE]


async def get_due_soon_obligations() -> list[ObligationRead]:
    """Return obligations due within the next 30 days."""
    all_items = await get_obligations()
    return [o for o in all_items if o.status == ObligationStatus.DUE_SOON]


async def create_obligation(obligation: ObligationCreate) -> ObligationRead:
    """Create a new compliance obligation."""
    fields: dict = {
        CAL_FIELDS["obligation_name"]: obligation.obligation_name,
        CAL_FIELDS["type"]: obligation.type.value,
        CAL_FIELDS["authority"]: obligation.authority,
        CAL_FIELDS["due_date"]: obligation.due_date.isoformat(),
        CAL_FIELDS["recurrence"]: obligation.recurrence.value,
    }
    fields.update(_person_write_field("Owner", obligation.owner_id))

    item = await create_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        fields,
    )
    return await _sp_item_to_obligation(item)


async def update_obligation(item_id: str, obligation: ObligationUpdate) -> ObligationRead:
    """Partially update a compliance obligation."""
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

    await update_list_item(
        LIST_IDS["compliance_calendar"],
        LIST_NAMES["compliance_calendar"],
        item_id,
        fields,
    )
    return await get_obligation(item_id)


# =============================================================================
#  Contract Register
# =============================================================================

async def get_contracts(
    contract_type: Optional[str] = None,
) -> list[ContractRead]:
    """Retrieve all contracts. Status calculated on read."""
    odata_filter = (
        f"fields/ContractType eq '{contract_type}'" if contract_type else None
    )
    items = await get_list_items(
        LIST_IDS["contract_register"],
        LIST_NAMES["contract_register"],
        odata_filter=odata_filter,
    )
    return [await _sp_item_to_contract(item) for item in items]


async def get_contract(item_id: str) -> ContractRead:
    """Retrieve a single contract."""
    item = await get_list_item(
        LIST_IDS["contract_register"], LIST_NAMES["contract_register"], item_id
    )
    return await _sp_item_to_contract(item)


async def get_expiring_contracts() -> list[ContractRead]:
    """Return contracts expiring within the next 60 days."""
    all_contracts = await get_contracts()
    return [
        c for c in all_contracts
        if c.status == ContractStatus.EXPIRING_SOON
    ]


async def create_contract(contract: ContractCreate) -> ContractRead:
    """Create a new contract record."""
    fields: dict = {
        CONTRACT_FIELDS["contract_reference"]: contract.contract_reference,
        CONTRACT_FIELDS["title"]: contract.title,
        CONTRACT_FIELDS["counterparty"]: contract.counterparty,
        CONTRACT_FIELDS["contract_type"]: contract.contract_type.value,
        CONTRACT_FIELDS["applicable_standards"]: ";".join(contract.applicable_standards),
    }
    if contract.start_date:
        fields[CONTRACT_FIELDS["start_date"]] = contract.start_date.isoformat()
    if contract.end_date:
        fields[CONTRACT_FIELDS["end_date"]] = contract.end_date.isoformat()
    if contract.review_date:
        fields[CONTRACT_FIELDS["review_date"]] = contract.review_date.isoformat()

    fields.update(_person_write_field("Owner", contract.owner_id))

    item = await create_list_item(
        LIST_IDS["contract_register"],
        LIST_NAMES["contract_register"],
        fields,
    )
    return await _sp_item_to_contract(item)


async def update_contract(item_id: str, contract: ContractUpdate) -> ContractRead:
    """Partially update a contract record."""
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
    if contract.review_date is not None:
        fields[CONTRACT_FIELDS["review_date"]] = contract.review_date.isoformat()
    if contract.applicable_standards is not None:
        fields[CONTRACT_FIELDS["applicable_standards"]] = ";".join(
            contract.applicable_standards
        )

    await update_list_item(
        LIST_IDS["contract_register"],
        LIST_NAMES["contract_register"],
        item_id,
        fields,
    )
    return await get_contract(item_id)
