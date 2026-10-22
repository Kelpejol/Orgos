# =============================================================================
# evidence/obligations.py — evidence obligations, one per control × record
#
# A confirmed control names the records that prove it operated (its Evidence
# field, by Record ID). Each control–record pair is one obligation: produce
# that record, and have it checked, on a schedule. One control can need
# several records, so evidence is tracked per link, not per control.
#
# Two frequencies, never one (architecture plan §9):
#   • operating trigger — when the control runs; the definition's Trigger
#   • check frequency   — how often we confirm the proof exists; stated by a
#     person (documents rarely state it). Until set, the obligation is
#     Unscheduled and says so. A cadence word in the trigger ("quarterly") is
#     offered as a suggestion, never applied silently.
#
# Reference at source: the obligation points at the record's authoritative
# location from the Records Catalogue. A submission is a reference to the
# record where it lives plus the date it was produced; it is uploaded into
# OrgOS only when OrgOS itself is that location (system S09).
#
# Pure: no I/O.
# =============================================================================

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

ORGOS_SYSTEM_ID = "S09"
DUE_SOON_DAYS = 14

# (pattern, days) — cadence words as they appear in triggers and schedules
_CADENCES = [
    (r"\bdaily\b|\beach day\b|\bevery day\b", 1),
    (r"\bweekly\b|\beach week\b|\bevery week\b", 7),
    (r"\bmonthly\b|\beach month\b|\bevery month\b", 30),
    (r"\bquarterly\b|\beach quarter\b|\bevery quarter\b", 91),
    (r"\bsemi-?annual(?:ly)?\b|\bbi-?annual(?:ly)?\b|\btwice a year\b|\bevery six months\b", 182),
    (r"\bannual(?:ly)?\b|\byearly\b|\bonce a year\b|\beach year\b|\bevery year\b", 365),
]
_DAYS = re.compile(r"^\s*(\d{1,4})\s*(day|days|d)\s*$", re.I)
_NAMED = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 91,
          "semi-annually": 182, "semi-annual": 182, "annually": 365, "annual": 365}


def parse_frequency(text: str) -> Optional[int]:
    """'quarterly' → 91, '90 days' → 90; None if not a schedule this reads."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in _NAMED:
        return _NAMED[t]
    m = _DAYS.match(t)
    if m:
        return int(m.group(1)) or None
    return None


def suggest_frequency(trigger: str) -> Optional[tuple[int, str]]:
    """
    A check frequency suggested by a cadence word in the operating trigger:
    (days, the word as written). One cadence only — a trigger naming two
    ("monthly review, annual audit") suggests nothing.
    """
    found = []
    for pattern, days in _CADENCES:
        m = re.search(pattern, trigger or "", re.I)
        if m:
            found.append((days, m.group(0)))
    return found[0] if len(found) == 1 else None


# ── an obligation as generated from a confirmed control ─────────────────────

@dataclass
class Obligation:
    key: str                  # "CDI-001|REC-0623"
    control_id: str
    record_id: str
    record_name: str          # the Catalogue's name, else as the document wrote it
    control_title: str
    operating_trigger: str
    owner_role: str           # who produces it: the Control owner (older documents: the executing role, else the accountable)
    defined_in: str
    location: str = ""        # the Catalogue's authoritative location
    system_id: str = ""
    custodian: str = ""
    suggested_frequency_days: Optional[int] = None
    suggested_frequency_basis: str = ""

    def fields(self) -> dict:
        """Generated fields only — schedule and submission state are never overwritten."""
        return {
            "Title": f"{self.control_id} · {self.record_id} {self.record_name}"[:255],
            "ObligationKey": self.key,
            "LinkedControlId": self.control_id,
            "RecordId": self.record_id,
            "EvidenceDescription": self.record_name,
            "OperatingTrigger": self.operating_trigger,
            "OwnerRole": self.owner_role,
            "SourceDocument": self.defined_in,
            "SourceSystem": self.location,
            "Custodian": self.custodian,
            "SuggestedFrequencyDays": self.suggested_frequency_days or 0,
            "SuggestedFrequencyBasis": self.suggested_frequency_basis,
        }


def obligations_for(definition: dict, catalogue: Optional[dict] = None) -> list[Obligation]:
    """
    One obligation per Record ID the control's evidence names. A record named
    without an ID makes no obligation — it can't be found; Gap Analysis
    reports it. A withdrawn duplicate proposal makes none either.
    """
    out: dict[str, Obligation] = {}
    cid = definition["control_id"]
    owner = (definition.get("executing") or definition.get("accountable") or "").strip()
    suggestion = suggest_frequency(definition.get("trigger", ""))
    for ref in definition.get("evidence") or []:
        rid = ref.get("record_id")
        if not rid or rid in out:
            continue
        entry = (catalogue or {}).get(rid)
        if entry is not None and entry.withdrawn:
            continue
        out[rid] = Obligation(
            key=f"{cid}|{rid}",
            control_id=cid,
            record_id=rid,
            record_name=(entry.name if entry else "") or ref.get("name", ""),
            control_title=definition.get("title", ""),
            operating_trigger=definition.get("trigger", ""),
            owner_role=owner,
            defined_in=definition.get("defined_in_label", ""),
            location=entry.location if entry else "",
            system_id=entry.system_id if entry else "",
            custodian=entry.custodian if entry else "",
            suggested_frequency_days=suggestion[0] if suggestion else None,
            suggested_frequency_basis=(f"Trigger says “{suggestion[1]}”" if suggestion else ""),
        )
    return list(out.values())


# ── reconciling with the Evidence Tracker ───────────────────────────────────

@dataclass
class ObligationAction:
    kind: str                 # create | update | retire
    key: str
    fields: dict
    item_id: str = ""


RETIRED = "Withdrawn"


def _same(stored, generated) -> bool:
    """SharePoint returns number columns as floats and blanks as None."""
    if isinstance(generated, int):
        try:
            return int(float(stored or 0)) == generated
        except (TypeError, ValueError):
            return False
    return (stored or "") == generated


def plan_obligations(controls: list[dict], existing: list[dict],
                     catalogue: Optional[dict] = None) -> list[ObligationAction]:
    """
    `controls`: live Control Register rows ({control_id, status, definition}).
    `existing`: Evidence Tracker items. Creates what's missing, refreshes
    generated fields that changed, retires links no longer stated. Rows
    without an ObligationKey (legacy, one per control) are left alone.
    """
    wanted: dict[str, Obligation] = {}
    for c in controls:
        if c.get("definition") and c.get("status") not in ("Withdrawn", "Superseded"):
            for ob in obligations_for(c["definition"], catalogue):
                wanted[ob.key] = ob

    by_key: dict[str, dict] = {}
    for item in existing:
        key = ((item.get("fields") or {}).get("ObligationKey") or "").strip()
        if key and key not in by_key:
            by_key[key] = item

    actions: list[ObligationAction] = []
    for key, ob in wanted.items():
        item = by_key.get(key)
        generated = ob.fields()
        if item is None:
            actions.append(ObligationAction("create", key, {**generated, "Status": "Pending"}))
            continue
        current = item.get("fields") or {}
        changed = {k: v for k, v in generated.items() if not _same(current.get(k), v)}
        if current.get("Status") == RETIRED:
            changed["Status"] = "Pending"               # the link is stated again
        if changed:
            actions.append(ObligationAction("update", key, changed, str(item["id"])))

    for key, item in by_key.items():
        if key not in wanted and (item.get("fields") or {}).get("Status") != RETIRED:
            actions.append(ObligationAction("retire", key, {
                "Status": RETIRED,
                "RejectionNote": "Withdrawn: the control no longer names this record, or the "
                                 "control was withdrawn.",
            }, str(item["id"])))
    return actions


# ── where an obligation stands today ────────────────────────────────────────

def _as_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass
class Assessment:
    state: str                # Unscheduled | Awaiting first record | Missing | Current |
                              # Due soon | Late | Stale | Submitted | Rejected | Withdrawn
    next_due: Optional[date]
    detail: str

    def to_dict(self) -> dict:
        return {"state": self.state, "next_due": self.next_due.isoformat() if self.next_due else "",
                "detail": self.detail}


def assess(fields: dict, today: Optional[date] = None) -> Assessment:
    """
    Pure function of the stored fields and today's date — like obligation and
    contract statuses elsewhere, never a stored truth that goes stale itself.
      CheckFrequencyDays  how often the record must be confirmed (0 = not set)
      FreshnessDays       how old an accepted record may be (0 = the frequency)
      ScheduledFrom       when the schedule started (first record due one period later)
      LastRecordDate      date the last ACCEPTED record was produced
      Status              Pending | Submitted | Accepted | Rejected | Withdrawn
    """
    today = today or date.today()
    status = fields.get("Status") or "Pending"
    if status == RETIRED:
        return Assessment("Withdrawn", None, "No longer required by the control.")

    freq = int(fields.get("CheckFrequencyDays") or 0)
    if freq <= 0:
        hint = fields.get("SuggestedFrequencyBasis")
        return Assessment("Unscheduled", None,
                          "No check frequency is set." + (f" Suggested: {hint}." if hint else ""))

    fresh = int(fields.get("FreshnessDays") or 0) or freq
    last = _as_date(fields.get("LastRecordDate"))
    start = _as_date(fields.get("ScheduledFrom")) or today
    next_due = (last or start) + timedelta(days=freq)

    if status == "Submitted":
        return Assessment("Submitted", next_due, "A record is waiting for verification.")
    if status == "Rejected":
        note = fields.get("RejectionNote") or "see the verifier's note"
        return Assessment("Rejected", next_due, f"The last record was rejected: {note}")

    if last is None:
        if today > next_due:
            return Assessment("Missing", next_due, f"No record has been accepted; the first was due {next_due}.")
        return Assessment("Awaiting first record", next_due, f"First record due {next_due}.")
    if today > next_due:
        return Assessment("Late", next_due, f"The next record was due {next_due}.")
    if (today - last).days > fresh:
        return Assessment("Stale", next_due,
                          f"The accepted record dates from {last}, older than the {fresh}-day freshness limit.")
    if (next_due - today).days <= DUE_SOON_DAYS:
        return Assessment("Due soon", next_due, f"Next record due {next_due}.")
    return Assessment("Current", next_due, f"Accepted record of {last}; next due {next_due}.")


ATTENTION = {"Missing", "Late", "Stale", "Rejected"}


def system_id_of(location: str) -> str:
    """'S01' from 'S01 SharePoint, Governance & Records library, …', or ''."""
    m = re.match(r"^\s*(S\d{2})\b", location or "")
    return m.group(1) if m else ""


def may_upload(system_id: str) -> bool:
    """A file is uploaded into OrgOS only where OrgOS is the record's home."""
    return system_id == ORGOS_SYSTEM_ID
