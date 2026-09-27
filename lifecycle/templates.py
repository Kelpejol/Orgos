# =============================================================================
# lifecycle/templates.py — Controlled Document Templating (CDT) template manager
#
# Two jobs:
#   1. Locate + fetch the one master .docx template per document type from the
#      ORGOS LIBRARY `Templates/` folder (the Graph part).
#   2. Validate a template's STRUCTURE (MT-02): the expected markers are present
#      across the TWO controlled zones, no UNKNOWN markers are referenced, and
#      no marker leaks into the body prose. (The pure, unit-testable part.)
#
# v06: the compliance officer confirmed the header/footer carry no control
# data (blank header; a fixed classification+page-number footer only) — so
# CDT is TWO zones now, not three: the cover (control facts, with the
# `standards` repeating block as its tail) and the revision-history table.
# There is no per-page header strip any more.
#
# Validation is deliberately separate from fetching so it can be exercised with
# no live SharePoint. Marker discovery uses docxtpl's own introspection, which
# stitches Word's run-splitting and scans headers/footers — far more reliable
# than a raw regex over the XML.
#
# Depends on: docxtpl, python-docx, config, graph/client, lifecycle/schemas,
#             lifecycle/merge
# =============================================================================

from __future__ import annotations

import io
from dataclasses import dataclass, field

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docxtpl import DocxTemplate

from config import settings
from graph.client import download_drive_item_by_path, resolve_compliance_drive
from lifecycle.merge import _MARKER_RE, _jinja_env
from lifecycle.schemas import SCALAR_MARKER_KEYS

# The full marker vocabulary a template may reference: the scalar control facts
# plus the two repeating-row loop iterables. (Loop variables `r`/`s` are
# declared by their own loop, so they never appear as "undeclared".)
KNOWN_MARKERS: frozenset[str] = SCALAR_MARKER_KEYS | {"revision_history", "standards"}

# Without these a template cannot fulfil its purpose (the document's identity +
# version). Missing any of them fails validation hard. (v06 dropped separate
# revision/issue markers in favour of the single `version` field.)
REQUIRED_MARKERS: frozenset[str] = frozenset({"doc_code", "version"})

# Expected but not fatal if missing (a template author may omit, e.g., a
# distribution cell). Reported as a warning so authors can confirm intent.
RECOMMENDED_MARKERS: frozenset[str] = KNOWN_MARKERS - REQUIRED_MARKERS


class TemplateError(Exception):
    """Base for template-manager failures."""


class TemplateNotFoundError(TemplateError):
    """No master template exists for the requested document type."""


class InvalidTemplateError(TemplateError):
    """A template failed structural validation. Carries the `.validation`."""

    def __init__(self, validation: "TemplateValidation"):
        self.validation = validation
        super().__init__(validation.summary())


@dataclass
class TemplateValidation:
    """Result of validating a master template's structure."""

    present: set[str] = field(default_factory=set)         # known markers found
    missing_required: list[str] = field(default_factory=list)
    missing_recommended: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)       # referenced, not in vocabulary
    markers_in_body: list[str] = field(default_factory=list)  # markers leaked into body prose

    @property
    def ok(self) -> bool:
        return not self.missing_required and not self.unknown and not self.markers_in_body

    def summary(self) -> str:
        if self.ok:
            note = ""
            if self.missing_recommended:
                note = f" (recommended markers absent: {', '.join(self.missing_recommended)})"
            return f"Template OK — {len(self.present)} known markers present{note}."
        problems = []
        if self.missing_required:
            problems.append(f"missing required markers: {', '.join(self.missing_required)}")
        if self.unknown:
            problems.append(f"unknown markers (typos?): {', '.join(self.unknown)}")
        if self.markers_in_body:
            problems.append(
                f"markers found in body prose (must live only in the cover/history tables): "
                f"{', '.join(dict.fromkeys(self.markers_in_body))}"
            )
        return "Invalid template — " + "; ".join(problems)


def template_filename_for(doc_type: str) -> str:
    """Map a document type to its master template filename, e.g. 'Procedure.docx'."""
    return f"{doc_type}.docx"


def _referenced_markers(source_bytes: bytes) -> set[str]:
    """Every top-level variable the template references (across all zones)."""
    tpl = DocxTemplate(io.BytesIO(source_bytes))
    return set(tpl.get_undeclared_template_variables(_jinja_env()))


def _markers_in_body(source_bytes: bytes) -> list[str]:
    """
    Markers found in true BODY PROSE — a top-level paragraph that comes AFTER
    the last cover/history table in document order.

    The confirmed v06 cover is not purely tabular: the brand block, the
    dynamic "{{ domain }} · {{ doc_type }}" subtitle, and the big document
    title are legitimate cover content sitting in plain paragraphs BEFORE the
    control table — not inside it. So "the two controlled zones" really means
    "everything up to and including the last cover/history table", not
    "only inside a table". Anything AFTER that last table is the document's
    actual prose body (1.0 Purpose, 2.0 Scope, …) and must never carry a
    marker — that's what this check protects.

    Walking `doc.element.body` directly (rather than the separate
    `doc.paragraphs`/`doc.tables` collections) is what lets us tell BEFORE
    from AFTER — paragraphs and tables are siblings in one ordered list, and
    python-docx's separate collections don't preserve that relative order.
    `paragraph.text` reassembles run-split markers, so this is reliable.
    """
    doc = Document(io.BytesIO(source_bytes))
    body = doc.element.body

    last_table_index = -1
    for i, child in enumerate(body):
        if child.tag == qn("w:tbl"):
            last_table_index = i
    if last_table_index == -1:
        # No table at all — every paragraph is "after" (nothing to exempt).
        last_table_index = -1

    found: list[str] = []
    for i, child in enumerate(body):
        if child.tag == qn("w:p") and i > last_table_index:
            para = Paragraph(child, doc)
            found.extend(_MARKER_RE.findall(para.text))
    return found


def validate_template(source_bytes: bytes) -> TemplateValidation:
    """
    Validate a master template's structure (MT-02). Pure — no I/O.

    Fails when: a required marker is missing, an unknown marker is referenced
    (typo / not in the register vocabulary), or a marker leaks into body prose.
    """
    referenced = _referenced_markers(source_bytes)
    return TemplateValidation(
        present=referenced & KNOWN_MARKERS,
        missing_required=sorted(REQUIRED_MARKERS - referenced),
        missing_recommended=sorted(RECOMMENDED_MARKERS - referenced),
        unknown=sorted(referenced - KNOWN_MARKERS),
        markers_in_body=_markers_in_body(source_bytes),
    )


async def fetch_master_template(doc_type: str) -> bytes:
    """
    Download the master template bytes for a document type from the ORGOS
    LIBRARY `Templates/` folder. Raises TemplateNotFoundError if absent.
    """
    filename = template_filename_for(doc_type)
    path = f"{settings.cdt_templates_folder}/{filename}"
    _, drive_id = await resolve_compliance_drive()
    try:
        return await download_drive_item_by_path(drive_id, path)
    except Exception as exc:  # GraphNotFoundError et al.
        raise TemplateNotFoundError(
            f"No master template for document type '{doc_type}' at "
            f"'{path}' in the ORGOS LIBRARY."
        ) from exc


async def load_master_template(doc_type: str, *, validate: bool = True) -> bytes:
    """
    Fetch AND (by default) validate the master template for a document type.
    Raises InvalidTemplateError if validation fails, so a structurally broken
    master can never be used for a merge.
    """
    source = await fetch_master_template(doc_type)
    if validate:
        result = validate_template(source)
        if not result.ok:
            raise InvalidTemplateError(result)
    return source
