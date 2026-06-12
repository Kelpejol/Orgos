# =============================================================================
# scripts/bulk_extract.py — Bulk extraction with checkpoint and resume
# Processes all documents in GRC MASTERY and writes to AI Review Queue.
# Saves progress after each file — safe to interrupt and resume.
# Already-processed files are skipped automatically on resume.
#
# Usage:
#   python scripts/bulk_extract.py --dry-run
#   python scripts/bulk_extract.py --folder "Policies & SOPs" --limit 5
#   python scripts/bulk_extract.py --folder "Policies & SOPs"
#   python scripts/bulk_extract.py --folder "Job Descriptions"
#   python scripts/bulk_extract.py  (all folders)
#   python scripts/bulk_extract.py --reset  (clear checkpoint and start fresh)
#
# Checkpoint file: scripts/bulk_extract_checkpoint.json
# Processed file IDs are stored there — resume picks up where it left off.
# =============================================================================

import asyncio
import argparse
import json
import logging
import sys
import os
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from config import settings, configure_logging
from graph.auth import get_graph_access_token
from graph.client import startup, shutdown, create_list_item
from agents.extractor.ollama_client import (
    classify_document,
    run_extraction,
    DocumentType,
    NON_EXTRACTION_TYPES,
)
from agents.extractor.service import (
    extract_text_from_pdf,
    extract_text_from_docx,
    _validate_items,
)

configure_logging()
logger = logging.getLogger(__name__)

CHECKPOINT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "bulk_extract_checkpoint.json"
)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
VALID_ITEM_TYPES     = {"Extraction", "Orphan", "Harmonisation"}


# =============================================================================
#  Checkpoint management
# =============================================================================

def load_checkpoint() -> dict:
    if not os.path.exists(CHECKPOINT_FILE):
        return {"processed_ids": [], "failed_ids": [], "total_written": 0}
    try:
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"processed_ids": [], "failed_ids": [], "total_written": 0}


def save_checkpoint(state: dict) -> None:
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as exc:
        logger.warning(f"Could not save checkpoint: {exc}")


def reset_checkpoint() -> None:
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Checkpoint cleared — will process all documents from scratch.\n")


# =============================================================================
#  SharePoint helpers
# =============================================================================

async def get_headers() -> dict:
    token = await get_graph_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def resolve_compliance_drive() -> tuple[str, str]:
    headers = await get_headers()
    base    = settings.graph_base_url
    url     = settings.compliance_site_url.rstrip("/")
    parts   = url.replace("https://", "").split("/", 1)
    hostname = parts[0]
    path     = parts[1] if len(parts) > 1 else ""

    async with httpx.AsyncClient(timeout=30.0) as client:
        site_resp = await client.get(
            f"{base}/sites/{hostname}:/{path}", headers=headers
        )
        site_resp.raise_for_status()
        site_id = site_resp.json()["id"]

        drives_resp = await client.get(
            f"{base}/sites/{site_id}/drives", headers=headers
        )
        drives_resp.raise_for_status()
        drives = drives_resp.json().get("value", [])

        drive_id = None
        for drive in drives:
            if drive.get("name") == settings.compliance_library_name:
                drive_id = drive["id"]
                break
        if not drive_id and drives:
            drive_id = drives[0]["id"]

    return site_id, drive_id


async def list_folder(drive_id: str, folder_id: Optional[str] = None) -> list[dict]:
    headers = await get_headers()
    base    = settings.graph_base_url
    url = (
        f"{base}/drives/{drive_id}/items/{folder_id}/children"
        if folder_id
        else f"{base}/drives/{drive_id}/root/children"
    )
    params = {
        "$top":    200,
        "$select": "id,name,size,folder,file,lastModifiedDateTime,webUrl",
    }
    all_items = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        while url:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            all_items.extend(data.get("value", []))
            url    = data.get("@odata.nextLink")
            params = None
    return all_items


async def walk_folder(
    drive_id: str,
    folder_name: str,
    folder_id: Optional[str] = None,
) -> list[dict]:
    """Recursively collect all processable files in a folder."""
    items = await list_folder(drive_id, folder_id)
    files = []
    for item in items:
        name    = item.get("name", "")
        item_id = item["id"]
        if "folder" in item:
            sub_path  = f"{folder_name}/{name}"
            sub_files = await walk_folder(drive_id, sub_path, item_id)
            files.extend(sub_files)
        else:
            ext = os.path.splitext(name)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append({
                    "id":          item_id,
                    "name":        name,
                    "folder_path": folder_name,
                    "extension":   ext,
                    "size":        item.get("size", 0),
                    "web_url":     item.get("webUrl", ""),
                })
    return files


async def download_file(drive_id: str, item_id: str) -> tuple[bytes, str]:
    headers = await get_headers()
    base    = settings.graph_base_url
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        meta = await client.get(
            f"{base}/drives/{drive_id}/items/{item_id}",
            headers=headers,
            params={"$select": "id,name"},
        )
        meta.raise_for_status()
        filename = meta.json().get("name", "document")

        content = await client.get(
            f"{base}/drives/{drive_id}/items/{item_id}/content",
            headers=headers,
        )
        content.raise_for_status()
    return content.content, filename


def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext == ".docx":
        return extract_text_from_docx(file_bytes)
    elif ext == ".txt":
        return file_bytes.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported: {ext}")


# =============================================================================
#  Write to AI Review Queue
# =============================================================================

async def write_to_queue(
    items: list[dict],
    doc_code: str,
    doc_type: DocumentType,
    web_url: str = "",
) -> int:
    list_id   = settings.ai_review_queue_list_id
    list_name = "AI Review Queue"

    if not settings.is_list_configured(list_id):
        logger.warning("AI Review Queue list not configured")
        return 0

    written = 0
    for item in items:
        try:
            title = (
                item.get("control_statement")
                or item.get("responsibility_statement")
                or item.get("finding_statement")
                or item.get("obligation_statement")
                or "Untitled item"
            )

            # Force ItemType to a valid value — never allow model free-text through
            raw_cat = item.get("extraction_category", "")
            if raw_cat not in VALID_ITEM_TYPES:
                item["extraction_category"] = (
                    "Orphan" if doc_type == DocumentType.JD else "Extraction"
                )

            fields = {
                "Title":              title[:255],
                "ItemType":           item["extraction_category"],
                "DocumentType":       item.get("document_type", doc_type.value),
                "SourceDocumentCode": doc_code,
                "SourceClause":       item.get("source_clause") or "",
                "ConfidenceScore":    item.get("confidence_score", 0.0),
                "ReviewStatus":       "Pending Review",
            }

            # SharePoint file URL for document viewer in Extraction Review
            if web_url:
                fields["SourceDocumentUrl"] = web_url

            # Control fields
            for k, v in {
                "ControlStatement":          item.get("control_statement"),
                "RiskStatement":             item.get("risk_statement"),
                "ControlType":               item.get("control_type"),
                "ProposedOwnerRole":         item.get("proposed_owner_role"),
                "ISOClause":                 item.get("iso_clause"),
                "SourceType":                item.get("source_type", "Policy"),
                "CompletenessFlag":          item.get("completeness_flag"),
                "DeficiencyReason":          item.get("deficiency_reason"),
                "EvidenceType":              item.get("evidence_type"),
                "EvidenceDescription":       item.get("evidence_description"),
                "EvidenceSourceSystem":      item.get("source_system"),
                "EvidenceFormat":            item.get("evidence_format"),
                "EvidenceFrequency":         item.get("evidence_frequency"),
                "EvidenceCollectionMethod":  item.get("evidence_collection_method"),
                "EvidenceOwnerRole":         item.get("evidence_owner_role"),
                "EvidenceValidationCriteria":item.get("evidence_validation_criteria"),
            }.items():
                if v:
                    fields[k] = (
                        str(v)[:500]
                        if k in ("EvidenceDescription", "EvidenceValidationCriteria", "DeficiencyReason")
                        else v
                    )

            if item.get("evidence_undefined"):
                fields["EvidenceUndefined"] = True
            if item.get("evidence_undefined_reason"):
                fields["EvidenceUndefinedReason"] = item["evidence_undefined_reason"]

            # Orphan fields
            if item.get("responsibility_statement"):
                fields.update({
                    "OrphanDirection":         item.get("orphan_direction", "JD_to_Doc"),
                    "ResponsibilityStatement": str(item.get("responsibility_statement", ""))[:500],
                    "OrphanClassification":    item.get("orphan_classification", ""),
                    "OrphanReason":            str(item.get("orphan_reason", ""))[:500],
                })

            # Regulatory fields
            if item.get("obligation_statement") and doc_type == DocumentType.REGULATORY:
                fields.update({
                    "Authority":            item.get("authority", ""),
                    "ObligationDeadline":   item.get("deadline", ""),
                    "ObligationRecurrence": item.get("recurrence", ""),
                })
                if item.get("standards_reference"):
                    fields["StandardReference"] = item["standards_reference"]

            # Audit fields
            if item.get("finding_statement"):
                fields.update({
                    "FindingType":               item.get("finding_type", "Finding"),
                    "Severity":                  item.get("severity", "Minor"),
                    "GapType":                   item.get("gap_type", "Unknown"),
                    "RemediationRequired":       str(item.get("remediation_required", ""))[:500],
                    "TriggersDocumentLifecycle": item.get("triggers_document_lifecycle", False),
                    "IsRepeatedFinding":         item.get("is_repeated_finding", False),
                })
                if item.get("standard_reference"):
                    fields["StandardReference"] = item["standard_reference"]

            await create_list_item(list_id, list_name, fields)
            written += 1

        except Exception as exc:
            logger.error(f"Failed to write queue item: {exc}")

    return written


# =============================================================================
#  Main
# =============================================================================

async def bulk_extract(
    folder_filter: Optional[str] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> None:
    await startup()

    checkpoint    = load_checkpoint()
    processed_ids = set(checkpoint.get("processed_ids", []))
    failed_ids    = set(checkpoint.get("failed_ids", []))
    total_written = checkpoint.get("total_written", 0)

    print("\n" + "="*60)
    print("OrgOS — Bulk Extraction (with checkpoint/resume)")
    if dry_run:       print("MODE: DRY RUN")
    if folder_filter: print(f"FOLDER FILTER: {folder_filter}")
    if limit:         print(f"BATCH LIMIT: {limit} documents then stop")
    if processed_ids: print(f"RESUMING — {len(processed_ids)} already processed, will skip them")
    print("="*60 + "\n")

    try:
        print("Connecting to Compliance SharePoint...")
        site_id, drive_id = await resolve_compliance_drive()
        print("Connected\n")

        starting_folder = settings.compliance_starting_folder
        headers         = await get_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            root_resp = await client.get(
                f"{settings.graph_base_url}/drives/{drive_id}/root:/{starting_folder}",
                headers=headers,
                params={"$select": "id,name"},
            )
            root_resp.raise_for_status()
            root_id = root_resp.json()["id"]

        # Collect files
        all_files = []
        top_level = await list_folder(drive_id, root_id)
        for top_item in top_level:
            if "folder" not in top_item:
                continue
            folder_name = top_item["name"]
            if folder_filter and folder_filter.lower() not in folder_name.lower():
                continue
            folder_files = await walk_folder(drive_id, folder_name, top_item["id"])
            all_files.extend(folder_files)

        remaining = [
            f for f in all_files
            if f["id"] not in processed_ids and f["id"] not in failed_ids
        ]

        print(f"Total files found:       {len(all_files)}")
        print(f"Already processed:       {len(processed_ids)}")
        print(f"Previously failed:       {len(failed_ids)}")
        print(f"Remaining to process:    {len(remaining)}")

        if limit:
            remaining = remaining[:limit]
            print(f"Processing this batch:   {len(remaining)}")
        print()

        if not remaining:
            print("Nothing left to process. All documents have been extracted.")
            print("Run with --reset to start fresh.\n")
            return

        batch_written   = 0
        batch_skipped   = 0
        batch_failed    = 0
        batch_processed = 0

        for i, file_info in enumerate(remaining, 1):
            filename    = file_info["name"]
            file_id     = file_info["id"]
            folder_path = file_info["folder_path"]
            web_url     = file_info.get("web_url", "")

            name_no_ext = os.path.splitext(filename)[0]
            doc_code    = name_no_ext.upper().replace(" ", "-").replace("_", "-")[:60]
            doc_type    = classify_document(filename, doc_code, folder_path)

            prefix = f"[{i}/{len(remaining)}]"

            if doc_type in NON_EXTRACTION_TYPES or doc_type == DocumentType.UNCLASSIFIED:
                reason = "non-extraction target" if doc_type in NON_EXTRACTION_TYPES else "unclassified"
                print(f"  {prefix} SKIP  {filename[:50]} ({reason})")
                processed_ids.add(file_id)
                checkpoint["processed_ids"] = list(processed_ids)
                save_checkpoint(checkpoint)
                batch_skipped += 1
                continue

            print(f"  {prefix} {doc_type.value.upper():14} {filename[:50]}")

            if dry_run:
                batch_processed += 1
                continue

            try:
                file_bytes, _ = await download_file(drive_id, file_id)

                text = extract_text(file_bytes, filename)
                if not text.strip():
                    print(f"              → Empty — skipping")
                    processed_ids.add(file_id)
                    checkpoint["processed_ids"] = list(processed_ids)
                    save_checkpoint(checkpoint)
                    batch_skipped += 1
                    continue

                # Run extraction
                raw_items = await run_extraction(text, doc_code, doc_type)

                if not raw_items:
                    print(f"              → No items extracted")
                    processed_ids.add(file_id)
                    checkpoint["processed_ids"] = list(processed_ids)
                    save_checkpoint(checkpoint)
                    batch_processed += 1
                    continue

                # Validate and clean — fixes ItemType, ControlType, EvidenceType
                raw_items = _validate_items(raw_items, doc_type, doc_code)

                # Write to queue
                written = await write_to_queue(
                    raw_items, doc_code, doc_type, web_url=web_url
                )
                print(f"              → {len(raw_items)} extracted, {written} written ✓")

                total_written   += written
                batch_written   += written
                batch_processed += 1
                processed_ids.add(file_id)
                checkpoint["processed_ids"] = list(processed_ids)
                checkpoint["total_written"]  = total_written
                save_checkpoint(checkpoint)

            except Exception as exc:
                err_msg = str(exc)[:80]
                print(f"              → FAILED: {err_msg}")
                logger.exception(f"Failed: {filename}")
                failed_ids.add(file_id)
                checkpoint["failed_ids"] = list(failed_ids)
                save_checkpoint(checkpoint)
                batch_failed += 1

            await asyncio.sleep(3)

        print("\n" + "="*60)
        print("BATCH COMPLETE")
        print(f"  Processed:     {batch_processed}")
        print(f"  Skipped:       {batch_skipped}")
        print(f"  Failed:        {batch_failed}")
        print(f"  Written:       {batch_written} items → AI Review Queue")
        print(f"  Total written: {total_written} items (all runs)")
        remaining_after = len(all_files) - len(processed_ids) - len(failed_ids)
        if remaining_after > 0:
            print(f"\n  {remaining_after} documents still remaining.")
            if limit:
                print(f"  Run again with the same command to process the next {limit}.")
            else:
                print(f"  Run again to process remaining documents.")
        else:
            print(f"\n  All documents in this folder have been processed.")
        if batch_written > 0:
            try:
                from agents.classifier.service import run_classifier
                print("\n  Running classifier for newly extracted queue items...")
                summary = await run_classifier(triggered_by="system: bulk_extract")
                print(
                    "  Classifier complete: "
                    f"{summary.get('total_written', 0)} written, "
                    f"{summary.get('role_variants_suppressed', 0) + summary.get('duplicates_suppressed', 0) + summary.get('conflicts_suppressed', 0)} suppressed"
                )
            except Exception as exc:
                logger.exception("Automatic classifier run after bulk extract failed")
                print(f"  Classifier failed: {str(exc)[:120]}")
        print("="*60 + "\n")

    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bulk extract GRC MASTERY documents into AI Review Queue"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Walk and classify without extracting or writing")
    parser.add_argument("--folder",  type=str, default=None,
                        help="Only process folders containing this name")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Max documents to process in this run (for batching)")
    parser.add_argument("--reset",   action="store_true",
                        help="Clear checkpoint and process everything from scratch")
    args = parser.parse_args()

    if args.reset:
        reset_checkpoint()

    asyncio.run(bulk_extract(
        folder_filter=args.folder,
        dry_run=args.dry_run,
        limit=args.limit,
    ))
