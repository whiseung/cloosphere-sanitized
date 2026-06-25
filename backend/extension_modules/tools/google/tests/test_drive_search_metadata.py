"""drive_search 메타데이터(modifiedTime/owner/location) 보강 테스트."""

from __future__ import annotations

import json

from extension_modules.tools.google.inprocess import drive as drive_mod
from extension_modules.tools.google.inprocess.drive import make_drive_search


async def test_search_returns_metadata_and_location(monkeypatch):
    captured = []

    async def fake_api(method, path, user_id, host, params):
        captured.append(params)
        if "sharedWithMe" in params.get("q", ""):
            return {
                "files": [
                    {
                        "id": "s1",
                        "name": "shared.doc",
                        "mimeType": "application/vnd.google-apps.document",
                    }
                ]
            }
        return {
            "files": [
                {
                    "id": "m1",
                    "name": "mine.doc",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-08T00:00:00Z",
                    "owners": [{"displayName": "Me"}],
                    "ownedByMe": True,
                },
                {
                    "id": "d1",
                    "name": "team.doc",
                    "mimeType": "application/vnd.google-apps.document",
                    "driveId": "drv1",
                },
            ]
        }

    monkeypatch.setattr(drive_mod, "call_google_api", fake_api)

    raw = await make_drive_search("u1").coroutine(q="fullText contains 'x'")
    data = json.loads(raw)
    by_id = {r["id"]: r for r in data["results"]}

    assert by_id["m1"]["location"] == "my_drive"
    assert by_id["m1"]["modifiedTime"] == "2026-06-08T00:00:00Z"
    assert by_id["m1"]["owner"] == "Me"
    assert by_id["d1"]["location"] == "shared_drive"
    assert by_id["s1"]["location"] == "shared_with_me"
    assert by_id["s1"]["owner"] is None

    assert any("modifiedTime" in p.get("fields", "") for p in captured)
    assert any("ownedByMe" in p.get("fields", "") for p in captured)
    assert any("driveId" in p.get("fields", "") for p in captured)
