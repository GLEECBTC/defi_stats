#!/usr/bin/env python3
from fastapi.testclient import TestClient
import pytest

from lib import dex_version as dex_version_lib
from main import app
import routes.dex as dex_route
import util.memcache as memcache


class DummyReleaseClient:
    def __init__(self, tag_name="0.9.3", html_url="https://example.com"):
        self.tag_name = tag_name
        self.html_url = html_url

    def get_latest_release(self):
        return {"tag_name": self.tag_name, "html_url": self.html_url}


@pytest.mark.parametrize(
    "tag,expected_status",
    [
        ("0.9.4", "recommended"),
        ("v0.10.0", "required"),
        ("1.2", "required"),
    ],
)
def test_refresh_sets_expected_status(monkeypatch, tag, expected_status):
    captured = {}

    def _set_cache(data):
        captured["data"] = data

    monkeypatch.setattr(memcache, "set_dex_version", _set_cache)
    monkeypatch.setattr(memcache, "get_dex_version", lambda: None)
    service = dex_version_lib.DexVersionService(client=DummyReleaseClient(tag_name=tag))

    payload = service.refresh()

    assert payload is not None
    assert captured["data"]["data"]["status"] == expected_status


def test_get_version_info_returns_cached(monkeypatch):
    cached = {"data": {"status": "recommended"}}
    monkeypatch.setattr(memcache, "get_dex_version", lambda: cached)
    service = dex_version_lib.DexVersionService(client=DummyReleaseClient())

    result = service.get_version_info()

    assert result == cached["data"]


def test_dex_version_endpoint_success(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        dex_route.service,
        "get_version_info",
        lambda: {
            "status": "recommended",
            "new_version": "0.9.3",
            "changelog": "https://example.com/changelog",
            "download_url": "https://example.com",
        },
    )

    resp = client.post("/api/v3/dex_version")

    assert resp.status_code == 200
    assert resp.json()["status"] == "recommended"


def test_dex_version_endpoint_failure(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(dex_route.service, "get_version_info", lambda: None)

    resp = client.post("/api/v3/dex_version")

    assert resp.status_code == 503
