import json
from urllib.parse import unquote
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook

from graph.exceptions import GraphNotFoundError, GraphPermissionError
from scripts import import_staff_roles as importer


def write_register(tmp_path, rows):
    path = tmp_path / "staff.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Staff List"
    sheet.append(["Example staff register"])
    sheet.append(["S/N", "Staff Name", "Email", "Job Title", "Department", "Location"])
    for i, row in enumerate(rows, 1):
        sheet.append([i, *row, "Example City"])
    workbook.save(path)
    workbook.close()
    return path


@pytest.fixture
def graph_store(monkeypatch):
    items, users, calls = [], [], []
    async def request(method, url, json=None, params=None, **kwargs):
        calls.append((method, url, json))
        if url.endswith("/users"):
            wanted = params["$filter"].split("'")[1].casefold()
            return {"value": [user for user in users if wanted in
                              {(user.get("mail") or "").casefold(), (user.get("userPrincipalName") or "").casefold()}]}
        if "/users/" in url:
            target = unquote(url.rsplit("/", 1)[1])
            user = next((u for u in users if target in (u["id"], u.get("userPrincipalName"))), None)
            if not user:
                raise GraphNotFoundError("Example account")
            return user
        if url.endswith("/lists"):
            assert method == "GET"
            return {"value": [{"id": "staff-roles-list", "displayName": "OrgOS Groups"}]}
        if url.endswith("/columns"):
            assert method == "GET"
            return {"value": importer.groups_service._GROUP_COLUMNS}
        if url.endswith("/staff-roles-list/items"):
            if method == "GET":
                return {"value": list(items)}
            assert method == "POST"
            item = {"id": str(len(items) + 1), **json}
            items.append(item)
            return item
        prefix, item_id = url.rsplit("/", 1)
        if item_id == "fields":
            item_id = prefix.rsplit("/", 1)[1]
            item = next(item for item in items if item["id"] == item_id)
            assert method == "PATCH"
            item["fields"].update(json)
            return item["fields"]
        assert method == "GET" and "/staff-roles-list/items/" in url
        return next(item for item in items if item["id"] == item_id)

    monkeypatch.setattr(importer.graph_client, "_request", request)
    monkeypatch.setattr(importer.groups_service, "_graph", request)
    monkeypatch.setattr(importer.graph_client, "_user_cache", {})
    monkeypatch.setattr(importer.groups_service, "_list_id_cache", {"id": None})
    monkeypatch.setattr(importer.groups_service, "_cols_known", False)
    monkeypatch.setattr(importer.groups_service, "_available_cols", set())

    def add_role(name, *, aliases=None, members=None, status="Active"):
        role = {"id": str(len(items) + 1), "fields": {"Title": name, "Aliases": json.dumps(aliases or []),
                 "Members": json.dumps(members or []), "Category": "Original category", "Status": status}}
        items.append(role)
        return role

    def add_user(name="Avery Example", email="avery@example.test", oid="example-oid"):
        user = {"id": oid, "displayName": name, "mail": email, "userPrincipalName": email}
        users.append(user)
        return user

    return items, calls, add_role, add_user


def test_generated_workbook_reads_row_two_and_preserves_exact_title(tmp_path):
    path = write_register(tmp_path, [("Avery Example", "avery@example.test", " Coordinator / Auditor ", "Operations")])
    person, = importer.read_staff_register(path)
    assert person.name == "Avery Example" and person.email == "avery@example.test"
    assert person.title == " Coordinator / Auditor " and person.department == "Operations"
    assert "avery@example.test" not in repr(person)


@pytest.mark.parametrize("title,parts", [
    ("Managing Director/Chief Executive Officer", ["Managing Director", "Chief Executive Officer"]),
    ("Product and Innovation Officer / Compliance Officer / Technology Officer",
     ["Product and Innovation Officer", "Compliance Officer", "Technology Officer"]),
    ("Finance & Administration Officer", ["Finance & Administration Officer"]),
    ("Officer / Officer//", ["Officer"]),
])
def test_split_only_slashes(title, parts):
    assert importer.split_title(title) == parts


async def test_existing_name_and_agreed_alias_are_exact_matches(graph_store):
    items, calls, add_role, add_user = graph_store
    role = add_role("People & Operations", aliases=["People Coordinator"])
    add_user()
    staff = [importer.StaffPerson("Avery Example", "avery@example.test", "People Coordinator", "People")]
    plan = await importer.import_staff(staff, {}, apply=True)
    assert not plan.proposals and not plan.unmatched
    assert len(items) == 1
    assert json.loads(role["fields"]["Members"])[0]["oid"] == "example-oid"
    assert role["fields"]["Category"] == "Original category"
    assert role["fields"]["Aliases"] == '["People Coordinator"]'


async def test_mapping_uses_canonical_role_without_creating_variant(graph_store):
    items, calls, add_role, add_user = graph_store
    role = add_role("Graphics Designer")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Graphic Designer", "Design")
    plan = await importer.import_staff([person], {"Graphic Designer": ["Graphics Designer"]}, apply=True)
    assert not plan.proposals and not plan.unmatched and not plan.missing_mappings
    assert len(items) == 1 and json.loads(role["fields"]["Members"])[0]["oid"] == "example-oid"


async def test_no_fuzzy_adds_or_unreviewed_near_duplicate_creation(graph_store, capsys):
    items, calls, add_role, add_user = graph_store
    role = add_role("Graphics Designer")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Graphic Designer", "Design")
    plan = await importer.import_staff([person], {}, apply=True)
    assert plan.proposals[0].near and not plan.proposals[0].create
    assert plan.unmatched[0][0] == "Graphic Designer" and plan.unmatched[0][2] == "Graphics Designer"
    assert not plan.additions and not any(method != "GET" for method, _, _ in calls)
    assert json.loads(role["fields"]["Members"]) == []
    assert "Review; no creation" in capsys.readouterr().out


async def test_bad_fuzzy_suggestion_cannot_assign_a_different_role(graph_store):
    items, calls, add_role, add_user = graph_store
    wrong_role = add_role("Head of Finance")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Head of Marketing", "Marketing")
    await importer.import_staff([person], {}, apply=True)
    assert json.loads(wrong_role["fields"]["Members"]) == []
    for item in items:
        if json.loads(item["fields"]["Members"]):
            assert item["fields"]["Title"] == "Head of Marketing"


async def test_missing_account_is_listed_and_skipped(graph_store, capsys):
    items, calls, add_role, add_user = graph_store
    role = add_role("Coordinator")
    person = importer.StaffPerson("Morgan Example", "missing@example.test", "Coordinator", "Operations")
    plan = await importer.import_staff([person], {}, apply=True)
    assert plan.unresolved == [("Morgan Example", "Coordinator", "No matching Entra account")]
    assert not plan.additions and json.loads(role["fields"]["Members"]) == []
    output = capsys.readouterr().out
    assert "Morgan Example" in output and "missing@example.test" not in output


async def test_email_filter_fallback_uses_unique_account_and_existing_profile_resolver(graph_store):
    items, calls, add_role, add_user = graph_store
    user = add_user()
    user["userPrincipalName"] = "avery-login@example.test"
    resolved, reason = await importer.resolve_person("avery@example.test")
    assert not reason and resolved["oid"] == "example-oid"
    assert any(url.endswith("/users") for _, url, _ in calls)
    assert any(url.endswith("/users/example-oid") for _, url, _ in calls)


async def test_ambiguous_entra_accounts_are_not_guessed(graph_store):
    items, calls, add_role, add_user = graph_store
    first = add_user(oid="first-example")
    second = add_user(oid="second-example")
    first["userPrincipalName"] = "first-login@example.test"
    second["userPrincipalName"] = "second-login@example.test"
    user, reason = await importer.resolve_person("avery@example.test")
    assert user is None and reason == "Multiple matching Entra accounts"


async def test_apply_is_idempotent_with_split_titles_and_new_roles(graph_store):
    items, calls, add_role, add_user = graph_store
    existing_member = {"oid": "existing-person", "display_name": "Riley Example", "email": "riley@example.test", "note": "retain"}
    original = add_role("Coordinator", members=[existing_member])
    add_user()
    title = "Coordinator/Auditor"
    staff = [importer.StaffPerson("Avery Example", "avery@example.test", title, "Operations")]
    mapping = {title: ["Coordinator", "Auditor"]}
    await importer.import_staff(staff, mapping, apply=True)
    writes = [call for call in calls if call[0] != "GET"]
    assert len(items) == 2 and len(writes) == 3  # one creation, two membership additions
    original_members = json.loads(original["fields"]["Members"])
    assert original_members[0] == existing_member
    assert original["fields"]["Category"] == "Original category"
    new_role = items[1]["fields"]
    assert new_role["Title"] == "Auditor" and new_role["Category"] == "Operations"
    assert json.loads(new_role["Aliases"]) == []
    plan = await importer.import_staff(staff, mapping, apply=True)
    assert not plan.additions and not plan.proposals
    assert [call for call in calls if call[0] != "GET"] == writes


async def test_new_exact_title_role_can_receive_person_after_creation(graph_store):
    items, calls, add_role, add_user = graph_store
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Courier", "Operations")
    await importer.import_staff([person], {}, apply=True)
    writes = sum(method != "GET" for method, _, _ in calls)
    assert items[0]["fields"]["Title"] == "Courier"
    assert json.loads(items[0]["fields"]["Members"])[0]["oid"] == "example-oid"
    await importer.import_staff([person], {}, apply=True)
    assert sum(method != "GET" for method, _, _ in calls) == writes


async def test_combined_title_without_mapping_is_one_role_and_never_split(graph_store):
    items, calls, add_role, add_user = graph_store
    add_role("Coordinator")
    add_role("Auditor")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Coordinator/Auditor", "Operations")
    plan = await importer.import_staff([person], {}, apply=True)
    assert [p.name for p in plan.proposals] == ["Coordinator/Auditor"]          # the slash is part of the name
    assert set(plan.additions) == {"Coordinator/Auditor"}                       # not Coordinator, not Auditor


async def test_mapping_to_missing_role_is_reported_without_inventing_it(graph_store):
    items, calls, add_role, add_user = graph_store
    add_role("Graphics Designer")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Graphic Designer", "Design")
    plan = await importer.import_staff([person], {"Graphic Designer": ["Nonexistent Target"]}, apply=True)
    assert plan.missing_mappings == [("Graphic Designer", "Nonexistent Target", "Missing or withdrawn; skipped")]
    assert not plan.additions and not plan.proposals and len(items) == 1


async def test_mapping_keys_require_verbatim_register_title(graph_store):
    items, calls, add_role, add_user = graph_store
    add_role("Graphics Designer")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Graphic Designer ", "Design")
    plan = await importer.import_staff([person], {"Graphic Designer": ["Graphics Designer"]})
    assert plan.unmatched and not plan.additions


async def test_withdrawn_role_never_recreated_or_given_members(graph_store):
    items, calls, add_role, add_user = graph_store
    add_role("Coordinator", status="Withdrawn")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Coordinator", "Operations")
    plan = await importer.import_staff([person], {"Coordinator": ["Coordinator"]}, apply=True)
    assert not plan.proposals and not plan.additions and plan.missing_mappings
    assert not any(method != "GET" for method, _, _ in calls)


async def test_existing_members_rechecked_before_adding(graph_store):
    items, calls, add_role, add_user = graph_store
    role = add_role("Coordinator")
    add_user()
    person = importer.StaffPerson("Avery Example", "avery@example.test", "Coordinator", "Operations")
    plan = await importer.build_plan([person], {})
    role["fields"]["Members"] = json.dumps([{"oid": "example-oid", "display_name": "Existing Name", "email": "old@example.test"}])
    snapshot = role["fields"]["Members"]
    assert await importer.apply_plan(plan) == (0, 0)
    assert role["fields"]["Members"] == snapshot
    assert not any(method != "GET" for method, _, _ in calls)


async def test_duplicate_account_rows_add_once(graph_store):
    items, calls, add_role, add_user = graph_store
    add_role("Coordinator")
    add_user()
    staff = [importer.StaffPerson("Avery Example", "avery@example.test", "Coordinator", "Operations") for _ in range(2)]
    plan = await importer.import_staff(staff, {}, apply=True)
    assert sum(map(len, plan.additions.values())) == 1
    assert len(json.loads(items[0]["fields"]["Members"])) == 1


def test_cli_generated_workbook_is_dry_run_and_never_prints_emails(tmp_path, graph_store, monkeypatch, capsys):
    items, calls, add_role, add_user = graph_store
    add_role("Coordinator")
    add_user()
    path = write_register(tmp_path, [("Avery Example", "avery@example.test", "Coordinator", "Operations")])
    mapping = tmp_path / "mapping.json"
    mapping.write_text('{"_about": "Fake mapping"}')
    monkeypatch.setattr(importer.graph_client, "startup", AsyncMock())
    monkeypatch.setattr(importer.graph_client, "shutdown", AsyncMock())
    before = json.dumps(items)
    files = sorted(tmp_path.iterdir())
    assert importer.main([str(path), "--mapping", str(mapping)]) == 0
    assert sorted(tmp_path.iterdir()) == files and json.dumps(items) == before
    assert all(method == "GET" for method, _, _ in calls)
    output = capsys.readouterr().out
    assert "DRY RUN" in output and "Avery Example" in output and "@" not in output


def test_cli_graph_failure_redacts_exception_and_attempts_no_writes(tmp_path, monkeypatch, capsys):
    path = write_register(tmp_path, [("Avery Example", "avery@example.test", "Coordinator", "Operations")])
    mapping = tmp_path / "mapping.json"
    mapping.write_text("{}")
    monkeypatch.setattr(importer.graph_client, "startup", AsyncMock())
    monkeypatch.setattr(importer.graph_client, "shutdown", AsyncMock())
    request = AsyncMock(side_effect=GraphPermissionError("Private detail: avery@example.test"))
    monkeypatch.setattr(importer.graph_client, "_request", request)
    create = AsyncMock()
    monkeypatch.setattr(importer.groups_service, "create_group", create)
    assert importer.main([str(path), "--mapping", str(mapping), "--apply"]) == 1
    create.assert_not_awaited()
    assert "@" not in capsys.readouterr().out


@pytest.mark.parametrize("data", [[], {"Title": "Not a list"}, {"Title": []}, {"Title": [""]}, {"Title": [42]}])
def test_mapping_validation_rejects_malformed_entries(tmp_path, data):
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        importer.load_mapping(path)


def test_shipped_mapping_contains_only_nonempty_role_lists():
    mapping = importer.load_mapping(importer.Path(importer.__file__).with_name("staff_role_map.json"))
    assert mapping and all(isinstance(targets, list) and targets for targets in mapping.values())
