# Lifecycle tests run without SharePoint. Approval looks up the Document Register by code
# (lifecycle/router.py `_register_target`); a test that cares patches get_list_items itself.
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _empty_register_by_default():
    with patch("lifecycle.router.get_list_items", new=AsyncMock(return_value=[])):
        yield
