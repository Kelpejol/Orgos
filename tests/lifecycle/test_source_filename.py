# =============================================================================
# tests/lifecycle/test_source_filename.py — naming a SharePoint file
#
# Graph's webUrl for an Office file is a viewer link, not a file path:
#   .../_layouts/15/Doc.aspx?sourcedoc={GUID}&file=Name.docx&action=default
# Reading the last path segment gave "Doc.aspx", which the extractor rejects as
# an unsupported type — so a freshly approved document never had its controls
# extracted. And download_file_from_sharepoint returns (bytes, CONTENT TYPE):
# approval unpacked that as a filename and uploaded the published copy under
# ".../application/vnd.openxmlformats-officedocument...".
# =============================================================================

from unittest.mock import AsyncMock, patch

import pytest

import lifecycle.router as lr
from lifecycle.schemas import CdtCoverFacts

VIEWER_URL = (
    "https://dragnetnigeria.sharepoint.com/sites/everybody/_layouts/15/Doc.aspx"
    "?sourcedoc=%7BE87F6A46-D5CA-40D3-B281-FDF51B4DC49A%7D"
    "&file=BCDR%20Impact,%20Register%20and%20Process%20Continuity%20Procedure.docx"
    "&action=default&mobileredirect=true"
)


def test_viewer_link_yields_the_real_filename():
    assert lr._filename_from_sharepoint_url(VIEWER_URL) == (
        "BCDR Impact, Register and Process Continuity Procedure.docx"
    )


def test_plain_file_path_still_works():
    url = "https://x/sites/everybody/ORGOS%20LIBRARY/Access%20Control/Policy.docx"
    assert lr._filename_from_sharepoint_url(url) == "Policy.docx"


@pytest.mark.parametrize("content_type,expected", [
    ("application/pdf", "document.pdf"),
    ("text/plain", "document.txt"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document.docx"),
])
def test_viewer_link_without_a_file_param_falls_back_to_content_type(content_type, expected):
    """Never return the viewer page itself as the name."""
    url = "https://x/sites/everybody/_layouts/15/Doc.aspx?sourcedoc=%7BABC%7D"
    assert lr._filename_from_sharepoint_url(url, content_type) == expected


async def test_approval_uploads_the_published_copy_under_a_real_filename():
    """Regression: the content type was used as the filename."""
    doc = {
        "id": "10", "Title": "BCDR Impact", "DocumentCode": "DRG-ISMS-PRO-BCI",
        "DocumentType": "Procedure", "Department": "GRC", "OwnerEntraId": "o", "OwnerName": "O",
        "SharePointFileUrl": VIEWER_URL, "RevisionOf": "", "Notes": "",
        "CDTCoverFacts": CdtCoverFacts().to_json(), "RevisionHistory": "[]",
    }
    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock), \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock), \
         patch("lifecycle.router.create_list_item", new_callable=AsyncMock) as mock_create, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.resolve_user", new_callable=AsyncMock) as mock_resolve, \
         patch("lifecycle.router._upload_to_sharepoint", new_callable=AsyncMock) as mock_upload, \
         patch("lifecycle.router.merge") as mock_merge, \
         patch("lifecycle.router._background_extract_and_flag", new_callable=AsyncMock):
        mock_resolve.return_value = {"display_name": "Approver", "email": "a@x.com"}
        mock_dl.return_value = (b"SOURCE", content_type)
        mock_merge.return_value = type("R", (), {"document": b"M", "sha256": "x", "doc_code": "c"})()
        mock_upload.return_value = "https://sp/published.docx"
        mock_create.return_value = {"id": "99", "fields": {}}

        await lr._finalize_document_approval("10", doc, approver_oid="a", approver_email="",
                                             change_summary="First issue of the BCDR procedure.")

    uploaded_name = mock_upload.call_args.args[1]
    assert "/" not in uploaded_name
    assert uploaded_name == "BCDR Impact, Register and Process Continuity Procedure.docx"


# ── media type: a PDF must never be served as a .docx ────────────────────────
def test_media_type_follows_the_real_extension():
    assert lr._media_type_for("Policy.pdf") == "application/pdf"
    assert lr._media_type_for("Policy.docx").endswith("wordprocessingml.document")
    assert lr._media_type_for("Doc.aspx") == "application/octet-stream"
