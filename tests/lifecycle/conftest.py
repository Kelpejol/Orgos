# Lifecycle tests run without SharePoint. Approval looks up the Document Register by code
# (lifecycle/router.py `_register_target`); a test that cares patches get_list_items itself.
#
# A document's file lives in a fake library (`library`): one file per link, which OrgOS reads
# and saves over in place (lifecycle/document_file.py). A test adds the files it needs.
from unittest.mock import AsyncMock, patch

import pytest

from lifecycle import document_file
from lifecycle.document_file import DocFile, NoFile


class FakeLibrary:
    """Files by link. Every save is a new version of the SAME file; nothing is ever copied."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.saves: list[tuple[str, bytes]] = []
        self.created: list[str] = []

    def add(self, url: str, data: bytes, name: str = "Document.docx") -> str:
        self.files[url] = {"name": name, "data": data, "version": 1}
        return url

    def _file(self, url: str) -> DocFile:
        entry = self.files[url]
        return DocFile(drive_id="drive", item_id=url, name=entry["name"], web_url=url,
                       ctag=f"ctag-{entry['version']}", parent_id="folder")

    async def locate(self, fields: dict) -> DocFile:
        url = fields.get("SharePointFileUrl") or document_file.stored_state(fields).get("item") or ""
        if url not in self.files:
            raise NoFile("There is no file yet.")
        return self._file(url)

    async def read(self, f: DocFile) -> bytes:
        return self.files[f.item_id]["data"]

    async def save(self, f: DocFile, data: bytes) -> DocFile:
        entry = self.files[f.item_id]
        entry["data"], entry["version"] = data, entry["version"] + 1
        self.saves.append((f.item_id, data))
        return self._file(f.item_id)

    async def rename(self, f: DocFile, name: str) -> DocFile:
        self.files[f.item_id]["name"] = name
        return self._file(f.item_id)

    async def create_new(self, filename: str, data: bytes) -> DocFile:
        url = self.add(f"https://x.sharepoint.com/New documents/{filename}", data, filename)
        self.created.append(url)
        return self._file(url)

    async def create_beside(self, f: DocFile, filename: str, data: bytes) -> DocFile:
        url = self.add(f"https://x.sharepoint.com/beside/{filename}", data, filename)
        self.created.append(url)
        return self._file(url)


@pytest.fixture(autouse=True)
def _empty_register_by_default():
    with patch("lifecycle.router.get_list_items", new=AsyncMock(return_value=[])):
        yield


@pytest.fixture(autouse=True)
def library():
    lib = FakeLibrary()
    with patch.object(document_file, "locate", new=lib.locate), \
         patch.object(document_file, "read", new=lib.read), \
         patch.object(document_file, "save", new=lib.save), \
         patch.object(document_file, "rename", new=lib.rename), \
         patch.object(document_file, "create_new", new=lib.create_new), \
         patch.object(document_file, "create_beside", new=lib.create_beside), \
         patch("lifecycle.router.latest_version_id", new=AsyncMock(return_value="before")), \
         patch("lifecycle.router.restore_drive_item_version", new=AsyncMock()):
        yield lib
