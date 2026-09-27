"""
reextract_by_code.py — Re-run control extraction on one already-registered
document, by its Document Register code, and write the controls to the AI
Review Queue.

Use when a document was approved/finalised while the LLM was unavailable, so
its extraction produced nothing. Uses the app's own Graph (client-credentials)
auth — no user token needed.

    cd /opt/orgos
    ./venv/bin/python scripts/reextract_by_code.py DRG-XXX-POL-REF-01-26
"""

import asyncio
import sys
from urllib.parse import unquote, urlparse

sys.path.insert(0, ".")

import graph.client as gc  # noqa: E402
from agents.extractor.service import run_extraction_from_file  # noqa: E402
from config import settings  # noqa: E402
from graph.client import download_file_from_sharepoint, get_list_items  # noqa: E402
from grc.constants import DOC_FIELDS  # noqa: E402

# Same rule the lifecycle uses: only these types are extraction targets.
_TARGET_TYPES = {"policy", "procedure", "sop", "guidelines"}


def _extractor_type(doc_type: str):
    return "Policy" if (doc_type or "").strip().lower() in _TARGET_TYPES else None


def _filename_from_url(web_url: str, content_type: str) -> str:
    name = unquote(urlparse(web_url).path.split("/")[-1]) or "document"
    if not name.lower().endswith((".pdf", ".docx", ".doc", ".txt")):
        ct = (content_type or "").lower()
        if "pdf" in ct:
            name += ".pdf"
        else:
            name += ".docx"
    return name


async def main(doc_code: str) -> int:
    await gc.startup()
    try:
        if not settings.is_list_configured(settings.document_register_list_id):
            print("Document Register list is not configured.")
            return 1

        items = await get_list_items(
            settings.document_register_list_id, "Document Register"
        )
        target = doc_code.strip().upper()
        match = next(
            (
                it
                for it in items
                if (it.get("fields", {}).get(DOC_FIELDS["document_code"]) or "")
                .strip()
                .upper()
                == target
            ),
            None,
        )
        if not match:
            print(f"No Document Register item with code {doc_code}.")
            return 1

        f = match.get("fields", {})
        web_url = f.get(DOC_FIELDS["sharepoint_url"]) or ""
        doc_type = f.get(DOC_FIELDS["type"]) or ""
        department = f.get(DOC_FIELDS["department"], "") or ""

        if not web_url:
            print("Register item has no SharePointUrl — cannot fetch the file.")
            return 1

        ext_type = _extractor_type(doc_type)
        if not ext_type:
            print(f"Document type '{doc_type}' is not an extraction target — nothing to do.")
            return 0

        print(f"Found {doc_code} (type={doc_type}). Downloading file…")
        file_bytes, content_type = await download_file_from_sharepoint(web_url)
        filename = _filename_from_url(web_url, content_type)
        print(f"Downloaded {len(file_bytes)} bytes as '{filename}'. Running extraction…\n")

        result = await run_extraction_from_file(
            file_bytes=file_bytes,
            filename=filename,
            doc_code=doc_code,
            write_to_sharepoint=True,
            folder_path=department,
            web_url=web_url,
            document_type_override=ext_type,
        )

        print("=== EXTRACTION RESULT ===")
        print(f"  document_type      : {result.document_type}")
        print(f"  total_extracted    : {result.total_extracted}")
        print(f"  complete_count     : {result.complete_count}")
        print(f"  deficient_count    : {result.deficient_count}")
        print(f"  written_to_queue   : {result.written_to_sharepoint}")
        print(f"  skipped_reason     : {result.skipped_reason}")
        print()
        if result.complete_count and result.written_to_sharepoint:
            print("→ Controls were extracted and written to the AI Review Queue. "
                  "It was almost certainly an LLM outage at finalise time; it is now fixed.")
        elif result.total_extracted == 0:
            print("→ The model read the document but found no controls. Not a bug — "
                  "the document simply has no extractable control statements.")
        else:
            print("→ Items were found but all DEFICIENT (missing required fields), "
                  "so none were written to the queue.")
        return 0
    finally:
        await gc.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reextract_by_code.py DRG-XXX-POL-REF-01-26")
        raise SystemExit(1)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
