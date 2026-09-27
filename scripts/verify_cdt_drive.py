"""
verify_cdt_drive.py — Prove the CDT file I/O path end-to-end against live SharePoint.

INFRA-1 verification. Resolves the ORGOS LIBRARY drive, creates a throwaway
folder, uploads a tiny .docx, downloads it back, checks the bytes round-trip,
then deletes the throwaway file and folder.

This WRITES to the real ORGOS LIBRARY (into a clearly-named __cdt_verify__
folder that it removes afterwards). Run it deliberately:

    python scripts/verify_cdt_drive.py

Exit code 0 = full round-trip OK. Non-zero = something to fix before Phase 1.
"""

import asyncio
import io
import logging
import sys

from docx import Document

# Ensure repo root on path when run as a script
sys.path.insert(0, ".")

import graph.client as gc  # noqa: E402
from config import settings  # noqa: E402

logging.disable(logging.CRITICAL)

VERIFY_FOLDER = "__cdt_verify__"
VERIFY_FILE = "cdt_drive_check.docx"


def _tiny_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("CDT drive verification — safe to delete.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def _delete_item(drive_id: str, item_id: str) -> None:
    client = gc.get_client()
    headers = await gc._get_headers()
    url = f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}"
    resp = await client.delete(url, headers=headers)
    if resp.status_code not in (200, 204, 404):
        print(f"  ! cleanup: could not delete item {item_id} (status {resp.status_code})")


async def main() -> int:
    await gc.startup()
    ok = True
    drive_id = ""
    uploaded_id = ""
    folder_id = ""
    try:
        site_id, drive_id = await gc.resolve_compliance_drive()
        print(f"1. Resolved ORGOS LIBRARY drive: {drive_id[:40]}…")

        folder_id = await gc.ensure_drive_folder(drive_id, VERIFY_FOLDER)
        print(f"2. Ensured throwaway folder '{VERIFY_FOLDER}' (id {folder_id[:24]}…)")

        payload = _tiny_docx()
        item = await gc.upload_bytes_to_drive(drive_id, VERIFY_FOLDER, VERIFY_FILE, payload)
        uploaded_id = item.get("id", "")
        web_url = item.get("webUrl", "")
        print(f"3. Uploaded {VERIFY_FILE} ({len(payload)} bytes) → {web_url[:60]}…")

        downloaded, _ = await gc.download_file_from_sharepoint(web_url)
        match = downloaded == payload
        print(f"4. Downloaded {len(downloaded)} bytes — round-trip {'MATCH ✅' if match else 'MISMATCH ❌'}")
        ok = ok and match
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}")
        ok = False
    finally:
        # Cleanup — remove the throwaway file and folder.
        try:
            if uploaded_id and drive_id:
                await _delete_item(drive_id, uploaded_id)
            if folder_id and drive_id:
                await _delete_item(drive_id, folder_id)
                print("5. Cleaned up throwaway folder ✅")
        finally:
            await gc.shutdown()

    print("\nRESULT:", "PASS ✅ — CDT file I/O works end-to-end" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
