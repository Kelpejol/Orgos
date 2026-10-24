"""Read-only acceptance rules shared by previews and register writes."""

from doc_standards.roles import is_placeholder, names_several


def definition_refusal(item: dict) -> str:
    if not item.get("ControlId") or item.get("ResolutionKey"):
        return ""
    candidate = item.get("Candidate")
    owner = (candidate.get("accountable") or "") if isinstance(candidate, dict) else ""
    if names_several(owner) or is_placeholder(owner):
        problem = "names several roles" if names_several(owner) else "is a field name, not a role"
        return (f"Control {item['ControlId']} writes Control owner: “{owner}”, which {problem}. "
                "Acceptance refused. The document author must revise the document to name exactly one role "
                "that exists in Org Roles, then submit the revised definition for review.")
    return ""


def acceptance_refusal(item: dict) -> str:
    if item.get("ControlId") and not item.get("ResolutionKey"):
        return definition_refusal(item)
    if item.get("ItemType") not in (None, "", "Extraction"):
        return ""
    from agents.extractor.ollama_client import require_legacy_extraction

    try:
        require_legacy_extraction(item.get("DocumentType"), item.get("SourceDocumentCode", ""))
    except ValueError as exc:
        return str(exc)
    return ""


def legacy_accept_plan(item: dict, overrides: dict | None = None) -> dict:
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
        "Status": "Active" if owner else "Blocked",
    }
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
        f"status: {control['Status']}"
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
