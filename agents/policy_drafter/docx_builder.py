# =============================================================================
# agents/policy_drafter/docx_builder.py
# Converts AI-generated draft sections into a properly formatted .docx file.
# Called after draft_document() produces the sections dict.
# Returns a BytesIO buffer ready for HTTP response / SharePoint upload.
# =============================================================================

import io

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# =============================================================================
#  Colour palette — Dragnet brand
# =============================================================================

BRAND_DARK   = RGBColor(0x1A, 0x1A, 0x2E)   # near-black navy
BRAND_ACCENT = RGBColor(0x37, 0x8A, 0xDD)   # Dragnet blue
BRAND_MID    = RGBColor(0x44, 0x47, 0x5A)   # dark grey


# =============================================================================
#  Helpers
# =============================================================================

def _set_para_border_bottom(para, color: str = "CCCCCC", size: int = 4):
    """Add a bottom border rule to a paragraph (replaces table-as-divider)."""
    pPr = para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _run(para, text: str, bold=False, italic=False,
         size_pt: int = 10, color: RGBColor = None, font: str = "Arial"):
    run = para.add_run(text)
    run.bold  = bold
    run.italic = italic
    run.font.name  = font
    run.font.size  = Pt(size_pt)
    if color:
        run.font.color.rgb = color
    return run


def _heading(doc: Document, text: str, level: int = 1):
    """
    Add a CDI-style section heading with a bottom rule.
    level 1 = major section (blue, 11pt bold)
    level 2 = sub-section (dark, 10pt bold)
    """
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(14 if level == 1 else 8)
    para.paragraph_format.space_after  = Pt(2)
    if level == 1:
        _run(para, text.upper(), bold=True, size_pt=11, color=BRAND_ACCENT)
        _set_para_border_bottom(para, color="378ADD", size=6)
    else:
        _run(para, text, bold=True, size_pt=10, color=BRAND_DARK)
    return para


def _body(doc: Document, text: str, indent: bool = False):
    """Add a body paragraph."""
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after  = Pt(4)
    if indent:
        para.paragraph_format.left_indent = Inches(0.25)
    _run(para, text, size_pt=10, color=BRAND_MID)
    return para


def _bullet(doc: Document, text: str, numbered: bool = False, num_val: int = 1):
    """Add a properly formatted bullet or numbered list item."""
    para = doc.add_paragraph(style="List Bullet" if not numbered else "List Number")
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after  = Pt(2)
    para.paragraph_format.left_indent  = Inches(0.3)
    _run(para, text.lstrip("•-– 0123456789."), size_pt=10, color=BRAND_MID)
    return para


def _parse_and_add_lines(doc: Document, text: str, is_policy_statement: bool = False):
    """
    Intelligently render multi-line AI output:
    - Numbered lines (1. / 2.) → numbered list
    - Dash/bullet lines (- / • / *) → bullet list
    - Sub-role headers (e.g. "Compliance Lead\n-") → bold role + bullets
    - Plain paragraphs → body text
    """
    lines = [l.rstrip() for l in text.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Numbered item: "1." "2." etc.
        if len(line) > 2 and line[0].isdigit() and line[1] in ".)" :
            content = line[2:].strip() if len(line) > 2 else line
            para = doc.add_paragraph(style="List Number")
            para.paragraph_format.space_before = Pt(0)
            para.paragraph_format.space_after  = Pt(3)
            para.paragraph_format.left_indent  = Inches(0.3)
            _run(para, content, size_pt=10, color=BRAND_MID)

        # Bullet item: "- " or "• " or "* "
        elif line.startswith(("-", "•", "*")) and len(line) > 2:
            content = line.lstrip("-•* ").strip()
            para = doc.add_paragraph(style="List Bullet")
            para.paragraph_format.space_before = Pt(0)
            para.paragraph_format.space_after  = Pt(3)
            para.paragraph_format.left_indent  = Inches(0.3)
            _run(para, content, size_pt=10, color=BRAND_MID)

        # Role header in responsibilities section (not starting with dash/number/blank)
        # Heuristic: all-caps or title-case short line followed by bullet lines
        elif (
            not line.startswith(("-", "•", "*"))
            and not (line[0].isdigit() and line[1:2] in (".", ")"))
            and len(line) < 60
            and i + 1 < len(lines)
            and lines[i + 1].strip().startswith("-")
        ):
            para = doc.add_paragraph()
            para.paragraph_format.space_before = Pt(8)
            para.paragraph_format.space_after  = Pt(2)
            _run(para, line, bold=True, size_pt=10, color=BRAND_DARK)

        # Plain body paragraph
        else:
            _body(doc, line)

        i += 1

# =============================================================================
#  Main builder — v06
#
#  The cover, standards block and revision-history table are NOT hand-built
#  here any more — they come from the document TYPE's master CDT template
#  (fetched + validated by the caller via lifecycle.templates.load_master_
#  template). This function opens THAT document and appends the AI-generated
#  body content after it, leaving the master's {{ markers }} untouched — the
#  same "AI never touches the file; deterministic merge does" principle as
#  the rest of CDT. The lifecycle item's cover facts (seeded by
#  draft_document()) get merged into those markers later, on demand
#  (GET .../preview.pdf) and at approval (_finalize_document_approval) — never
#  here. This also means the master template's own page setup, fonts and
#  styling are respected, not overridden by a second, competing style.
# =============================================================================

def build_docx(draft: dict, master_template_bytes: bytes) -> io.BytesIO:
    """
    Build a formatted .docx from a draft dict produced by service.py, on top
    of the document type's master CDT template.

    Parameters
    ----------
    draft : dict
        Must contain: doc_code, sections {purpose, scope, policy_statement,
        responsibilities, procedure, records}.
    master_template_bytes : bytes
        The type's master template (cover + revision-history markers intact).

    Returns
    -------
    io.BytesIO
        Ready to send as HTTP response or upload to SharePoint. Still
        contains live {{ markers }} in its cover — this is the SOURCE
        document, not a published copy.
    """
    doc = Document(io.BytesIO(master_template_bytes))

    sections = draft.get("sections", {})

    # ── 1. Purpose ───────────────────────────────────────────────────────────
    _heading(doc, "1. Purpose", level=1)
    _parse_and_add_lines(doc, sections.get("purpose", "[Purpose not generated]"))
    doc.add_paragraph()

    # ── 2. Scope ─────────────────────────────────────────────────────────────
    _heading(doc, "2. Scope", level=1)
    _parse_and_add_lines(doc, sections.get("scope", "[Scope not generated]"))
    doc.add_paragraph()

    # ── 3. Policy Statement ──────────────────────────────────────────────────
    _heading(doc, "3. Policy Statement", level=1)
    _parse_and_add_lines(doc, sections.get("policy_statement", "[Policy statement not generated]"),
                         is_policy_statement=True)
    doc.add_paragraph()

    # ── 4. Responsibilities ──────────────────────────────────────────────────
    _heading(doc, "4. Responsibilities", level=1)
    _parse_and_add_lines(doc, sections.get("responsibilities", "[Responsibilities not generated]"))
    doc.add_paragraph()

    # ── 5. Procedure ─────────────────────────────────────────────────────────
    _heading(doc, "5. Procedure", level=1)
    _parse_and_add_lines(doc, sections.get("procedure", "Refer to the associated procedure document."))
    doc.add_paragraph()

    # ── 6. Records ───────────────────────────────────────────────────────────
    _heading(doc, "6. Records", level=1)
    records_text = sections.get("records", "")
    if records_text:
        # Records are usually "Name (Type: X) — Source: Y — Retain: Z" lines
        for line in records_text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Render each record as a bullet
            para = doc.add_paragraph(style="List Bullet")
            para.paragraph_format.space_before = Pt(0)
            para.paragraph_format.space_after  = Pt(3)
            para.paragraph_format.left_indent  = Inches(0.3)
            _run(para, line.lstrip("-•* "), size_pt=9, color=BRAND_MID)
    else:
        _body(doc, "[Records not generated]")
    doc.add_paragraph()

    # ── 7. Related Documents ──────────────────────────────────────────────────
    _heading(doc, "7. Related Documents", level=1)
    _body(doc, "[To be completed by document owner]", indent=False)
    doc.add_paragraph()

    # ── End marker ────────────────────────────────────────────────────────────
    doc.add_paragraph()
    end_para = doc.add_paragraph()
    end_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_para_border_bottom(end_para, color="378ADD", size=4)
    _run(end_para, f"END OF DOCUMENT — {draft['doc_code']}",
         size_pt=8, color=BRAND_MID, italic=True)

    # ── Serialize ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
