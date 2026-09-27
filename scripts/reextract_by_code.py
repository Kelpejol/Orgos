"""Re-extract one registered document, using the file link on its LIFECYCLE
item (that's where SharePointFileUrl actually lives). Writes controls to the
AI Review Queue. Uses the app's own Graph auth."""

import asyncio
import sys
from urllib.parse import unquote, urlparse

sys.path.insert(0, ".")

import graph.client as gc
from agents.extractor.service import run_extraction_from_file
from config import settings
from graph.client import download_file_from_sharepoint, get_list_items
from grc.constants import DOC_FIELDS

# Same rule the lifecycle uses: only these types are extraction targets.
_TARGET_TYPES = {"policy", "procedure", "sop", "guidelines"}


def _extractor_type(doc_type: str):
    return "Policy" if (doc_type or "").strip().lower() in _TARGET_TYPES else None


def _match(items, field, value):
    v = (value or "").strip().upper()
    return [it for it in items if (it.get("fields", {}).get(field) or "").strip().upper() == v]


def _filename_from_url(web_url: str, content_type: str) -> str:
    name = unquote(urlparse(web_url).path.split("/")[-1]) or "document"
    if not name.lower().endswith((".pdf", ".docx", ".doc", ".txt")):
        name += ".pdf" if "pdf" in (content_type or "").lower() else ".docx"
    return name


async def main(doc_code: str) -> int:
    await gc.startup()
    try:
        web_url, doc_type, department = "", "", ""

        # 1) Prefer the lifecycle item's file link.
        if settings.is_list_configured(settings.document_lifecycle_list_id):
            lc = await get_list_items(settings.document_lifecycle_list_id, "Document Lifecycle")
            hits = _match(lc, "DocumentCode", doc_code)
            hits.sort(key=lambda it: bool(it.get("fields", {}).get("SharePointFileUrl")), reverse=True)
            if hits:
                f = hits[0].get("fields", {})
                web_url = f.get("SharePointFileUrl") or ""
                doc_type = f.get("DocumentType") or ""
                department = f.get("Department", "") or ""

        # 2) Fallback to the register's URL.
        if not web_url and settings.is_list_configured(settings.document_register_list_id):
            reg = await get_list_items(settings.document_register_list_id, "Document Register")
            hits = _match(reg, DOC_FIELDS["document_code"], doc_code)
            if hits:
                f = hits[0].get("fields", {})
                web_url = f.get(DOC_FIELDS["sharepoint_url"]) or ""
                doc_type = f.get(DOC_FIELDS["type"]) or ""
                department = f.get(DOC_FIELDS["department"], "") or ""

        if not web_url:
            print(f"No SharePoint file URL found (lifecycle or register) for {doc_code}.")
            return 1

        ext_type = _extractor_type(doc_type)
        if not ext_type:
            print(f"Document type '{doc_type}' is not an extraction target — nothing to do.")
            return 0

        print(f"{doc_code} (type={doc_type}) — downloading file...")
        file_bytes, content_type = await download_file_from_sharepoint(web_url)
        filename = _filename_from_url(web_url, content_type)
        print(f"Downloaded {len(file_bytes)} bytes as '{filename}'. Extracting...\n")

        result = await run_extraction_from_file(
            file_bytes=file_bytes, filename=filename, doc_code=doc_code,
            write_to_sharepoint=True, folder_path=department, web_url=web_url,
            document_type_override=ext_type,
        )

        print("=== EXTRACTION RESULT ===")
        print(f"  document_type    : {result.document_type}")
        print(f"  total_extracted  : {result.total_extracted}")
        print(f"  complete_count   : {result.complete_count}")
        print(f"  deficient_count  : {result.deficient_count}")
        print(f"  written_to_queue : {result.written_to_sharepoint}")
        print(f"  skipped_reason   : {result.skipped_reason}\n")
        if result.complete_count and result.written_to_sharepoint:
            print("-> Controls extracted and written to the AI Review Queue. Extraction")
            print("   failed silently at skip time (LLM down or download error); now fixed.")
        elif result.total_extracted == 0:
            print("-> Model read the document but found no controls. If this PDF is a scan,")
            print("   the text layer may be empty -- check whether OCR is configured.")
        else:
            print("-> Items found but all DEFICIENT (missing required fields); none written.")
        return 0
    finally:
        await gc.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reextract_by_code.py DRG-SD-POL-SDLC-01-26")
        raise SystemExit(1)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
