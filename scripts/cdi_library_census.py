# =============================================================================
# scripts/cdi_library_census.py — how the Control Library reads, document by document
#
# Runs the CDI parser over every document in the Control Library and reports:
#   - each document's role (Defining / Implementing / Authority / Supporting /
#     Unstructured), what it defines and carries out, and its findings;
#   - how much of the library is structured enough to read without AI;
#   - cross-document findings: controls defined twice, carried out but
#     defined nowhere, defined but carried out by nothing;
#   - folder and file names that look like drafts, WIP or superseded copies,
#     so the exclusion rules can be checked against the real library before
#     ingestion is switched on.
#
# READ-ONLY. It downloads and reads; it writes nothing to SharePoint.
#
# Usage:
#   python scripts/cdi_library_census.py                    # the SharePoint library
#   python scripts/cdi_library_census.py --folder "Policies" # one root folder
#   python scripts/cdi_library_census.py --local docs/       # files on disk
#   python scripts/cdi_library_census.py --json report.json # also write everything as JSON
# =============================================================================

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdi.library import LibraryIndex, document_label
from cdi.model import DocumentRole, ParsedDocument, Severity
from cdi.parser import parse_document
from cdi.reader import UnsupportedDocument

# Names that suggest a copy should not be ingested. Reported, not excluded:
# the real conventions are confirmed from this report first.
_SUSPECT_NAME = re.compile(
    r"\b(wip|draft|superseded|archived?|old|retired|obsolete|copy of|backup|deprecated)\b",
    re.IGNORECASE,
)
_ROLE_ORDER = [r.value for r in DocumentRole]


class Entry:
    def __init__(self, path: str, doc: Optional[ParsedDocument] = None, error: str = ""):
        self.path, self.doc, self.error = path, doc, error


def _parse(path: str, data: bytes) -> Entry:
    try:
        return Entry(path, parse_document(data, os.path.basename(path)))
    except UnsupportedDocument as exc:
        return Entry(path, error=str(exc))
    except Exception as exc:  # a census reports every file; one bad file stops nothing
        return Entry(path, error=f"{type(exc).__name__}: {exc}")


def collect_local(root: str) -> list[Entry]:
    entries = []
    for p in sorted(Path(root).rglob("*")):
        if p.suffix.lower() in {".docx", ".pdf", ".doc"} and not p.name.startswith("~$"):
            entries.append(_parse(str(p.relative_to(root)), p.read_bytes()))
    return entries


async def collect_sharepoint(folder_filter: Optional[str]) -> list[Entry]:
    from graph.client import shutdown, startup
    from scripts.intake_sharepoint_to_lifecycle import (
        configured_intake_roots,
        download_file,
        resolve_compliance_drive,
        walk_folder,
    )

    await startup()
    try:
        _, drive_id = await resolve_compliance_drive()
        files = []
        for root in await configured_intake_roots(drive_id, folder_filter):
            files.extend(await walk_folder(drive_id, root["name"], root["id"]))
        print(f"{len(files)} file(s) found. Reading…", file=sys.stderr)
        entries = []
        for i, f in enumerate(files, 1):
            path = f"{f['folder_path']}/{f['name']}"
            try:
                data, _ = await download_file(drive_id, f["id"])
            except Exception as exc:
                entries.append(Entry(path, error=f"download failed: {exc}"))
                continue
            entries.append(_parse(path, data))
            if i % 25 == 0:
                print(f"  {i}/{len(files)}", file=sys.stderr)
        return entries
    finally:
        await shutdown()


def report(entries: list[Entry]) -> dict:
    docs = [e.doc for e in entries if e.doc]
    lib = LibraryIndex(docs)
    roles = Counter(d.role.value for d in docs)

    print("\n" + "=" * 100)
    print("DOCUMENTS")
    print("=" * 100)
    for e in entries:
        if e.error:
            print(f"  {e.path[:62]:62}  UNREADABLE  {e.error[:60]}")
            continue
        d = e.doc
        problems = Counter(f.severity.value for f in d.findings if f.severity is not Severity.INFO)
        flag = ", ".join(f"{n} {s}" for s, n in sorted(problems.items())) or "ok"
        print(f"  {e.path[:62]:62}  {d.role.value:12} {d.header.code or '-':24} "
              f"defines {len(d.controls):3}  carries out {len(d.implemented_ids):3}  {flag}")

    structured = sum(n for r, n in roles.items() if r != DocumentRole.UNSTRUCTURED.value)
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"  Files: {len(entries)}  read: {len(docs)}  unreadable: {len(entries) - len(docs)}")
    for role in _ROLE_ORDER:
        if roles.get(role):
            print(f"    {role:13} {roles[role]}")
    if docs:
        print(f"  Readable from structure, no AI needed: {structured} of {len(docs)} "
              f"({100 * structured // len(docs)}%)")
    print(f"  Controls defined: {sum(len(d.controls) for d in docs)}  "
          f"distinct IDs carried out: {len(lib.implemented_by)}")

    cross = lib.findings()
    print("\n" + "=" * 100)
    print("ACROSS DOCUMENTS")
    print("=" * 100)
    for kind, n in Counter(f.finding.kind.value for f in cross).most_common():
        print(f"  {kind:26} {n}")
    for f in cross:
        if f.finding.severity is not Severity.INFO:
            print(f"    {f.finding.severity.value:7} {f.document}: {f.finding.message[:110]}")

    suspects = [e.path for e in entries if _SUSPECT_NAME.search(e.path)]
    print("\n" + "=" * 100)
    print("NAMES THAT LOOK LIKE DRAFTS OR OLD COPIES (not excluded — check these)")
    print("=" * 100)
    for p in suspects or ["  (none)"]:
        print(f"  {p}")

    return {
        "documents": [
            {"path": e.path, "error": e.error, "parsed": e.doc.to_dict() if e.doc else None}
            for e in entries
        ],
        "summary": {"roles": dict(roles), "files": len(entries), "read": len(docs)},
        "library_findings": [
            {"document": f.document, "kind": f.finding.kind.value,
             "severity": f.finding.severity.value, "message": f.finding.message}
            for f in cross
        ],
        "suspect_names": suspects,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else None)
    ap.add_argument("--local", help="read documents from this directory instead of SharePoint")
    ap.add_argument("--folder", help="only this SharePoint root folder")
    ap.add_argument("--json", help="also write the full report to this file")
    args = ap.parse_args()

    entries = collect_local(args.local) if args.local else asyncio.run(collect_sharepoint(args.folder))
    data = report(entries)
    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\nFull report written to {args.json}")


if __name__ == "__main__":
    main()
