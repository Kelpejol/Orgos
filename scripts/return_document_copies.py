#!/usr/bin/env python3
# =============================================================================
# scripts/return_document_copies.py — put OrgOS's old copies back into the library
#
# OrgOS used to copy a document into "Lifecycle Documents/{item}/" on the OrgOS
# site before changing it (Fix CDI issues, Use this role, amendments, a cover,
# a conversion, Edit in Word) and to publish an approved document as a second
# copy under ".../Published/". The library file never saw those changes. Now a
# document has one file — the library's — and OrgOS saves over it.
#
# This finds every Lifecycle item and Document Register entry still pointing at
# such a copy, and with --apply:
#   • saves the copy's content over the document's file in the library (a new
#     SharePoint version: the library's previous content stays in its history).
#     Where there are several copies of one document, the newest work wins: a
#     document still in Lifecycle, else its approved (published) copy;
#   • points the items and the Register entry at the library file;
#   • with --delete-copies too, deletes the copies it returned (to the SharePoint
#     recycle bin, from which they can be restored for 93 days).
# The library original is found from the intake record (scripts/intake_lifecycle_
# checkpoint.json), else by its file name when exactly one library file has it.
# Anything it cannot match is listed and left alone. A library file that was
# itself changed after the copy was made (edited in SharePoint meanwhile) has
# work in BOTH places: it is never overwritten; it is listed for a person to
# decide, and --use-copy <item id> returns that one anyway.
#
# Run it BEFORE scripts/reset_data.py: the purge re-reads the library, so work
# that is only in a copy would be lost.
#
#   python scripts/return_document_copies.py                        # dry run: lists everything
#   python scripts/return_document_copies.py --apply                # return the work
#   python scripts/return_document_copies.py --apply --delete-copies
# =============================================================================

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COPY_FOLDER = "/Lifecycle Documents/"
CHECKPOINT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intake_lifecycle_checkpoint.json")


def is_copy(meta: dict) -> bool:
    path = unquote((meta.get("parentReference") or {}).get("path", "")) + "/"
    return COPY_FOLDER in path


def intake_record() -> dict[str, str]:
    """Lifecycle item id → the library file intake made it from."""
    try:
        with open(CHECKPOINT, encoding="utf-8") as fh:
            created = json.load(fh).get("created", [])
    except (OSError, ValueError):
        return {}
    return {str(c.get("lifecycle_id")): c.get("id", "") for c in created if c.get("lifecycle_id")}


async def library_files(drive_id: str, folder_id: str, path: str = "") -> list[dict]:
    from graph.client import list_drive_children
    files = []
    for child in await list_drive_children(drive_id, folder_id):
        if "folder" in child:
            files.extend(await library_files(drive_id, child["id"], f"{path}/{child['name']}"))
        else:
            files.append({**child, "_path": f"{path}/{child['name']}".lstrip("/")})
    return files


def changed_since_copied(original: dict, copy_meta: dict) -> bool:
    """The library file was saved after the copy was made: both hold work the other lacks."""
    return (original.get("lastModifiedDateTime") or "") > (copy_meta.get("createdDateTime") or "~")


async def run(apply: bool, delete_copies: bool, use_copy: set[str]) -> int:
    from config import settings
    from graph import client as gc
    from lifecycle.document_file import DocFile, content_digest, state_json

    await gc.startup()
    try:
        _, drive_id = await gc.resolve_compliance_drive()
        start = next((c for c in await gc.list_drive_children(drive_id)
                      if c.get("name") == settings.compliance_starting_folder and "folder" in c), None)
        if start is None:
            print(f"'{settings.compliance_starting_folder}' was not found in the library.")
            return 1
        library = await library_files(drive_id, start["id"])
        by_id = {f["id"]: f for f in library}
        by_name: dict[str, list[dict]] = defaultdict(list)
        for f in library:
            by_name[f["name"].lower()].append(f)
        made_from = intake_record()

        lifecycle = await gc.get_list_items(settings.document_lifecycle_list_id, "Document Lifecycle")
        register = (await gc.get_list_items(settings.document_register_list_id, "Document Register")
                    if settings.is_list_configured(settings.document_register_list_id) else [])

        # Every copy, with what points at it.
        copies: list[dict] = []
        unreadable: list[str] = []
        for list_name, column, rows in (("Document Lifecycle", "SharePointFileUrl", lifecycle),
                                        ("Document Register", "SharePointUrl", register)):
            for row in rows:
                fields = row.get("fields") or {}
                url = fields.get(column) or ""
                if not url:
                    continue
                try:
                    meta = await gc.sharepoint_item_metadata(url)
                except Exception as exc:
                    if "Lifecycle%20Documents" in url or "Lifecycle Documents" in url:
                        unreadable.append(f"{list_name} {row.get('id')}: {url} ({str(exc)[:80]})")
                    continue
                if is_copy(meta):
                    copies.append({"list": list_name, "column": column, "row": row, "fields": fields, "meta": meta})

        if not copies:
            print("Nothing points at an OrgOS copy: every document already uses its library file.")
        # The library original of each copy.
        groups: dict[str, list[dict]] = defaultdict(list)
        unmatched: list[str] = []
        for c in copies:
            original = None
            if c["list"] == "Document Lifecycle":
                original = by_id.get(made_from.get(str(c["row"].get("id")), ""))
            if original is None:
                same = by_name.get(c["meta"].get("name", "").lower(), [])
                original = same[0] if len(same) == 1 else None
                if original is None:
                    unmatched.append(f"{c['list']} {c['row'].get('id')} {c['fields'].get('DocumentCode') or ''} "
                                     f"“{c['meta'].get('name')}”: {len(same)} library file(s) have that name")
                    continue
            groups[original["id"]].append(c)

        returned, failed, deleted = 0, 0, 0
        conflicts: list[str] = []
        for original_id, group in groups.items():
            original = by_id[original_id]
            # The newest work wins: a document still in Lifecycle, else its approved published copy.
            def rank(c):
                f = c["fields"]
                in_progress = c["list"] == "Document Lifecycle" and f.get("ApprovalStatus") != "Approved"
                published = c["list"] == "Document Register" or "/Published" in unquote(
                    (c["meta"].get("parentReference") or {}).get("path", ""))
                return (in_progress, published, c["meta"].get("lastModifiedDateTime", ""))
            chosen = max(group, key=rank)
            print(f"\n{original['_path']}")
            for c in group:
                mark = "→ content" if c is chosen else "         "
                print(f"   {mark} {c['list']} {c['row'].get('id')} "
                      f"({c['fields'].get('Stage') or c['fields'].get('Status') or ''}) "
                      f"copy “{c['meta'].get('name')}”, saved {c['meta'].get('lastModifiedDateTime', '')[:16]}")
            if changed_since_copied(original, chosen["meta"]) and str(chosen["row"].get("id")) not in use_copy:
                conflicts.append(f"{original['_path']} (library saved {original.get('lastModifiedDateTime', '')[:16]}, "
                                 f"copy made {chosen['meta'].get('createdDateTime', '')[:16]}): item "
                                 f"{chosen['row'].get('id')}")
                print("   CHANGED IN BOTH PLACES — left alone (see the end)")
                continue
            if not apply:
                continue
            try:
                meta = chosen["meta"]
                copy_drive = (meta.get("parentReference") or {}).get("driveId", "")
                data = await gc.download_drive_item(copy_drive, meta["id"])
                current = await gc.download_drive_item(drive_id, original_id)
                saved = original
                if content_digest(current) != content_digest(data):
                    saved = await gc.replace_drive_item_content(drive_id, original_id, data)
                f = DocFile.from_item(saved if saved.get("parentReference") else {**saved, "parentReference": {"driveId": drive_id}})
                for c in group:
                    update = {c["column"]: f.web_url or original.get("webUrl", "")}
                    await gc.update_list_item(
                        settings.document_lifecycle_list_id if c["list"] == "Document Lifecycle"
                        else settings.document_register_list_id, c["list"], str(c["row"].get("id")), update)
                    if c["list"] == "Document Lifecycle":
                        try:
                            await gc.update_list_item(settings.document_lifecycle_list_id, c["list"],
                                                      str(c["row"].get("id")), {"FileState": state_json(f, data)})
                        except Exception:
                            pass                     # FileState column not added yet: changes noticed by date
                returned += 1
                print("   returned to the library; items now point at the library file")
                if delete_copies:
                    for c in group:
                        m = c["meta"]
                        try:
                            await gc.delete_drive_item((m.get("parentReference") or {}).get("driveId", ""), m["id"])
                            deleted += 1
                        except Exception as exc:
                            if "404" not in str(exc) and "not found" not in str(exc).lower():
                                print(f"   could not delete the copy “{m.get('name')}”: {str(exc)[:120]}")
            except Exception as exc:
                failed += 1
                print(f"   FAILED: {str(exc)[:200]} — nothing about this document was changed after the failure")

        if unmatched:
            print("\nNot matched to a library file (left alone — return these by hand):")
            for line in unmatched:
                print(f"   {line}")
        if conflicts:
            print("\nChanged in both places — the library file was edited after OrgOS copied it, so each holds")
            print("work the other lacks. Nothing was overwritten. Either redo the OrgOS changes on the library")
            print("file (Fix CDI issues now saves there), or return the copy anyway with --use-copy <item id>:")
            for line in conflicts:
                print(f"   {line}")
        if unreadable:
            print("\nCopies that could not be read (already gone?):")
            for line in unreadable:
                print(f"   {line}")
        print(f"\n{len(groups)} document(s) with copies; {len(unmatched)} not matched; "
              f"{len(conflicts)} changed in both places.")
        if apply:
            print(f"Returned {returned}, failed {failed}" + (f", copies deleted {deleted}." if delete_copies else "."))
        else:
            print("Dry run: nothing written. Re-run with --apply (and --delete-copies to remove the copies).")
        return 1 if failed else 0
    finally:
        await gc.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="return the copies' work to the library")
    parser.add_argument("--delete-copies", action="store_true", help="with --apply: delete the returned copies")
    parser.add_argument("--use-copy", action="append", default=[], metavar="ITEM_ID",
                        help="return this Lifecycle item's copy even though the library file changed too")
    args = parser.parse_args()
    if args.delete_copies and not args.apply:
        parser.error("--delete-copies needs --apply")
    sys.exit(asyncio.run(run(args.apply, args.delete_copies, set(args.use_copy))))


if __name__ == "__main__":
    main()
