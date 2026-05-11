# =============================================================================
# scripts/sync_roles.py — Entra ID → Role Register sync
# Reads all Dragnet staff from Entra ID via Graph API and populates
# the Role Register in SharePoint with one entry per unique job title.
# Run once during setup, then again when org structure changes.
#
# Usage (from orgos/ root with venv activated):
#   python scripts/sync_roles.py
#   python scripts/sync_roles.py --dry-run     (preview without writing)
#   python scripts/sync_roles.py --department "Compliance & Technology"
#
# Depends on: config.py, graph/auth.py, grc/constants.py
# =============================================================================

import asyncio
import argparse
import logging
import sys
import os

# Add the project root to the path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from config import settings, configure_logging
from graph.auth import get_graph_access_token
from graph.client import startup, shutdown, create_list_item, get_list_items
from grc.constants import LIST_IDS, LIST_NAMES, ROLE_FIELDS

configure_logging()
logger = logging.getLogger(__name__)


# =============================================================================
#  Fetch all users from Entra ID
# =============================================================================

async def fetch_all_users(department_filter: str = None) -> list[dict]:
    """
    Fetch all Dragnet staff from Entra ID via Graph API.
    Returns a list of user dicts with id, displayName, jobTitle, department.
    """
    token = await get_graph_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    url = f"{settings.graph_base_url}/users"
    params = {
        "$select": "id,displayName,jobTitle,department,mail,userPrincipalName",
        "$top": 200,
        "$filter": "accountEnabled eq true",
    }

    if department_filter:
        params["$filter"] += f" and department eq '{department_filter}'"

    all_users = []
    next_link = url

    async with httpx.AsyncClient(timeout=30.0) as client:
        first = True
        while next_link:
            resp = await client.get(
                next_link,
                headers=headers,
                params=params if first else None,
            )
            resp.raise_for_status()
            data = resp.json()
            all_users.extend(data.get("value", []))
            next_link = data.get("@odata.nextLink")
            first = False

    # Filter out users with no job title
    users_with_titles = [
        u for u in all_users
        if u.get("jobTitle") and u.get("jobTitle").strip()
    ]

    logger.info(
        f"Fetched {len(all_users)} users from Entra ID, "
        f"{len(users_with_titles)} have job titles"
    )
    return users_with_titles


# =============================================================================
#  Build role mapping from users
# =============================================================================

def build_role_map(users: list[dict]) -> dict[str, dict]:
    """
    Build a map of job_title → best user for that role.
    When multiple people share a job title, keeps the first one found.
    Returns: {job_title: {oid, display_name, email, department, job_title}}
    """
    role_map: dict[str, dict] = {}

    for user in users:
        job_title = user.get("jobTitle", "").strip()
        if not job_title or job_title.strip().upper() in ("N/A", "NA", "-", "TBA", "TBD"):
         continue

        if job_title not in role_map:
            role_map[job_title] = {
                "oid":          user["id"],
                "display_name": user.get("displayName", ""),
                "email":        user.get("mail") or user.get("userPrincipalName", ""),
                "department":   user.get("department", ""),
                "job_title":    job_title,
            }
        else:
            # Log when multiple people share a title — worth knowing
            existing = role_map[job_title]["display_name"]
            logger.info(
                f"Multiple holders for '{job_title}': "
                f"{existing} (kept) and {user.get('displayName')} (skipped)"
            )

    return role_map


# =============================================================================
#  Get existing Role Register entries
# =============================================================================

async def get_existing_roles() -> dict[str, str]:
    """
    Fetch existing Role Register entries from SharePoint.
    Returns: {role_title: sharepoint_item_id}
    """
    items = await get_list_items(
        LIST_IDS["role_register"],
        LIST_NAMES["role_register"],
    )

    existing = {}
    for item in items:
        fields = item.get("fields", {})
        title = fields.get(ROLE_FIELDS["role_title"], "")
        if title:
            existing[title] = str(item["id"])

    logger.info(f"Found {len(existing)} existing roles in Role Register")
    return existing


# =============================================================================
#  Write roles to SharePoint
# =============================================================================

async def write_role(
    role: dict,
    existing_id: str = None,
    dry_run: bool = False,
) -> str:
    """
    Create or update a role in the Role Register SharePoint list.
    Returns: "created", "skipped" (already exists, no change needed)
    """
    fields = {
        ROLE_FIELDS["role_title"]:        role["job_title"],
        ROLE_FIELDS["department"]:        role["department"],
        ROLE_FIELDS["jd_reference"]:      "",  # JD reference added manually later
        ROLE_FIELDS["source_system"]:     "Entra ID",
        ROLE_FIELDS["assignment_status"]: "Assigned",
        # Store OID in the companion text column
        "CurrentHolderEntraId":           role["oid"],
    }

    if existing_id:
        # Role already exists — skip to avoid overwriting manual assignments
        logger.info(f"  SKIP   '{role['job_title']}' — already in register (id={existing_id})")
        return "skipped"

    if dry_run:
        logger.info(
            f"  DRY    '{role['job_title']}' "
            f"→ {role['display_name']} ({role['department']})"
        )
        return "dry_run"

    await create_list_item(
        LIST_IDS["role_register"],
        LIST_NAMES["role_register"],
        fields,
    )
    logger.info(
        f"  CREATE '{role['job_title']}' "
        f"→ {role['display_name']} ({role['department']})"
    )
    return "created"


# =============================================================================
#  Main sync function
# =============================================================================

async def sync_roles(
    department_filter: str = None,
    dry_run: bool = False,
) -> None:
    """
    Full sync: Entra ID users → Role Register.

    Steps:
    1. Fetch all users with job titles from Entra ID
    2. Build one role entry per unique job title
    3. Compare against existing Role Register entries
    4. Create new entries — never overwrite existing ones
    5. Print summary

    Args:
        department_filter: If set, only sync users from this department
        dry_run: If True, preview what would be written without writing
    """
    await startup()

    try:
        print("\n" + "="*60)
        print("OrgOS Role Register — Entra ID Sync")
        if dry_run:
            print("MODE: DRY RUN — no changes will be written")
        if department_filter:
            print(f"FILTER: department = '{department_filter}'")
        print("="*60 + "\n")

        # Step 1 — fetch users
        print("Fetching users from Entra ID...")
        users = await fetch_all_users(department_filter)
        print(f"Found {len(users)} users with job titles\n")

        # Step 2 — build role map
        role_map = build_role_map(users)
        print(f"Unique job titles: {len(role_map)}\n")

        # Step 3 — get existing roles
        print("Checking existing Role Register entries...")
        existing = await get_existing_roles()
        print(f"Existing entries: {len(existing)}\n")

        # Step 4 — sync
        print("Syncing roles:\n")
        counts = {"created": 0, "skipped": 0, "dry_run": 0}

        # Sort by department then title for readable output
        sorted_roles = sorted(
            role_map.values(),
           key=lambda r: ((r["department"] or "").lower(), r["job_title"].lower())
        )

        for role in sorted_roles:
            existing_id = existing.get(role["job_title"])
            result = await write_role(role, existing_id, dry_run)
            counts[result] = counts.get(result, 0) + 1

        # Step 5 — summary
        print("\n" + "="*60)
        print("SYNC COMPLETE")
        print(f"  Created:  {counts.get('created', 0)}")
        print(f"  Skipped:  {counts.get('skipped', 0)} (already existed)")
        if dry_run:
            print(f"  Dry run:  {counts.get('dry_run', 0)} (would have been created)")
        print("="*60 + "\n")

        if not dry_run and counts.get("created", 0) > 0:
            print(
                "Next step: open the Role Register in OrgOS and verify "
                "the entries look correct. Assign JD references manually "
                "where needed.\n"
            )

    finally:
        await shutdown()


# =============================================================================
#  Entry point
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync Dragnet Entra ID users to the OrgOS Role Register"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be written without making any changes",
    )
    parser.add_argument(
        "--department",
        type=str,
        default=None,
        help="Only sync users from this department (e.g. 'Compliance & Technology')",
    )
    args = parser.parse_args()

    asyncio.run(sync_roles(
        department_filter=args.department,
        dry_run=args.dry_run,
    ))