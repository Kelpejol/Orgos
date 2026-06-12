# =============================================================================
# scripts/publish_approved_lifecycle.py — Backfill approved lifecycle documents
#
# Finds existing Document Lifecycle items with ApprovalStatus=Approved, creates
# missing Document Register entries, links the lifecycle item to the register,
# and optionally runs extraction into AI Review Queue.
#
# Usage:
#   myenv/bin/python scripts/publish_approved_lifecycle.py --dry-run
#   myenv/bin/python scripts/publish_approved_lifecycle.py
#   myenv/bin/python scripts/publish_approved_lifecycle.py --limit 10
#   myenv/bin/python scripts/publish_approved_lifecycle.py --code DRG-ISMS-POL-ACP-01-26
#   myenv/bin/python scripts/publish_approved_lifecycle.py --no-extract
#   myenv/bin/python scripts/publish_approved_lifecycle.py --force-extract
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

from agents.cdi_checker.service import DOC_CODE_PATTERN
from agents.extractor.service import run_extraction_from_file
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


def filename_from_sharepoint_url(url: str, content_type: str = "") -> str:
    path_name = unquote(urlparse(url or "").path.rsplit("/", 1)[-1])
    if "." in path_name:
        return path_name
    if "pdf" in (content_type or "").lower():
        return f"{path_name or 'document'}.pdf"
    if "text" in (content_type or "").lower():
        return f"{path_name or 'document'}.txt"
    return f"{path_name or 'document'}.docx"


def extractor_type_for_lifecycle(document_type: str) -> Optional[str]:
    normalized = (document_type or "").strip().lower()
    if normalized in {"policy", "procedure", "sop", "guidelines"}:
        return "Policy"
    return None


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


async def existing_queue_counts_by_code() -> dict[str, int]:
    if not settings.is_list_configured(settings.ai_review_queue_list_id):
        return {}
    items = await get_list_items(settings.ai_review_queue_list_id, AI_QUEUE_LIST)
    counts: dict[str, int] = {}
    for item in items:
        fields = item.get("fields", {})
        code = field_text(fields, "SourceDocumentCode").upper()
        if code:
            counts[code] = counts.get(code, 0) + 1
    return counts


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


async def extract_to_review_queue(lifecycle_fields: dict) -> dict:
    doc_code = field_text(lifecycle_fields, "DocumentCode")
    file_url = field_text(lifecycle_fields, "SharePointFileUrl")
    if not doc_code or not file_url:
        return {
            "started": False,
            "written_to_sharepoint": False,
            "reason": "Missing DocumentCode or SharePointFileUrl.",
        }

    extractor_type = extractor_type_for_lifecycle(field_text(lifecycle_fields, "DocumentType"))
    if not extractor_type:
        return {
            "started": False,
            "written_to_sharepoint": False,
            "reason": f"Document type '{field_text(lifecycle_fields, 'DocumentType')}' is not an extraction target.",
        }

    file_bytes, content_type = await download_file_from_sharepoint(file_url)
    filename = filename_from_sharepoint_url(file_url, content_type)
    result = await run_extraction_from_file(
        file_bytes=file_bytes,
        filename=filename,
        doc_code=doc_code,
        write_to_sharepoint=True,
        folder_path=field_text(lifecycle_fields, "Department"),
        web_url=file_url,
        document_type_override=extractor_type,
    )
    return {
        "started": True,
        "document_type": result.document_type,
        "total_extracted": result.total_extracted,
        "written_to_sharepoint": result.written_to_sharepoint,
        "skipped_reason": result.skipped_reason,
    }


async def run_publish(
    dry_run: bool,
    limit: Optional[int],
    code_filter: Optional[str],
    no_extract: bool,
    force_extract: bool,
) -> None:
    if not settings.is_list_configured(settings.document_lifecycle_list_id):
        raise RuntimeError("DOCUMENT_LIFECYCLE_LIST_ID is not configured.")
    if not settings.is_list_configured(settings.document_register_list_id):
        raise RuntimeError("DOCUMENT_REGISTER_LIST_ID is not configured.")

    await startup()
    try:
        lifecycle_items = await get_list_items(settings.document_lifecycle_list_id, LIFECYCLE_LIST)
        register_by_code = await existing_register_by_code()
        queue_counts = await existing_queue_counts_by_code() if not no_extract else {}

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
        print(f"EXTRACTION: {'OFF' if no_extract else 'ON'}")
        print(f"FORCE EXTRACTION: {'YES' if force_extract else 'NO'}")
        print("=" * 72 + "\n")

        created = linked = extracted = skipped = failed = 0

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
            if not DOC_CODE_PATTERN.match(doc_code.strip().upper()):
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

            if no_extract:
                continue

            existing_queue_count = queue_counts.get(code_key, 0)
            if existing_queue_count and not force_extract:
                print(f"  -> Extraction skipped: {existing_queue_count} queue item(s) already exist")
                skipped += 1
                continue

            if dry_run:
                print("  -> Would run extraction into AI Review Queue")
                continue

            try:
                result = await extract_to_review_queue(fields)
                print(f"  -> Extraction result: {result}")
                if result.get("total_extracted") is not None and register_id:
                    try:
                        await update_list_item(
                            settings.document_register_list_id,
                            REGISTER_LIST,
                            register_id,
                            {"LinkedControlsCount": result.get("total_extracted", 0)},
                        )
                    except Exception as exc:
                        logger.warning(f"Could not update LinkedControlsCount for {doc_code}: {exc}")
                if result.get("written_to_sharepoint"):
                    extracted += 1
                    queue_counts[code_key] = queue_counts.get(code_key, 0) + int(result.get("total_extracted", 0) or 0)
            except Exception as exc:
                print(f"  -> FAILED extraction: {str(exc)[:100]}")
                logger.exception(f"Extraction failed for lifecycle {lifecycle_id}")
                failed += 1

        print("\n" + "=" * 72)
        print("PUBLISH COMPLETE")
        print(f"  Register entries created: {created}")
        print(f"  Existing register links fixed: {linked}")
        print(f"  Documents extracted: {extracted}")
        print(f"  Skipped: {skipped}")
        print(f"  Failed: {failed}")
        print("=" * 72 + "\n")
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
    parser.add_argument("--force-extract", action="store_true",
                        help="Run extraction even if AI Review Queue already has items for the document code")
    args = parser.parse_args()

    asyncio.run(run_publish(
        dry_run=args.dry_run,
        limit=args.limit,
        code_filter=args.code,
        no_extract=args.no_extract,
        force_extract=args.force_extract,
    ))
