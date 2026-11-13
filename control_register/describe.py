# =============================================================================
# control_register/describe.py — what a control is, in words a person reads
#
# Screens used to lead with "ICX-001" and "DRG-QI-PRO-ICX", which say nothing to the people
# who must carry the control out. A control is described by what it requires (its title where
# the document gives one, else its requirement, shortened) and by the NAME of the document that
# defines it. The Control ID and document code stay available for the detail view and search.
# Pure: a Control Register row's fields in, words out.
# =============================================================================

from __future__ import annotations

import json
import re
from typing import Optional

NAME_LIMIT = 120


def _definition(fields: dict) -> dict:
    try:
        return json.loads(fields.get("DefinitionJson") or "null") or {}
    except (TypeError, ValueError):
        return {}


def short_name(text: str, limit: int = NAME_LIMIT) -> str:
    """The first sentence of `text`, cut at a word near `limit` characters."""
    text = re.sub(r"\s+", " ", text or "").strip()
    first = re.split(r"(?<=[.;:])\s", text, maxsplit=1)[0].rstrip(".;: ")
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(" ", 1)[0].rstrip(",;:- ")
    return f"{cut}…"


def describe(fields: dict) -> dict:
    """ControlName, ControlSummary, ControlDocument (+ the codes, for detail and search)."""
    d = _definition(fields)
    defined_in = d.get("defined_in") or {}
    requirement = (d.get("requirement") or fields.get("ControlStatement") or "").strip()
    title = (d.get("title") or "").strip()
    code = (defined_in.get("code") or fields.get("SourceDocument") or "").strip()
    return {
        "ControlName":         title or short_name(requirement),
        "ControlSummary":      requirement,
        "ControlDocument":     (defined_in.get("title") or "").strip() or code,
        "ControlDocumentCode": code,
        "ControlId":           (d.get("control_id") or fields.get("ControlId") or "").strip(),
        "ControlTrigger":      (d.get("trigger") or "").strip(),
    }


def by_control_id(control_rows: list[dict]) -> dict[str, dict]:
    """{Control ID: describe(row)} for Control Register items (as Graph returns them)."""
    out: dict[str, dict] = {}
    for item in control_rows:
        fields = item.get("fields", item)
        desc = describe(fields)
        if desc["ControlId"] and desc["ControlId"] not in out:
            out[desc["ControlId"]] = desc
    return out


def for_record(record: dict, controls: dict[str, dict]) -> Optional[dict]:
    """The description of the control a record evidences, if that control is known."""
    return controls.get((record.get("LinkedControlId") or "").strip())
