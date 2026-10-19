# =============================================================================
# scripts/publish_approved_lifecycle.py — Backfill approved lifecycle documents
#
# Finds existing Document Lifecycle items with ApprovalStatus=Approved, creates
# missing Document Register entries, links the lifecycle item to the register,
# then reads the approved library for controls (by Control ID).
#
# Usage:
#   myenv/bin/python scripts/publish_approved_lifecycle.py --dry-run
#   myenv/bin/python scripts/publish_approved_lifecycle.py
#   myenv/bin/python scripts/publish_approved_lifecycle.py --limit 10
#   myenv/bin/python scripts/publish_approved_lifecycle.py --code DRG-ISMS-POL-ACP-01-26
#   myenv/bin/python scripts/publish_approved_lifecycle.py --no-extract
# =============================================================================

import argparse
import asyncio
import logging
import os
import sys
from datetime import date
from typing import Optional
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.cdi_checker.service import is_valid_doc_code
from config import configure_logging, settings
from graph.client import (
    create_list_item,
    download_file_from_sharepoint,
    get_list_items,
    startup,
    shutdown,
    update_list_item,
)

configure_logging()
logger = logging.getLogger(__name__)

LIFECYCLE_LIST = "Document Lifecycle"
REGISTER_LIST = "Document Register"
AI_QUEUE_LIST = "AI Review Queue"


def field_text(fields: dict, key: str) -> str:
    return str(fields.get(key) or "").strip()





def build_register_fields(lifecycle_fields: dict) -> dict:
    effective_date = date.today()
    approved_date = field_text(lifecycle_fields, "ApprovedDate")
    if approved_date:
        try:
            effective_date = date.fromisoformat(approved_date[:10])
        except ValueError:
            pass

    return {
        "Title": field_text(lifecycle_fields, "Title"),
        "DocumentCode": field_text(lifecycle_fields, "DocumentCode"),
        "DocumentType": field_text(lifecycle_fields, "DocumentType"),
        "Department": field_text(lifecycle_fields, "Department"),
        "Status": "Active",
        "OwnerId": field_text(lifecycle_fields, "OwnerEntraId"),
        "Owner": field_text(lifecycle_fields, "Owner"),
        "CurrentVersion": "R01",
        "EffectiveDate": effective_date.isoformat(),
        "ApplicableStandards": field_text(lifecycle_fields, "StandardsMapping"),
        "LinkedControlsCount": 0,
    }


async def existing_register_by_code() -> dict[str, str]:
    if not settings.is_list_configured(settings.document_register_list_id):
        return {}
    items = await get_list_items(settings.document_register_list_id, REGISTER_LIST)
    result: dict[str, str] = {}
    for item in items:
        fields = item.get("fields", {})
        code = field_text(fields, "DocumentCode").upper()
        status = field_text(fields, "Status").lower()
        if code and status != "withdrawn":
            result[code] = str(item.get("id", ""))
    return result



async def write_optional_register_trace(register_item_id: str, lifecycle_fields: dict) -> None:
    optional_fields = {
        "Source": "Document Lifecycle",
    }
    file_url = field_text(lifecycle_fields, "SharePointFileUrl")
    if file_url:
        optional_fields["SharePointUrl"] = file_url
    try:
        await update_list_item(
            settings.document_register_list_id,
            REGISTER_LIST,
            register_item_id,
            optional_fields,
        )
    except Exception as exc:
        logger.warning(f"Optional Document Register trace fields were not written: {exc}")



async def run_publish(
    dry_run: bool,
    limit: Optional[int],
    code_filter: Optional[str],
    no_extract: bool,
) -> None:
    if not settings.is_list_configured(settings.document_lifecycle_list_id):
        raise RuntimeError("DOCUMENT_LIFECYCLE_LIST_ID is not configured.")
    if not settings.is_list_configured(settings.document_register_list_id):
        raise RuntimeError("DOCUMENT_REGISTER_LIST_ID is not configured.")

    await startup()
    try:
        lifecycle_items = await get_list_items(settings.document_lifecycle_list_id, LIFECYCLE_LIST)
        register_by_code = await existing_register_by_code()

        approved = []
        for item in lifecycle_items:
            fields = item.get("fields", {})
            code = field_text(fields, "DocumentCode")
            if field_text(fields, "ApprovalStatus").lower() != "approved":
                continue
            if code_filter and code.upper() != code_filter.upper():
                continue
            approved.append(item)

        approved.sort(
            key=lambda i: (
                i.get("lastModifiedDateTime") or i.get("createdDateTime") or "",
                int(i.get("id") or 0) if str(i.get("id") or "").isdigit() else 0,
            ),
            reverse=True,
        )
        if limit:
            approved = approved[:limit]

        print("\n" + "=" * 72)
        print("OrgOS — Publish Approved Lifecycle Documents")
        if dry_run:
            print("MODE: DRY RUN")
        if code_filter:
            print(f"CODE FILTER: {code_filter}")
        if limit:
            print(f"LIMIT: {limit}")
        print(f"CONTROLS FROM APPROVED LIBRARY: {'OFF' if no_extract else 'ON'}")
        print("=" * 72 + "\n")

        created = linked = skipped = failed = 0

        for item in approved:
            lifecycle_id = str(item.get("id", ""))
            fields = item.get("fields", {})
            doc_code = field_text(fields, "DocumentCode")
            code_key = doc_code.upper()
            existing_link = field_text(fields, "LinkedDocumentRegisterItem")

            print(f"Lifecycle #{lifecycle_id} | {doc_code or '(no code)'} | {field_text(fields, 'Title')[:48]}")

            if not doc_code:
                print("  -> SKIP: missing DocumentCode")
                skipped += 1
                continue
            if not is_valid_doc_code(doc_code):
                print(f"  -> SKIP: invalid DocumentCode '{doc_code}'")
                skipped += 1
                continue

            register_id = existing_link or register_by_code.get(code_key, "")
            if register_id:
                print(f"  -> Register already exists: #{register_id}")
                if not dry_run:
                    await write_optional_register_trace(register_id, fields)
                    if not existing_link:
                        await update_list_item(
                            settings.document_lifecycle_list_id,
                            LIFECYCLE_LIST,
                            lifecycle_id,
                            {"LinkedDocumentRegisterItem": register_id},
                        )
                        linked += 1
            else:
                register_fields = build_register_fields(fields)
                if dry_run:
                    print("  -> Would create Document Register entry")
                    register_id = "(dry-run)"
                else:
                    try:
                        register_item = await create_list_item(
                            settings.document_register_list_id,
                            REGISTER_LIST,
                            register_fields,
                        )
                        register_id = str(register_item.get("id", ""))
                        register_by_code[code_key] = register_id
                        await write_optional_register_trace(register_id, fields)
                        await update_list_item(
                            settings.document_lifecycle_list_id,
                            LIFECYCLE_LIST,
                            lifecycle_id,
                            {"LinkedDocumentRegisterItem": register_id},
                        )
                        print(f"  -> Created Document Register entry #{register_id}")
                        created += 1
                    except Exception as exc:
                        print(f"  -> FAILED register publish: {str(exc)[:100]}")
                        logger.exception(f"Register publish failed for lifecycle {lifecycle_id}")
                        failed += 1
                        continue

        print("\n" + "=" * 72)
        print("PUBLISH COMPLETE")
        print(f"  Register entries created: {created}")
        print(f"  Existing register links fixed: {linked}")
        print(f"  Skipped: {skipped}")
        print(f"  Failed: {failed}")
        print("=" * 72 + "\n")

        # Controls come from the approved library as a whole, read by Control ID
        # (control_register/approved_library.py) — the same thing approval does.
        if not no_extract and not dry_run:
            from control_register.approved_library import sync_approved_library
            print("Reading the approved library for controls…")
            print(await sync_approved_library())
    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Publish already-approved Document Lifecycle items to Document Register and Extraction Review.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing to SharePoint")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most this many approved lifecycle items")
    parser.add_argument("--code", type=str, default=None,
                        help="Only process one DocumentCode")
    parser.add_argument("--no-extract", action="store_true",
                        help="Only create/link Document Register entries; do not write AI Review Queue items")
    args = parser.parse_args()

    asyncio.run(run_publish(
        dry_run=args.dry_run,
        limit=args.limit,
        code_filter=args.code,
        no_extract=args.no_extract,
    ))
