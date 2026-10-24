import json
from io import BytesIO
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from scripts import import_roles_from_jds as importer


def pdf_bytes(lines=(), *, image_only=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    stream = DecodedStreamObject()
    if image_only:
        image = DecodedStreamObject()
        image.set_data(b"\xff\xff\xff")
        for key, value in {"Type": "/XObject", "Subtype": "/Image", "ColorSpace": "/DeviceRGB"}.items():
            image[NameObject("/" + key)] = NameObject(value)
        for key, value in {"Width": 1, "Height": 1, "BitsPerComponent": 8}.items():
            image[NameObject("/" + key)] = NumberObject(value)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): writer._add_object(image)}),
        })
        stream.set_data(b"q 500 0 0 700 40 40 cm /Scan Do Q")
    else:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        })
        commands = ["BT /F1 11 Tf 40 760 Td 14 TL"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj T*")
        commands.append("ET")
        stream.set_data("\n".join(commands).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def make_zip(tmp_path, pdfs):
    path = tmp_path / "jds.zip"
    with ZipFile(path, "w") as archive:
        for name, data in pdfs.items():
            archive.writestr(name, data)
    return path


def test_generated_pdf_title_wins_over_filename_and_extracts_metadata(tmp_path):
    path = make_zip(tmp_path, {"Job Descriptions/IT Executive.pdf": pdf_bytes([
        "Job Title:", "Information Security Officer", "Department:", "IT Support and Infrastructure",
        "Reports to: Head of Technology", "Location: Lagos", "Main Job Purpose:", "Protect systems.",
    ])})
    jd, = importer.read_job_descriptions(path)
    assert (jd.title, jd.source) == ("Information Security Officer", "PDF text")
    assert jd.department == "IT Support and Infrastructure"
    assert jd.reports_to == "Head of Technology"
    assert not jd.no_text and not jd.error


def test_generated_scan_uses_filename_and_is_reported(tmp_path):
    path = make_zip(tmp_path, {"Job Descriptions/Finance Intern.PDF": pdf_bytes(image_only=True)})
    jd, = importer.read_job_descriptions(path)
    assert jd.title == "Finance Intern"
    assert jd.source == "file name"
    assert jd.no_text and not jd.error
    assert not jd.department and not jd.reports_to


def test_missing_title_and_corrupt_pdf_are_not_silently_skipped(tmp_path):
    path = make_zip(tmp_path, {
        "Job Descriptions/Legal Officer.pdf": pdf_bytes(["Responsibilities", "Review agreements."]),
        "Job Descriptions/Unreadable.pdf": b"broken PDF",
        "__MACOSX/._Ignored.pdf": b"not a PDF",
        "Job Descriptions/notes.txt": b"notes",
    })
    normal, broken = importer.read_job_descriptions(path)
    assert (normal.title, normal.source, normal.no_text) == ("Legal Officer", "file name", False)
    assert broken.title == "Unreadable" and broken.error


def test_archive_paths_cannot_escape_temporary_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = make_zip(tmp_path, {"../../escaped.pdf": pdf_bytes(["Job title: Developer"])})
    jd, = importer.read_job_descriptions(path)
    assert jd.title == "Developer"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("text,title,department,reports", [
    ("Job Title:QA InternDepartment:Product& Software DevelopmentLocation(City, Country)Remote",
     "QA Intern", "Product& Software Development", ""),
    ("Job title Account Executive\nEmployee name\nDepartment Revenue Team\nLocation Lagos\n"
     "Reporting line Head of Enterprise Sales\nInterim reporting line Chief Revenue Officer\nEffective date",
     "Account Executive", "Revenue Team", "Head of Enterprise Sales"),
    ("JOB TITLE:\nDirect Sales Manager\nDEPARTMENT: Scholarship and\nEducation Services\n"
     "REPORTS TO: Chief Revenue Officer LOCATION: Lagos\nJOB GRADE/LEVEL: Manager",
     "Direct Sales Manager", "Scholarship and Education Services", "Chief Revenue Officer"),
    ("Job Title: Test Centre Manager\nDepartment: Dragnet Prometric Test Centre (Revenue Department)\nLocation Lagos",
     "Test Centre Manager", "Dragnet Prometric Test Centre (Revenue Department)", ""),
    ("Job Title: Administrative Officer\nDepartment: Administrative Department\nLocation Lagos",
     "Administrative Officer", "Administrative Department", ""),
    ("Job Title: Verification - Head\nDepartment: Verification Operations\nMain Job Purpose:\n"
     "Reporting to the CEO, the Head of Verification is responsible for operations.",
     "Verification - Head", "Verification Operations", "CEO"),
])
def test_metadata_layouts(text, title, department, reports):
    jd = importer.parse_job_description("fallback.pdf", text)
    assert (jd.title, jd.department, jd.reports_to) == (title, department, reports)


def test_department_columns_do_not_include_profession_or_level():
    text = "Job Title: Sales Officer\nProfession (Marketing, Finance, etc.): Department:\nRevenue Corporate Solutions\nWork Level: Officer"
    layout = ("Job Title: Sales Officer\nProfession (Marketing, Finance, etc.):    Department:\n"
              "Revenue                                  Corporate Solutions\n\nWork Level: Officer")
    jd = importer.parse_job_description("Sales Officer.pdf", text, layout)
    assert jd.department == "Corporate Solutions"
    layout = ("JOB DESCRIPTION\nSoftware Engineer\n\nDEPARTMENT       LEVEL        EMPLOYMENT TYPE\n"
              "Technology /     Mid-Senior   Full-Time\nOperations\n\nROLE OVERVIEW\nBuild things")
    jd = importer.parse_job_description("Fallback.pdf", layout, layout)
    assert jd.title == "Software Engineer"
    assert jd.department == "Technology / Operations"


def test_layout_restores_spaces_but_does_not_replace_readable_plain_text():
    jd = importer.parse_job_description("fallback.pdf", "Job Title:SoftwareArchitecture&ResearchInternDepartment:Software Development",
                                        "Job Title:\nSoftware Architecture & Research Intern\nDepartment:\nSoftware Development")
    assert jd.title == "Software Architecture & Research Intern"
    jd = importer.parse_job_description("fallback.pdf", "Job Title:QA InternDepartment:Product& Software Development",
                                        "JobTitle:\nQAIntern\nDepartment:\nProduct&SoftwareDevelopment")
    assert jd.title == "QA Intern" and jd.department == "Product& Software Development"


def test_unlabelled_heading_and_signature_job_title():
    text = ("AI Enablement & Agentic Automation Lead\nLagos | Software Engineering | Reports to: Head of Software\n"
            "ABOUT THE ROLE\nDeploy AI tools.\nJob Title\nAs accepted\nDate\nDD/MM/YYYY")
    jd = importer.parse_job_description("AI Enablement & Agentic Automation Lead.pdf", text)
    assert jd.title == "AI Enablement & Agentic Automation Lead" and jd.source == "PDF text"
    assert jd.reports_to == "Head of Software"


@pytest.mark.parametrize("line,expected", [
    ("Reports to the Head of Software", "the Head of Software"),
    ("▪ Reports to Chief Revenue Officer", "Chief Revenue Officer"),
    ("Reports To: Compliance Leads", "Compliance Leads"),
    ("Reports to:\nHead of Finance", "Head of Finance"),
    ("Provide updates and reports to stakeholders.", ""),
])
def test_reporting_channel_after_duties(line, expected):
    text = f"Job Title: Officer\nDepartment: Operations\nMain Job Purpose:\nCarry out duties.\n{line}\nSkills Required:\nTeamwork"
    jd = importer.parse_job_description("Officer.pdf", text)
    assert jd.reports_to == expected


@pytest.fixture
def graph_store(monkeypatch):
    items = []
    methods = []
    async def request(method, url, json=None, **kwargs):
        methods.append(method)
        if url.endswith("/lists"):
            assert method == "GET"
            return {"value": [{"id": "org-roles-list", "displayName": "OrgOS Groups"}]}
        if url.endswith("/columns"):
            assert method == "GET"
            return {"value": importer.groups_service._GROUP_COLUMNS}
        assert url.endswith("/org-roles-list/items")
        if method == "GET":
            return {"value": list(items)}
        assert method == "POST"
        item = {"id": str(len(items) + 1), **json}
        items.append(item)
        return item
    monkeypatch.setattr(importer.graph_client, "_request", request)
    monkeypatch.setattr(importer.groups_service, "_graph", request)
    monkeypatch.setattr(importer.groups_service, "_list_id_cache", {"id": None})
    monkeypatch.setattr(importer.groups_service, "_cols_known", False)
    monkeypatch.setattr(importer.groups_service, "_available_cols", set())
    return items, methods


async def test_dry_run_is_get_only_with_real_service_paths(graph_store, capsys):
    items, methods = graph_store
    scan = importer.JobDescription("Finance Intern.pdf", "Finance Intern", "file name", no_text=True)
    await importer.import_roles([scan])
    assert not items and methods == ["GET", "GET"]
    output = capsys.readouterr().out
    assert "DRY RUN" in output and "file name" in output and "Finance Intern.pdf" in output
    assert "PDFs with no readable text (1" in output


async def test_missing_list_dry_run_never_provisions(monkeypatch, capsys):
    request = AsyncMock(return_value={"value": []})
    monkeypatch.setattr(importer.graph_client, "_request", request)
    provision = AsyncMock(side_effect=AssertionError("Must not provision"))
    monkeypatch.setattr(importer.groups_service, "get_groups_list_id", provision)
    await importer.import_roles([importer.JobDescription("Officer.pdf", "Officer", "file name")])
    assert [call.args[0] for call in request.call_args_list] == ["GET"]
    provision.assert_not_awaited()
    assert "nothing provisioned" in capsys.readouterr().out


async def test_apply_idempotent_normalized_names_aliases_and_withdrawn(graph_store, capsys):
    items, methods = graph_store
    items.extend([
        {"id": "1", "fields": {"Title": "People & Compliance", "Aliases": '["HR Officer"]',
                               "Members": '[{"oid":"person-1"}]', "Category": "Existing"}},
        {"id": "2", "fields": {"Title": "Old Role", "Status": "Withdrawn"}},
    ])
    original = json.loads(json.dumps(items))
    descriptions = [importer.JobDescription("one.pdf", "people / compliance", "PDF text"),
                    importer.JobDescription("two.pdf", "HR Officer", "PDF text"),
                    importer.JobDescription("three.pdf", "Old Role", "PDF text"),
                    importer.JobDescription("four.pdf", "IT Officer", "PDF text", "Technology", "Head of IT"),
                    importer.JobDescription("five.pdf", "IT-OFFICER", "PDF text", "Different department")]
    create = importer.groups_service.create_group
    with pytest.MonkeyPatch.context() as patch:
        spy = AsyncMock(wraps=create)
        patch.setattr(importer.groups_service, "create_group", spy)
        await importer.import_roles(descriptions, apply=True)
        await importer.import_roles(descriptions, apply=True)
    assert len(items) == 3 and items[:2] == original
    assert methods.count("POST") == 1
    spy.assert_awaited_once()
    fields = items[2]["fields"]
    assert fields["Title"] == "IT Officer" and fields["Category"] == "Technology"
    assert json.loads(fields["Members"]) == [] and json.loads(fields["Aliases"]) == []
    assert "Reports to: Head of IT" in fields["Description"]
    assert "Possible duplicates for human review" in capsys.readouterr().out


async def test_failed_role_lookup_stops_apply(monkeypatch):
    monkeypatch.setattr(importer.graph_client, "_request", AsyncMock(side_effect=RuntimeError("Graph unavailable")))
    create = AsyncMock()
    monkeypatch.setattr(importer.groups_service, "create_group", create)
    with pytest.raises(RuntimeError, match="Graph unavailable"):
        await importer.import_roles([importer.JobDescription("x.pdf", "Officer", "file name")], apply=True)
    create.assert_not_awaited()


def test_cli_defaults_to_dry_run(tmp_path, graph_store, monkeypatch):
    path = make_zip(tmp_path, {"Officer.pdf": pdf_bytes(["Job Title: Officer"])})
    monkeypatch.setattr(importer.graph_client, "startup", AsyncMock())
    monkeypatch.setattr(importer.graph_client, "shutdown", AsyncMock())
    assert importer.main([str(path)]) == 0
    items, methods = graph_store
    assert not items and set(methods) == {"GET"}


def test_cli_rejects_empty_zip_before_graph_reads(tmp_path, monkeypatch):
    path = make_zip(tmp_path, {})
    startup = AsyncMock()
    monkeypatch.setattr(importer.graph_client, "startup", startup)
    assert importer.main([str(path)]) == 1
    startup.assert_not_awaited()
