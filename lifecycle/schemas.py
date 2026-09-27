# =============================================================================
# lifecycle/schemas.py — Controlled Document Templating (CDT) schemas — v06
#
# Pydantic v2 models that define the CONTRACT between the Document Register/
# Document Lifecycle and the master template. The field names on MergeContext
# ARE the canonical marker vocabulary — a template must reference only these.
#
# v06 REBUILD (2026-09) — replaces the original 3CX-shaped model after the
# compliance officer confirmed the final cover template and answered the open
# questions in docs/CDT-V06-TEMPLATE-ANALYSIS.md §8. What changed and why:
#
#   • Revision + Issue → ONE "Version" field (may literally be "Draft" before
#     first approval — confirmed answer #8).
#   • Approved By (one field) → First Pass Approval + Final Approval (two
#     segregated gates, per the v06 CDI Procedure).
#   • Serial Number — retired. Not on the v06 cover at all.
#   • Domain, Parent Document, Owner (role/group label, NOT a person) — new
#     cover fields.
#   • The two fixed ISO cells become a GROWING list (`standards`) — the
#     officer confirmed three regulatory bodies today (ISO 9001:2015, ISO
#     27001:2022, NDPA) and that the count can grow further (answer #5).
#   • Header/footer are confirmed empty of control data (answer #2) — CDT is
#     two zones now: the cover (control facts + the standards tail) and the
#     revision-history table. There is no per-page header strip any more.
#   • Every cover field is editable at every revision, with no field treated
#     as fixed-forever (answer #4).
#
# STORAGE NOTE — why CdtCoverFacts is ONE bundled model, not one field each:
# OrgOS cannot create SharePoint columns (confirmed via a live 403 while
# building the OrgOS Groups list) — only a human can add a column, once, by
# hand. Fourteen new scalar cover fields would mean fourteen columns for an
# admin to add, on TWO lists (Document Lifecycle *and* Document Register).
# Bundling them into one JSON blob column (`CDTCoverFacts`) cuts that to one
# new column per list (plus `RevisionHistory`, already a natural JSON blob),
# matching the JSON-in-a-text-column idiom already used everywhere else in
# OrgOS (Stakeholders, CDIFailures, SensitisationFeedback, Members, Aliases).
# MergeContext itself stays FLAT (one marker per field) — the blob is a
# storage detail the template author never needs to know about.
#
# This module is pure data. It performs no I/O and never calls AI.
# Depends on: pydantic v2
# =============================================================================

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # hint only — no runtime coupling to the grc (register) layer
    from grc.schemas import DocumentRead


# =============================================================================
#  Constituent shapes
# =============================================================================

class StandardEntry(BaseModel):
    """
    One row of the cover page's growing standards block (the former fixed
    "ISO 9001:2015 / ISO 27001:2022" cells). e.g.
        {"name": "ISO 9001:2015", "reference": "Clause 7.5"}
        {"name": "NDPA 2023",     "reference": "Section 24"}
    Fields default to "" so an incomplete entry renders a blank cell rather
    than hard-failing a publish.
    """

    name: str = Field(default="", description="Standard/body name, e.g. 'ISO 27001:2022'")
    reference: str = Field(default="", description="Clause/section reference, e.g. 'Clause 7.5'")


class RevisionHistoryEntry(BaseModel):
    """
    One row of the revision-history table. Header confirmed by the compliance
    officer: Version | Date | Purpose of Change | Approved By — no separate
    "Issue" column any more (folded into the single Version field).

    Stored in a JSON array (the RevisionHistory column) and expanded by the
    repeating-row marker at merge time.
    """

    version: str = Field(default="", description="Version as printed at that revision, e.g. '06' or 'Draft'")
    date: str = Field(default="", description="Human date as printed, e.g. 'March 2026'")
    purpose: str = Field(default="", description="'Purpose of Change' cell, e.g. 'Issued for use'")
    approved_by: str = Field(default="", description="'Approved By' cell — a name or approval role")

    @classmethod
    def list_from_json(cls, raw: Any) -> list["RevisionHistoryEntry"]:
        """
        Parse the SharePoint RevisionHistory column into typed entries.

        Tolerant of: None/"" (→ []), an already-decoded list, or a JSON string.
        Raises ValueError on malformed JSON or wrong-shaped entries so the merge
        can fail loudly rather than publish a broken history table.
        """
        if not raw:
            return []
        if isinstance(raw, list):
            data = raw
        else:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"RevisionHistory is not valid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("RevisionHistory JSON must be an array of objects")
        return [cls.model_validate(entry) for entry in data]

    @staticmethod
    def list_to_json(entries: list["RevisionHistoryEntry | dict"]) -> str:
        """Serialise entries to the JSON string stored in SharePoint."""
        payload = [
            e.model_dump() if isinstance(e, RevisionHistoryEntry) else e for e in entries
        ]
        return json.dumps(payload, ensure_ascii=False)


class CdtCoverFacts(BaseModel):
    """
    Every v06 cover-page control fact EXCEPT doc_code/title/doc_type (those
    keep their own dedicated columns — they exist independently of CDT) and
    revision_history (its own column, unchanged shape philosophy). This is
    the STORAGE shape for the single `CDTCoverFacts` JSON column — see the
    module comment above for why it's bundled rather than one column each.

    All fields default to "" / [] — an absent value is simply a blank cell,
    never an error. Every field is editable at any time (confirmed answer
    #4): nothing here is "set once at creation and locked".
    """

    domain: str = Field(default="", description="e.g. 'Quality & Compliance'")
    parent_document: str = Field(default="", description="e.g. 'Control of Documented Information Policy (Layer 2)'")
    type_layer: str = Field(default="", description="Full 'Document Type / Layer' cell, e.g. 'Procedure (Layer 4)'")
    classification: str = Field(default="", description="e.g. 'Internal use only'")
    distribution: str = Field(default="", description="e.g. 'All staff'")
    owner: str = Field(
        default="",
        description="Cover 'Owner' cell — a ROLE or GROUP label (e.g. 'Compliance Senior "
                    "Executive' or 'Compliance Team'), never a specific person. Distinct from "
                    "the register's owner_id/OwnerEntraId, which is who manages this document "
                    "record inside OrgOS.",
    )
    first_pass_approval: str = Field(default="", description="e.g. 'Compliance Senior Executive'")
    final_approval: str = Field(default="", description="e.g. 'Chief Compliance Officer'")
    version: str = Field(
        default="",
        description="The literal 'Version' cell. May be the string 'Draft' before first "
                    "approval (confirmed answer #8), then a real value e.g. '06'.",
    )
    effective_date: str = Field(default="", description="Human-printed, e.g. 'August 2026'. Blank while in Draft.")
    next_review_due: str = Field(default="", description="Human-printed, e.g. 'August 2027'.")
    standards: list[StandardEntry] = Field(default_factory=list)

    @classmethod
    def from_json(cls, raw: Any) -> "CdtCoverFacts":
        """Parse the CDTCoverFacts column. Tolerant of None/""/dict/JSON string."""
        if not raw:
            return cls()
        if isinstance(raw, dict):
            return cls.model_validate(raw)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"CDTCoverFacts is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("CDTCoverFacts JSON must be an object")
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()


# =============================================================================
#  MergeContext — the flat render context templates actually see
# =============================================================================

class MergeContext(BaseModel):
    """
    The resolved control facts fed into the template render.

    IMPORTANT: every scalar field name here is a marker the template may use
    (e.g. field `version` → marker `{{ version }}`). `revision_history` and
    `standards` are the two lists, each consumed by its own repeating-row
    marker (`{%tr for r in revision_history %}` / `{%tr for s in standards %}`).

    All scalars default to "" so the render context is always complete — an
    absent value renders as empty, never as a missing-variable error. (A
    marker NOT in this set — a template typo — still fails loudly via
    StrictUndefined.)
    """

    doc_code: str = ""
    title: str = ""
    doc_type: str = ""          # short form for the subtitle, e.g. "Procedure"
    type_layer: str = ""        # full cover cell, e.g. "Procedure (Layer 4)"
    domain: str = ""
    parent_document: str = ""
    classification: str = ""
    distribution: str = ""
    owner: str = ""              # role/group label — see CdtCoverFacts.owner
    first_pass_approval: str = ""
    final_approval: str = ""
    version: str = ""            # may be the literal string "Draft"
    effective_date: str = ""
    next_review_due: str = ""
    standards: list[StandardEntry] = Field(default_factory=list)
    revision_history: list[RevisionHistoryEntry] = Field(default_factory=list)

    def to_template_context(self) -> dict:
        """
        Render context for docxtpl. model_dump() turns nested entries into plain
        dicts; jinja resolves `s.name` / `r.version` against a dict correctly.
        """
        return self.model_dump()

    @classmethod
    def _doc_type_short(cls, doc_type: Any) -> str:
        if hasattr(doc_type, "value"):  # DocumentType enum → its printable value
            return doc_type.value
        return doc_type or ""

    @classmethod
    def from_document_read(cls, doc: "DocumentRead") -> "MergeContext":
        """
        Build a MergeContext from an APPROVED Document Register record — used
        once a document is live/published. Duck-typed (reads attributes) so
        this module keeps no runtime dependency on the grc layer.

        `effective_date`/`next_review_date` are real `date` objects on the
        register (used elsewhere for calculations, e.g. Standards Map) — they
        are formatted into the human-printed cover style here, at render time,
        rather than duplicating them as separate free-text fields.
        """
        cover: CdtCoverFacts = getattr(doc, "cdt_cover", None) or CdtCoverFacts()
        history = RevisionHistoryEntry.list_from_json(getattr(doc, "revision_history", None))

        eff = getattr(doc, "effective_date", None)
        nrd = getattr(doc, "next_review_date", None)

        return cls(
            doc_code=getattr(doc, "document_code", None) or "",
            title=getattr(doc, "title", None) or "",
            doc_type=cls._doc_type_short(getattr(doc, "type", "")),
            type_layer=cover.type_layer,
            domain=cover.domain,
            parent_document=cover.parent_document,
            classification=cover.classification,
            distribution=cover.distribution,
            owner=cover.owner,
            first_pass_approval=cover.first_pass_approval,
            final_approval=cover.final_approval,
            version=cover.version,
            effective_date=eff.strftime("%B %Y") if eff else cover.effective_date,
            next_review_due=nrd.strftime("%B %Y") if nrd else cover.next_review_due,
            standards=list(cover.standards),
            revision_history=history,
        )

    @classmethod
    def from_lifecycle_dict(cls, doc: dict) -> "MergeContext":
        """
        Build a MergeContext from a Document Lifecycle item — the dict shape
        returned by lifecycle/router.py's `_sp_to_doc()`. This is the path used
        BEFORE a document is approved (Draft / Review / Sensitisation /
        Approval), so a live preview reflects whatever Compliance has entered
        so far, including a literal "Draft" version and a blank effective date.
        """
        cover = CdtCoverFacts.from_json(doc.get("CDTCoverFacts", ""))
        history = RevisionHistoryEntry.list_from_json(doc.get("RevisionHistory", ""))

        return cls(
            doc_code=doc.get("DocumentCode", "") or "",
            title=doc.get("Title", "") or "",
            doc_type=cls._doc_type_short(doc.get("DocumentType", "")),
            type_layer=cover.type_layer,
            domain=cover.domain,
            parent_document=cover.parent_document,
            classification=cover.classification,
            distribution=cover.distribution,
            owner=cover.owner,
            first_pass_approval=cover.first_pass_approval,
            final_approval=cover.final_approval,
            version=cover.version,
            effective_date=cover.effective_date,
            next_review_due=cover.next_review_due,
            standards=list(cover.standards),
            revision_history=history,
        )


# The canonical scalar marker vocabulary — the names a template author may use
# (excluding `revision_history` / `standards` and their loop variables).
_LIST_FIELDS: frozenset[str] = frozenset({"revision_history", "standards"})
SCALAR_MARKER_KEYS: frozenset[str] = frozenset(
    k for k in MergeContext.model_fields if k not in _LIST_FIELDS
)
