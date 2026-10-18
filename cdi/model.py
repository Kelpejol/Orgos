# =============================================================================
# cdi/model.py — what a parsed controlled document contains
#
# The shapes here mirror the CDI framework, not OrgOS's lists: a control is
# DEFINED once (in a Standard, or the defining Procedure) and IMPLEMENTED by
# Procedures under the same ID. Persisting these into SharePoint is a later
# layer's job; this layer only says what the document states.
#
# Two rules run through every class:
#   - What the document says is kept as written. Interpretation (a role split,
#     a parsed mapping) sits beside it, never instead of it, so a reviewer can
#     always see the source of a value and a better resolver can redo it.
#   - Nothing is filled in. A field the document does not state is empty, and
#     the gap is reported as a Finding rather than covered over.
# =============================================================================

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DocumentRole(str, Enum):
    """What a document contributes to the control framework."""

    DEFINING = "Defining"          # states controls in labelled blocks
    IMPLEMENTING = "Implementing"  # carries out controls defined elsewhere
    AUTHORITY = "Authority"        # a Policy: authority and intent, no controls
    SUPPORTING = "Supporting"      # guideline, playbook, checklist, form, register, manual
    UNSTRUCTURED = "Unstructured"  # should carry controls, but no structure was found


class Severity(str, Enum):
    ERROR = "error"      # the document cannot be relied on for this item
    WARNING = "warning"  # usable, but a person should look
    INFO = "info"        # a known, visible gap — not a fault


class FindingKind(str, Enum):
    # Reading the document
    UNREADABLE_DOCUMENT = "unreadable_document"
    TRACKED_CHANGES = "tracked_changes"
    TABLE_ROW_UNALIGNED = "table_row_unaligned"
    # The document's own control block
    NO_CONTROL_BLOCK = "no_control_block"
    HEADER_CONFLICT = "header_conflict"
    POLICY_DEFINES_CONTROLS = "policy_defines_controls"
    # Control definitions
    CONTROL_MISSING_FIELD = "control_missing_field"
    CONTROL_DUPLICATE_ID = "control_duplicate_id"
    RESPONSIBILITY_AMBIGUOUS = "responsibility_ambiguous"
    MAPPING_UNREADABLE = "mapping_unreadable"
    # Implementation
    IMPLEMENTED_NOT_CITED = "implemented_not_cited"
    CITED_NOT_LISTED = "cited_not_listed"
    CONTROL_MAP_MISMATCH = "control_map_mismatch"
    OPEN_PARAMETER = "open_parameter"
    # The document as a whole
    NO_STRUCTURE = "no_structure"
    # Across documents (cdi/library.py)
    DUPLICATE_DOCUMENT_CODE = "duplicate_document_code"
    DEFINED_TWICE = "defined_twice"
    IMPLEMENTS_UNDEFINED = "implements_undefined"
    DEFINED_NOT_IMPLEMENTED = "defined_not_implemented"


@dataclass(frozen=True)
class Location:
    """Where in the document something was read — shown to the reviewer."""

    section: str = ""   # the nearest heading, e.g. "5.0 CDI Controls"
    item: str = ""      # a control ID, table name or field label

    def __str__(self) -> str:
        return " › ".join(p for p in (self.section, self.item) if p)


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    severity: Severity
    message: str
    location: Location = Location()


@dataclass(frozen=True)
class StandardsRef:
    """One standards clause a control or document maps to."""

    standard: str          # canonical: "ISO 27001", "ISO 9001", "ISO 22301", "NDPA"
    clause: str            # "7.5.2", "A.5.1", "S.24"
    qualifier: str = ""    # a sub-item the document names, e.g. "a)"
    edition: str = ""      # "2022" where the document states it
    as_written: str = ""   # the token as the document wrote it

    @property
    def key(self) -> str:
        """"ISO 27001 A.5.1", or just "NDPA" for a reference to a whole law."""
        return f"{self.standard} {self.clause}" if self.clause else self.standard


@dataclass
class RecordRef:
    """
    A governed record the document refers to. `record_id` is None when the
    document names a record without its Catalogue ID — that is a gap to
    resolve, not something to guess.
    """

    record_id: Optional[str]
    name: str = ""                 # the name the document gives it
    as_written: str = ""
    # From a records table (e.g. a Procedure's Annex B), where present
    created_by: str = ""
    at_step: str = ""
    kept_in: str = ""
    retention: str = ""
    production_mode: str = ""
    # Controls this record evidences, where the document says so
    control_ids: list[str] = field(default_factory=list)
    location: Location = Location()


@dataclass(frozen=True)
class Responsibility:
    """
    Who answers for a control (accountable) and who carries it out
    (executing). A control block states both on one line, split by " / ";
    where it states one role, that role is both.
    """

    accountable: str
    executing: str
    as_written: str
    ambiguous: bool = False   # the split could not be decided from the text

    @property
    def single_role(self) -> bool:
        return self.accountable == self.executing


@dataclass
class ControlDefinition:
    """A control as its defining document states it."""

    control_id: str
    title: str
    requirement: str = ""
    trigger: str = ""
    responsibility: Optional[Responsibility] = None
    evidence: list[RecordRef] = field(default_factory=list)
    evidence_as_written: str = ""
    risk: str = ""
    failure_route: str = ""
    exception_route: str = ""
    mapping: list[StandardsRef] = field(default_factory=list)
    mapping_as_written: str = ""
    # Any other labelled field in the block, kept verbatim, so nothing a
    # document states is lost because this parser did not expect it.
    other_fields: dict[str, str] = field(default_factory=dict)
    location: Location = Location()

    # The CDI control block's eight fields, as the document labels them.
    FIELD_LABELS = {
        "requirement": "Requirement",
        "trigger": "Trigger",
        "responsibility": "Accountable / Executing",
        "evidence": "Evidence",
        "risk": "Risk",
        "failure_route": "Failure route",
        "exception_route": "Exception route",
        "mapping": "Mapping",
    }

    @property
    def missing_fields(self) -> list[str]:
        """Labels of the eight CDI fields this block does not state."""
        stated = {
            "requirement": self.requirement,
            "trigger": self.trigger,
            "responsibility": self.responsibility,
            "evidence": self.evidence_as_written,
            "risk": self.risk,
            "failure_route": self.failure_route,
            "exception_route": self.exception_route,
            "mapping": self.mapping_as_written,
        }
        return [self.FIELD_LABELS[k] for k, v in stated.items() if not v]


@dataclass(frozen=True)
class Clause:
    number: str   # "4.1"
    text: str


@dataclass
class ImplementationStep:
    """
    A section of an implementing document that carries out one or more
    controls, e.g. "4.0 Business impact assessment (BCDR-01)".
    """

    control_ids: list[str]
    section_number: str
    section_title: str
    clauses: list[Clause] = field(default_factory=list)
    # "Risk statement (BCDR-01): …" — keyed by the control it names
    risk_statements: dict[str, str] = field(default_factory=dict)
    record_ids: list[str] = field(default_factory=list)
    location: Location = Location()


@dataclass(frozen=True)
class RoleDuty:
    """A row of a document's Roles table: a role and what it does here."""

    role: str
    duty: str
    location: Location = Location()


@dataclass(frozen=True)
class ControlMapEntry:
    """A row of a control map (a Procedure's Annex A): control → its clause."""

    control_id: str
    title: str
    clause: str
    location: Location = Location()


@dataclass(frozen=True)
class OpenParameter:
    """
    A value the document deliberately leaves open (a Procedure's Annex C).
    `value` is None while it is unset — an open parameter is a visible gap.
    """

    parameter: str
    used_in: str
    value: Optional[str]
    location: Location = Location()


@dataclass
class DocumentHeader:
    """
    The document's identity and governance facts, from its control block and
    cover. `fields` keeps every label/value pair found; `sources` says where
    each chosen value came from ("control block", "cover", "body", "filename").
    """

    title: str = ""
    code: str = ""
    type_code: str = ""            # STD, PRO, POL, … from the document code
    layer_as_written: str = ""     # "Layer 4 Procedure"
    domain: str = ""
    version: str = ""
    issue_status: str = ""
    effective_date: str = ""
    next_review: str = ""
    parent_as_written: str = ""
    parent_codes: list[str] = field(default_factory=list)
    child_documents_as_written: str = ""
    child_codes: list[str] = field(default_factory=list)
    child_record_ids: list[str] = field(default_factory=list)
    related_as_written: str = ""
    related_codes: list[str] = field(default_factory=list)
    owner: str = ""
    approval_authority: str = ""
    first_pass_approval: str = ""
    final_approval: str = ""
    classification: str = ""
    distribution: str = ""
    review_cycle: str = ""
    supersedes: str = ""
    legacy_code: str = ""
    standards: list[StandardsRef] = field(default_factory=list)
    standards_as_written: str = ""
    controls_implemented: list[str] = field(default_factory=list)
    controls_implemented_as_written: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    filename: str
    format: str                    # "docx" | "pdf"
    header: DocumentHeader
    role: DocumentRole
    controls: list[ControlDefinition] = field(default_factory=list)
    implementations: list[ImplementationStep] = field(default_factory=list)
    roles: list[RoleDuty] = field(default_factory=list)
    records: list[RecordRef] = field(default_factory=list)
    control_map: list[ControlMapEntry] = field(default_factory=list)
    open_parameters: list[OpenParameter] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    tracked_changes: int = 0
    parser_version: str = ""

    @property
    def defined_ids(self) -> list[str]:
        return [c.control_id for c in self.controls]

    @property
    def implemented_ids(self) -> list[str]:
        """Every control this document carries out, from any statement of it."""
        ids: list[str] = []
        for source in (
            self.header.controls_implemented,
            [i for step in self.implementations for i in step.control_ids],
            [e.control_id for e in self.control_map],
        ):
            for cid in source:
                if cid not in ids:
                    ids.append(cid)
        return ids

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form — enums as their values."""
        return _jsonable(dataclasses.asdict(self))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
