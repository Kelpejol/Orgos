#!/usr/bin/env python3
# =============================================================================
# scripts/list_sharepoint_lists.py — print every list on the OrgOS SharePoint
# site with its ID, so a new list's ID can be copied into .env.
#
#   python scripts/list_sharepoint_lists.py
#   python scripts/list_sharepoint_lists.py "Records Catalogue"   # just that one
# =============================================================================

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings                     # noqa: E402
from graph.client import _request, shutdown, startup   # noqa: E402


async def main(name_filter: str) -> int:
    await startup()
    try:
        data = await _request("GET", settings.sharepoint_lists_base,
                              params={"$select": "id,displayName"}, context="List SharePoint lists")
        lists = sorted(data.get("value", []), key=lambda x: x.get("displayName", "").lower())
        if name_filter:
            lists = [l for l in lists if l.get("displayName", "").lower() == name_filter.lower()]
            if not lists:
                print(f"No list named '{name_filter}' on the site. Check the name in SharePoint.")
                return 1
        for l in lists:
            print(f"{l.get('displayName', ''):40} {l.get('id', '')}")
        return 0
    finally:
        await shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(" ".join(sys.argv[1:]).strip())))
