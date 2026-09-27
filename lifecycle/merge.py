# =============================================================================
# lifecycle/merge.py — Controlled Document Templating (CDT) merge engine
#
# The deterministic core of CDT. Given a source .docx (containing {{ markers }})
# and a MergeContext (control facts from the Document Register), it produces a
# published .docx with every marker filled and validated.
#
# HARD INVARIANTS (compliance-critical — see DRG-PSA-CDT-01-26 §10):
#   • DETERMINISTIC — same source + same context ⇒ byte-identical output.
#   • NO AI — this module never calls any inference endpoint. Ever.
#   • FAIL LOUD — a document with an unresolved/leftover marker is never
#     returned; the merge raises instead.
#   • NO I/O — pure transform over bytes. SharePoint/register/audit live in the
#     orchestration layer that calls this engine.
#
# Depends on: docxtpl, jinja2, lifecycle/schemas.py
# =============================================================================

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass

from docx.opc.exceptions import PackageNotFoundError
from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined
from jinja2.exceptions import TemplateSyntaxError, UndefinedError

from lifecycle.schemas import MergeContext

# Matches any leftover jinja/docxtpl marker in rendered XML: {{ }}, {% %}, {# #}
_MARKER_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)

# Any marker-opening token appearing inside a control-fact VALUE (not the
# template) would survive rendering as literal text and then trip the leftover
# scan. Control facts (codes, dates, names, classification…) never legitimately
# contain these, so we reject them up front with a precise error.
_VALUE_TOKEN_RE = re.compile(r"\{\{|\{%|\{#")


# =============================================================================
#  Errors — every failure mode is explicit so callers can react precisely
# =============================================================================

class MergeError(Exception):
    """Base for all merge-engine failures."""


class MissingContextError(MergeError):
    """
    The template references a marker the register did not supply (usually a
    template typo, e.g. {{ revison }}). Raised via jinja StrictUndefined so a
    missing value can never silently render blank.
    """


class TemplateRenderError(MergeError):
    """The source template is not valid (bad jinja/docx structure)."""


class UnresolvedMarkerError(MergeError):
    """
    The rendered output still contains marker tokens. The document must NOT be
    published. `.markers` lists the offending tokens.
    """

    def __init__(self, markers: list[str]):
        self.markers = markers
        preview = ", ".join(dict.fromkeys(markers))  # de-dup, preserve order
        super().__init__(
            f"Merge produced {len(markers)} unresolved marker(s); refusing to "
            f"publish. Tokens: {preview}"
        )


@dataclass(frozen=True)
class MergeResult:
    """Result of a successful merge."""

    document: bytes          # the published .docx
    sha256: str              # hash of `document` — determinism / audit anchor
    doc_code: str            # convenience echo of the document code merged


# =============================================================================
#  Engine
# =============================================================================

def _jinja_env() -> Environment:
    """
    Jinja environment for the merge.

    • undefined=StrictUndefined → an undeclared marker raises instead of
      rendering empty (catches template typos).
    • autoescape=True → values containing XML-significant characters (& < > ")
      are escaped so a title like "Fast & Secure <ops>" cannot corrupt the
      document XML.
    """
    return Environment(undefined=StrictUndefined, autoescape=True)


def scan_markers(docx_bytes: bytes) -> list[str]:
    """
    Return every leftover marker token found anywhere in a .docx's XML parts
    (body, headers, footers, tables — all of word/*.xml). Empty list == clean.

    Scanning the raw XML (rather than python-docx paragraph text) is deliberate:
    it catches markers wherever they hide, including headers/footers/cells.
    """
    found: list[str] = []
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        for name in zf.namelist():
            if name.startswith("word/") and name.endswith(".xml"):
                xml = zf.read(name).decode("utf-8", errors="ignore")
                found.extend(_MARKER_RE.findall(xml))
    return found


# Fields on MergeContext that are lists of sub-entries (each entry itself has
# named string fields) rather than a plain scalar. Both are repeating-row
# markers in the template. Kept in one place so a future third list (were one
# ever added) only needs adding here, not duplicating the whole scan function.
_LIST_ENTRY_FIELDS: tuple[str, ...] = ("revision_history", "standards")


def _assert_values_marker_free(context: MergeContext) -> None:
    """
    Reject control-fact values that themselves contain marker tokens ({{ {% {#).
    Such a value would render as literal text and then be misreported by the
    leftover scan; catching it here gives a precise, actionable error instead.

    Checks every scalar field, and every string field of every entry in every
    list field (revision_history rows, standards rows) — generically, so a
    future list field is covered automatically rather than by copy-paste.
    """
    dump = context.model_dump()
    scalars = {k: v for k, v in dump.items() if k not in _LIST_ENTRY_FIELDS}
    for name, value in scalars.items():
        if isinstance(value, str) and _VALUE_TOKEN_RE.search(value):
            raise MergeError(
                f"Control fact '{name}' contains a template token ({value!r}); "
                f"control-fact values must not contain '{{{{', '{{%' or '{{#'."
            )
    for list_name in _LIST_ENTRY_FIELDS:
        for idx, entry in enumerate(dump.get(list_name, [])):
            for field, value in entry.items():
                if isinstance(value, str) and _VALUE_TOKEN_RE.search(value):
                    raise MergeError(
                        f"{list_name}[{idx}].{field} contains a template token "
                        f"({value!r}); values must not contain '{{{{', '{{%' or '{{#'."
                    )


def render_document(source_bytes: bytes, context: MergeContext) -> bytes:
    """
    Render a source template to published bytes. Does NOT validate leftovers —
    use merge() for the full guaranteed path. Raises MissingContextError /
    TemplateRenderError on template problems.
    """
    try:
        tpl = DocxTemplate(io.BytesIO(source_bytes))
        tpl.render(context.to_template_context(), jinja_env=_jinja_env())
    except UndefinedError as exc:
        raise MissingContextError(
            f"Template references a marker the register did not supply: {exc}. "
            f"Check the template for a typo or an unknown marker name."
        ) from exc
    except TemplateSyntaxError as exc:
        raise TemplateRenderError(
            f"Source template has invalid marker syntax at line {exc.lineno}: {exc.message}"
        ) from exc
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as exc:
        raise TemplateRenderError(
            f"Source is not a readable .docx template: {type(exc).__name__}: {exc}"
        ) from exc
    out = io.BytesIO()
    tpl.save(out)
    return out.getvalue()


def merge(source_bytes: bytes, context: MergeContext) -> MergeResult:
    """
    The full, guaranteed merge path.

    1. Render the source with the register's control facts (StrictUndefined).
    2. Scan the output for any leftover marker → refuse to publish if any.
    3. Return the published bytes + their SHA-256 (determinism/audit anchor).

    Raises MissingContextError / TemplateRenderError / UnresolvedMarkerError /
    MergeError (a control-fact value containing a template token).
    """
    _assert_values_marker_free(context)
    published = render_document(source_bytes, context)

    leftovers = scan_markers(published)
    if leftovers:
        raise UnresolvedMarkerError(leftovers)

    digest = hashlib.sha256(published).hexdigest()
    return MergeResult(document=published, sha256=digest, doc_code=context.doc_code)
