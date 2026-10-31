"""Read-only acceptance rules shared by previews and register writes."""

from doc_standards.roles import is_placeholder, names_several


def owner_problem(owner: str, is_role=None) -> str:
    """Why this Control owner can't be accepted as written, or "". `is_role` (is this text a role in
    Org Roles?) lets "CISO and DPO" be told apart from a role whose own name contains "and"."""
    if names_several(owner, is_role):
        return "names several roles"
    if is_placeholder(owner):
        return "is a field name, not a role"
    return ""


def definition_refusal(item: dict, is_role=None) -> str:
    if not item.get("ControlId") or item.get("ResolutionKey"):
        return ""
    candidate = item.get("Candidate")
    owner = (candidate.get("accountable") or "") if isinstance(candidate, dict) else ""
    problem = owner_problem(owner, is_role)
    if problem:
        return (f"Control {item['ControlId']} writes Control owner: “{owner}”, which {problem}. "
                "Acceptance refused. The document author must revise the document to name exactly one role "
                "that exists in Org Roles, then submit the revised definition for review.")
    return ""


def acceptance_refusal(item: dict, is_role=None, owner: str | None = None) -> str:
    """Why this item can't be accepted, or "". For an older extraction, `owner` is the Control owner
    the reviewer is accepting (an edit may change it); it must be one role, not a field name."""
    if item.get("ControlId") and not item.get("ResolutionKey"):
        return definition_refusal(item, is_role)
    if item.get("ItemType") not in (None, "", "Extraction"):
        return ""
    from agents.extractor.ollama_client import require_legacy_extraction

    try:
        require_legacy_extraction(item.get("DocumentType"), item.get("SourceDocumentCode", ""))
    except ValueError as exc:
        return str(exc)
    owner = item.get("ProposedOwnerRole", "") if owner is None else owner
    problem = owner_problem(owner or "", is_role)
    if problem:
        return (f"The proposed Control owner “{owner}” {problem}. Choose one role that exists in Org Roles "
                "(Edit before accepting).")
    return ""


def legacy_accept_plan(item: dict, overrides: dict | None = None, resolve=None) -> dict:
    """What accepting an older extraction creates. With `resolve` (OwnershipIndex.resolve) the
    control's status is decided by the same rule as every other control: Active only when its
    Control owner is a role in Org Roles. Without it the status is left for acceptance to decide."""
    overrides = overrides or {}

    def value(override, field, default=""):
        return overrides.get(override) or item.get(field, default) or ""

    statement = value("control_statement", "ControlStatement")
    owner = value("proposed_owner", "ProposedOwnerRole")
    control = {
        "Title": statement[:255], "ControlStatement": statement,
        "ControlType": value("control_type", "ControlType"),
        "OwnerRole": owner, "OwnerEntraId": "",
        "ISOClause": value("iso_clause", "ISOClause"),
        "SourceDocument": item.get("SourceDocumentCode", ""),
        "SourceClause": item.get("SourceClause", ""),
        "RiskImplication": (item.get("RiskStatement") or "")[:500],
    }
    if resolve is not None:
        from control_register.definitions import decide_status
        control["Status"], control["BlockedReason"] = decide_status({"accountable": owner}, resolve)
    else:
        control["Status"] = ""
    evidence_type = value("evidence_type", "EvidenceType")
    undefined = item.get("EvidenceUndefined")
    if isinstance(undefined, str):
        undefined = undefined.lower() == "true"
    if evidence_type and undefined and item.get("EvidenceType"):
        undefined = False
    record = None
    if evidence_type and not undefined:
        description = value("evidence_description", "EvidenceDescription")
        record = {
            "Title": description[:255] if description else f"Evidence for: {statement[:200]}",
            "EvidenceDescription": description, "EvidenceType": evidence_type,
            "SourceSystem": value("evidence_source_system", "EvidenceSourceSystem"),
            "Frequency": value("evidence_frequency", "EvidenceFrequency"),
            "CollectionMethod": value("evidence_collection_method", "EvidenceCollectionMethod"),
            "OwnerRole": value("evidence_owner_role", "EvidenceOwnerRole", owner),
            "ValidationCriteria": value("evidence_validation_criteria", "EvidenceValidationCriteria"),
            "Status": "Pending", "SourceDocument": item.get("SourceDocumentCode", ""),
        }
    return {"control": control, "record": record}


def legacy_accept_preview(plan: dict) -> dict:
    control, record = plan["control"], plan["record"]
    statement = control["ControlStatement"]
    creates = [{"register": "Control Register", "detail": (
        f"{control['ControlType'] or 'Control'} — “{statement[:140]}"
        f"{'…' if len(statement) > 140 else ''}”, Control owner: {control['OwnerRole'] or 'Unknown'}, "
        f"status: {control['Status'] or 'Active if its Control owner is a role in Org Roles, otherwise Blocked'}"
    )}]
    warnings = []
    if record:
        creates.append({"register": "Record Tracker", "detail": (
            f"{record['EvidenceType']} record — {record['EvidenceDescription'][:120] or record['Title']}, "
            f"frequency: {record['Frequency'] or 'not set'}, kept by: {record['OwnerRole'] or 'not set'}, "
            "status: Pending"
        )})
    else:
        warnings.append("No Record Tracker entry will be created: evidence is undefined or has no type. "
                        "The control chain will be incomplete until evidence is designed.")
    creates.append({"register": "Audit Log", "detail": "Decision record — reviewer, rationale, cascade result."})
    if not control["OwnerRole"]:
        warnings.append("No Control owner proposed — the control will be created as Blocked (unassigned owner).")
    return {"creates": creates, "warnings": warnings}
