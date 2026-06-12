# =============================================================================
# scripts/audit_document_register_codes.py — Find bad Document Register codes
#
# Usage:
#   myenv/bin/python scripts/audit_document_register_codes.py
#   myenv/bin/python scripts/audit_document_register_codes.py --withdraw-invalid
#
# The withdraw option soft-hides invalid rows by setting Status="Withdrawn".
# It does not delete SharePoint records.
# =============================================================================

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.cdi_checker.service import DOC_CODE_PATTERN
from config import configure_logging, settings
from graph.client import get_list_items, startup, shutdown, update_list_item

configure_logging()
logger = logging.getLogger(__name__)

REGISTER_LIST = "Document Register"


def field_text(fields: dict, key: str) -> str:
    return str(fields.get(key) or "").strip()


async def run(withdraw_invalid: bool) -> None:
    if not settings.is_list_configured(settings.document_register_list_id):
        raise RuntimeError("DOCUMENT_REGISTER_LIST_ID is not configured.")

    await startup()
    try:
        items = await get_list_items(settings.document_register_list_id, REGISTER_LIST)
        invalid = []

        for item in items:
            fields = item.get("fields", {})
            code = field_text(fields, "DocumentCode")
            if not DOC_CODE_PATTERN.match(code.upper()):
                invalid.append(item)

        print("\n" + "=" * 72)
        print("OrgOS — Document Register Code Audit")
        print(f"Items checked: {len(items)}")
        print(f"Invalid codes: {len(invalid)}")
        print("=" * 72 + "\n")

        for item in invalid:
            item_id = str(item.get("id", ""))
            fields = item.get("fields", {})
            code = field_text(fields, "DocumentCode") or "(blank)"
            title = field_text(fields, "Title") or "(untitled)"
            status = field_text(fields, "Status") or "(blank)"
            print(f"#{item_id} | {code} | {status} | {title}")

            if withdraw_invalid:
                await update_list_item(
                    settings.document_register_list_id,
                    REGISTER_LIST,
                    item_id,
                    {"Status": "Withdrawn"},
                )
                print("  -> Status set to Withdrawn")

        if invalid and not withdraw_invalid:
            print("\nRun with --withdraw-invalid to soft-hide these rows from normal register use.")
        print()
    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Audit Document Register rows for invalid controlled document codes.",
    )
    parser.add_argument(
        "--withdraw-invalid",
        action="store_true",
        help="Set invalid rows to Status=Withdrawn. Does not delete records.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.withdraw_invalid))
