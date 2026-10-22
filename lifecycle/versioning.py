# =============================================================================
# lifecycle/versioning.py — one version number, and what approval does to it
#
# CDI Procedure §12, §14: a document has ONE field, Version, "set on issue"
# (it replaces the former Revision and Issue fields). So:
#
#   • A draft has no version.                                     (§12.1)
#   • A new version needs a change summary stating what changed and why. "Issued
#     for use" does not meet this.                                (§14.2, V20)
#   • Correcting a typo, a broken cross-reference or formatting is not a material
#     change and does NOT increment the version. It is logged.    (§14.3)
#   • An annual review that finds no substantial change KEEPS the version,
#     updates the review dates, and logs "annual review, no change". (§14.5)
#
# Until now OrgOS kept two numbers for one fact — "R02" in the Document Register
# and "02" on the cover — and raised both on every approval, even when nothing
# had changed. There is one now, written "01", "02"…; the old "R02" is still
# READ (an existing Register entry is not broken) and is never written again.
#
# Pure: values in, values out. No I/O.
# =============================================================================

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

NEW, CORRECTION, REVIEW = "new", "correction", "review"
DECISIONS = (NEW, CORRECTION, REVIEW)

MIN_NEW_SUMMARY = 20
MIN_CORRECTION_SUMMARY = 10

# "R02", "r2", "02", "2", "v2", "Version 2" → 2.  "Draft", "", "TBC" → no version.
_NUMBER = re.compile(r"^\s*(?:r|v|ver|version)?\s*\.?\s*0*(\d+)\s*$", re.IGNORECASE)

# A change summary that says nothing. CDI §14.2: "A row saying only 'issued for use'
# does not meet this."
_SAYS_NOTHING = {
    "issued for use", "issued", "approved for use", "approved", "initial issue", "first issue",
    "initial release", "new document", "n/a", "na", "none", "nil", "update", "updated", "updates",
    "no change", "no changes", "change", "changes", "minor changes", "various", "various changes", "tbc",
}


class VersionError(ValueError):
    """The approval cannot go ahead as asked; the message says why, for a person."""


def parse_version(value) -> Optional[int]:
    m = _NUMBER.match(str(value or ""))
    n = int(m.group(1)) if m else 0
    return n or None


def format_version(n: int) -> str:
    return f"{n:02d}"


def next_version(current) -> str:
    return format_version((parse_version(current) or 0) + 1)


def display_version(value) -> str:
    """How a stored version reads now: 'R02' → '02'; 'Draft' and blank stay as they are."""
    n = parse_version(value)
    return format_version(n) if n else str(value or "").strip()


def _words(text: str) -> str:
    return re.sub(r"[^a-z ]+", "", (text or "").lower()).strip()


def validate_summary(decision: str, summary: str) -> str:
    """The reason a change summary is not acceptable, or '' if it is."""
    text = (summary or "").strip()
    if decision == REVIEW:
        return ""                                   # "annual review, no change" is the entry; a note is optional
    minimum = MIN_NEW_SUMMARY if decision == NEW else MIN_CORRECTION_SUMMARY
    if _words(text) in _SAYS_NOTHING:
        return (f"“{text}” does not say what changed. CDI requires a change summary stating what changed "
                "and why; “issued for use” does not meet it.")
    if len(text) < minimum:
        what = "what changed and why" if decision == NEW else "what was corrected"
        return f"Say {what} (at least {minimum} characters)."
    return ""


@dataclass(frozen=True)
class VersionOutcome:
    decision: str
    version: str                                  # the version the document carries after approval
    issues_new_version: bool
    effective_date: Optional[date]                # None: leave the existing effective date as it is
    next_review_date: Optional[date]              # None: leave the existing review date as it is
    history_purpose: str                          # the revision-history row
    history_new_row_is_issue: bool                # True: a version row; False: a logged correction or review


def plan(decision: Optional[str], summary: str, *, existing_version, today: date,
         review_days: int) -> VersionOutcome:
    """
    What approval does to the version. `existing_version` is the Register's
    current version for a revision; blank for a document being issued for the
    first time.
    """
    has_issued = parse_version(existing_version) is not None
    decision = (decision or "").strip().lower() or None

    if not has_issued:
        if decision in (CORRECTION, REVIEW):
            raise VersionError("There is no issued version yet, so there is nothing to correct or review: "
                               "this is the first issue.")
        decision = NEW
    elif decision not in DECISIONS:
        raise VersionError("Choose how this approval treats the version: a new version, a correction "
                           "(no new version), or an annual review with no change.")

    problem = validate_summary(decision, summary)
    if problem:
        raise VersionError(problem)
    text = (summary or "").strip()

    if decision == NEW:
        return VersionOutcome(NEW, next_version(existing_version), True, today,
                              today + timedelta(days=review_days), text, True)
    if decision == CORRECTION:
        return VersionOutcome(CORRECTION, display_version(existing_version), False, None, None,
                              f"Correction, no new version: {text}", False)
    return VersionOutcome(REVIEW, display_version(existing_version), False, None,
                          today + timedelta(days=review_days),
                          "Annual review, no change" + (f": {text}" if text else ""), False)
