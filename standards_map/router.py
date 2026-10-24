# =============================================================================
# standards_map/router.py — Standards Map API
# GET /api/v1/standards/map           — all clauses with traffic lights
# GET /api/v1/standards/map/{clause}  — full chain for one clause
# Traffic lights calculated live from Control Register + Record Tracker
# Per DRG-QI-REF-DINT-01-26 Section 5.4
# =============================================================================

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth.validator import CurrentUser, get_current_user
from config import settings
from graph.client import get_list_items
# The clauses — and how a control is matched to one — come from the catalogue,
# shared with the Gap Analyzer.
from standards_map import catalogue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/standards", tags=["Standards Map"])

# Short-TTL cache for the whole-map endpoint. The map is read on every dashboard
# load and recomputed from two full register reads; a few seconds of staleness
# is fine for a traffic-light overview and spares Graph the repeated scans.
_MAP_CACHE_TTL_SECONDS = 15.0
_map_cache: dict[str, tuple[float, list]] = {}

def _calculate_traffic_light(
    controls: list[dict],
    clause_records: list[dict],
    ownership=None,
) -> str:
    """
    Calculate traffic light per DINT Section 5.4.
    Green:  all controls have accepted records, all owners assigned, nothing overdue
    Amber:  record due soon (≤7 days), submitted but not verified, or new control with no record yet
    Red:    record overdue, no controls, owner unassigned, record rejected
    Returns: "Green" | "Amber" | "Red"

    `clause_records` must already be scoped to `controls` (the caller indexes
    records by control id — this avoids an O(controls × records) scan here).

    Ownership is judged by resolving the Control owner's OwnerRole to people
    via `ownership`, whose legacy directory-title fallback remains — NOT by OwnerEntraId,
    which the accept cascade never populates.
    """
    if not controls:
        return "Red"

    for c in controls:
        if c.get("Status") == "Blocked":
            return "Red"
        owner_role = c.get("OwnerRole") or ""
        if ownership is not None:
            if not ownership.has_owner(owner_role):
                return "Red"
        elif not owner_role:
            # No index available — fall back to "a role is named at all".
            return "Red"

    if not clause_records:
        return "Amber"  # Controls exist but no record defined yet

    for r in clause_records:
        status = r.get("Status", "Pending")
        if status == "Overdue":
            return "Red"
        if status == "Rejected":
            return "Red"

    for r in clause_records:
        status = r.get("Status", "Pending")
        if status in ("Pending", "Due Soon"):
            return "Amber"
        if status == "Submitted":
            return "Amber"  # Awaiting verification

    return "Green"


# =============================================================================
#  Endpoints
# =============================================================================


async def _registers() -> tuple[list[dict], dict[str, list[dict]]]:
    """Controls (each with its mapped clauses) and records grouped by control."""
    cr_items = await get_list_items(settings.control_register_list_id, "Control Register")
    record_items = await get_list_items(settings.evidence_tracker_list_id, "Evidence Tracker")

    controls = []
    for item in cr_items:
        f = item.get("fields", {})
        controls.append({"id": str(item["id"]), **f, "_refs": catalogue.control_mapping(f)})

    # One control may need several records: group them, never keep the last.
    records_by_control: dict[str, list[dict]] = {}
    for item in record_items:
        f = item.get("fields", {})
        records_by_control.setdefault(f.get("LinkedControlId", ""), []).append(
            {"id": str(item["id"]), **f}
        )
    return controls, records_by_control


def _controls_for(row: catalogue.Clause, controls: list[dict]) -> list[dict]:
    return [c for c in controls if any(catalogue.covers(row, r) for r in c["_refs"])]


@router.get("/map")
async def get_standards_map(
    standard: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """
    Every clause Dragnet must cover, plus every clause a control maps to,
    each with a traffic light calculated from the live registers.
    Optional filter by standard: ISO 27001 | ISO 9001 | ISO 22301 | NDPA | …
    """
    cache_key = standard or "__all__"
    cached = _map_cache.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    try:
        controls, records_by_control = await _registers()

        from ownership.resolver import get_ownership_index
        ownership = await get_ownership_index()

        rows: dict[str, tuple[catalogue.Clause, Optional[str]]] = {
            c.key: (c, requires) for c, requires in catalogue.applicable_clauses()
        }
        for c in catalogue.rows_for(r for ctrl in controls for r in ctrl["_refs"]):
            rows.setdefault(c.key, (c, None))

        result = []
        for row, requires in rows.values():
            if standard and row.standard != standard:
                continue
            clause_controls = _controls_for(row, controls)
            clause_records = [r for c in clause_controls for r in records_by_control.get(c["id"], [])]
            result.append({
                "standard": row.standard,
                "clause": row.clause,
                "title": row.title,
                "applicable": requires is not None,
                "requires": requires,
                "controls_count": len(clause_controls),
                "records_accepted": sum(1 for r in clause_records if r.get("Status") == "Accepted"),
                "traffic_light": _calculate_traffic_light(clause_controls, clause_records, ownership),
            })

        _map_cache[cache_key] = (time.monotonic() + _MAP_CACHE_TTL_SECONDS, result)
        return result

    except Exception as exc:
        logger.exception("Standards map calculation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/map/{clause_code:path}")
async def get_clause_detail(
    clause_code: str,
    standard: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Full chain for one clause: controls, record items, owners, record links.
    This is what an auditor sees when they drill down on a clause.

    `standard` says which standard's clause is meant. Without it, a clause
    number shared by several standards (7.5 is in ISO 27001, 9001 and 22301)
    cannot be resolved and is refused rather than guessed.
    """
    try:
        if standard:
            row = catalogue.clause(standard, clause_code)
        else:
            # Across the WHOLE catalogue: once a control maps to ISO 27001 7.5,
            # the map shows it beside ISO 9001 7.5, and a bare "7.5" could be
            # either.
            candidates = [c for c in catalogue.CLAUSES.values() if c.clause == clause_code]
            if len(candidates) > 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"Clause {clause_code} exists in more than one standard "
                           f"({', '.join(c.standard for c in candidates)}); say which.",
                )
            row = candidates[0] if candidates else None
        if row is None:
            raise HTTPException(status_code=404, detail=f"Clause {clause_code} not found")

        controls, records_by_control = await _registers()
        clause_controls = _controls_for(row, controls)
        clause_records = [r for c in clause_controls for r in records_by_control.get(c["id"], [])]

        def fmt_control(f: dict) -> dict:
            return {
                "id": f["id"],
                "ControlStatement": f.get("ControlStatement", ""),
                "ControlType": f.get("ControlType", ""),
                "OwnerRole": f.get("OwnerRole", ""),
                "OwnerEntraId": f.get("OwnerEntraId", ""),
                "RiskImplication": f.get("RiskImplication", ""),
                "EscalationNote": f.get("EscalationNote", ""),
                "Status": f.get("Status", "Active"),
                "SourceDocument": f.get("SourceDocument", ""),
                "SourceClause": f.get("SourceClause", ""),
            }

        def fmt_record(f: dict) -> dict:
            return {
                "id": f["id"],
                "RecordDescription": f.get("EvidenceDescription", ""),
                "EvidenceType": f.get("EvidenceType", ""),
                "SourceSystem": f.get("SourceSystem", ""),
                "Frequency": f.get("Frequency", ""),
                "Status": f.get("Status", "Pending"),
                "RecordLink": f.get("EvidenceLink", ""),
                "ValidationCriteria": f.get("ValidationCriteria", ""),
                "OwnerRole": f.get("OwnerRole", ""),
                "LinkedControlId": f.get("LinkedControlId", ""),
                "LastCollected": f.get("LastCollected", ""),
            }

        from ownership.resolver import get_ownership_index
        ownership = await get_ownership_index()
        return {
            "standard": row.standard,
            "clause": row.clause,
            "title": row.title,
            "traffic_light": _calculate_traffic_light(clause_controls, clause_records, ownership),
            "controls": [fmt_control(c) for c in clause_controls],
            "records": [fmt_record(r) for r in clause_records],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Clause detail failed for {clause_code}")
        raise HTTPException(status_code=500, detail=str(exc))
