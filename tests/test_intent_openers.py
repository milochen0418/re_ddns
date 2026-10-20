"""``GET /api/intent/openers?kind=``: the intent actions that open a collection item kind."""

import asyncio

import httpx
from fastapi import FastAPI

from re_ddns.api import intent_registry

CATALOG = {
    "dicom-viewer": {
        "dicom.open-series": {"title": "Open series", "route": "/intent/dicom-open-series",
                              "params": {"ref": {"type": "str", "required": True}}, "accepts": ["dicom.series"]},
        "dicom.annotate": {"title": "Annotate", "route": "/intent/dicom-annotate", "accepts": ["dicom.series", "dicom.seg"]},
    },
    "dicom-data-explorer": {
        "dicom.fetch-series": {"title": "Fetch", "route": "/intent/dicom-fetch-series", "params": {}},
    },
    "odd": {"x.y": "not a dict", "z.w": {"accepts": "dicom.series"}},
}


def test_openers_in():
    got = intent_registry.openers_in(CATALOG, "dicom.series")
    assert got == [
        {"app": "dicom-viewer", "action": "dicom.annotate", "title": "Annotate", "route": "/intent/dicom-annotate"},
        {"app": "dicom-viewer", "action": "dicom.open-series", "title": "Open series",
         "route": "/intent/dicom-open-series"},
    ]
    assert [o["action"] for o in intent_registry.openers_in(CATALOG, "dicom.seg")] == ["dicom.annotate"]
    assert intent_registry.openers_in(CATALOG, "video.file") == []


def test_openers_endpoint(monkeypatch):
    async def fake_catalog():
        return CATALOG

    monkeypatch.setattr(intent_registry, "_catalog", fake_catalog)
    app = FastAPI()
    app.include_router(intent_registry.router)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://re-ddns") as c:
            return (await c.get("/api/intent/openers", params={"kind": "dicom.series"})).json()

    body = asyncio.run(go())
    assert body["kind"] == "dicom.series" and [o["app"] for o in body["openers"]] == ["dicom-viewer", "dicom-viewer"]
