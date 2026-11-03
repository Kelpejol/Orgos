# =============================================================================
# tests/lifecycle/test_source_filename.py — naming a SharePoint file
#
# Graph's webUrl for an Office file is a viewer link, not a file path:
#   .../_layouts/15/Doc.aspx?sourcedoc={GUID}&file=Name.docx&action=default
# Reading the last path segment gave "Doc.aspx", which the extractor rejects as
# an unsupported type — so a freshly approved document never had its controls
# extracted. And download_file_from_sharepoint returns (bytes, CONTENT TYPE),
# which must never be taken for a file name.
# =============================================================================

import pytest

import lifecycle.router as lr

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


# ── media type: a PDF must never be served as a .docx ────────────────────────
def test_media_type_follows_the_real_extension():
    assert lr._media_type_for("Policy.pdf") == "application/pdf"
    assert lr._media_type_for("Policy.docx").endswith("wordprocessingml.document")
    assert lr._media_type_for("Doc.aspx") == "application/octet-stream"
