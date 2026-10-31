# =============================================================================
# scripts/rebuild_chat_index.py — rebuild the chat assistant's search index
#
# Re-reads the Control Register and the procedural steps and re-indexes them, each
# control with its Control ID and Control owner role. Dry run by default.
#
#   python scripts/rebuild_chat_index.py            # says what it would do
#   python scripts/rebuild_chat_index.py --apply    # rebuilds
# =============================================================================

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main(apply: bool) -> int:
    from graph import client as gc
    if not apply:
        print("Dry run: would rebuild the controls and procedure-step collections from SharePoint. "
              "Re-run with --apply.")
        return 0
    await gc.startup()
    try:
        from agents.nl_search.router import rebuild_all
        result = await rebuild_all()
    finally:
        await gc.shutdown()
    print(f"Indexed {result['controls_indexed']} controls and {result['procedures_indexed']} procedure steps.")
    for err in result["errors"]:
        print(f"  error: {err}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--apply" in sys.argv[1:])))
