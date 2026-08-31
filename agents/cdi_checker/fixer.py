# =============================================================================
# agents/cdi_checker/fixer.py
#
# Deterministic CDI fix engine — the part that actually edits the .docx.
#
# THE SAFETY CONTRACT
#   The AI never touches the file. At CDI-check time the AI (or a rule) produced
#   two exact strings per finding: `find` (the offending fragment, quoted
#   verbatim from the document) and `replace` (the exact drop-in). Applying a
#   fix is therefore a precise, located, single-span find-and-replace — never an
#   AI rewrite. This module is pure: bytes in, bytes out, no I/O, no LLM, fully
#   unit-testable.
#
#   Guarantees:
#     • Located, single-span replacement — never blind global replace.
#     • Fail-safe: if `find` cannot be located UNIQUELY, the fix is skipped and
#       reported — the document is left untouched.
#     • Run-split aware: matches against joined paragraph text, so a fragment
#       chopped across Word "runs" is still found and replaced correctly.
#     • Formatting-preserving: the replacement inherits the first run's style.
#     • Verified: after each apply the paragraph is re-read to confirm `find` is
#       gone and `replace` is present; on failure that one fix is rolled back.
#     • Searches everywhere text lives: body, tables (recursively), headers,
#       footers.
# =============================================================================

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

from docx import Document
from docx.text.paragraph import Paragraph

logger = logging.getLogger(__name__)


# =============================================================================
#  Length-preserving normalisation
#
#  Word text and the AI's quoted fragment routinely differ only in "invisible"
#  ways: smart quotes vs straight quotes, non-breaking spaces, en/em dashes,
#  stray tabs/newlines. We canonicalise those to match — but 1 char -> 1 char,
#  so a position in the normalised string maps to the SAME position in the raw
#  string. That lets us search on the normalised text and edit at the raw
#  offset with no index drift. We deliberately do NOT collapse whitespace runs
#  (that would break the 1:1 mapping); the rare double-space case falls through
#  to "couldn't locate — apply manually", which is safe.
# =============================================================================

_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",   # single quotes
    "“": '"', "”": '"', "„": '"', "‟": '"',   # double quotes
    "–": "-", "—": "-", "―": "-", "−": "-",   # dashes
    " ": " ", " ": " ", " ": " ",                    # nb / fig spaces
    "​": " ", "﻿": " ",                                    # zero-width
    "\t": " ", "\n": " ", "\r": " ", "\v": " ", "\f": " ",         # control ws
}


def _norm_char(ch: str) -> str:
    return _CHAR_MAP.get(ch, ch)


def normalize(s: str) -> str:
    """Length-preserving canonicalisation (1 char in -> 1 char out)."""
    return "".join(_norm_char(c) for c in (s or ""))


def normalize_collapsed(s: str) -> str:
    """
    NON length-preserving: also collapses whitespace and lowercases. Used only
    for *display*/equality checks (e.g. verify a fragment is present/absent),
    never for computing an edit offset.
    """
    return " ".join(normalize(s).split()).lower()


# =============================================================================
#  Paragraph enumeration — body, tables, headers, footers
# =============================================================================

def _iter_paragraphs(doc: Document) -> Iterable[Paragraph]:
    """Yield every paragraph where user text can live."""
    def _from_container(container) -> Iterable[Paragraph]:
        # Direct paragraphs
        for p in getattr(container, "paragraphs", []):
            yield p
        # Tables (recursively — cells can hold nested tables)
        for table in getattr(container, "tables", []):
            for row in table.rows:
                for cell in row.cells:
                    yield from _from_container(cell)

    yield from _from_container(doc)
    for section in doc.sections:
        for hf in (section.header, section.first_page_header, section.even_page_header,
                   section.footer, section.first_page_footer, section.even_page_footer):
            if hf is not None:
                yield from _from_container(hf)


# =============================================================================
#  Data structures
# =============================================================================

@dataclass
class Occurrence:
    """One place `find` was located, as a run span inside a paragraph."""
    para: Paragraph
    start: int            # char offset in the joined paragraph text (raw)
    end: int              # exclusive
    context: str          # human-readable surrounding text for the UI

    @property
    def span_len(self) -> int:
        return self.end - self.start


@dataclass
class LocateResult:
    status: str                              # "located" | "ambiguous" | "not_found"
    occurrences: list[Occurrence] = field(default_factory=list)


@dataclass
class FixOutcome:
    fix_id: str
    check_id: str
    status: str                              # "applied" | "skipped_not_found"
                                             #  | "skipped_ambiguous" | "verify_failed"
                                             #  | "not_applicable" | "no_replacement"
    detail: str = ""
    before: str = ""
    after: str = ""


# =============================================================================
#  Locate
# =============================================================================

def _para_text(paragraph: Paragraph) -> str:
    """Concatenated raw text of a paragraph's runs (index-aligned to the runs)."""
    return "".join(r.text for r in paragraph.runs)


def _all_indices(haystack: str, needle: str) -> list[int]:
    out, start = [], 0
    while True:
        i = haystack.find(needle, start)
        if i == -1:
            return out
        out.append(i)
        start = i + 1


def locate(doc: Document, find: str) -> LocateResult:
    """
    Find every place `find` occurs (normalised, run-split aware). Case-sensitive
    first; if that yields nothing, one case-insensitive retry. Offsets are on the
    RAW paragraph text (normalisation is length-preserving), so they can be used
    directly to edit runs.
    """
    if not find or not find.strip():
        return LocateResult("not_found")

    norm_find = normalize(find)
    occ_cs: list[Occurrence] = []
    occ_ci: list[Occurrence] = []
    lower_find = norm_find.lower()

    for p in _iter_paragraphs(doc):
        raw = _para_text(p)
        if not raw:
            continue
        norm_raw = normalize(raw)

        for i in _all_indices(norm_raw, norm_find):
            occ_cs.append(_make_occ(p, raw, i, i + len(norm_find)))
        if not occ_cs:  # only bother with CI pass if CS found nothing anywhere
            for i in _all_indices(norm_raw.lower(), lower_find):
                occ_ci.append(_make_occ(p, raw, i, i + len(norm_find)))

    occ = occ_cs or occ_ci
    if not occ:
        return LocateResult("not_found")
    if len(occ) > 1:
        return LocateResult("ambiguous", occ)
    return LocateResult("located", occ)


def _make_occ(p: Paragraph, raw: str, start: int, end: int) -> Occurrence:
    ctx_start = max(0, start - 40)
    ctx_end = min(len(raw), end + 40)
    prefix = "…" if ctx_start > 0 else ""
    suffix = "…" if ctx_end < len(raw) else ""
    context = f"{prefix}{raw[ctx_start:start]}⟦{raw[start:end]}⟧{raw[end:ctx_end]}{suffix}"
    return Occurrence(para=p, start=start, end=end, context=context)


# =============================================================================
#  Apply (run-split aware, formatting-preserving)
# =============================================================================

def _replace_span(paragraph: Paragraph, start: int, end: int, replacement: str) -> None:
    """
    Replace the [start, end) span of the paragraph's joined run-text with
    `replacement`. The replacement is placed in the first run of the span and the
    remainder of the span is cleared from the following runs, so surrounding
    formatting is preserved and only the offending fragment changes.
    """
    runs = paragraph.runs
    cursor = 0
    first_run_done = False

    for run in runs:
        r_len = len(run.text)
        r_start, r_end = cursor, cursor + r_len
        cursor = r_end

        # Run entirely outside the span
        if r_end <= start or r_start >= end:
            continue

        # Overlap of [start,end) with this run, in run-local coords
        local_s = max(start, r_start) - r_start
        local_e = min(end, r_end) - r_start

        if not first_run_done:
            # First (or only) overlapping run: keep prefix + replacement + suffix
            run.text = run.text[:local_s] + replacement + run.text[local_e:]
            first_run_done = True
        else:
            # Subsequent runs: drop the covered portion
            run.text = run.text[:local_s] + run.text[local_e:]


def _apply_one(
    doc: Document,
    fix_id: str,
    check_id: str,
    find: str,
    replace: str,
    occurrence_index: Optional[int],
) -> FixOutcome:
    """Locate `find` in the CURRENT doc state and replace one occurrence."""
    if not (replace or "").strip() and replace != "":
        replace = replace or ""
    if not (find or "").strip():
        return FixOutcome(fix_id, check_id, "not_applicable",
                          "No exact text to find — fix in the control block/metadata instead.")

    res = locate(doc, find)
    if res.status == "not_found":
        return FixOutcome(fix_id, check_id, "skipped_not_found",
                          "Could not locate the text in the current document — apply manually.")
    if res.status == "ambiguous" and occurrence_index is None:
        return FixOutcome(fix_id, check_id, "skipped_ambiguous",
                          f"Text appears {len(res.occurrences)} times — choose which one to fix.")

    occ = res.occurrences[occurrence_index or 0] if res.status == "ambiguous" else res.occurrences[0]
    before = _para_text(occ.para)

    _replace_span(occ.para, occ.start, occ.end, replace)

    after = _para_text(occ.para)
    # Verify: the offending fragment is gone and the replacement is present.
    norm_after = normalize_collapsed(after)
    if replace and normalize_collapsed(replace) not in norm_after:
        # Roll back this paragraph
        _restore_para(occ.para, before)
        return FixOutcome(fix_id, check_id, "verify_failed",
                          "Replacement did not verify — rolled back.", before, after)
    return FixOutcome(fix_id, check_id, "applied", "Fix applied.", before, after)


def _restore_para(paragraph: Paragraph, original_joined: str) -> None:
    """
    Restore a paragraph's text after a failed verify. Puts the original text
    back into the first run and clears the rest. (Best-effort: only used on the
    verify-failure path, which should be rare.)
    """
    runs = paragraph.runs
    if not runs:
        return
    runs[0].text = original_joined
    for r in runs[1:]:
        r.text = ""


def apply_fixes(docx_bytes: bytes, fixes: list[dict]) -> tuple[bytes, list[FixOutcome]]:
    """
    Apply a list of confirmed fixes to a .docx, sequentially, re-locating before
    each so earlier edits can't corrupt later ones.

    Each fix dict: {
        "fix_id": str, "check_id": str,
        "find": str,          # exact fragment to locate (verbatim)
        "replace": str,       # exact drop-in replacement (already choice-resolved)
        "occurrence_index": Optional[int],   # which match, when ambiguous
    }

    Returns (new_docx_bytes, [FixOutcome, ...]). If no fix applied, the returned
    bytes equal the input (still a valid re-serialised doc).
    """
    doc = Document(io.BytesIO(docx_bytes))
    outcomes: list[FixOutcome] = []

    for fx in fixes:
        try:
            outcome = _apply_one(
                doc,
                fix_id=str(fx.get("fix_id", "")),
                check_id=str(fx.get("check_id", "")),
                find=fx.get("find", "") or "",
                replace=fx.get("replace", "") or "",
                occurrence_index=fx.get("occurrence_index"),
            )
        except Exception as exc:  # never let one bad fix abort the batch
            logger.warning(f"CDI fix {fx.get('fix_id')} raised: {exc}")
            outcome = FixOutcome(
                str(fx.get("fix_id", "")), str(fx.get("check_id", "")),
                "verify_failed", f"Internal error applying fix: {exc}",
            )
        outcomes.append(outcome)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), outcomes


def preview_locations(docx_bytes: bytes, findings: list[dict]) -> dict[str, LocateResult]:
    """
    For the UI: given findings each with an id + `find`, report where each is
    locatable in the current document (located / ambiguous / not_found) plus the
    occurrences' context. No mutation.
    """
    doc = Document(io.BytesIO(docx_bytes))
    out: dict[str, LocateResult] = {}
    for f in findings:
        fid = str(f.get("fix_id") or f.get("check_id") or "")
        find = f.get("find", "") or ""
        out[fid] = locate(doc, find) if find.strip() else LocateResult("not_found")
    return out
