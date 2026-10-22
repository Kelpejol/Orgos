# =============================================================================
# doc_standards/gate.py — the CDI checks as a gate in Document Lifecycle
#
# The checks in checks.py are the CDI Procedure's V01–V24. This is where they
# stop a document: at the Review → Sensitisation step, and again at approval.
#
#   mode (settings.standard_gate)
#     off       not run at the gate
#     advisory  run and shown; a document that WOULD be stopped says so, and is
#               not stopped. The default — enforcing 18 BLOCK rules would halt
#               nearly every existing document at once.
#     enforce   a BLOCK failure, or a FLAG nobody has decided, stops it.
#
#   BLOCK    can never be waived. CDI: "BLOCK" means blocked.
#   FLAG     the Compliance Executive "decides FLAG results" (CDI): Compliance
#            records a decision with a reason. It is remembered against the exact
#            findings, so a DIFFERENT problem on the same check reopens it.
#   REPORT   shown, never stops anything.
#   could not check / not built   never pass and are listed — but they do not
#            stop a document either, or the first minutes after a restart (the
#            library not yet read) would stop everything. The gate says how many
#            checks it could not make, so "ready" is never read as "fully checked".
#
# A gate that cannot run at all (the file cannot be read, a service is down)
# does not wave the document through in enforce mode: it stops it and says why.
# =============================================================================

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from cdi.parser import parse_document
from cdi.reader import UnsupportedDocument
from config import settings
from doc_standards import service
from doc_standards.checks import FAIL, FLAG, run_checks
from lifecycle.merge import merge, scan_markers
from lifecycle.schemas import MergeContext

logger = logging.getLogger(__name__)

MODES = ("off", "advisory", "enforce")
MIN_REASON = 10
_CACHE_SECONDS = 300
_cache: dict[str, tuple[float, dict, list]] = {}


def invalidate() -> None:
    """Forget cached results. Called when a role changes: a role someone has just created must
    be found by the very next check, not five minutes later."""
    _cache.clear()


def mode() -> str:
    value = (settings.standard_gate or "").strip().lower()
    return value if value in MODES else "advisory"


# ── decisions on FLAGs ──────────────────────────────────────────────────────

def fingerprint(result: dict) -> str:
    """Identifies WHAT a check found, so a decision covers those findings and no others."""
    material = sorted((f.get("where", ""), f.get("message", "")) for f in result.get("findings", []))
    return hashlib.sha256(json.dumps([result["id"], material], ensure_ascii=False).encode()).hexdigest()[:16]


def parse_decisions(raw) -> dict[str, dict]:
    """The stored decisions, by check id. Tolerant of blank or damaged data."""
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    return {d["check"]: d for d in data if isinstance(d, dict) and d.get("check")}


def dump_decisions(decisions: dict[str, dict]) -> str:
    return json.dumps(sorted(decisions.values(), key=lambda d: d["check"]), ensure_ascii=False)


def record_decision(decisions: dict[str, dict], report: dict, check_id: str, accept: bool,
                    reason: str, by_name: str, by_oid: str) -> dict[str, dict]:
    """Add or withdraw a decision. Only a FLAG that is currently raised can be decided."""
    result = next((r for r in report["results"] if r["id"] == check_id), None)
    out = dict(decisions)
    if not accept:
        out.pop(check_id, None)
        return out
    if result is None or result["status"] != FLAG:
        raise ValueError(f"{check_id} has no flag to decide. Only a flagged check can be accepted; "
                         "a blocking problem cannot be waived.")
    if len((reason or "").strip()) < MIN_REASON:
        raise ValueError(f"Give a reason of at least {MIN_REASON} characters: it is the audit trail.")
    out[check_id] = {"check": check_id, "fingerprint": fingerprint(result), "reason": reason.strip(),
                     "by": by_name, "by_oid": by_oid, "at": datetime.now(timezone.utc).isoformat()}
    return out


def attach_decisions(report: dict, decisions: dict[str, dict]) -> None:
    """Mark each FLAG result with its decision — if one exists AND still covers what was found."""
    for r in report["results"]:
        if r["status"] != FLAG:
            continue
        d = decisions.get(r["id"])
        r["decision"] = d if d and d.get("fingerprint") == fingerprint(r) else None
        r["decision_stale"] = bool(d and d.get("fingerprint") != fingerprint(r))


def summarise(report: dict) -> dict:
    results = report["results"]
    blocking = [r["id"] for r in results if r["status"] == FAIL]
    flags = [r for r in results if r["status"] == FLAG]
    undecided = [r["id"] for r in flags if not r.get("decision")]
    return {
        "mode": mode(), "enforced": mode() == "enforce",
        "ready": not blocking and not undecided,
        "blocking": blocking, "undecided_flags": undecided,
        "decided_flags": [r["id"] for r in flags if r.get("decision")],
        "could_not_check": [r["id"] for r in results if r["status"] == "could_not_check"],
        "not_built": [r["id"] for r in results if r["status"] == "not_built"],
        "checks_run": report["checks_run"], "checks_total": report["checks_total"],
    }


def block_message(report: dict, summary: dict) -> str:
    by_id = {r["id"]: r for r in report["results"]}
    parts = []
    for cid in summary["blocking"]:
        r = by_id[cid]
        parts.append(f"{cid} {r['name']} ({len(r['findings'])} problem(s))")
    text = "The document does not meet the CDI standard yet. "
    if parts:
        text += "Blocking: " + "; ".join(parts) + ". "
    if summary["undecided_flags"]:
        text += ("Compliance must decide: " + ", ".join(summary["undecided_flags"]) + ". ")
    return text + "Open “Document standard” on the card to see where and how to fix each."


# ── evaluating a file ───────────────────────────────────────────────────────

class Unreadable(Exception):
    """The file cannot be read at all, so no check could run."""


async def evaluate_bytes(file_bytes: bytes, filename: str, *, wait_for_library: bool) -> tuple[dict, list]:
    key = hashlib.sha256(file_bytes + filename.encode()).hexdigest()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1], hit[2]
    try:
        parsed = await asyncio.to_thread(parse_document, file_bytes, filename)
    except UnsupportedDocument as exc:
        raise Unreadable(str(exc))
    except Exception as exc:
        raise Unreadable(f"The document could not be read ({type(exc).__name__}).")
    ctx, notes = await service.build_context(parsed, wait_for_library=wait_for_library)
    report = await asyncio.to_thread(run_checks, parsed, filename, file_bytes, ctx)
    if ctx.index is not None and ctx.register is not None and ctx.catalogue is not None and ctx.roles is not None:
        _cache[key] = (time.monotonic(), report, notes)       # never cache a result made without its context
    return report, notes


async def evaluate_item(doc: dict, *, wait_for_library: bool = False) -> dict:
    """The standard check of a Lifecycle item's file, with its decisions applied."""
    from graph.client import download_file_from_sharepoint
    from lifecycle.router import _filename_from_sharepoint_url

    url = doc.get("SharePointFileUrl")
    if not url:
        return {"mode": mode(), "available": False, "reason": "There is no file yet."}
    data, content_type = await download_file_from_sharepoint(url)
    filename = _filename_from_sharepoint_url(url, content_type)
    check_bytes = data
    if filename.lower().endswith(".docx"):
        try:
            has_markers = bool(scan_markers(data))
        except Exception:                     # not a Word file at all, whatever its name says
            return {"mode": mode(), "available": False, "unreadable": True,
                    "reason": f"“{filename}” could not be opened as a Word document."}
        if has_markers:                       # a CDT source: judge it as a reader will see it
            check_bytes = merge(data, MergeContext.from_lifecycle_dict(doc)).document
    try:
        report, notes = await evaluate_bytes(check_bytes, filename, wait_for_library=wait_for_library)
    except Unreadable as exc:
        return {"mode": mode(), "available": False, "unreadable": True, "reason": str(exc)}
    report = json.loads(json.dumps(report))                    # never mutate the cached copy
    decisions = parse_decisions(doc.get("StandardsDecisions"))
    attach_decisions(report, decisions)
    return {"mode": mode(), "available": True, "report": report, "context_notes": notes,
            "gate": summarise(report)}


async def enforce(doc: dict) -> Optional[dict]:
    """
    The gate. Does nothing unless the mode is `enforce`, where it raises 422 if the
    document does not clear it. (In advisory mode results are shown on demand, so
    no time is spent evaluating at the moment a document is moved.)
    """
    if mode() != "enforce":
        return None            # advisory shows results (panel, approval preview); it never stops anything
    try:
        result = await evaluate_item(doc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("The standard check could not run for lifecycle item %s", doc.get("id"))
        if mode() == "enforce":
            raise HTTPException(status_code=503, detail=(
                f"The document standard could not be checked ({type(exc).__name__}), so the document "
                "cannot be passed on. Try again in a moment."))
        return None
    if not result.get("available"):
        if mode() == "enforce" and result.get("unreadable"):
            raise HTTPException(status_code=422, detail=(
                f"The document standard cannot be checked: {result['reason']}"))
        return result
    gate = result["gate"]
    if mode() == "enforce" and not gate["ready"]:
        raise HTTPException(status_code=422, detail=block_message(result["report"], gate))
    return result
