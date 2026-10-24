"""Import JD titles into Org Roles. Preview by default; write only with --apply."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from doc_standards.roles import RoleBook, norm, similarity
from graph import client as graph_client
from groups import service as groups_service


@dataclass(frozen=True)
class JobDescription:
    pdf: str
    title: str
    source: str
    department: str = ""
    reports_to: str = ""
    no_text: bool = False
    error: str = ""


_FIELDS = (
    r"job\s*title|role\s*title|position\s*title|employee\s+name|department|"
    r"profession\b[^\n:]*|work\s+level|job\s+grade/level|level|"
    r"interim\s+reporting\s+line|reporting\s+line|reports\s*[-–]?\s*to|"
    r"location|employment\s+type|engagement\s+type|position\s+type|"
    r"effective\s+date|commencement\s+date|document\s+code|job\s+summary"
)
_SECTION = re.compile(
    r"main\s+job\s+purpose|job\s+purpose|about\s+the\s+role|role\s+overview|"
    r"(?:1\.0\s+)?role\s+summary|key\s+responsibilities|^\s*summary\s*:", re.I | re.M,
)


def _clean(value: str) -> str:
    return " ".join(value.split()).strip(" :|\t")


def _field(text: str, label: str, *, multiline: bool = True) -> str:
    match = re.search(rf"(?:{label})[ \t]*:[ \t]*|\b(?:{label})\b[ \t]*", text, re.I)
    if not match:
        return ""
    tail = text[match.end():].lstrip()
    if not multiline:
        tail = tail.splitlines()[0] if tail else ""
    stop = re.search(rf"(?:^[ \t]*(?:{_FIELDS})\b|(?:{_FIELDS})[ \t]*:|Location[ \t]*\()",
                     tail, re.I | re.M)
    value = _clean(tail[:stop.start()] if stop else tail)
    return value if len(value) <= 250 else ""


def _column_department(layout: str) -> str:
    """Keep the department cell apart from profession/level in PDF tables."""
    lines = layout.splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"profession|\blevel\b", line, re.I):
            continue
        columns = list(re.finditer(r"\S.*?(?=\s{2,}|$)", line))
        for j, col in enumerate(columns):
            if col.group().strip().lower().rstrip(":") != "department":
                continue
            if len(columns) < 2:
                continue
            left = max(0, col.start() - 2)
            right = columns[j + 1].start() - 2 if j + 1 < len(columns) else None
            values = []
            for row in lines[i + 1:]:
                if not row.strip():
                    if values:
                        break
                    continue
                if re.search(rf"\b(?:{_FIELDS})\b", row, re.I):
                    break
                cell = _clean(row[left:right])
                if cell:
                    values.append(cell)
            return _clean(" ".join(values))
    return ""


def parse_job_description(pdf: str, text: str, layout: str = "") -> JobDescription:
    filename_title = PurePosixPath(pdf).stem
    if not text.strip():
        return JobDescription(pdf, filename_title, "file name", no_text=True)

    header = _SECTION.split(layout or text, maxsplit=1)[0]
    plain_header = _SECTION.split(text, maxsplit=1)[0]
    title = _field(plain_header, r"job\s*title|role\s*title|position\s*title")
    layout_title = _field(header, r"job\s*title|role\s*title|position\s*title")
    if (not title or (len(layout_title.split()) > len(title.split())
                      and norm(layout_title).replace(" ", "") == norm(title).replace(" ", ""))):
        title = layout_title
    if not title:
        heading = re.search(r"^\s*JOB DESCRIPTION\s*\n\s*([^\n]+)", header, re.I | re.M)
        if heading:
            title = _clean(heading.group(1))
        else:
            # An unlabelled heading is clear when it agrees with the PDF's name.
            title = next((_clean(line) for line in header.splitlines()
                          if norm(line) == norm(filename_title)), "")
    department = _column_department(layout) or _field(plain_header, "department")
    reports_to = _field(plain_header, r"reports\s*[-–]?\s*to|reporting\s+line", multiline=False)
    if not reports_to:
        # Many JDs put the reporting channel after the duties, rather than in the header.
        reporting = re.search(
            r"^[ \t]*(?:[▪•●\uf0b7-][ \t]*)?(?:reports\s*[-–]?\s*to|reporting\s+line)\b"
            r"[ \t]*:?[ \t]*(?:\n[ \t]*)?([^\n]+)", text, re.I | re.M,
        )
        reports_to = _clean(reporting.group(1)) if reporting else ""
    if not reports_to:
        reporting = re.search(r"^\s*Reporting to (?:the )?([^,\n]+),", text, re.I | re.M)
        reports_to = _clean(reporting.group(1)) if reporting else ""
    return JobDescription(pdf, title or filename_title, "PDF text" if title else "file name",
                          department, reports_to)


NAMES_FILE = Path(__file__).with_name("jd_role_names.json")


def load_name_overrides(path: Path = NAMES_FILE) -> dict[str, str]:
    """PDF path in the ZIP -> the role name to create (where the PDF's own title is not the name to use)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: " ".join(v.split()) for k, v in data.items() if not k.startswith("_") and (v or "").strip()}


def apply_name_overrides(descriptions: list[JobDescription], overrides: dict[str, str]) -> list[JobDescription]:
    return [replace(jd, title=overrides[jd.pdf], source="renamed") if jd.pdf in overrides else jd
            for jd in descriptions]


def read_job_descriptions(zip_path: Path) -> list[JobDescription]:
    descriptions = []
    with TemporaryDirectory(prefix="orgos-jds-") as temp, ZipFile(zip_path) as archive:
        pdfs = sorted((info for info in archive.infolist()
                       if not info.is_dir() and info.filename.lower().endswith(".pdf")
                       and "__MACOSX" not in PurePosixPath(info.filename).parts),
                      key=lambda info: info.filename.casefold())
        for i, info in enumerate(pdfs):
            # Never use archive paths as local paths (including ../ entries).
            path = Path(temp) / f"{i}.pdf"
            try:
                with archive.open(info) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                reader = PdfReader(path)
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                layout = reader.pages[0].extract_text(extraction_mode="layout") if reader.pages else ""
                descriptions.append(parse_job_description(info.filename, text, layout or ""))
            except Exception as exc:
                descriptions.append(JobDescription(info.filename, PurePosixPath(info.filename).stem,
                                                   "file name", error=str(exc)))
    return descriptions


async def read_existing_roles() -> list[dict]:
    """GET only: list_groups() would also try to provision lists and columns."""
    data = await graph_client._request(
        "GET", f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}/lists",
        params={"$filter": "displayName eq 'OrgOS Groups'", "$select": "id,displayName"},
    )
    lists = data.get("value", [])
    if not lists:
        print("Org Roles list does not exist yet (read-only lookup; nothing provisioned).")
        return []
    items = await graph_client.get_list_items(lists[0]["id"], "OrgOS Groups")
    # Include withdrawn entries too: never recreate or reactivate an existing role.
    return [groups_service._to_group(item) for item in items]


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[i]) for row in [headers, *rows]) for i in range(len(headers))]
    print(" | ".join(value.ljust(width) for value, width in zip(headers, widths)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(value.ljust(width) for value, width in zip(row, widths)))


async def import_roles(descriptions: list[JobDescription], *, apply: bool = False) -> None:
    existing = await read_existing_roles()
    book = RoleBook.from_groups(existing)
    planned = []
    rows = []
    for jd in descriptions:
        found = book.find(jd.title)
        status = f"Yes: {found.name}" if found else "No"
        if not found:
            pending = RoleBook.from_groups(planned).find(jd.title)
            if pending:
                status = f"No; same title as {pending.group_id}"
            else:
                planned.append({"id": jd.pdf, "name": jd.title})
        rows.append((jd.title, jd.source, jd.department or "—", jd.reports_to or "—", status))

    print("APPLY" if apply else "DRY RUN — no SharePoint writes")
    _table(("Title", "Source", "Department", "Reports to", "Already in Org Roles"), rows)
    print(f"\n{len(descriptions)} PDFs; {len(planned)} new roles; "
          f"{len(existing)} existing roles read (including withdrawn).")
    print("\nPDF provenance:")
    for jd in descriptions:
        print(f"- {jd.pdf} -> {jd.title} ({jd.source})")
    scans = [jd.pdf for jd in descriptions if jd.no_text]
    print(f"\nPDFs with no readable text ({len(scans)}; using file names):")
    for pdf in scans:
        print(f"- {pdf}")
    errors = [jd for jd in descriptions if jd.error]
    print(f"\nUnreadable PDFs ({len(errors)}; using file names):")
    for jd in errors:
        print(f"- {jd.pdf}: {jd.error}")

    print("\nPossible duplicates for human review (no aliases added):")
    for i, jd in enumerate(descriptions):
        for other in descriptions[i + 1:]:
            if norm(jd.title) == norm(other.title) or similarity(jd.title, other.title)[0] >= 80:
                print(f"- {jd.pdf} [{jd.title}] / {other.pdf} [{other.title}]")
    for jd in descriptions:
        if not book.find(jd.title):
            for suggestion in book.suggest(jd.title):
                if suggestion.score >= 80:
                    print(f"- {jd.pdf} [{jd.title}] / existing role [{suggestion.role.name}]")

    if not apply:
        return
    created = 0
    for jd in descriptions:
        if book.find(jd.title):
            continue
        # Refresh before every write, including other entries created in this run.
        existing = await read_existing_roles()
        book = RoleBook.from_groups(existing)
        if book.find(jd.title):
            continue
        description = f"Imported from job description: {jd.pdf}"
        if jd.reports_to:
            description += f"\nReports to: {jd.reports_to}"
        role = await groups_service.create_group(
            name=jd.title, description=description, category=jd.department,
            members=[], creator_oid="", creator_name="JD role import", aliases=[],
        )
        existing.append(role)
        book = RoleBook.from_groups(existing)
        created += 1
        print(f"Created: {jd.title}")
    print(f"\nCreated {created} roles. Existing roles left unchanged.")


async def _run(args: argparse.Namespace) -> None:
    descriptions = await asyncio.to_thread(read_job_descriptions, args.zip_path)
    if not descriptions:
        raise ValueError("The ZIP contains no PDFs.")
    overrides = load_name_overrides()
    unused = sorted(set(overrides) - {jd.pdf for jd in descriptions})
    for pdf in unused:
        print(f"Note: jd_role_names.json names {pdf}, which is not in this ZIP.")
    descriptions = apply_name_overrides(descriptions, overrides)
    await graph_client.startup()
    try:
        await import_roles(descriptions, apply=args.apply)
    finally:
        await graph_client.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path, help="Path to the ZIP of job description PDFs")
    parser.add_argument("--apply", action="store_true", help="Create missing roles with no members or aliases")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args))
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
