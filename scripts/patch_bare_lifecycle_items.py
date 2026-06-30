#!/usr/bin/env python3
"""
scripts/patch_bare_lifecycle_items.py — Fill in missing fields on bare lifecycle items.

Bare items were created during the initial intake when the SharePointFileUrl column
was "Single line of text" (255-char limit). Long URLs caused a 400 error, so a
6-field bare fallback was used. Those items are missing:

  DocumentCode, DocumentType, Department, Owner, Notes, Revised,
  RejectionCount, StakeholderResponseCount, SharePointFileUrl,
  OwnerEntraId, CDIFailures (and the corrected Trigger)

This script identifies bare items (SharePointFileUrl is empty), downloads each
file, re-runs CDI, and PATCHes the lifecycle item with all missing fields.

Run AFTER changing SharePointFileUrl to "Multiple lines of text" in SharePoint.

Usage:
  python3 scripts/patch_bare_lifecycle_items.py --dry-run
  python3 scripts/patch_bare_lifecycle_items.py --owner-email automations@dragnet-solutions.com
  python3 scripts/patch_bare_lifecycle_items.py
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from agents.cdi_checker.service import extract_text, run_cdi_check, DOC_CODE_PATTERN
from config import configure_logging, settings
from graph.auth import get_graph_access_token
from graph.client import get_list_items, update_list_item, startup, shutdown

configure_logging()
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

_SCRIPTS_DIR   = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(_SCRIPTS_DIR, "intake_lifecycle_checkpoint.json")

LIFECYCLE_LIST_NAME = "Document Lifecycle"
DEFAULT_OWNER_NAME  = "System (SharePoint Intake)"
DEFAULT_STANDARDS   = "ISO 27001, ISO 9001, NDPA"

DOC_CODE_SEARCH_PATTERN = re.compile(
    r"\bDRG-[A-Z]{2,6}-[A-Z]{2,3}-[A-Z0-9]{2,6}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def get_headers() -> dict:
    token = await get_graph_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def resolve_compliance_drive() -> str:
    headers = await get_headers()
    base = settings.graph_base_url
    url = settings.compliance_site_url.rstrip("/")
    parts = url.replace("https://", "").split("/", 1)
    hostname, path = parts[0], (parts[1] if len(parts) > 1 else "")
    async with httpx.AsyncClient(timeout=30.0) as client:
        site_resp = await client.get(f"{base}/sites/{hostname}:/{path}", headers=headers)
        site_resp.raise_for_status()
        site_id = site_resp.json()["id"]
        drives_resp = await client.get(f"{base}/sites/{site_id}/drives", headers=headers)
        drives_resp.raise_for_status()
        drives = drives_resp.json().get("value", [])
    return next(
        (d["id"] for d in drives if d.get("name") == settings.compliance_library_name),
        drives[0]["id"] if drives else "",
    )


async def resolve_owner_by_email(email: str) -> tuple[str, str]:
    if not email:
        return "", ""
    try:
        headers = await get_headers()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{settings.graph_base_url}/users/{email}", headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data.get("id", ""), data.get("displayName", "") or data.get("userPrincipalName", email)
    except Exception as exc:
        logger.warning(f"Could not resolve owner email '{email}': {exc}")
        return "", ""


async def fetch_role_titles() -> list[str]:
    try:
        items = await get_list_items(settings.role_register_list_id, "Role Register")
        return [i.get("fields", {}).get("Title", "") for i in items if i.get("fields", {}).get("Title")]
    except Exception as exc:
        logger.warning(f"Could not load Role Register: {exc}")
        return []


def _department_from_path(folder_path: str, filename: str) -> str:
    text = f"{folder_path} {filename}".lower()
    for needle, dept in [
        ("isms", "ISMS"), ("information security", "ISMS"), ("cyber", "ISMS"),
        ("data protection", "DPO"), ("privacy", "DPO"), ("ndpa", "DPO"),
        ("hr", "HR"), ("human resources", "HR"),
        ("finance", "FIN"), ("account", "FIN"),
        ("legal", "LEGAL"), ("contract", "LEGAL"),
        ("procurement", "PROC"), ("vendor", "PROC"),
        ("operations", "OPS"),
        ("quality", "QMS"), ("qms", "QMS"),
        ("audit", "AUDIT"), ("risk", "RISK"),
        ("compliance", "GRC"), ("grc", "GRC"),
    ]:
        if needle in text:
            return dept
    return "GRC"


def _document_type_from_path(folder_path: str, filename: str) -> tuple[str, str, str]:
    text = f"{folder_path} {filename}".lower()
    if any(t in text for t in ["form", "template", "checklist"]):
        return "Form", "high", "folder or filename indicates a form/template/checklist"
    if any(t in text for t in ["guideline", "guide", "manual", "handbook"]):
        return "Guidelines", "high", "folder or filename indicates guidance/manual content"
    if any(t in text for t in ["sop", "standard operating procedure", "work instruction"]):
        return "SOP", "high", "folder or filename indicates SOP/work instruction"
    if any(t in text for t in ["procedure", "process"]):
        return "Procedure", "high", "folder or filename indicates procedure/process"
    if "policy" in text or "policies" in text:
        return "Policy", "high", "folder or filename indicates policy"
    if any(t in text for t in ["job description", " jd ", "_jd_", "-jd-", "role profile"]):
        return "Procedure", "medium", "job description mapped to lifecycle-safe Procedure"
    if any(t in text for t in ["contract", "agreement", "nda", "sla"]):
        return "Procedure", "medium", "contract/agreement mapped to lifecycle-safe Procedure"
    if any(t in text for t in ["regulatory", "statutory", "law", "act", "regulation"]):
        return "Guidelines", "medium", "regulatory/reference material mapped to Guidelines"
    if any(t in text for t in ["audit", "finding", "risk assessment", "risk register"]):
        return "Procedure", "medium", "audit/risk document mapped to Procedure for review"
    if filename.lower().endswith(("-pol.docx", "-pol.pdf")):
        return "Policy", "medium", "filename suffix suggests policy"
    return "Policy", "low", "no strong signal; defaulted to Policy for human review"


def extract_document_code_from_text(text: str) -> str:
    match = DOC_CODE_SEARCH_PATTERN.search(text.upper())
    if not match:
        return ""
    candidate = match.group(0).upper().strip()
    return candidate if DOC_CODE_PATTERN.match(candidate) else ""


def _clean_sp_text(text: str) -> str:
    return "".join(c for c in str(text) if (ord(c) >= 0x20 or c in "\t\n\r") and ord(c) != 0x7F)


def cdi_failures_json(checks: list[dict]) -> str:
    return json.dumps([
        {
            "check": c.get("check_id", "CDI"),
            "detail": _clean_sp_text(c.get("finding", "")),
            "fix": _clean_sp_text(c.get("proposed_fix", "")),
        }
        for c in checks if c.get("result") == "FAIL"
    ])


def parse_folder_from_parent_ref(parent_ref: dict) -> str:
    """Extract GRC-MASTERY-relative folder path from Graph API parentReference."""
    path = parent_ref.get("path", "")
    marker = f"/{settings.compliance_starting_folder}/"
    idx = path.find(marker)
    if idx >= 0:
        return path[idx + len(marker):]
    marker2 = f"/{settings.compliance_starting_folder}"
    idx2 = path.find(marker2)
    if idx2 >= 0:
        remainder = path[idx2 + len(marker2):]
        return remainder.lstrip("/") or settings.compliance_starting_folder
    return path.split("/root:/", 1)[-1] if "/root:/" in path else path


async def get_drive_item_meta(drive_id: str, item_id: str) -> dict:
    headers = await get_headers()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}",
            headers=headers,
            params={"$select": "id,name,webUrl,parentReference"},
        )
        resp.raise_for_status()
        return resp.json()


async def download_drive_item(drive_id: str, item_id: str) -> tuple[bytes, str]:
    headers = await get_headers()
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        meta = await client.get(
            f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}",
            headers=headers, params={"$select": "id,name"},
        )
        meta.raise_for_status()
        filename = meta.json().get("name", "document")
        content = await client.get(
            f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}/content",
            headers=headers,
        )
        content.raise_for_status()
    return content.content, filename


# ── Main ─────────────────────────────────────────────────────────────────────

async def run_patch(owner_email: Optional[str], dry_run: bool) -> int:
    """Returns number of failures (0 = clean run)."""
    await startup()
    try:
        # Load checkpoint
        if not os.path.exists(CHECKPOINT_FILE):
            print("No checkpoint file found. Run the intake script first.")
            return 0
        with open(CHECKPOINT_FILE) as f:
            checkpoint = json.load(f)

        created_entries = checkpoint.get("created", [])
        if not created_entries:
            print("No created entries in checkpoint. Nothing to patch.")
            return 0

        # Map lifecycle_id → checkpoint entry
        id_to_entry: dict[str, dict] = {str(e["lifecycle_id"]): e for e in created_entries}
        print(f"Checkpoint: {len(created_entries)} created entries.\n")

        # Query Document Lifecycle list
        print("Querying Document Lifecycle list...")
        lifecycle_items = await get_list_items(settings.document_lifecycle_list_id, LIFECYCLE_LIST_NAME)
        print(f"Found {len(lifecycle_items)} lifecycle items in SharePoint.\n")

        # Identify bare items: in checkpoint AND SharePointFileUrl is empty
        bare: list[dict] = []
        for sp_item in lifecycle_items:
            sp_id = str(sp_item.get("id", ""))
            if sp_id not in id_to_entry:
                continue
            fields = sp_item.get("fields", {})
            if not (fields.get("SharePointFileUrl") or "").strip():
                bare.append({
                    "lifecycle_id": sp_id,
                    "drive_item_id": id_to_entry[sp_id]["id"],
                    "name": id_to_entry[sp_id]["name"],
                })

        if not bare:
            print("No bare items found — all lifecycle items already have SharePointFileUrl set.")
            print("If you expected bare items, verify the SharePointFileUrl column name in SharePoint.")
            return 0

        print(f"Bare items to patch: {len(bare)}")
        if dry_run:
            print("DRY RUN — no changes will be made.\n")
        else:
            print()

        # Resolve owner + roles once
        drive_id = await resolve_compliance_drive()
        owner_oid, owner_name = await resolve_owner_by_email(owner_email or "")
        if owner_email and owner_oid:
            print(f"Owner: {owner_name} ({owner_oid})")
        elif owner_email:
            print(f"WARNING: Could not resolve {owner_email}; using '{DEFAULT_OWNER_NAME}'")

        role_titles = await fetch_role_titles()
        print(f"Loaded {len(role_titles)} role titles for CDI checks.\n")

        patched = failed = 0

        for i, item in enumerate(bare, 1):
            name       = item["name"]
            lifecycle_id  = item["lifecycle_id"]
            drive_item_id = item["drive_item_id"]

            print(f"[{i}/{len(bare)}] {name[:64]}")

            try:
                # Get folder path + webUrl from Graph (no file download needed for this)
                meta = await get_drive_item_meta(drive_id, drive_item_id)
                web_url     = meta.get("webUrl", "")
                folder_path = parse_folder_from_parent_ref(meta.get("parentReference", {}))

                # Download file + extract text
                file_bytes, download_name = await download_drive_item(drive_id, drive_item_id)
                doc_text  = extract_text(file_bytes, download_name or name)
                doc_code  = extract_document_code_from_text(doc_text)

                # Classify
                doc_type, confidence, reason = _document_type_from_path(folder_path, name)
                department = _department_from_path(folder_path, name)

                # CDI check
                cdi_result = await run_cdi_check(file_bytes, download_name or name, doc_code, role_titles)
                if cdi_result.get("error"):
                    cdi_status   = "Error"
                    cdi_failures = json.dumps([{
                        "check": "CDI",
                        "detail": cdi_result["error"],
                        "fix": "Fix the parsing/check issue then upload the controlled version in Review.",
                    }])
                elif cdi_result.get("passed"):
                    cdi_status   = "Passed"
                    cdi_failures = ""
                else:
                    cdi_status   = "Failed"
                    cdi_failures = cdi_failures_json(cdi_result.get("checks", []))

                trigger  = "SharePoint Intake" if cdi_status != "Failed" else "CDI Fix"
                revised  = cdi_status == "Passed"

                notes = (
                    "Imported from SharePoint GRC MASTERY for controlled lifecycle onboarding. "
                    "Do not extract controls until this item is approved and appears in the "
                    "Document Register. "
                    f"Detected type: {doc_type} ({confidence} confidence: {reason}). "
                    f"Source folder: {folder_path}."
                )

                patch_fields: dict = {
                    "DocumentCode":              doc_code,
                    "DocumentType":              doc_type,
                    "Department":                department,
                    "Trigger":                   trigger,
                    "Revised":                   revised,
                    "CDIStatus":                 cdi_status,
                    "Owner":                     owner_name or DEFAULT_OWNER_NAME,
                    "Notes":                     notes,
                    "RejectionCount":            0,
                    "StakeholderResponseCount":  0,
                    "SharePointFileUrl":          web_url,
                    "StandardsMapping":           DEFAULT_STANDARDS,
                }
                if owner_oid:
                    patch_fields["OwnerEntraId"] = owner_oid
                if cdi_failures:
                    patch_fields["CDIFailures"] = cdi_failures

                if dry_run:
                    print(
                        f"  → DRY RUN | folder={folder_path!r} "
                        f"type={doc_type} dept={department} "
                        f"code={doc_code!r} cdi={cdi_status}"
                    )
                    print(f"     url={web_url[:90]}")
                    patched += 1
                    await asyncio.sleep(0.5)
                    continue

                await update_list_item(
                    settings.document_lifecycle_list_id,
                    LIFECYCLE_LIST_NAME,
                    lifecycle_id,
                    patch_fields,
                )
                print(
                    f"  → PATCHED | folder={folder_path!r} "
                    f"type={doc_type} dept={department} "
                    f"code={doc_code!r} cdi={cdi_status}"
                )
                patched += 1

            except Exception as exc:
                print(f"  → FAILED: {str(exc)[:100]}")
                logger.exception(f"Patch failed for {name}")
                failed += 1

            await asyncio.sleep(1)

        print()
        print("=" * 70)
        if dry_run:
            print(f"DRY RUN complete — would patch {patched}, would fail {failed}")
        else:
            print(f"Patch complete: {patched} patched, {failed} failed")
        print("=" * 70)

        return failed

    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Patch bare Document Lifecycle items with full field data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/patch_bare_lifecycle_items.py --dry-run
  python3 scripts/patch_bare_lifecycle_items.py --owner-email automations@dragnet-solutions.com
  python3 scripts/patch_bare_lifecycle_items.py
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be patched without making any changes")
    parser.add_argument("--owner-email", type=str, default=None,
                        help="M365 email to set as lifecycle owner (falls back to INTAKE_OWNER_EMAIL env var)")

    args = parser.parse_args()
    if not args.owner_email:
        args.owner_email = os.environ.get("INTAKE_OWNER_EMAIL", "")

    failures = asyncio.run(run_patch(args.owner_email, args.dry_run))
    sys.exit(failures)
