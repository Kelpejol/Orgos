# =============================================================================
# tests/lifecycle/test_preview_url_guard.py
#
# The by-URL read endpoint takes a URL from the caller, so without a host check
# OrgOS would fetch and return whatever it was pointed at. Only Dragnet's own
# SharePoint hosts may be rendered.
# =============================================================================

from unittest.mock import patch

from lifecycle.preview import allowed_sharepoint_url


def _with_hosts(site="https://dragnetnigeria.sharepoint.com/sites/orgos",
                compliance="https://dragnetnigeria.sharepoint.com/sites/everybody"):
    return patch.multiple("lifecycle.preview.settings",
                          sharepoint_site_url=site, compliance_site_url=compliance)


def test_tenant_sharepoint_urls_are_allowed():
    with _with_hosts():
        assert allowed_sharepoint_url(
            "https://dragnetnigeria.sharepoint.com/sites/everybody/Shared%20Documents/P.docx")
        assert allowed_sharepoint_url(
            "https://dragnetnigeria.sharepoint.com/_layouts/15/Doc.aspx?file=P.docx")


def test_other_hosts_are_refused():
    with _with_hosts():
        for url in ("https://evil.example.com/payload.docx",
                    "https://other-tenant.sharepoint.com/sites/x/P.docx",
                    "http://169.254.169.254/latest/meta-data/",
                    "file:///etc/passwd",
                    ""):
            assert not allowed_sharepoint_url(url), url


def test_a_lookalike_host_is_refused():
    with _with_hosts():
        assert not allowed_sharepoint_url(
            "https://dragnetnigeria.sharepoint.com.evil.example/P.docx")
