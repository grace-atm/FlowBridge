import asyncio
import io
import zipfile
from collections.abc import Callable, Iterable

import httpx
import pytest


@pytest.fixture
def make_zip() -> Callable[[Iterable[tuple[str | zipfile.ZipInfo, bytes]]], bytes]:
    def build(entries: Iterable[tuple[str | zipfile.ZipInfo, bytes]]) -> bytes:
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries:
                archive.writestr(name, content)
        return result.getvalue()

    return build


@pytest.fixture(autouse=True)
def no_environment_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture
def mock_client():
    clients = []

    def build(handler, **kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    yield build
    for client in clients:
        asyncio.run(client.aclose())
