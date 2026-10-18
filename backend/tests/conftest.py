import os

# Starlette's TestClient sends `Host: testserver`; production defaults only allow loopback names.
# Must be set before `app.main` is imported, because importing it builds the default settings.
os.environ.setdefault("NODECRAFT_ALLOWED_HOSTS", "testserver,127.0.0.1,localhost,[::1]")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(f"sqlite:///{tmp_path / 'test.db'}")) as c:
        yield c
