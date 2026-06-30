# =============================================================================
# scripts/intake_sharepoint_to_lifecycle.py — SharePoint document intake
# Scans GRC MASTERY and creates Document Lifecycle Review cards.
#
# This is the controlled Phase 1 intake path:
#   SharePoint GRC document → Document Lifecycle Review → CDI → Sensitisation
#   → Approval → Document Register → later extraction into AI Review Queue.
#
# It does NOT write to Extraction Review / AI Review Queue.
#
# Dedup (two layers — both must pass for a document to be created):
#   1. Checkpoint  — processed SharePoint drive item IDs never re-queued.
#   2. Live query  — Document Lifecycle + Document Register checked by code
#                    and URL at the start of every run. Safe even if the
#                    checkpoint is cleared.
#
# Scheduling:
#   Designed to run twice daily via cron (6am and 8pm WAT = 5am and 7pm UTC).
#   Use scripts/setup_intake_cron.sh to install the cron entries.
#   Set INTAKE_OWNER_EMAIL in .env to assign a default lifecycle owner without
#   passing --owner-email on every invocation.
#
# Lock file: scripts/intake_lifecycle.lock  (prevents overlapping runs)
# Checkpoint: scripts/intake_lifecycle_checkpoint.json
# Logs: logs/intake/intake_YYYY-MM-DD_HHMM.log
#
# Usage:
#   python3 scripts/intake_sharepoint_to_lifecycle.py --dry-run
#   python3 scripts/intake_sharepoint_to_lifecycle.py --owner-email you@dragnet-solutions.com
#   python3 scripts/intake_sharepoint_to_lifecycle.py --folder "Policies & SOPs" --limit 10
#   python3 scripts/intake_sharepoint_to_lifecycle.py --no-cdi
#   python3 scripts/intake_sharepoint_to_lifecycle.py --reset
# =============================================================================

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from agents.cdi_checker.service import DOC_CODE_PATTERN, extract_text, run_cdi_check
from config import configure_logging, settings
from graph.auth import get_graph_access_token
from graph.client import create_list_item, get_list_items, startup, shutdown

configure_logging()
logger = logging.getLogger(__name__)

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR    = os.path.dirname(_SCRIPTS_DIR)

CHECKPOINT_FILE = os.path.join(_SCRIPTS_DIR, "intake_lifecycle_checkpoint.json")
LOCK_FILE       = os.path.join(_SCRIPTS_DIR, "intake_lifecycle.lock")
LOG_DIR         = os.path.join(_REPO_DIR, "logs", "intake")

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
# .doc (old OLE2 binary) excluded — python cannot read these reliably.
# Convert to .docx in Word before uploading to SharePoint.
LIFECYCLE_LIST_NAME = "Document Lifecycle"
REGISTER_LIST_NAME = "Document Register"

DEFAULT_OWNER_NAME = "System (SharePoint Intake)"
DEFAULT_STANDARDS = "ISO 27001, ISO 9001, NDPA"
DOC_CODE_SEARCH_PATTERN = re.compile(
    r"\bDRG-[A-Z]{2,6}-[A-Z]{2,3}-[A-Z0-9]{2,6}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntakeClassification:
    document_type: str
    department: str
    document_code: str
    confidence: str
    reason: str


# =============================================================================
#  Checkpoint
# =============================================================================

def load_checkpoint() -> dict:
    if not os.path.exists(CHECKPOINT_FILE):
        return {"processed_ids": [], "created": [], "skipped": [], "failed": []}
    try:
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"processed_ids": [], "created": [], "skipped": [], "failed": []}


def save_checkpoint(state: dict) -> None:
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as exc:
        logger.warning(f"Could not save checkpoint: {exc}")


def reset_checkpoint() -> None:
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Lifecycle intake checkpoint cleared.\n")


# =============================================================================
#  Lock file — prevents two runs overlapping (e.g. cron fires while previous
#  run is still downloading large documents)
# =============================================================================

def acquire_lock() -> bool:
    """
    Write our PID to the lock file.
    Returns False if another instance is already running; True if we got the lock.
    """
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if the PID is still alive
            os.kill(old_pid, 0)
            # If we reach here the process exists — another run is live
            logger.warning(
                f"Another intake run is already in progress (PID {old_pid}). "
                "Exiting to avoid overlap."
            )
            return False
        except (ValueError, OSError):
            # PID file is stale (process gone) — safe to overwrite
            pass

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


# =============================================================================
#  Per-run log file — appended under logs/intake/
# =============================================================================

def setup_run_log() -> str:
    """
    Add a FileHandler to the root logger that writes to logs/intake/intake_<ts>.log.
    Returns the log file path so it can be reported at the end of the run.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    ts       = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
    log_path = os.path.join(LOG_DIR, f"intake_{ts}.log")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
    logging.getLogger().addHandler(fh)
    return log_path


# =============================================================================
#  SharePoint document library helpers
# =============================================================================

async def get_headers() -> dict:
    token = await get_graph_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def resolve_compliance_drive() -> tuple[str, str]:
    headers = await get_headers()
    base = settings.graph_base_url
    url = settings.compliance_site_url.rstrip("/")
    parts = url.replace("https://", "").split("/", 1)
    hostname = parts[0]
    path = parts[1] if len(parts) > 1 else ""

    async with httpx.AsyncClient(timeout=30.0) as client:
        site_resp = await client.get(f"{base}/sites/{hostname}:/{path}", headers=headers)
        site_resp.raise_for_status()
        site_id = site_resp.json()["id"]

        drives_resp = await client.get(f"{base}/sites/{site_id}/drives", headers=headers)
        drives_resp.raise_for_status()
        drives = drives_resp.json().get("value", [])

    drive_id = next(
        (d["id"] for d in drives if d.get("name") == settings.compliance_library_name),
        drives[0]["id"] if drives else "",
    )
    if not drive_id:
        raise RuntimeError(f"No SharePoint drive found for {settings.compliance_site_url}")
    return site_id, drive_id


async def list_folder(drive_id: str, folder_id: Optional[str] = None) -> list[dict]:
    headers = await get_headers()
    url = (
        f"{settings.graph_base_url}/drives/{drive_id}/items/{folder_id}/children"
        if folder_id
        else f"{settings.graph_base_url}/drives/{drive_id}/root/children"
    )
    params = {
        "$top": 200,
        "$select": "id,name,size,folder,file,webUrl,lastModifiedDateTime",
    }
    items: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        while url:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            params = None
    return items


async def walk_folder(
    drive_id: str,
    folder_name: str,
    folder_id: Optional[str] = None,
) -> list[dict]:
    items = await list_folder(drive_id, folder_id)
    files: list[dict] = []
    for item in items:
        name = item.get("name", "")
        if "folder" in item:
            files.extend(await walk_folder(drive_id, f"{folder_name}/{name}", item["id"]))
            continue

        ext = os.path.splitext(name)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            files.append({
                "id": item["id"],
                "name": name,
                "folder_path": folder_name,
                "extension": ext,
                "size": item.get("size", 0),
                "web_url": item.get("webUrl", ""),
            })
    return files


async def download_file(drive_id: str, item_id: str) -> tuple[bytes, str]:
    headers = await get_headers()
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        meta = await client.get(
            f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}",
            headers=headers,
            params={"$select": "id,name"},
        )
        meta.raise_for_status()
        filename = meta.json().get("name", "document")

        content = await client.get(
            f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}/content",
            headers=headers,
        )
        content.raise_for_status()
    return content.content, filename


async def resolve_owner_by_email(email: str) -> tuple[str, str]:
    if not email:
        return "", ""
    try:
        headers = await get_headers()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.graph_base_url}/users/{email}",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        return (
            data.get("id", ""),
            data.get("displayName", "") or data.get("userPrincipalName", email),
        )
    except Exception as exc:
        logger.warning(f"Could not resolve owner email '{email}': {exc}")
        return "", ""


async def fetch_role_titles() -> list[str]:
    try:
        items = await get_list_items(settings.role_register_list_id, "Role Register")
        return [
            i.get("fields", {}).get("Title", "")
            for i in items
            if i.get("fields", {}).get("Title")
        ]
    except Exception as exc:
        logger.warning(f"Could not load Role Register for CDI-16: {exc}")
        return []


# =============================================================================
#  OrgOS classification and duplicate checks
# =============================================================================

def _department_from_path(folder_path: str, filename: str) -> str:
    text = f"{folder_path} {filename}".lower()
    department_map = {
        "isms": "ISMS",
        "information security": "ISMS",
        "cyber": "ISMS",
        "data protection": "DPO",
        "privacy": "DPO",
        "ndpa": "DPO",
        "hr": "HR",
        "human resources": "HR",
        "finance": "FIN",
        "account": "FIN",
        "legal": "LEGAL",
        "contract": "LEGAL",
        "procurement": "PROC",
        "vendor": "PROC",
        "operations": "OPS",
        "quality": "QMS",
        "qms": "QMS",
        "audit": "AUDIT",
        "risk": "RISK",
        "compliance": "GRC",
        "grc": "GRC",
    }
    for needle, department in department_map.items():
        if needle in text:
            return department
    return "GRC"


def _document_type_from_path(folder_path: str, filename: str) -> tuple[str, str, str]:
    text = f"{folder_path} {filename}".lower()
    name = filename.lower()

    if any(token in text for token in ["form", "template", "checklist"]):
        return "Form", "high", "folder or filename indicates a form/template/checklist"
    if any(token in text for token in ["guideline", "guide", "manual", "handbook"]):
        return "Guidelines", "high", "folder or filename indicates guidance/manual content"
    if any(token in text for token in ["sop", "standard operating procedure", "work instruction"]):
        return "SOP", "high", "folder or filename indicates SOP/work instruction"
    if any(token in text for token in ["procedure", "process"]):
        return "Procedure", "high", "folder or filename indicates procedure/process"
    if "policy" in text or "policies" in text:
        return "Policy", "high", "folder or filename indicates policy"

    # These are controlled documents but are not valid Lifecycle choice values.
    # Intake them as Procedures so governance can review and reclassify if needed.
    if any(token in text for token in ["job description", " jd ", "_jd_", "-jd-", "role profile"]):
        return "Procedure", "medium", "job description mapped to lifecycle-safe Procedure"
    if any(token in text for token in ["contract", "agreement", "nda", "sla"]):
        return "Procedure", "medium", "contract/agreement mapped to lifecycle-safe Procedure"
    if any(token in text for token in ["regulatory", "statutory", "law", "act", "regulation"]):
        return "Guidelines", "medium", "regulatory/reference material mapped to Guidelines"
    if any(token in text for token in ["audit", "finding", "risk assessment", "risk register"]):
        return "Procedure", "medium", "audit/risk document mapped to Procedure for review"

    # Last small clue from extension-stripped name.
    if name.endswith(("-pol.docx", "-pol.pdf")):
        return "Policy", "medium", "filename suffix suggests policy"
    return "Policy", "low", "no strong signal; defaulted to Policy for human review"


def extract_document_code_from_text(text: str) -> str:
    """
    Read the controlled document code from the document body.
    Never invent a code from the SharePoint filename.
    """
    match = DOC_CODE_SEARCH_PATTERN.search(text.upper())
    if not match:
        return ""
    candidate = match.group(0).upper().strip()
    return candidate if DOC_CODE_PATTERN.match(candidate) else ""


def classify_for_lifecycle(filename: str, folder_path: str, document_code: str) -> IntakeClassification:
    document_type, confidence, reason = _document_type_from_path(folder_path, filename)
    department = _department_from_path(folder_path, filename)

    return IntakeClassification(
        document_type=document_type,
        department=department,
        document_code=document_code,
        confidence=confidence,
        reason=reason,
    )


def _field_text(fields: dict, key: str) -> str:
    value = fields.get(key)
    return str(value or "").strip()


async def existing_lifecycle_keys() -> tuple[set[str], set[str]]:
    codes: set[str] = set()
    urls: set[str] = set()
    if not settings.is_list_configured(settings.document_lifecycle_list_id):
        return codes, urls

    items = await get_list_items(settings.document_lifecycle_list_id, LIFECYCLE_LIST_NAME)
    for item in items:
        fields = item.get("fields", {})
        code = _field_text(fields, "DocumentCode").upper()
        url = _field_text(fields, "SharePointFileUrl")
        if code:
            codes.add(code)
        if url:
            urls.add(url)
    return codes, urls


async def existing_register_keys() -> tuple[set[str], set[str]]:
    codes: set[str] = set()
    urls: set[str] = set()
    if not settings.is_list_configured(settings.document_register_list_id):
        return codes, urls

    items = await get_list_items(settings.document_register_list_id, REGISTER_LIST_NAME)
    for item in items:
        fields = item.get("fields", {})
        status = _field_text(fields, "Status").lower()
        code = _field_text(fields, "DocumentCode").upper()
        url = _field_text(fields, "SharePointUrl")
        if status in {"active", "under review"} and code:
            codes.add(code)
        if status in {"active", "under review"} and url:
            urls.add(url)
    return codes, urls


def _clean_sp_text(text: str) -> str:
    """
    Remove characters SharePoint text fields reject.
    Keeps printable ASCII, basic whitespace (space/tab/newline), and
    non-ASCII printable Unicode (accented chars, etc.).
    Strips ASCII control characters (0x00–0x1F except 0x09/0x0A/0x0D)
    and the DEL character (0x7F).
    """
    return "".join(
        c for c in str(text)
        if (ord(c) >= 0x20 or c in "\t\n\r") and ord(c) != 0x7F
    )


def cdi_failures_json(checks: list[dict]) -> str:
    return json.dumps([
        {
            "check": c.get("check_id", "CDI"),
            "detail": _clean_sp_text(c.get("finding", "")),
            "fix": _clean_sp_text(c.get("proposed_fix", "")),
        }
        for c in checks
        if c.get("result") == "FAIL"
    ])


async def create_lifecycle_entry(
    file_info: dict,
    classification: IntakeClassification,
    owner_oid: str,
    owner_name: str,
    run_cdi: bool,
    file_bytes: bytes,
    download_name: str,
    role_titles: list[str],
) -> tuple[str, str]:
    filename = file_info["name"]
    web_url = file_info.get("web_url", "")
    cdi_status = "Pending"
    cdi_failures = ""

    if run_cdi:
        result = await run_cdi_check(
            file_bytes,
            download_name or filename,
            classification.document_code,
            role_titles,
        )
        if result.get("error"):
            cdi_status = "Error"
            cdi_failures = json.dumps([{
                "check": "CDI",
                "detail": result["error"],
                "fix": "Fix the parsing/check issue, then upload the controlled version in Review.",
            }])
        elif result.get("passed"):
            cdi_status = "Passed"
        else:
            cdi_status = "Failed"
            cdi_failures = cdi_failures_json(result.get("checks", []))

    effective_owner = owner_name or DEFAULT_OWNER_NAME
    revised = bool(run_cdi and cdi_status == "Passed")
    trigger = "SharePoint Intake" if cdi_status != "Failed" else "CDI Fix"

    notes = (
        "Imported from SharePoint GRC MASTERY for controlled lifecycle onboarding. "
        "Do not extract controls until this item is approved and appears in the "
        "Document Register. "
        f"Detected type: {classification.document_type} "
        f"({classification.confidence} confidence: {classification.reason}). "
        f"Source folder: {file_info.get('folder_path', '')}."
    )

    fields: dict = {
        "Title": os.path.splitext(filename)[0],
        "DocumentCode": classification.document_code,
        "DocumentType": classification.document_type,
        "Department": classification.department,
        "Stage": "Review",
        "Trigger": trigger,
        "AIGenerated": False,
        "Revised": revised,
        "CDIStatus": cdi_status,
        "Owner": effective_owner,
        "Notes": notes,
        "RejectionCount": 0,
        "StakeholderResponseCount": 0,
        "SharePointFileUrl": web_url,
        "StandardsMapping": DEFAULT_STANDARDS,
    }
    if owner_oid:
        fields["OwnerEntraId"] = owner_oid
    if cdi_failures:
        fields["CDIFailures"] = cdi_failures

    logger.debug(
        f"Creating lifecycle entry for {filename!r} | "
        f"trigger={trigger!r} cdi_status={cdi_status!r} "
        f"title_len={len(fields['Title'])} "
        f"notes_len={len(notes)} "
        f"cdi_failures_len={len(cdi_failures)} "
        f"code={classification.document_code!r}"
    )

    def _is_400(exc: Exception) -> bool:
        s = str(exc)
        return "invalidRequest" in s or "Invalid request" in s

    try:
        item = await create_list_item(
            settings.document_lifecycle_list_id,
            LIFECYCLE_LIST_NAME,
            fields,
        )
    except Exception as exc:
        if not _is_400(exc):
            raise

        # --- Fallback 1: strip CDIFailures ---
        logger.warning(f"400 on full payload for {filename!r} — retrying without CDIFailures")
        fields.pop("CDIFailures", None)
        try:
            item = await create_list_item(
                settings.document_lifecycle_list_id,
                LIFECYCLE_LIST_NAME,
                fields,
            )
        except Exception as exc2:
            if not _is_400(exc2):
                raise

            # --- Fallback 2: bare minimum fields only ---
            logger.warning(f"400 still on {filename!r} — trying bare fields to find culprit")
            # Log full values so we can inspect them
            for k, v in fields.items():
                logger.debug(f"  FIELD {k!r} = {str(v)[:200]!r}")

            bare = {
                "Title": fields["Title"],
                "Stage": fields["Stage"],
                "Trigger": fields["Trigger"],
                "AIGenerated": fields["AIGenerated"],
                "CDIStatus": fields["CDIStatus"],
                "StandardsMapping": fields["StandardsMapping"],
            }
            try:
                item = await create_list_item(
                    settings.document_lifecycle_list_id,
                    LIFECYCLE_LIST_NAME,
                    bare,
                )
                logger.warning(
                    f"Bare fields succeeded for {filename!r} — "
                    f"one of the stripped fields was causing the 400"
                )
            except Exception as exc3:
                if _is_400(exc3):
                    # Even bare fields fail — log Title to inspect it
                    logger.error(
                        f"Even bare fields rejected for {filename!r} — "
                        f"Title={fields['Title']!r}"
                    )
                raise exc3 from None

    return str(item.get("id", "")), cdi_status


# =============================================================================
#  Main
# =============================================================================

async def run_intake(
    folder_filter: Optional[str],
    dry_run: bool,
    limit: Optional[int],
    owner_email: Optional[str],
    run_cdi: bool,
) -> int:
    """Run the intake. Returns number of failures (0 = clean run)."""
    if not settings.is_list_configured(settings.document_lifecycle_list_id):
        raise RuntimeError("DOCUMENT_LIFECYCLE_LIST_ID is not configured.")

    # Fall back to env var if no --owner-email flag was passed
    if not owner_email:
        owner_email = os.environ.get("INTAKE_OWNER_EMAIL", "")

    await startup()
    try:
        checkpoint = load_checkpoint()
        processed_ids = set(checkpoint.get("processed_ids", []))

        print("\n" + "=" * 72)
        print("OrgOS — SharePoint → Document Lifecycle Intake")
        if dry_run:
            print("MODE: DRY RUN")
        if folder_filter:
            print(f"FOLDER FILTER: {folder_filter}")
        if limit:
            print(f"BATCH LIMIT: {limit}")
        print(f"CDI CHECKS: {'ON' if run_cdi else 'OFF'}")
        if processed_ids:
            print(f"RESUMING — {len(processed_ids)} already processed")
        print("=" * 72 + "\n")

        print("Connecting to Compliance SharePoint...")
        _, drive_id = await resolve_compliance_drive()
        print("Connected.\n")

        owner_oid, owner_name = await resolve_owner_by_email(owner_email or "")
        if owner_email and owner_oid:
            print(f"Owner resolved: {owner_name} ({owner_oid})")
        elif owner_email:
            print(f"WARNING: Could not resolve {owner_email}; using {DEFAULT_OWNER_NAME}")

        role_titles = await fetch_role_titles() if run_cdi else []
        if run_cdi:
            print(f"Loaded {len(role_titles)} Role Register titles for CDI checks.\n")

        lifecycle_codes, lifecycle_urls = await existing_lifecycle_keys()
        register_codes, register_urls = await existing_register_keys()

        headers = await get_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            root_resp = await client.get(
                f"{settings.graph_base_url}/drives/{drive_id}/root:/{settings.compliance_starting_folder}",
                headers=headers,
                params={"$select": "id,name"},
            )
            root_resp.raise_for_status()
            root_id = root_resp.json()["id"]

        all_files: list[dict] = []
        for item in await list_folder(drive_id, root_id):
            if "folder" not in item:
                continue
            folder_name = item["name"]
            if folder_filter and folder_filter.lower() not in folder_name.lower():
                continue
            all_files.extend(await walk_folder(drive_id, folder_name, item["id"]))

        remaining = [f for f in all_files if f["id"] not in processed_ids]
        if limit:
            remaining = remaining[:limit]

        print(f"Files found:      {len(all_files)}")
        print(f"Already done:     {len(processed_ids)}")
        print(f"This batch:       {len(remaining)}\n")

        created = skipped = failed = 0

        for i, file_info in enumerate(remaining, 1):
            prefix = f"[{i}/{len(remaining)}]"
            filename = file_info["name"]
            url_key = file_info.get("web_url", "")

            try:
                file_bytes, download_name = await download_file(drive_id, file_info["id"])
                document_text = extract_text(file_bytes, download_name or filename)
                document_code = extract_document_code_from_text(document_text)
            except Exception as exc:
                print(f"  {prefix} {filename[:64]}")
                print(f"              → FAILED TO READ DOCUMENT CODE: {str(exc)[:90]}")
                logger.exception(f"Could not read document code from {filename}")
                checkpoint.setdefault("failed", []).append({
                    "id": file_info["id"],
                    "name": filename,
                    "error": f"Could not read document code: {exc}",
                })
                save_checkpoint(checkpoint)
                failed += 1
                continue

            classification = classify_for_lifecycle(
                filename,
                file_info["folder_path"],
                document_code,
            )
            code_key = classification.document_code.upper()

            duplicate_reason = ""
            if url_key and url_key in lifecycle_urls:
                duplicate_reason = "already in Document Lifecycle"
            elif url_key and url_key in register_urls:
                duplicate_reason = "already in Document Register"

            print(
                f"  {prefix} {classification.document_type:<10} "
                f"{classification.department:<6} {filename[:48]}"
            )
            print(f"              code={classification.document_code or '(not found in document)'}")

            if duplicate_reason:
                print(f"              → SKIP ({duplicate_reason})")
                processed_ids.add(file_info["id"])
                checkpoint.setdefault("skipped", []).append({
                    "id": file_info["id"],
                    "name": filename,
                    "reason": duplicate_reason,
                })
                checkpoint["processed_ids"] = list(processed_ids)
                save_checkpoint(checkpoint)
                skipped += 1
                continue

            if dry_run:
                print(
                    f"              → DRY RUN ({classification.confidence}: "
                    f"{classification.reason})"
                )
                continue

            try:
                item_id, cdi_status = await create_lifecycle_entry(
                    file_info=file_info,
                    classification=classification,
                    owner_oid=owner_oid,
                    owner_name=owner_name,
                    run_cdi=run_cdi,
                    file_bytes=file_bytes,
                    download_name=download_name,
                    role_titles=role_titles,
                )
                print(f"              → CREATED lifecycle #{item_id} | CDI={cdi_status}")
                processed_ids.add(file_info["id"])
                # Only add URL to the intra-run dedup set (prevents the exact same
                # SharePoint file from being written twice if it appears in two folders).
                # Do NOT add code_key — form templates share one code across many
                # distinct instance files (e.g. CORRECTIVE ACTION RESPONSE FORM - HR/IT/FIN).
                # Code-based dedup is only meaningful against the pre-run lifecycle state.
                if url_key:
                    lifecycle_urls.add(url_key)
                checkpoint.setdefault("created", []).append({
                    "id": file_info["id"],
                    "name": filename,
                    "lifecycle_id": item_id,
                    "code": classification.document_code,
                    "cdi_status": cdi_status,
                })
                checkpoint["processed_ids"] = list(processed_ids)
                save_checkpoint(checkpoint)
                created += 1
            except Exception as exc:
                print(f"              → FAILED: {str(exc)[:90]}")
                logger.exception(f"Lifecycle intake failed for {filename}")
                checkpoint.setdefault("failed", []).append({
                    "id": file_info["id"],
                    "name": filename,
                    "error": str(exc),
                })
                save_checkpoint(checkpoint)
                failed += 1

            await asyncio.sleep(1)

        logger.info(
            f"Intake complete — created={created} skipped={skipped} failed={failed}"
        )
        try:
            print("\n" + "=" * 72)
            print("INTAKE COMPLETE")
            print(f"  Created lifecycle cards: {created}")
            print(f"  Skipped duplicates:      {skipped}")
            print(f"  Failed:                  {failed}")
            if dry_run:
                print("  Dry run only: no SharePoint list items were created.")
            print("=" * 72 + "\n")
        except BrokenPipeError:
            pass  # stdout piped to head/grep — processing completed normally
        return failed
    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bring SharePoint GRC documents into Document Lifecycle Review.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/intake_sharepoint_to_lifecycle.py --dry-run
  python scripts/intake_sharepoint_to_lifecycle.py --owner-email you@dragnet-solutions.com
  python scripts/intake_sharepoint_to_lifecycle.py --folder "Policies & SOPs" --limit 10
  python scripts/intake_sharepoint_to_lifecycle.py --no-cdi
  python scripts/intake_sharepoint_to_lifecycle.py --reset
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview files and lifecycle fields without creating items")
    parser.add_argument("--folder", type=str, default=None,
                        help="Only process top-level folders whose name contains this text")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after this many unprocessed documents")
    parser.add_argument("--owner-email", type=str, default=None,
                        help="M365 email to assign as initial lifecycle owner")
    parser.add_argument("--no-cdi", action="store_true",
                        help="Create Review cards with CDIStatus=Pending after reading the document code")
    parser.add_argument("--reset", action="store_true",
                        help="Clear the checkpoint and exit")

    args = parser.parse_args()
    if args.reset:
        reset_checkpoint()
        raise SystemExit(0)

    if not args.dry_run:
        if not acquire_lock():
            raise SystemExit(1)

    log_path = setup_run_log()
    logger.info(
        f"Intake job started — dry_run={args.dry_run} folder={args.folder} "
        f"limit={args.limit} cdi={not args.no_cdi} log={log_path}"
    )

    exit_code = 0
    try:
        failures = asyncio.run(run_intake(
            folder_filter=args.folder,
            dry_run=args.dry_run,
            limit=args.limit,
            owner_email=args.owner_email,
            run_cdi=not args.no_cdi,
        ))
        if failures:
            logger.warning(f"{failures} document(s) failed during this run — check log: {log_path}")
            exit_code = 1
    except BrokenPipeError:
        # stdout was piped to something that closed early (e.g. head/grep).
        # Processing completed — not a real failure.
        import os as _os
        _os.dup2(_os.open(_os.devnull, _os.O_WRONLY), sys.stdout.fileno())
    except Exception as exc:
        logger.exception(f"Intake job crashed: {exc}")
        exit_code = 1
    finally:
        if not args.dry_run:
            release_lock()
        logger.info(f"Intake job finished — exit_code={exit_code} log={log_path}")

    raise SystemExit(exit_code)
