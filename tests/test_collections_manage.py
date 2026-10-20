"""What the App Store's storage page uses: usage, the index, item details, previews,
deleting, the replica cap, quotas and imports.  All of it needs the admin token."""

import json
import os
import time

import pytest
from starlette.testclient import TestClient

from re_ddns.api import collections_api as ca
from test_collections_api import Cluster, publish, run

from reflex_ddns_auth.collections import Collection, QuotaExceeded  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    for name in ("DDNS_APP_ID", "DDNS_COLLECTIONS_NODE_URL", "RE_DDNS_API_URL"):
        monkeypatch.delenv(name, raising=False)
    cl = Cluster(tmp_path)
    for name, node in cl.nodes.items():
        node.settings_file = tmp_path / f"{name}-settings.json"
    return cl


def _get(cluster, name, path, **params):
    async def go():
        async with cluster.admin(name) as c:
            r = await c.get(path, params=params)
            assert r.status_code == 200, r.text
            return r.json()

    return run(go())


def _status(cluster, name, method, path, admin=True, **kw):
    async def go():
        async with (cluster.admin(name) if admin else cluster.client(name)) as c:
            return (await c.request(method, path, **kw)).status_code

    return run(go())


# -- every page endpoint is admin-only --------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/collections/_usage"), ("GET", "/api/collections/_index"),
    ("GET", "/api/collections/_item?ref=video:a/b"), ("GET", "/api/collections/_thumb?ref=video:a/b"),
    ("GET", "/api/collections/_settings"), ("PUT", "/api/collections/_settings"),
    ("POST", "/api/collections/_import"), ("POST", f"/api/collections/_import/{'0' * 32}/finish"),
    ("PUT", f"/api/collections/_import/{'0' * 32}/files/x"), ("DELETE", f"/api/collections/_import/{'0' * 32}"),
    ("DELETE", "/api/collections/video/by-app/a/b"),
])
def test_page_endpoints_need_admin(cluster, method, path):
    assert _status(cluster, "a", method, path, admin=False, json={}) == 401


# -- usage and the index ------------------------------------------------------------

def test_usage_index_filters_and_remote(cluster):
    a = cluster.nodes["a"]
    publish(cluster.collection("a", "downloader"), "clip1", data=b"x" * 100)
    publish(cluster.collection("a", "downloader"), "clip2", data=b"y" * 10, kind="video.short")
    publish(cluster.collection("a", "converter"), "mp4", data=b"z" * 50)
    publish(cluster.collection("a", "explorer", "dicom"), "1.2.3", data=b"d" * 30, kind="dicom.series")
    far = publish(cluster.collection("b", "downloader"), "far-away", data=b"f" * 7)
    (a.root / "video" / "by-app" / "downloader" / ".tmp" / "half.1.ab").mkdir(parents=True)
    (a.root / "video" / "by-app" / "downloader" / ".tmp" / "half.1.ab" / "f.part").write_bytes(b"p" * 5)

    usage = _get(cluster, "a", "/api/collections/_usage")
    assert usage["node"] == "a" and usage["disk"]["total"] > 0 and usage["replica_cap"] == 0
    video = next(c for c in usage["collections"] if c["name"] == "video")
    assert video["items"] == 3 and video["bytes"] == 101 + 11 + 51 and video["staging_bytes"] == 5
    assert [o["owner"] for o in video["owners"]] == ["converter", "downloader"]

    def refs(**params):
        return [i["ref"] for i in _get(cluster, "a", "/api/collections/_index", **params)["items"]]

    assert set(refs(location="here")) == {"video:downloader/clip1", "video:downloader/clip2",
                                          "video:converter/mp4", "dicom:explorer/1.2.3"}
    assert refs(collection="video", location="all", sort="largest") == [
        "video:downloader/clip1", "video:converter/mp4", "video:downloader/clip2", far]
    assert refs(location="remote") == [far]
    assert refs(kind="video.short") == ["video:downloader/clip2"]
    assert refs(owner="converter") == ["video:converter/mp4"]
    assert refs(q="CLIP2") == ["video:downloader/clip2"] and refs(q="far") == [far]
    assert refs(q="clip owner-nobody") == []
    page = _get(cluster, "a", "/api/collections/_index", location="here", sort="title", limit=2, offset=1)
    assert [i["id"] for i in page["items"]] == ["clip1", "clip2"] and page["total"] == 4
    facets = _get(cluster, "a", "/api/collections/_index")["facets"]
    assert {f["value"]: f["items"] for f in facets["kinds"]} == {"dicom.series": 1, "video.file": 3, "video.short": 1}
    assert _status(cluster, "a", "GET", "/api/collections/_index", params={"location": "x"}) == 400
    assert _status(cluster, "a", "GET", "/api/collections/_index", params={"sort": "x"}) == 400


def test_index_follows_the_tree(cluster, tmp_path):
    a = cluster.nodes["a"]
    col = cluster.collection("a", "downloader")
    assert a.index.sync()["changed"] == 0
    publish(col, "one")
    assert a.index.sync()["changed"] == 1
    assert a.index.sync()["changed"] == 0                       # nothing moved: nothing re-read
    publish(col, "two")
    col.remove("one")
    a.index.sync()
    assert [r["id"] for r in a.index.query()[0]] == ["two"]
    # a full pass catches what directory times would miss
    m = col.own_dir / "two" / ca.META_DIR / ca.MANIFEST_NAME
    data = json.loads(m.read_text())
    data["title"] = "Renamed in place"
    m.write_text(json.dumps(data))
    a.index.sync(full=True)
    assert a.index.get("video:downloader/two")["title"] == "Renamed in place"
    # the index is disposable: a corrupt file is rebuilt from the manifests
    path = tmp_path / "idx.sqlite"
    path.write_bytes(b"not a database" * 100)
    n = ca.Node(a.root, "a", index_file=path)
    n.index.sync()
    assert [r["id"] for r in n.index.query()[0]] == ["two"]


def test_index_sees_a_revision_at_once(cluster):
    """An app revising its own item in place (ReflexGrid saving a workbook): the next quick sync
    re-reads it, so the storage page shows the new size and title without waiting for a full pass."""
    a = cluster.nodes["a"]
    col = cluster.collection("a", "grid", "spreadsheets")
    publish(col, "book1", kind="spreadsheet.workbook")
    a.index.sync()
    with col.revise("book1", title="Q3 plan") as rev:
        with rev.open("f0.bin") as fh:
            fh.write(b"x" * 1000)
    assert a.index.sync()["changed"] == 1
    row = a.index.get("spreadsheets:grid/book1")
    assert row["title"] == "Q3 plan" and row["bytes"] == 1000
    assert _get(cluster, "a", "/api/collections/spreadsheets/quota/grid")["used"] == 1000


def test_item_details_and_lineage(cluster):
    col = cluster.collection("a", "downloader")
    parent = publish(col, "orig")
    conv = cluster.collection("a", "converter")
    with conv.publish("small", kind="video.file", title="Smaller", derived_from=[parent, "video:gone/x"]) as item:
        with item.open("s.mp4") as fh:
            fh.write(b"s")
    child = conv.ref("small")

    p = _get(cluster, "a", "/api/collections/_item", ref=parent)
    assert p["derived_into"] == [{"ref": child, "title": "Smaller", "kind": "video.file", "owner": "converter"}]
    assert p["host_path"] == "/host/a/video/by-app/downloader/orig" and p["manifest"]["files"]
    c = _get(cluster, "a", "/api/collections/_item", ref=child)
    assert c["derived_from_items"] == [
        {"ref": parent, "title": "orig", "kind": "video.file", "here": True},
        {"ref": "video:gone/x", "title": "", "kind": "", "here": False},
    ]
    far = publish(cluster.collection("b", "downloader"), "far")
    remote = _get(cluster, "a", "/api/collections/_item", ref=far)
    assert remote["home"] == "b" and remote["local"] is False and remote["manifest"]["files"]
    assert _status(cluster, "a", "GET", "/api/collections/_item", params={"ref": "video:x/nope"}) == 404
    assert _status(cluster, "a", "GET", "/api/collections/_item", params={"ref": "bad"}) == 400


# -- previews -------------------------------------------------------------------

def test_previews_local_replica_and_remote(cluster):
    col_b = cluster.collection("b", "downloader")
    with col_b.publish("thumbed", kind="video.file") as item:
        with item.open("v.mp4") as fh:
            fh.write(b"v" * 10)
        item.set_thumbnail(PNG)
    with col_b.publish("picture", kind="image.file") as item:
        with item.open("p.png") as fh:
            fh.write(PNG)
    with col_b.publish("fake", kind="image.file") as item:
        with item.open("p.png") as fh:
            fh.write(b"<svg onload=alert(1)>")
    publish(col_b, "plain")

    async def go():
        async with cluster.admin("b") as b, cluster.admin("a") as a, cluster.client("b") as anon_b:
            r = await b.get("/api/collections/_thumb", params={"ref": "video:downloader/thumbed"})
            assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
            assert (await b.get("/api/collections/_thumb", params={"ref": "video:downloader/picture"})).content == PNG
            assert (await b.get("/api/collections/_thumb", params={"ref": "video:downloader/fake"})).status_code == 404
            assert (await b.get("/api/collections/_thumb", params={"ref": "video:downloader/plain"})).status_code == 404
            # the peer endpoint needs the node token
            base = "/api/collections/video/by-app/downloader/thumbed/thumbnail"
            assert (await anon_b.get(base)).status_code == 401
            # another host shows the preview of an item it has not copied
            r = await a.get("/api/collections/_thumb", params={"ref": "video:downloader/thumbed"})
            assert r.status_code == 200 and r.content == PNG
            r = await a.get("/api/collections/_thumb", params={"ref": "video:downloader/picture"})
            assert r.status_code == 200 and r.content == PNG
            # ... and a copy brings the thumbnail along
            assert (await a.post("/api/collections/video/fetch", json={"ref": "video:downloader/thumbed"})).status_code == 200

    run(go())
    rep = cluster.nodes["a"].root / "video" / "by-app" / "downloader" / "thumbed"
    assert (rep / ca.META_DIR / "thumbnail.png").read_bytes() == PNG
    rows = {r["id"]: r for r in cluster.nodes["b"].index.query()[0]} if cluster.nodes["b"].index.sync() else {}
    assert rows["thumbed"]["preview"] == "thumbnail" and rows["picture"]["preview"] == "primary"
    assert rows["plain"]["preview"] == ""


# -- deleting ------------------------------------------------------------------

def test_delete_item_and_replica(cluster):
    col = cluster.collection("a", "downloader")
    ref = publish(col, "doomed")
    far = publish(cluster.collection("b", "downloader"), "far")
    a = cluster.nodes["a"]
    a.index.sync()

    async def go():
        async with cluster.admin("a") as c:
            assert (await c.post("/api/collections/video/fetch", json={"ref": far})).status_code == 200
            r = await c.delete("/api/collections/video/by-app/downloader/doomed")
            assert r.json() == {"removed": ref, "replica": False}
            r = await c.delete("/api/collections/video/by-app/downloader/far")
            assert r.json() == {"removed": far, "replica": True}
            assert (await c.delete("/api/collections/video/by-app/downloader/doomed")).status_code == 404
            assert (await c.delete("/api/collections/video/by-app/..%2Fx/doomed")).status_code in (400, 404)

    run(go())
    assert not (col.own_dir / "doomed").exists() and a.index.get(ref) is None
    assert list((col.own_dir / ca.TMP_DIR).iterdir()) == []
    assert (cluster.nodes["b"].root / "video" / "by-app" / "downloader" / "far").exists()   # its home keeps it


# -- the replica cap and quotas -----------------------------------------------------

def test_settings_replica_cap_and_quota(cluster):
    a = cluster.nodes["a"]
    r1 = publish(cluster.collection("b", "downloader"), "r1", data=b"1" * 100)
    r2 = publish(cluster.collection("b", "downloader"), "r2", data=b"2" * 100)

    async def go():
        async with cluster.admin("a") as c:
            for ref in (r1, r2):
                assert (await c.post("/api/collections/video/fetch", json={"ref": ref})).status_code == 200
            s = (await c.put("/api/collections/_settings", json={"replica_max_bytes": 150})).json()
            assert s["replica_max_bytes"] == 150 and s["replica_max_bytes_set"] and len(s["evicted"]) == 1
            s = (await c.put("/api/collections/_settings", json={"replica_max_bytes": None})).json()
            assert s["replica_max_bytes"] == 0 and not s["replica_max_bytes_set"]       # back to the env value
            assert (await c.put("/api/collections/_settings", json={"replica_max_bytes": -1})).status_code == 400
            s = (await c.put("/api/collections/_settings",
                             json={"quota": {"collection": "video", "owner": "downloader", "bytes": 120}})).json()
            assert s["quotas"] == {"video": {"downloader": 120}}
            assert (await c.put("/api/collections/_settings",
                                json={"quota": {"collection": "Bad", "owner": "x", "bytes": 1}})).status_code == 400
        async with cluster.client("a") as app:          # what the library asks, without the admin token
            q = (await app.get("/api/collections/video/quota/downloader")).json()
            assert q == {"collection": "video", "owner": "downloader", "limit": 120, "used": 0}

    run(go())
    # the library on host a respects it (replicas never count)
    app = ca.build_router(a)
    from fastapi import FastAPI
    fapi = FastAPI()
    fapi.include_router(app)
    http = TestClient(fapi, base_url="http://re-ddns")
    col = Collection("video", app_id="downloader", root=a.root, node_url="http://re-ddns", http=http)
    publish(col, "fits", data=b"f" * 99)                          # 100 bytes of 120
    with pytest.raises(QuotaExceeded):
        publish(col, "too-big", data=b"t" * 30)
    with pytest.raises(QuotaExceeded):
        a.set_quota("video", "downloader", 100)
        col.publish("no-room", kind="video.file").__enter__()
    a.set_quota("video", "downloader", 0)
    assert a.quotas() == {}
    publish(col, "free-again", data=b"t" * 30)


# -- importing a user's own files ------------------------------------------------------

def test_import_publishes_as_user(cluster):
    a = cluster.nodes["a"]

    async def go():
        async with cluster.admin("a") as c:
            assert (await c.post("/api/collections/_import", json={"collection": "dicom", "kind": "DICOM"})).status_code == 400
            assert (await c.post("/api/collections/_import", json={"collection": "Bad"})).status_code == 400
            up = (await c.post("/api/collections/_import",
                               json={"collection": "dicom", "kind": "dicom.series", "title": "CT 胸部 2024",
                                     "meta": {"Modality": "CT"}})).json()
            assert up["owner"] == "_user" and len(up["upload"]) == 32
            base = f"/api/collections/_import/{up['upload']}"
            assert (await c.put(f"{base}/files/a.dcm", content=b"a" * 10)).json() == {"path": "a.dcm", "bytes": 10}
            assert (await c.put(f"{base}/files/sub/b.dcm", content=b"b" * 5)).status_code == 200
            assert (await c.put(f"{base}/files/..%2Fescape", content=b"x")).status_code in (400, 404)
            assert (await c.put(f"{base}/files/.item/manifest.json", content=b"x")).status_code == 400
            entry = (await c.post(f"{base}/finish")).json()
            assert (await c.post(f"{base}/finish")).status_code == 404               # gone once published
            empty = (await c.post("/api/collections/_import", json={"collection": "dicom"})).json()
            assert (await c.post(f"/api/collections/_import/{empty['upload']}/finish")).status_code == 400
            assert (await c.delete(f"/api/collections/_import/{empty['upload']}")).json() == {"discarded": empty["upload"]}
            assert (await c.post(f"/api/collections/_import/{'f' * 32}/finish")).status_code == 404
            return entry

    entry = run(go())
    assert entry["owner"] == "_user" and entry["kind"] == "dicom.series" and entry["title"] == "CT 胸部 2024"
    assert entry["ref"].startswith("dicom:_user/") and entry["id"].endswith("-CT-2024") and entry["bytes"] == 15
    item = a.root / "dicom" / "by-app" / "_user" / entry["id"]
    manifest = json.loads((item / ca.META_DIR / ca.MANIFEST_NAME).read_text())
    assert manifest["files"] == [{"path": "a.dcm", "bytes": 10}, {"path": "sub/b.dcm", "bytes": 5}]
    assert manifest["meta"] == {"Modality": "CT"} and manifest["producer"] == {"app": "_user", "host": "a"}
    assert sorted(p.name for p in (item / ca.META_DIR).iterdir()) == [ca.MANIFEST_NAME]
    # any app reading the collection sees it, through the same library
    [it] = Collection("dicom", app_id="dicom-viewer", root=a.root).items(remote=False)
    assert it.ref == entry["ref"] and it.owner == "_user" and it.local


def test_import_respects_the_user_quota_and_gc_drops_stale_uploads(cluster):
    a = cluster.nodes["a"]
    a.set_quota("docs", "_user", 10)

    async def go():
        async with cluster.admin("a") as c:
            up = (await c.post("/api/collections/_import", json={"collection": "docs"})).json()
            base = f"/api/collections/_import/{up['upload']}"
            assert (await c.put(f"{base}/files/ok.txt", content=b"1" * 8)).status_code == 200
            assert (await c.put(f"{base}/files/big.txt", content=b"2" * 8)).status_code == 409
            assert (await c.post(f"{base}/finish")).status_code == 200                # 8 bytes fit
            stale = (await c.post("/api/collections/_import", json={"collection": "docs"})).json()
            return stale["upload"]

    upload = run(go())
    staging = a.root / "docs" / "by-app" / "_user" / ca.TMP_DIR / f"{ca.IMPORT_PREFIX}{upload}"
    old = time.time() - ca.IMPORT_MAX_AGE - 60
    os.utime(staging, (old, old))
    res = run(a.gc())
    assert res["stale_staging"] == [f"docs/by-app/_user/.tmp/{ca.IMPORT_PREFIX}{upload}"] and not staging.exists()
