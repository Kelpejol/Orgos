# =============================================================================
# scripts/restore_backup.py — put back a list from a reset backup
#
# scripts/reset_data.py writes every item it clears to backups/reset-<time>/<list>.json.
# This recreates the items of one list from that file, with the fields people and
# OrgOS wrote (SharePoint's own system fields are left to SharePoint). Items get new
# ids, so anything that pointed at an old id (a Lifecycle item's link to its Register
# entry, a record's link to a control row) points at nothing until it is rebuilt —
# which is why the reset's rebuild order re-creates them from the documents instead.
# Use it for what documents cannot rebuild: the Audit Log, the Compliance Calendar,
# the Contract Register, the Strategic Risk Register.
#
#   python scripts/restore_backup.py backups/reset-20261031-101500 "Strategic Risk Register"
#   python scripts/restore_backup.py <folder> "<list name>" --apply
# =============================================================================

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# SharePoint's own fields: never written back.
SYSTEM_FIELDS = {
    "id", "ID", "@odata.etag", "ContentType", "Modified", "Created", "AuthorLookupId", "EditorLookupId",
    "_UIVersionString", "Attachments", "Edit", "LinkTitleNoMenu", "LinkTitle", "DocIcon", "ItemChildCount",
    "FolderChildCount", "_ComplianceFlags", "_ComplianceTag", "_ComplianceTagWrittenTime",
    "_ComplianceTagUserId", "AppAuthorLookupId", "AppEditorLookupId",
}


def writable(fields: dict) -> dict:
    return {k: v for k, v in fields.items()
            if k not in SYSTEM_FIELDS and not k.startswith("_") and not k.endswith("LookupId")
            and not k.startswith("@")}


async def main(folder: str, list_name: str, apply: bool) -> int:
    path = os.path.join(folder, "".join(c if c.isalnum() or c in " ._-" else "_" for c in list_name) + ".json")
    if not os.path.exists(path):
        print(f"No backup of {list_name} in {folder}.")
        return 1
    with open(path, encoding="utf-8") as fh:
        backup = json.load(fh)
    items = backup.get("items", [])
    print(f"{list_name}: {len(items)} item(s) in the backup taken {backup.get('taken', '?')}.")
    if not apply:
        print("Dry run: nothing written. Re-run with --apply to recreate them.")
        return 0
    from config import settings
    from graph import client as gc
    list_id = backup.get("list_id") or ""
    if not settings.is_list_configured(list_id):
        print("The list in the backup is not configured here.")
        return 1
    await gc.startup()
    failed = 0
    try:
        for item in items:
            try:
                await gc.create_list_item(list_id, list_name, writable(item.get("fields") or {}))
            except Exception as exc:
                failed += 1
                print(f"  could not restore item {item.get('id')}: {str(exc)[:160]}")
    finally:
        await gc.shutdown()
    print(f"Restored {len(items) - failed} of {len(items)}.")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('usage: python scripts/restore_backup.py <backup folder> "<list name>" [--apply]')
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2], "--apply" in sys.argv[3:])))
