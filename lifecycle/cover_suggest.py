# =============================================================================
# lifecycle/cover_suggest.py — propose a document's CDT cover facts
#
# Compliance should not retype facts the platform already knows. This resolves
# each cover field from the signals available, and says WHERE each value came
# from and how much to trust it, so the reviewer is confirming a proposal
# rather than filling a blank form.
#
# NOTHING HERE DECIDES ANYTHING. Every suggestion is written to the document
# only after a person saves it — CDI-014 is explicit that agents "MUST NOT
# approve, publish, retire, reclassify or change the status of a document,
# control, role or record rule", and Procedure 18.4 requires a person to
# confirm extracted items. A suggestion that cannot be resolved is returned as
# UNRESOLVED rather than filled with something plausible: Procedure 11.2 says a
# document that cannot be placed in an Annex B domain "is not approved until
# its domain is assigned", so guessing would route it to the wrong approver.
#
# Pure: no I/O, no network, no AI. The caller supplies the register documents
# and folder path; this decides. That keeps the resolution rules testable
# without SharePoint.
# =============================================================================

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from lifecycle.domains import (
    FAMILIES_NEEDING_CONFIRMATION,
    PARENT_TYPE_OF,
    Domain,
    domain_for_family,
    domain_for_function,
    layer_for_type,
    parse_domain,
    route_for,
)

# CDI Procedure 6.7: "Classification is at least Internal Use Only.
# Distribution is All Staff unless content warrants restriction."
DEFAULT_CLASSIFICATION = "Internal Use Only"
DEFAULT_DISTRIBUTION = "All Staff"

# CDI-012 / Annex A: "Next review no later than 12 months after last review."
REVIEW_PERIOD_DAYS = 365


class Confidence(str):
    """How much a reviewer should scrutinise a suggestion."""

    HIGH = "high"          # resolved from a governed fact; confirm and move on
    MEDIUM = "medium"      # resolved from a sound default that can be overridden
    LOW = "low"            # resolved from a hint; check it
    UNRESOLVED = "unresolved"  # could not be resolved; a person must decide


@dataclass(frozen=True)
class Suggestion:
    """One proposed cover value, with its provenance."""

    value: str
    source: str
    confidence: str
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "note": self.note,
        }


def _unresolved(source: str, note: str) -> Suggestion:
    return Suggestion(value="", source=source, confidence=Confidence.UNRESOLVED, note=note)


# =============================================================================
#  Document code parsing
# =============================================================================

# Display code: DRG-[Function]-[Type]-[Mnemonic] (CDI Procedure Annex A, CDI-002).
# Legacy codes carry up to two trailing 2-digit groups (serial and/or year),
# which agents/cdi_checker/service.py's is_valid_doc_code tolerates
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


def family_from_path(folder_path: str | None) -> str:
    """
    The control-family folder a document sits under. The library is organised
    by family at its root, so the family is the FIRST path segment — but the
    '00 WORK IN PROGRESS' staging area nests families one level deeper, so that
    prefix is stepped over.
    """
    segments = [s for s in (folder_path or "").replace("\\", "/").split("/") if s.strip()]
    if not segments:
        return ""
    if segments[0].strip().upper().startswith("00 WORK IN PROGRESS"):
        segments = segments[1:]
        # The staging area groups families under headings like "Active
        # Families" / "Programme Assurance" before the family itself.
        if len(segments) > 1 and not domain_for_family(segments[0]):
            segments = segments[1:]
    return segments[0] if segments else ""


def library_path_from_url(url: str | None) -> str:
    """
    Recover the control-family path from a SharePoint file URL, for callers
    that hold a file link rather than a folder path.

    The library's folder names are not stable enough to slice positionally —
    the drive's display name differs from the name in the URL, and documents
    sit at varying depths. So instead of counting segments, this looks for the
    first segment that IS a known control family and returns the path from
    there, which family_from_path() can then read directly.

    When no segment is a known family this returns "" rather than the raw
    path: a folder nobody has mapped tells us nothing about the domain, and
    leaving the family signal absent is better than a misleading one.
    """
    if not url:
        return ""
    try:
        segments = [unquote(s) for s in urlparse(url).path.split("/") if s]
    except Exception:
        return ""
    for index, segment in enumerate(segments):
        if domain_for_family(segment) is not None:
            return "/".join(segments[index:])
    return ""


# =============================================================================
#  Field resolvers
# =============================================================================

def suggest_domain(
    doc_code: str | None,
    folder_path: str | None,
    parent_doc: Optional[dict] = None,
) -> Suggestion:
    """
    Resolve the Primary Domain, strongest signal first.

    The order matters and is not arbitrary — it follows how stable each signal
    is, and deliberately puts the two signals that travel WITH the document
    ahead of the one that depends on where the file happens to sit:

      1. The parent document's domain. A child inherits its parent's domain in
         practice (the whole CDI family sits in Quality & Compliance), and a
         file move cannot change it.
      2. The function code inside the document's own code. Also immune to
         moves. A DEFAULT only — CDI-017 keeps domain and function separate,
         and Procedure 6.4 gives the counter-example (a data protection
         document is coded QI but its domain is Data Protection & Privacy).
      3. The family folder. A HINT, mapped through FAMILY_TO_DOMAIN, because
         several families share one domain. Weakest, and the only one a file
         move breaks.
    """
    if parent_doc:
        parent_domain = parse_domain(_cover_value(parent_doc, "domain"))
        if parent_domain:
            return Suggestion(
                value=parent_domain.value,
                source=f"Inherited from parent document ({parent_doc.get('document_code') or parent_doc.get('DocumentCode') or 'parent'})",
                confidence=Confidence.HIGH,
                note="A child document normally sits in the same domain as its parent.",
            )

    function, _, _ = parse_doc_code(doc_code)
    by_function = domain_for_function(function)
    if by_function:
        return Suggestion(
            value=by_function.value,
            source=f"Default for function code {function}",
            confidence=Confidence.MEDIUM,
            note=(
                "Function code and domain are separate fields — if this document's "
                "subject matter is regulated (data protection, information security), "
                "that domain takes precedence."
            ),
        )

    family = family_from_path(folder_path)
    by_family = domain_for_family(family)
    if by_family:
        flagged = FAMILIES_NEEDING_CONFIRMATION.get(family)
        if flagged:
            _, alternative, reason = flagged
            return Suggestion(
                value=by_family.value,
                source=f"Library family '{family}'",
                confidence=Confidence.LOW,
                note=(
                    f"This family's domain is not yet confirmed by Compliance — it could "
                    f"also be {alternative.value}. {reason}"
                ),
            )
        return Suggestion(
            value=by_family.value,
            source=f"Library family '{family}'",
            confidence=Confidence.LOW,
            note="Taken from the folder the document sits in — confirm it matches the subject matter.",
        )

    return _unresolved(
        source="No parent, function code or known family",
        note=(
            "Assign the domain by hand. Where it cannot be resolved, the Chief "
            "Compliance Officer assigns it and the reason is recorded (Procedure 11.2)."
        ),
    )


def suggest_type_layer(doc_code: str | None, document_type: str | None) -> Suggestion:
    """The 'Document Type / Layer' cell, from the type code in the document code."""
    _, type_code, _ = parse_doc_code(doc_code)
    if not type_code and document_type:
        type_code = _TYPE_NAME_TO_CODE.get(document_type.strip().lower(), "")

    layer = layer_for_type(type_code)
    if not layer:
        return _unresolved(
            source="Document type could not be read from the code",
            note="Pick the document type from the Annex B list.",
        )

    if type_code.upper() == "POL":
        return Suggestion(
            value=layer,
            source=f"Type code {type_code}",
            confidence=Confidence.MEDIUM,
            note=(
                "Annex B gives POL as 'Layer 1 or 2' — add '(Layer 1)' for the Master "
                "Policy or '(Layer 2)' for a Domain Policy."
            ),
        )
    return Suggestion(value=layer, source=f"Type code {type_code}", confidence=Confidence.HIGH)


# Lifecycle items carry a human type name ("Procedure"); codes come from Annex B.
_TYPE_NAME_TO_CODE: dict[str, str] = {
    "policy": "POL",
    "standard": "STD",
    "procedure": "PRO",
    "specification": "SPEC",
    "manual": "MAN",
    "guideline": "GDL",
    "guidelines": "GDL",
    "playbook": "PBK",
    "checklist": "CHK",
    "form": "FM",
    "template": "FM",
    "register": "REG",
}


def find_parent_document(
    doc_code: str | None,
    folder_path: str | None,
    register_docs: list[dict],
) -> Optional[dict]:
    """
    Find the approved Document Register entry that should be this document's
    parent, per CDI Procedure 5.5: a Procedure's parent is its Standard (or its
    Policy where no Standard exists); a Standard's parent is its Domain Policy.

    The strong signal is the code itself: DRG-QI-PRO-CDI's parent is
    DRG-QI-STD-CDI — same function, same mnemonic, parent type. That is exactly
    how the real CDI family is coded, so it is tried first, and only then a
    looser same-family match.
    """
    function, type_code, mnemonic = parse_doc_code(doc_code)
    if not type_code:
        return None
    parent_types = PARENT_TYPE_OF.get(type_code.upper())
    if not parent_types:
        return None

    candidates = []
    for doc in register_docs:
        code = doc.get("document_code") or doc.get("DocumentCode") or ""
        d_function, d_type, d_mnemonic = parse_doc_code(code)
        if not d_type:
            continue
        candidates.append((doc, d_function, d_type.upper(), d_mnemonic))

    # 1. Same function + same mnemonic + parent type — the family's own chain.
    for parent_type in parent_types:
        for doc, d_function, d_type, d_mnemonic in candidates:
            if d_type == parent_type and d_function == function and d_mnemonic == mnemonic and mnemonic:
                return doc

    # 2. Same function + parent type, only when it is unambiguous.
    for parent_type in parent_types:
        matches = [
            doc for doc, d_function, d_type, _ in candidates
            if d_type == parent_type and d_function == function
        ]
        if len(matches) == 1:
            return matches[0]

    return None


def suggest_parent_document(
    doc_code: str | None,
    folder_path: str | None,
    register_docs: list[dict],
) -> Suggestion:
    parent = find_parent_document(doc_code, folder_path, register_docs)
    if not parent:
        _, type_code, _ = parse_doc_code(doc_code)
        if type_code.upper() == "POL":
            return _unresolved(
                source="No parent found",
                note=(
                    "A Domain Policy's parent is the Master Integrated Management System "
                    "Policy. Only the Master Policy and the Manual have no parent."
                ),
            )
        return _unresolved(
            source="No matching document in the Register",
            note=(
                "Every document except the Master Policy and the Manual needs an approved "
                "parent (CDI-001), and a document is not submitted until its parent is "
                "approved (Procedure 5.7)."
            ),
        )

    title = parent.get("title") or parent.get("Title") or ""
    code = parent.get("document_code") or parent.get("DocumentCode") or ""
    value = f"{title} ({code})" if title and code else (title or code)
    return Suggestion(
        value=value,
        source="Matched in the Document Register by function, type and mnemonic",
        confidence=Confidence.HIGH,
    )


def suggest_classification() -> Suggestion:
    return Suggestion(
        value=DEFAULT_CLASSIFICATION,
        source="CDI Procedure 6.7 default",
        confidence=Confidence.MEDIUM,
        note="Minimum is Internal Use Only — raise it where the content warrants restriction.",
    )


def suggest_distribution() -> Suggestion:
    return Suggestion(
        value=DEFAULT_DISTRIBUTION,
        source="CDI Procedure 6.7 default",
        confidence=Confidence.MEDIUM,
        note="Default is All Staff unless the content warrants restriction.",
    )


def suggest_owner(owner_role: str | None, owner_name: str | None) -> Suggestion:
    """
    The cover's Owner is a ROLE, never a person — Procedure 7.8: "Roles are
    named by controlled organisational title... Individuals are not named in
    control text", and 3.18: "Roles govern and individuals execute."
    """
    if owner_role and owner_role.strip():
        return Suggestion(
            value=owner_role.strip(),
            source="Document owner's role",
            confidence=Confidence.HIGH,
        )
    if owner_name and owner_name.strip():
        return _unresolved(
            source=f"Only a person is recorded as owner ({owner_name.strip()})",
            note=(
                "The cover names a ROLE, not a person — individuals are not named in "
                "controlled text (Procedure 7.8). Enter the owner's controlled job title."
            ),
        )
    return _unresolved(source="No owner recorded", note="Name the owning role.")


def suggest_approval_roles(domain_value: str | None) -> tuple[Suggestion, Suggestion]:
    """
    First Pass and Final Approval come FREE once the domain is known — that is
    the whole point of the domain (Procedure 11.1: "Approval authority follows
    the domain, not the layer"). They are never guessed independently.
    """
    route = route_for(domain_value)
    if not route:
        reason = _unresolved(
            source="Domain not resolved",
            note="The approval route is decided by the domain — assign the domain first.",
        )
        return reason, reason

    domain_label = parse_domain(domain_value).value  # type: ignore[union-attr]
    return (
        Suggestion(
            value=route.first_pass,
            source=f"{domain_label} approval route (Annex B)",
            confidence=Confidence.HIGH,
        ),
        Suggestion(
            value=route.final_approval,
            source=f"{domain_label} approval route (Annex B)",
            confidence=Confidence.HIGH,
        ),
    )


def suggest_dates(effective_date: str | None, approved_on: date | None = None) -> tuple[Suggestion, Suggestion]:
    """
    Effective date is the date of approval; next review is 12 months after it
    (Annex A: "Next review no later than 12 months after last review").

    For a document not yet approved, the effective date is not invented — it is
    stamped at approval, so this says so instead of proposing a date.
    """
    existing = (effective_date or "").strip()
    if existing:
        effective = Suggestion(
            value=existing,
            source="Already recorded on this document",
            confidence=Confidence.HIGH,
        )
        due = _next_review_from(existing)
        if due:
            return effective, Suggestion(
                value=due,
                source="12 months after the effective date",
                confidence=Confidence.HIGH,
            )
        return effective, _unresolved(
            source="Effective date could not be read as a date",
            note="Set the next review no later than 12 months after the last review.",
        )

    if approved_on:
        effective_value = approved_on.strftime("%B %Y")
        due_value = (approved_on + timedelta(days=REVIEW_PERIOD_DAYS)).strftime("%B %Y")
        return (
            Suggestion(value=effective_value, source="Date of approval", confidence=Confidence.HIGH),
            Suggestion(value=due_value, source="12 months after approval", confidence=Confidence.HIGH),
        )

    pending = Suggestion(
        value="",
        source="Set automatically on approval",
        confidence=Confidence.MEDIUM,
        note="The effective date is stamped when the document is approved, and the next review is set 12 months after it.",
    )
    return pending, pending


_MONTH_YEAR = re.compile(r"^([A-Za-z]+)\s+(\d{4})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _next_review_from(effective: str) -> str:
    """Add 12 months to an effective date written as 'March 2026' or an ISO date."""
    text = effective.strip()
    iso = _ISO_DATE.match(text)
    if iso:
        try:
            base = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            return (base + timedelta(days=REVIEW_PERIOD_DAYS)).strftime("%B %Y")
        except ValueError:
            return ""
    month_year = _MONTH_YEAR.match(text)
    if month_year:
        try:
            base = date(int(month_year.group(2)), _MONTHS[month_year.group(1).lower()], 1)
        except (KeyError, ValueError):
            return ""
        return f"{month_year.group(1).title()} {base.year + 1}"
    return ""


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _cover_value(doc: dict, key: str) -> str:
    """Read one cover fact off a register or lifecycle document, either shape."""
    cover = doc.get("cdt_cover") or doc.get("cover") or {}
    if hasattr(cover, "model_dump"):
        cover = cover.model_dump()
    if isinstance(cover, dict) and cover.get(key):
        return str(cover[key])
    return ""


# =============================================================================
#  Entry point
# =============================================================================

@dataclass
class CoverSuggestions:
    """Every proposed cover fact, each with its provenance."""

    domain: Suggestion
    type_layer: Suggestion
    parent_document: Suggestion
    classification: Suggestion
    distribution: Suggestion
    owner: Suggestion
    first_pass_approval: Suggestion
    final_approval: Suggestion
    effective_date: Suggestion
    next_review_due: Suggestion

    def as_dict(self) -> dict:
        return {name: getattr(self, name).as_dict() for name in (
            "domain", "type_layer", "parent_document", "classification", "distribution",
            "owner", "first_pass_approval", "final_approval", "effective_date",
            "next_review_due",
        )}

    @property
    def unresolved_fields(self) -> list[str]:
        """Fields a person must decide — surfaced so the UI can point at them."""
        return [
            name for name in (
                "domain", "type_layer", "parent_document", "classification", "distribution",
                "owner", "first_pass_approval", "final_approval",
            )
            if getattr(self, name).confidence == Confidence.UNRESOLVED
        ]


def suggest_cover_facts(
    lifecycle_doc: dict,
    register_docs: list[dict],
    folder_path: str | None = None,
    approved_on: date | None = None,
) -> CoverSuggestions:
    """
    Propose every cover fact for a document. Pure — the caller fetches the
    register documents and the folder path.

    `lifecycle_doc` is the shape lifecycle/router.py's _sp_to_doc() returns.
    """
    doc_code = lifecycle_doc.get("DocumentCode") or ""
    document_type = lifecycle_doc.get("DocumentType") or ""
    existing_cover = lifecycle_doc.get("cover") or {}
    if not isinstance(existing_cover, dict):
        existing_cover = {}

    parent = find_parent_document(doc_code, folder_path, register_docs)

    domain = suggest_domain(doc_code, folder_path, parent)
    # An existing, already-valid domain on the document wins over any proposal:
    # it was confirmed by a person, and re-deriving it would quietly overwrite
    # a decision — including after the file is moved between folders.
    existing_domain = parse_domain(existing_cover.get("domain"))
    if existing_domain:
        domain = Suggestion(
            value=existing_domain.value,
            source="Already set on this document",
            confidence=Confidence.HIGH,
            note="Confirmed previously — a proposal does not overwrite it.",
        )

    first_pass, final = suggest_approval_roles(domain.value)
    effective, next_review = suggest_dates(existing_cover.get("effective_date"), approved_on)

    return CoverSuggestions(
        domain=domain,
        type_layer=suggest_type_layer(doc_code, document_type),
        parent_document=suggest_parent_document(doc_code, folder_path, register_docs),
        classification=suggest_classification(),
        distribution=suggest_distribution(),
        owner=suggest_owner(existing_cover.get("owner"), lifecycle_doc.get("OwnerName")),
        first_pass_approval=first_pass,
        final_approval=final,
        effective_date=effective,
        next_review_due=next_review,
    )


# =============================================================================
#  CDI fix pre-fill
#
#  The CDI fix modal proposes template text for missing sections ("Document
#  Owner: [Role title]"). Where OrgOS already holds the answer, replace the
#  [bracketed] gap with it. Only RESOLVED suggestions are used — an unresolved
#  one leaves the placeholder, so the reviewer still has to decide (and the
#  server refuses to write a placeholder). The effective date is never invented:
#  it is stamped on approval (see suggest_dates).
# =============================================================================

_DOC_NOUN = {"policy": "policy", "procedure": "procedure", "sop": "procedure",
             "standard": "standard", "guideline": "guideline", "guidelines": "guideline",
             "framework": "framework", "manual": "manual", "form": "form"}


def _usable(s: Suggestion) -> str:
    return s.value.strip() if s.confidence != Confidence.UNRESOLVED and s.value.strip() else ""


def prefill_insert(check_id: str, insert: Optional[dict], suggestions: CoverSuggestions,
                   lifecycle_doc: dict) -> Optional[dict]:
    """Return `insert` with known facts substituted for its placeholders."""
    if not insert or not insert.get("text"):
        return insert
    text = insert["text"]
    title = (lifecycle_doc.get("Title") or "").strip()
    noun = _DOC_NOUN.get((lifecycle_doc.get("DocumentType") or "").strip().lower(), "document")

    if check_id in ("CDI-03", "CDI-04") and title:
        # Name what the document is; the substance is still the author's call.
        if check_id == "CDI-03":
            text = f"This {noun} establishes [what {title} controls and why it exists]."
        else:
            text = f"This {noun} applies to [who and what {title} covers] at Dragnet Solutions Limited."
    elif check_id == "CDI-12":
        owner = _usable(suggestions.owner)
        if owner:
            text = f"Document Owner: {owner}"
    elif check_id == "CDI-14":
        eff = _usable(suggestions.effective_date)
        if eff:
            text = f"Effective Date: {eff}"
    elif check_id == "CDI-15":
        version = _cover_value(lifecycle_doc, "version")
        if version:
            text = f"Version: {version}"
    elif check_id == "CDI-10":
        parent = _usable(suggestions.parent_document)
        if parent:
            text = parent
    elif check_id == "CDI-02":
        owner = _usable(suggestions.owner)
        eff = _usable(suggestions.effective_date)
        header, _, row = text.partition("\n")
        cells = [c.strip() for c in row.split("|")]
        if len(cells) == 5:
            if eff:
                cells[1] = eff
            if owner:
                cells[2] = owner
            row = " | ".join(cells)
        text = f"{header}\n{row}"
    return {**insert, "text": text}
