#!/usr/bin/env python3
# =============================================================================
# scripts/fix_intake_items.py — correct what intake guessed on existing items
#
# Intake used to fill in a document's code, type, title, department and
# standards by guessing from loose text (it filed a Standard as a Form because
# 'form' is inside 'Information'; took a CITED document's code as the
# document's own; gave 87 of 123 documents the department GRC and all of them
# every standard). It now reads each from the document itself. This re-reads
# the file of every intake item still in Review and corrects the item.
# Approved items, and items a person created, are never touched.
#
#   python scripts/fix_intake_items.py           # dry run — lists every change
#   python scripts/fix_intake_items.py --apply
# =============================================================================

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INTAKE_TRIGGERS = {"SharePoint Intake", "CDI Fix"}
PLACEHOLDER_STANDARDS = "ISO 27001, ISO 9001, NDPA"      # scripts/patch_bare_lifecycle_items.py's blanket default


async def run(apply: bool) -> int:
    from config import settings
    from graph.client import download_file_from_sharepoint, get_list_items, shutdown, startup, update_list_item
    from lifecycle.router import _filename_from_sharepoint_url
    from scripts.intake_sharepoint_to_lifecycle import classify_for_lifecycle, read_header

    await startup()
    try:
        items = await get_list_items(settings.document_lifecycle_list_id, "Document Lifecycle")
        changes: list[tuple[str, str, dict]] = []
        for item in items:
            f = item.get("fields") or {}
            if (f.get("Stage") != "Review" or f.get("ApprovalStatus") == "Approved"
                    or f.get("Trigger") not in INTAKE_TRIGGERS or not f.get("SharePointFileUrl")):
                continue
            try:
                data, content_type = await download_file_from_sharepoint(f["SharePointFileUrl"])
            except Exception as exc:
                print(f"  SKIP {f.get('Title')}: could not read the file ({exc})")
                continue
            name = _filename_from_sharepoint_url(f["SharePointFileUrl"], content_type)
            header = read_header(data, name)
            if header is None:
                print(f"  SKIP {f.get('Title')}: the file can't be parsed")
                continue
            folder = (f.get("Notes") or "").split("Source folder:")[-1].strip(" .")
            c = classify_for_lifecycle(name, folder, header["code"], header)
            want = {"DocumentCode": c.document_code, "DocumentType": c.document_type,
                    "Department": c.department, "Title": c.title}
            if c.standards:
                want["StandardsMapping"] = c.standards
            elif (f.get("StandardsMapping") or "").strip() == PLACEHOLDER_STANDARDS:
                # The blanket default an old patch script wrote on items with no standards. The document
                # states none, so none is the truth; left in place it would flow into the Document Register.
                want["StandardsMapping"] = ""
            diff = {k: v for k, v in want.items()
                    if (f.get(k) or "") != v and (v or k in ("DocumentCode", "StandardsMapping"))}
            if diff:
                changes.append((str(item["id"]), f.get("Title") or name, {k: (f.get(k) or "", v) for k, v in diff.items()}))

        for _, title, diff in changes:
            print(f"\n{title}")
            for k, (have, want) in diff.items():
                print(f"    {k:15} {have or '(none)'}  →  {want or '(none)'}")
        print(f"\n{len(changes)} item(s) to correct.")
        if not apply:
            print("Dry run — nothing written. Re-run with --apply.")
            return 0
        for item_id, _, diff in changes:
            await update_list_item(settings.document_lifecycle_list_id, "Document Lifecycle",
                                   item_id, {k: v for k, (_, v) in diff.items()})
        print(f"Corrected {len(changes)}.")
        return 0
    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    sys.exit(asyncio.run(run(parser.parse_args().apply)))
