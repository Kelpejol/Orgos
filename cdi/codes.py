# =============================================================================
# cdi/codes.py — the identifiers the CDI framework uses, and how to find them
#
#   Document code   DRG-QI-STD-CDI            a controlled document
#   Control ID      CDI-001, BCDR-01, IRG-024 a control, defined once
#   Record ID       REC-0676                  a governed record in the Catalogue
#
# Pure: no I/O, no settings, no network. Moved here from the CDI checker so the
# document parser can depend on it without importing the checker (and its LLM
# client); agents/cdi_checker/service.py re-exports the document-code names.
# =============================================================================

from __future__ import annotations

import re

# Per CDI v06 (§4.0 CODING) the trailing "-SERIAL-YEAR" suffix is retired —
# a code now stops at the document ID, e.g. DRG-QI-PRO-CDI, not
# DRG-QI-PRO-CDI-01-26. Confirmed by the compliance officer 2026-09:
#   - The new-format cover template is the one to build against (no suffix).
#   - Wani (Victoria Shobayo) is converting the ~112 legacy-format documents
#     herself, on no fixed timeline — so BOTH shapes must be accepted
#     indefinitely; there is no cutover date to design a hard switch around.
# The estate itself is messy across that transition — new codes with no
# suffix, legacy codes with a serial+year suffix, legacy codes with only a
# serial (no year, esp. combined policy-and-procedure documents), and legacy
# codes with no distinct mnemonic before the suffix. Trying to enumerate every
# shape as its own regex is unmaintainable and prone to missing a real one (as
# happened before: the combined-document fix assumed a serial+year suffix that
# the real documents don't have). is_valid_doc_code() instead checks the
# STRUCTURE directly — see its docstring for the shapes it accepts. (There is
# deliberately no fixed DOC_CODE_PATTERN constant any more — the estate has too
# many real shapes for one regex to be both correct and legible; see below.)

# Broad CANDIDATE finder for recovering a code out of document body text: DRG
# followed by 2-6 dash-separated alphanumeric groups. Deliberately loose — it
# only proposes candidates; is_valid_doc_code() below does the real acceptance
# check, so a loose find here can never let an invalid code through.
DOC_CODE_SEARCH_PATTERN = re.compile(r"\bDRG(?:-[A-Z0-9]+){2,6}\b", re.IGNORECASE)


def is_valid_doc_code(code: str) -> bool:
    """
    True for a well-formed controlled document code, new format OR any
    legacy format still in the estate — see the module comment above for why
    both must be accepted with no cutover date. Shapes accepted:

      NEW canonical      DRG-[FUNCTION]-[TYPE]-[ID]               DRG-QI-PRO-CDI
      NEW combined       DRG-[FUNCTION]-[TYPE]-[TYPE]-[ID]        DRG-QI-POL-PRO-NCA
      LEGACY             DRG-[DEPT]-[TYPE]-[SHORT]-SERIAL-YEAR    DRG-CAE-PRO-3CX-01-26
      LEGACY combined    DRG-[DEPT]-[TYPE]-[TYPE]-[SHORT]-SS-YY   DRG-QI-POL-PRO-NCA-01-26
      LEGACY (no short)  DRG-[DEPT]-[TYPE]-SERIAL-YEAR            DRG-CLE-SOP-01-25
      LEGACY single-serial combined (no year)                     DRG-QI-POL-PRO-NCA-01

    Expressed structurally rather than as one rigid regex, since the estate's
    real shapes vary too much for that (see the docs/CDT-V06-TEMPLATE-ANALYSIS.md
    library scan — this covers all of them, both old and new, with one rule):
    must start "DRG-", have a 2-6 letter FUNCTION/DEPT segment, then at least
    one more segment — optionally followed by one or two trailing pure-2-digit
    groups (a legacy SERIAL and/or YEAR). What's left after stripping those
    must start with a 2-4 letter TYPE code.
    """
    c = (code or "").strip().upper()
    if not c.startswith("DRG-"):
        return False
    parts = c.split("-")
    if len(parts) < 4 or parts[0] != "DRG":
        return False
    if not all(parts[1:]):  # no empty segments, e.g. "DRG--PRO-CDI"
        return False

    dept = parts[1]
    if not (dept.isalpha() and 2 <= len(dept) <= 6):
        return False

    body = parts[2:]
    stripped = 0
    while body and stripped < 2 and len(body[-1]) == 2 and body[-1].isdigit():
        body = body[:-1]
        stripped += 1
    if not body:
        return False  # nothing left for a TYPE code

    type_code = body[0]
    return bool(type_code.isalpha() and 2 <= len(type_code) <= 4)


def find_doc_code_in_text(text: str) -> str:
    """
    Recover a document code from the document body. Scans every DRG-prefixed
    candidate (new format, legacy format, combined — any shape) and returns
    the first that is actually valid. "" if none found.
    """
    for m in DOC_CODE_SEARCH_PATTERN.finditer((text or "").upper()):
        candidate = m.group(0).strip().upper()
        if is_valid_doc_code(candidate):
            return candidate
    return ""


# Display code: DRG-[Function]-[Type]-[Mnemonic] (CDI Procedure Annex A, CDI-002).
# Legacy codes carry up to two trailing 2-digit groups (serial and/or year),
# which is_valid_doc_code above tolerates
# indefinitely — so they are stripped here rather than rejected.
_TWO_DIGITS = re.compile(r"^\d{2}$")


def parse_doc_code(code: str | None) -> tuple[str, str, str]:
    """
    Split a display code into (function, type, mnemonic). Returns blanks for
    any part that cannot be read — this never raises, because a malformed code
    should degrade the suggestion, not break the panel.
    """
    parts = [p for p in (code or "").strip().upper().split("-") if p]
    if len(parts) < 3 or parts[0] != "DRG":
        return "", "", ""
    function = parts[1]
    body = parts[2:]
    # Drop legacy trailing serial / year groups.
    while len(body) > 1 and _TWO_DIGITS.match(body[-1]):
        body = body[:-1]
    if not body:
        return function, "", ""
    type_code = body[0]
    mnemonic = "-".join(body[1:]) if len(body) > 1 else ""
    return function, type_code, mnemonic


def find_doc_codes(text: str) -> list[str]:
    """Every valid document code in `text`, in order, without repeats."""
    found: list[str] = []
    for m in DOC_CODE_SEARCH_PATTERN.finditer((text or "").upper()):
        candidate = m.group(0).strip().upper()
        if is_valid_doc_code(candidate) and candidate not in found:
            found.append(candidate)
    return found


# -----------------------------------------------------------------------------
#  Record IDs
# -----------------------------------------------------------------------------

# Catalogue Record IDs are REC- plus exactly four digits (REC-0001 … REC-0729).
RECORD_ID_PATTERN = re.compile(r"\bREC-\d{4}\b")


def find_record_ids(text: str) -> list[str]:
    """Every Record ID in `text`, in order, without repeats."""
    found: list[str] = []
    for m in RECORD_ID_PATTERN.finditer(text or ""):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found


# -----------------------------------------------------------------------------
#  Control IDs
# -----------------------------------------------------------------------------

# A control ID is a family prefix and a two- or three-digit number: CDI-001,
# IRG-024, BCDR-01. The prefix is deliberately open — every domain mints its
# own — so the shape alone is not proof. RR-26 (a retention rule) and GR-01 (a
# Catalogue governance rule) have the same shape and are excluded by name;
# beyond that, callers only accept an ID where the document's STRUCTURE says
# it is a control (a labelled control block, a citing section heading, a
# control map). Never match this pattern against free prose and call the
# result a control.
CONTROL_ID_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{1,7})-(\d{2,3})\b")

# Same shape, not controls.
NON_CONTROL_PREFIXES: frozenset[str] = frozenset({
    "RR",    # Records Retention Rule Schedule entries
    "GR",    # Enterprise Records Catalogue governance rules
    "REC",   # Record IDs (four digits, but excluded explicitly anyway)
    "DRG",   # document code prefix
    "ISO", "IEC", "NDPA", "NDPR", "GDPR",
})


def is_control_id(token: str) -> bool:
    """True if `token`, on its own, has the shape of a control ID."""
    m = CONTROL_ID_PATTERN.fullmatch((token or "").strip())
    return bool(m) and m.group(1) not in NON_CONTROL_PREFIXES


def find_control_ids(text: str) -> list[str]:
    """
    Every control-ID-shaped token in `text`, in order, without repeats. Only
    call this on text the document's structure already marks as listing
    controls — see CONTROL_ID_PATTERN.
    """
    found: list[str] = []
    for m in CONTROL_ID_PATTERN.finditer(text or ""):
        if m.group(1) in NON_CONTROL_PREFIXES:
            continue
        if m.group(0) not in found:
            found.append(m.group(0))
    return found
