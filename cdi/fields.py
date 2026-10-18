# =============================================================================
# cdi/fields.py — interpret the VALUE of one labelled field
#
# A control block line is "Label: value". These turn a value into structure:
#
#   Mapping:                  "ISO 9001 7.5.2; ISO/IEC 27001 7.5.2, A.5.1"
#                             → [ISO 9001 7.5.2, ISO 27001 7.5.2, ISO 27001 A.5.1]
#   Evidence:                 "REC-0623 Controlled Document Register; validation result REC-0635"
#                             → [REC-0623 "Controlled Document Register", REC-0635 "validation result"]
#   Accountable / Executing:  "Compliance Executive (QMS & NDPA) / platform check V03"
#                             → accountable + executing
#
# Each returns its interpretation AND keeps the as-written text, and reports
# what it could not read instead of dropping it. Pure functions — the same
# input always gives the same output, with no I/O.
# =============================================================================

from __future__ import annotations

import re
from typing import Iterable

from cdi.codes import expand_control_ranges, find_control_ids, find_record_ids
from cdi.model import RecordRef, Responsibility, StandardsRef

_NONE_VALUES = {"none", "n/a", "na", "not applicable", "-", "—", "nil"}


def norm(text: str) -> str:
    """Comparison key: lower case, single spaces, no surrounding punctuation."""
    return re.sub(r"\s+", " ", (text or "")).strip(" .:;, ").lower()


def is_none_value(text: str) -> bool:
    return norm(text) in _NONE_VALUES


def split_top_level(text: str, sep: str) -> list[str]:
    """Split on `sep`, ignoring any inside parentheses."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


# =============================================================================
#  Standards mapping
# =============================================================================

_STANDARD = re.compile(
    r"""
    (?P<name>
        ISO\s*/\s*IEC\s*(?P<iso_iec>\d{4,5})
      | ISO\s*(?P<iso>\d{4,5})
      | (?P<ndpa_full>Nigeria(?:n)?\s+Data\s+Protection\s+Act)
      | (?P<ndpr_full>Nigeria(?:n)?\s+Data\s+Protection\s+Regulations?)
      | (?P<law>NDPA|NDPR|GDPR)
    )
    (?:\s*:\s*(?P<ed_colon>\d{4}))?             # ISO 9001:2015
    (?:\s+(?P<ed_year>(?:19|20)\d{2})\b(?!\.))?  # NDPA 2023
    (?:\s*\((?:NDPA|NDPR|GDPR)\))?               # "… Act 2023 (NDPA)"
    """,
    re.IGNORECASE | re.VERBOSE,
)
_LAWS = {"NDPA", "NDPR", "GDPR"}


def _canonical_standard(m: re.Match) -> str:
    if m.group("ndpa_full"):
        return "NDPA"
    if m.group("ndpr_full"):
        return "NDPR"
    if m.group("law"):
        return m.group("law").upper()
    return f"ISO {m.group('iso_iec') or m.group('iso')}"


def parse_mapping(text: str) -> tuple[list[StandardsRef], list[str]]:
    """
    Parse a standards mapping into clause references.

    Returns (references, unreadable_tokens). A token that is not a clause is
    reported, never silently dropped — a mapping that reads wrong must be
    visible, because the Standards Map and Gap Analysis are built on it.

    Handles the shapes in use: "ISO 9001 7.5.2 a)", "ISO/IEC 27001:2022
    Clause 7.5, Annex A 5.1, 5.12", "ISO 22301:2019 Clauses 8.2, 8.3",
    "NDPA 2023 s24, s39", "A.5.1", and a whole law with no section, "Nigeria
    Data Protection Act 2023 (NDPA)" (clause ""). A clause without a standard
    of its own inherits the standard named before it.
    """
    raw = (text or "").strip()
    if not raw or is_none_value(raw):
        return [], []
    body = raw.rstrip(".")

    refs: list[StandardsRef] = []
    bad: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    matches = list(_STANDARD.finditer(body))
    if not matches:
        return [], [t for t in re.split(r"[;,]", body) if t.strip()]

    leading = body[: matches[0].start()].strip(" ;,")
    if leading:
        bad.append(leading)

    for k, m in enumerate(matches):
        standard = _canonical_standard(m)
        edition = m.group("ed_colon") or m.group("ed_year") or ""
        segment = body[m.end(): matches[k + 1].start() if k + 1 < len(matches) else len(body)]
        annex = False
        found_before = len(refs) + len(bad)
        for token in re.split(r"[;,]|\band\b", segment):
            tok = token.strip()
            if not tok:
                continue
            t = tok
            if re.match(r"^(?:clauses?|cl\.)\s+", t, re.IGNORECASE):
                t = re.sub(r"^(?:clauses?|cl\.)\s+", "", t, flags=re.IGNORECASE)
                annex = False
            if re.match(r"^annex\s+a\b", t, re.IGNORECASE):
                t = re.sub(r"^annex\s+a\s*", "", t, flags=re.IGNORECASE)
                annex = True
            if not t:
                continue

            clause = qualifier = ""
            if standard in _LAWS:
                mm = re.match(r"^(?:s\.?|sec\.?|section)\s*(\d+[A-Za-z]?)\s*(.*)$", t, re.IGNORECASE)
                if mm:
                    clause, qualifier = f"S.{mm.group(1).upper()}", mm.group(2)
            if not clause:
                mm = re.match(r"^A\.\s?(\d+(?:\.\d+)*)\s*(.*)$", t)
                if mm:
                    clause, qualifier = f"A.{mm.group(1)}", mm.group(2)
            if not clause:
                mm = re.match(r"^(\d+(?:\.\d+)*)\s*(.*)$", t)
                if mm:
                    num = mm.group(1)
                    clause = f"A.{num}" if annex else num
                    qualifier = mm.group(2)
            if not clause:
                bad.append(tok)
                continue

            # Keep a short sub-item ("a)", "(b)"); a longer tail is a clause
            # title, which the clause catalogue already knows.
            qualifier = qualifier.strip()
            if not re.fullmatch(r"\(?[a-z]{1,2}\)|\(?[ivx]{1,4}\)", qualifier):
                qualifier = ""
            key = (standard, clause, qualifier)
            if key in seen:
                continue
            seen.add(key)
            refs.append(StandardsRef(standard, clause, qualifier, edition, tok))

        if len(refs) + len(bad) == found_before and (standard, "", "") not in seen:
            # The standard is named with no clause: a reference to all of it.
            seen.add((standard, "", ""))
            refs.append(StandardsRef(standard, "", "", edition, m.group(0).strip()))

    return refs, bad


# =============================================================================
#  Evidence
# =============================================================================

def parse_evidence(text: str) -> list[RecordRef]:
    """
    Parse an Evidence line into record references. A record named without a
    Record ID is kept with record_id=None — a gap to resolve, not to guess.
    """
    raw = (text or "").strip()
    if not raw or is_none_value(raw):
        return []
    refs: list[RecordRef] = []
    for part in split_top_level(raw.rstrip("."), ";"):
        ids = find_record_ids(part)
        if not ids:
            refs.append(RecordRef(record_id=None, name=part.strip(" .,"), as_written=part))
        elif len(ids) == 1:
            name = part.replace(ids[0], " ")
            name = re.sub(r"\s+", " ", name).strip(" .,:;-–()")
            refs.append(RecordRef(record_id=ids[0], name=name, as_written=part))
        else:
            refs.extend(RecordRef(record_id=rid, as_written=part) for rid in ids)
    return refs


# =============================================================================
#  Accountable / Executing
# =============================================================================

_ROLE_SEP = re.compile(r"\s+/\s+")
_ACRONYM = re.compile(r"^[A-Z]{2,5}$")


def _split_outside_parens(text: str) -> list[str]:
    """Split on " / " (spaced), but not inside parentheses."""
    parts, start = [], 0
    for m in _ROLE_SEP.finditer(text):
        before = text[: m.start()]
        if before.count("(") == before.count(")"):
            parts.append(text[start: m.start()])
            start = m.end()
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def split_responsibility(text: str, known_roles: Iterable[str] = ()) -> Responsibility:
    """
    Split "Accountable / Executing: A / B" into its two roles.

    The difficulty is that role names contain " / " too — "Managing Director /
    CEO", "Finance / Admin Manager" — so a slash is not always the divider.
    `known_roles` (the document's own Roles table, or the role vocabulary)
    settles it: the split that leaves known roles on each side wins.

    When the text cannot settle it, the most likely split is returned with
    ambiguous=True, so it is shown to a person rather than trusted. A single
    role is both accountable and executing.
    """
    as_written = (text or "").strip()
    value = as_written.rstrip(".").strip()
    known = {norm(r) for r in known_roles if r}

    parts = _split_outside_parens(value)
    if len(parts) <= 1 or norm(value) in known:
        return Responsibility(value, value, as_written)

    candidates = []
    for i in range(1, len(parts)):
        left, right = " / ".join(parts[:i]), " / ".join(parts[i:])
        score = (norm(left) in known) + (norm(right) in known)
        candidates.append((score, i, left, right))
    best = max(c[0] for c in candidates)
    top = [c for c in candidates if c[0] == best]
    _, _, accountable, executing = top[0]

    ambiguous = len(top) > 1
    if not ambiguous and best < 2 and len(parts) == 2:
        # One slash and the roles are not both recognised: usually a real
        # split, but "Managing Director / CEO" is one role. An acronym on
        # either side is the tell — say so rather than guess.
        ambiguous = bool(_ACRONYM.match(parts[0]) or _ACRONYM.match(parts[1]))
    elif not ambiguous and best == 0:
        ambiguous = True

    return Responsibility(accountable, executing, as_written, ambiguous)


# =============================================================================
#  Lists of control IDs
# =============================================================================

def parse_control_list(text: str) -> list[str]:
    """
    Control IDs from a field whose whole job is to list them — "Standard
    controls implemented: BCDR-01; BCDR-02", a heading's "(implements CDI-001,
    CDI-019)", "Controls: CM-01 to CM-06". Ranges are expanded. Never call
    this on free prose.
    """
    return find_control_ids(expand_control_ranges(text or ""))


# =============================================================================
#  The control field vocabulary
#
#  Dragnet's documents name the same field many ways: "Risk", "Risk statement",
#  "Risk treated"; "Accountable / Executing", "Responsible role", "Accountable
#  / operating role". Every spelling seen in the library maps to one canonical
#  field here, and every layout — labelled paragraphs, a per-control field
#  table, a row-per-control table — reads through this one map. A new spelling
#  is added once, here, and every layout learns it.
# =============================================================================

CONTROL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "requirement": (
        "requirement", "mandatory requirement", "mandatory control requirement",
        "canonical requirement", "control requirement", "control statement",
        "control", "statement",
    ),
    "trigger": (
        "trigger", "trigger and monitoring", "trigger / frequency", "trigger / monitor",
        "trigger / monitoring", "frequency", "timeline",
    ),
    "responsibility": (
        "accountable / executing", "accountable/executing", "accountable and executing",
        "accountable / operating role", "responsible role", "responsible roles",
        "role", "roles", "responsible", "owner role", "owner", "control owner",
    ),
    "accountable": ("accountable", "accountable role"),
    "executing": ("executing", "executing role", "operating role", "executor"),
    "evidence": (
        "evidence", "required evidence", "evidence record", "evidence records",
        "evidence / governed object", "evidence / record route",
        "required evidence / monitoring", "evidence and risk link",
    ),
    "record_ids": ("record ids", "record id", "record id(s)", "evidence record id", "evidence record ids"),
    "risk": ("risk", "risk statement", "risk treated"),
    "failure_route": ("failure route",),
    "exception_route": ("exception route",),
    "mapping": ("mapping", "standards mapping"),
    "authority": ("governing authority", "authority"),
    "clause": ("clause", "clauses", "clause in this procedure", "clauses of this procedure"),
    "title": ("title", "control title", "name"),
}
_CONTROL_ALIAS_INDEX = {a: k for k, aliases in CONTROL_FIELD_ALIASES.items() for a in aliases}

# For table headers that combine words ("Required evidence / monitoring"),
# a keyword decides, in this order. Exact aliases are always tried first.
_CONTROL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("requirement", "requirement"),
    ("control statement", "requirement"),
    ("record id", "record_ids"),
    ("evidence", "evidence"),
    ("risk", "risk"),
    ("accountable", "responsibility"),
    ("responsib", "responsibility"),
    ("role", "responsibility"),
    ("trigger", "trigger"),
    ("frequency", "trigger"),
    ("authority", "authority"),
    ("failure", "failure_route"),
    ("exception", "exception_route"),
    ("mapping", "mapping"),
    ("clause", "clause"),
)


def control_field(label: str, *, allow_keywords: bool = False) -> str | None:
    """
    The canonical control field a label names, or None. `allow_keywords`
    widens the match to compound table headers; leave it off for paragraph
    labels, where "Note:" or "Example:" must not be read as a field.
    """
    key = norm(label)
    if key in _CONTROL_ALIAS_INDEX:
        return _CONTROL_ALIAS_INDEX[key]
    if allow_keywords:
        for word, field_name in _CONTROL_KEYWORDS:
            if word in key:
                return field_name
    return None


_LABEL_START = re.compile(r"(?:^|(?<=[.;]\s))(?P<label>[A-Z][A-Za-z /&()-]{1,40}?)\s*:\s")


def split_labelled(text: str) -> list[tuple[str, str]] | None:
    """
    Read a paragraph of one or more "Label: value" pairs, or None if it does
    not open with a known field label.

    Access Control writes several to a paragraph — "Governing authority: X.
    Responsible role: Y. Required evidence: Z. Record IDs: REC-0691" — so the
    text is divided at every KNOWN label, and only known ones: a colon after
    any other word ("Note:") stays part of the value.
    """
    opening = _LABEL_START.match(text)
    if not opening:
        return None
    # The opening label may be one this vocabulary does not know — "Evidence
    # freshness:", "Control bindings:" — and is kept rather than lost, as long
    # as it is short enough to be a label and not a sentence with a colon.
    if not control_field(opening.group("label")) and len(opening.group("label").split()) > 4:
        return None
    starts = [opening] + [
        m for m in _LABEL_START.finditer(text, opening.end())
        if control_field(m.group("label"))
    ]
    pairs = []
    for k, m in enumerate(starts):
        end = starts[k + 1].start() if k + 1 < len(starts) else len(text)
        pairs.append((m.group("label").strip(), text[m.end():end].strip()))
    return pairs
