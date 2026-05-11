# =============================================================================
# standards_map/router.py — Standards Map API
# GET /api/v1/standards/map           — all clauses with traffic lights
# GET /api/v1/standards/map/{clause}  — full chain for one clause
# Traffic lights calculated live from Control Register + Evidence Tracker
# Per DRG-QI-REF-DINT-01-26 Section 5.4
# =============================================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user
from config import settings
from graph.client import get_list_items
from graph.exceptions import GraphAPIError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/standards", tags=["Standards Map"])

# =============================================================================
#  ISO 27001:2022, ISO 9001:2015, NDPA clauses relevant to Dragnet
# =============================================================================

CLAUSES = [
    # ISO 27001:2022
    {
        "standard": "ISO 27001",
        "clause": "A.5.1",
        "title": "Policies for information security",
    },
    {
        "standard": "ISO 27001",
        "clause": "A.5.12",
        "title": "Classification of information",
    },
    {"standard": "ISO 27001", "clause": "A.5.15", "title": "Access control"},
    {"standard": "ISO 27001", "clause": "A.5.16", "title": "Identity management"},
    {
        "standard": "ISO 27001",
        "clause": "A.5.17",
        "title": "Authentication information",
    },
    {"standard": "ISO 27001", "clause": "A.5.18", "title": "Access rights"},
    {
        "standard": "ISO 27001",
        "clause": "A.5.25",
        "title": "Assessment of information security events",
    },
    {
        "standard": "ISO 27001",
        "clause": "A.5.26",
        "title": "Response to information security incidents",
    },
    {"standard": "ISO 27001", "clause": "A.6.1", "title": "Screening"},
    {
        "standard": "ISO 27001",
        "clause": "A.7.1",
        "title": "Physical security perimeter",
    },
    {"standard": "ISO 27001", "clause": "A.8.1", "title": "User endpoint devices"},
    {"standard": "ISO 27001", "clause": "A.8.24", "title": "Use of cryptography"},
    {
        "standard": "ISO 27001",
        "clause": "A.8.25",
        "title": "Secure development life cycle",
    },
    {"standard": "ISO 27001", "clause": "A.8.32", "title": "Change management"},
    # ISO 9001:2015
    {"standard": "ISO 9001", "clause": "7.5", "title": "Documented information"},
    {
        "standard": "ISO 9001",
        "clause": "8.4",
        "title": "Control of externally provided processes",
    },
    {
        "standard": "ISO 9001",
        "clause": "9.1",
        "title": "Monitoring, measurement, analysis",
    },
    {"standard": "ISO 9001", "clause": "9.2", "title": "Internal audit"},
    {
        "standard": "ISO 9001",
        "clause": "10.2",
        "title": "Nonconformity and corrective action",
    },
    # NDPA
    {"standard": "NDPA", "clause": "S.24", "title": "Data protection principles"},
    {"standard": "NDPA", "clause": "S.30", "title": "Lawful basis for processing"},
    {
        "standard": "NDPA",
        "clause": "S.39",
        "title": "Breach notification to Commission",
    },
    {
        "standard": "NDPA",
        "clause": "S.40",
        "title": "Breach notification to data subject",
    },
]


def _calculate_traffic_light(
    controls: list[dict],
    evidence_items: list[dict],
) -> str:
    """
    Calculate traffic light per DINT Section 5.4.
    Green:  all controls have accepted evidence, all owners assigned, nothing overdue
    Amber:  evidence due soon (≤7 days), submitted but not verified, or new control with no evidence yet
    Red:    evidence overdue, no controls, owner unassigned, evidence rejected
    Returns: "Green" | "Amber" | "Red"
    """
    if not controls:
        return "Red"

    for c in controls:
        if c.get("Status") == "Blocked":
            return "Red"
        if not c.get("OwnerEntraId"):
            return "Red"

    clause_evidence = [
        e
        for e in evidence_items
        if any(e.get("LinkedControlId") == c["id"] for c in controls)
    ]

    if not clause_evidence and controls:
        return "Amber"  # Controls exist but no evidence defined yet

    for e in clause_evidence:
        status = e.get("Status", "Pending")
        if status == "Overdue":
            return "Red"
        if status == "Rejected":
            return "Red"

    for e in clause_evidence:
        status = e.get("Status", "Pending")
        if status in ("Pending", "Due Soon"):
            return "Amber"
        if status == "Submitted":
            return "Amber"  # Awaiting verification

    return "Green"


# =============================================================================
#  Endpoints
# =============================================================================


@router.get("/map")
async def get_standards_map(
    standard: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """
    Returns all clauses with traffic lights calculated from live register data.
    Optional filter by standard: ISO 27001 | ISO 9001 | NDPA
    """
    try:
        # Fetch all controls and evidence items
        cr_items = await get_list_items(
            settings.control_register_list_id, "Control Register"
        )
        evd_items = await get_list_items(
            settings.evidence_tracker_list_id, "Evidence Tracker"
        )

        controls = [
            {
                "id": str(i["id"]),
                "ControlStatement": i.get("fields", {}).get("ControlStatement", ""),
                "ControlType": i.get("fields", {}).get("ControlType", ""),
                "ISOClause": i.get("fields", {}).get("ISOClause", ""),
                "OwnerRole": i.get("fields", {}).get("OwnerRole", ""),
                "OwnerEntraId": i.get("fields", {}).get("OwnerEntraId", ""),
                "Status": i.get("fields", {}).get("Status", "Active"),
            }
            for i in cr_items
        ]

        evidence = [
            {
                "id": str(i["id"]),
                "EvidenceDescription": i.get("fields", {}).get(
                    "EvidenceDescription", ""
                ),
                "EvidenceType": i.get("fields", {}).get("EvidenceType", ""),
                "Status": i.get("fields", {}).get("Status", "Pending"),
                "LinkedControlId": i.get("fields", {}).get("LinkedControlId", ""),
                "EvidenceLink": i.get("fields", {}).get("EvidenceLink", ""),
                "Frequency": i.get("fields", {}).get("Frequency", ""),
                "OwnerRole": i.get("fields", {}).get("OwnerRole", ""),
                "OwnerEntraId": i.get("fields", {}).get("OwnerEntraId", ""),
            }
            for i in evd_items
        ]

        # Build result per clause
        clauses_to_show = [
            c for c in CLAUSES if not standard or c["standard"] == standard
        ]

        result = []
        for clause_def in clauses_to_show:
            clause_code = clause_def["clause"]
            # Match controls to this clause (exact or partial match)
            clause_controls = [
                c for c in controls if c.get("ISOClause", "").startswith(clause_code)
            ]
            traffic = _calculate_traffic_light(clause_controls, evidence)
            evidence_accepted = sum(
                1
                for e in evidence
                if any(e.get("LinkedControlId") == c["id"] for c in clause_controls)
                and e.get("Status") == "Accepted"
            )
            result.append(
                {
                    **clause_def,
                    "controls_count": len(clause_controls),
                    "evidence_accepted": evidence_accepted,
                    "traffic_light": traffic,
                }
            )

        return result

    except Exception as exc:
        logger.exception("Standards map calculation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/map/{clause_code:path}")
async def get_clause_detail(
    clause_code: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Full chain for one clause: controls, evidence items, owners, evidence links.
    This is what an auditor sees when they drill down on a clause.
    """
    try:
        clause_def = next((c for c in CLAUSES if c["clause"] == clause_code), None)
        if not clause_def:
            raise HTTPException(
                status_code=404, detail=f"Clause {clause_code} not found"
            )

        cr_items = await get_list_items(
            settings.control_register_list_id, "Control Register"
        )
        evd_items = await get_list_items(
            settings.evidence_tracker_list_id, "Evidence Tracker"
        )

        controls = [
            i
            for i in cr_items
            if i.get("fields", {}).get("ISOClause", "").startswith(clause_code)
        ]
        control_ids = {str(c["id"]) for c in controls}
        evidence = [
            i
            for i in evd_items
            if i.get("fields", {}).get("LinkedControlId", "") in control_ids
        ]

        def fmt_control(item):
            f = item.get("fields", {})
            return {
                "id": str(item["id"]),
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

        def fmt_evidence(item):
            f = item.get("fields", {})
            return {
                "id": str(item["id"]),
                "EvidenceDescription": f.get("EvidenceDescription", ""),
                "EvidenceType": f.get("EvidenceType", ""),
                "SourceSystem": f.get("SourceSystem", ""),
                "Frequency": f.get("Frequency", ""),
                "Status": f.get("Status", "Pending"),
                "EvidenceLink": f.get("EvidenceLink", ""),
                "ValidationCriteria": f.get("ValidationCriteria", ""),
                "OwnerRole": f.get("OwnerRole", ""),
                "LinkedControlId": f.get("LinkedControlId", ""),
                "LastCollected": f.get("LastCollected", ""),
            }

        fmt_controls = [fmt_control(c) for c in controls]
        fmt_evidence = [fmt_evidence(e) for e in evidence]
        traffic = _calculate_traffic_light(
            [{"id": str(c["id"]), **c.get("fields", {})} for c in controls],
            [{"id": str(e["id"]), **e.get("fields", {})} for e in evidence],
        )

        return {
            **clause_def,
            "traffic_light": traffic,
            "controls": fmt_controls,
            "evidence": fmt_evidence,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Clause detail failed for {clause_code}")
        raise HTTPException(status_code=500, detail=str(exc))
