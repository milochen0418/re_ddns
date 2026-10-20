"""Two re-ddns nodes talking to each other in-process (httpx ASGITransport).

Node ``a`` and node ``b`` have separate roots.  An app on ``a`` publishes with
the ``reflex_ddns_auth.collections`` library; ``b`` lists it as remote, fetches
it into a replica, and garbage-collects it once ``a`` deletes it.
"""

import asyncio
import json
import os
import time

import httpx
import pytest
from fastapi import FastAPI

from re_ddns.api import collections_api as ca
from re_ddns.api.admin_auth import ADMIN_HEADER
from re_ddns.api.collections_api import Node, StorageSpec, build_router, storage_binds

pytest.importorskip("reflex_ddns_auth.collections")
from reflex_ddns_auth.collections import Collection  # noqa: E402

from conftest import ADMIN_TOKEN  # noqa: E402

TOKEN = "s3cret"


def run(coro):
    return asyncio.run(coro)


class Cluster:
    def __init__(self, tmp_path, token=TOKEN, names=("a", "b")):
        self.apps: dict[str, FastAPI] = {}
        self.nodes: dict[str, Node] = {}

        def factory(url: str) -> httpx.AsyncClient:
            headers = {ca.TOKEN_HEADER: token} if token else {}
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.apps[url]), base_url=url, headers=headers)

        for name in names:
            node = Node(
                tmp_path / name, name, host_root=f"/host/{name}", token=token, cache_seconds=0,
                client_factory=factory, peers_file=tmp_path / f"{name}-peers.json",
            )
            app = FastAPI()
            app.include_router(build_router(node))
            self.nodes[name] = node
            self.apps[f"http://{name}"] = app
        for name in names:
            self.nodes[name].set_peers({n: f"http://{n}" for n in names if n != name})

    def client(self, name: str, token: str | None = None, admin: bool = False) -> httpx.AsyncClient:
        headers = {ca.TOKEN_HEADER: token} if token else {}
        if admin:
            headers[ADMIN_HEADER] = ADMIN_TOKEN
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.apps[f"http://{name}"]), base_url=f"http://{name}", headers=headers
        )

    def admin(self, name: str) -> httpx.AsyncClient:
        """What the App Store holds: the admin token (no node token)."""
        return self.client(name, admin=True)

    def collection(self, name: str, owner: str, cname: str = "video") -> Collection:
        return Collection(cname, app_id=owner, root=self.nodes[name].root)


def publish(col: Collection, item_id: str, data: bytes = b"bytes", kind: str = "video.file", files: int = 1) -> str:
    with col.publish(item_id, kind=kind, title=item_id) as item:
        for i in range(files):
            with item.open(f"f{i}.bin") as fh:
                fh.write(data + str(i).encode())
    return col.ref(item_id)


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    monkeypatch.delenv("DDNS_APP_ID", raising=False)
    monkeypatch.delenv("DDNS_COLLECTIONS_NODE_URL", raising=False)
    monkeypatch.delenv("RE_DDNS_API_URL", raising=False)
    return Cluster(tmp_path)


# -- index -----------------------------------------------------------------

def test_scopes_and_remote_index(cluster):
    ref = publish(cluster.collection("a", "downloader"), "one")

    async def go():
        async with cluster.client("a") as a, cluster.client("b") as b:
            local_a = (await a.get("/api/collections/video/items", params={"scope": "local"})).json()["items"]
            assert [i["ref"] for i in local_a] == [ref]
            assert local_a[0]["home"] == "a" and local_a[0]["local"] and not local_a[0]["replica"]
            remote_b = (await b.get("/api/collections/video/items", params={"scope": "remote"})).json()["items"]
            assert [i["ref"] for i in remote_b] == [ref]
            assert remote_b[0]["home"] == "a" and remote_b[0]["local"] is False
            assert remote_b[0]["manifest"]["files"] == [{"path": "f0.bin", "bytes": 6}]
            assert (await b.get("/api/collections/video/items", params={"scope": "local"})).json()["items"] == []
            assert [i["ref"] for i in (await b.get("/api/collections/video/items")).json()["items"]] == [ref]
            assert (await b.get("/api/collections/video/items", params={"kind": "nope"})).json()["items"] == []
            assert (await b.get("/api/collections/video/items", params={"scope": "bogus"})).status_code == 400
            assert (await b.get("/api/collections/Bad/items")).status_code == 400
            # the peer-to-peer scope needs the node token
            assert (await b.get("/api/collections/video/items", params={"scope": "authoritative"})).status_code == 401
        async with cluster.client("a", TOKEN) as peer:
            auth = (await peer.get("/api/collections/video/items", params={"scope": "authoritative"})).json()["items"]
            assert [i["ref"] for i in auth] == [ref]

    run(go())


def test_overview_and_peers(cluster):
    publish(cluster.collection("a", "downloader"), "one")

    async def go():
        async with cluster.client("b") as anon:
            # an app (no admin token) may look, but not change the peers
            assert (await anon.put("/api/collections/_peers", json={"peers": {}})).status_code == 401
        async with cluster.admin("b") as b:
            ov = (await b.get("/api/collections")).json()
            assert ov["node"] == "b" and ov["container_root"] == "/data/collections"
            assert ov["peers"] == {"a": {"url": "http://a", "reachable": True, "node": "a", "name_matches": True}}
            assert ov["collections"] == []
            assert (await b.get("/api/collections/_peers")).json() == {
                "node": "b", "peers": {"a": "http://a"}, "from_env": []}
            r = await b.put("/api/collections/_peers", json={"peers": {"a": "http://a", "nas": "https://nas"}})
            assert r.json()["peers"] == {"a": "http://a", "nas": "https://nas"}
            assert (await b.put("/api/collections/_peers", json={"peers": {"bad name": "http://x"}})).status_code == 400
            assert (await b.put("/api/collections/_peers", json={"peers": {"x": "ftp://x"}})).status_code == 400
        async with cluster.client("a") as a:
            ov = (await a.get("/api/collections")).json()
            assert ov["collections"] == [{"name": "video", "contributions": [
                {"owner": "downloader", "items": 1, "replicas": 0, "bytes": ov["collections"][0]["contributions"][0]["bytes"]}
            ]}]
            assert ov["collections"][0]["contributions"][0]["bytes"] > 6

    run(go())


# -- transfer --------------------------------------------------------------

def test_fetch_creates_replica_then_gc(cluster):
    col_a = cluster.collection("a", "downloader")
    ref = publish(col_a, "clip", data=b"x" * 5000, files=3)
    node_b = cluster.nodes["b"]

    async def go():
        async with cluster.client("b") as b:
            r = await b.post("/api/collections/video/fetch", json={"ref": ref})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["fetched"] and body["replica"] and body["home"] == "a" and body["bytes"] == 3 * 5001
            again = (await b.post("/api/collections/video/fetch", json={"ref": ref})).json()
            assert again["fetched"] is False and again["replica"] is True
            st = (await b.get("/api/collections/video/fetch-status", params={"ref": ref})).json()
            assert st["state"] == "done" and st["bytes_done"] == st["bytes_total"] == 3 * 5001
            assert (await b.get("/api/collections/video/items", params={"scope": "remote"})).json()["items"] == []
            local = (await b.get("/api/collections/video/items", params={"scope": "local"})).json()["items"]
            assert local[0]["replica"] is True and local[0]["home"] == "a" and local[0]["fetched_at"]
            assert (await b.get("/api/collections/video/fetch-status", params={"ref": "dicom:x/y"})).status_code == 400

    run(go())
    assert node_b.authoritative_items("video") == []      # a third host never pulls from a replica
    rep = node_b.root / "video" / "by-app" / "downloader" / "clip"
    src = cluster.nodes["a"].root / "video" / "by-app" / "downloader" / "clip"
    meta = rep / ca.META_DIR
    assert json.loads((meta / ca.REPLICA_NAME).read_text())["home"] == "a"
    for i in range(3):
        assert (rep / f"f{i}.bin").read_bytes() == (src / f"f{i}.bin").read_bytes()
    assert json.loads((meta / ca.MANIFEST_NAME).read_text()) == json.loads((src / ca.META_DIR / ca.MANIFEST_NAME).read_text())
    assert not (meta / ca.FETCH_INFO_NAME).exists()
    assert sorted(p.name for p in rep.iterdir() if p.is_file()) == ["f0.bin", "f1.bin", "f2.bin"]   # payload only
    assert list((rep.parent / ca.TMP_DIR).iterdir()) == []

    # the app-side library on host b sees a local replica
    it = {i.ref: i for i in cluster.collection("b", "converter").items(remote=False)}[ref]
    assert it.local and it.replica and it.home == "a" and it.primary is None and len(it.files) == 3

    # gc: the home deletes the item -> orphan replica removed; unknown home -> kept
    assert col_a.remove("clip")
    ghost = node_b.root / "video" / "by-app" / "ghost" / "it"
    (ghost / ca.META_DIR).mkdir(parents=True)
    (ghost / "f").write_bytes(b"1")
    (ghost / ca.META_DIR / ca.MANIFEST_NAME).write_text(json.dumps({"kind": "video.file", "bytes": 1, "files": [{"path": "f", "bytes": 1}]}))
    (ghost / ca.META_DIR / ca.REPLICA_NAME).write_text(json.dumps({"home": "nowhere"}))

    async def gc():
        async with cluster.client("b") as anon:
            assert (await anon.post("/api/collections/_gc")).status_code == 401
        async with cluster.admin("b") as b:
            return (await b.post("/api/collections/_gc")).json()

    res = run(gc())
    assert res["removed"] == [ref] and res["unknown_home"] == ["video:ghost/it"] and res["kept"] == []
    assert not rep.exists() and ghost.exists()


def test_gc_keeps_replicas_when_home_is_unreachable(cluster):
    ref = publish(cluster.collection("a", "downloader"), "clip")
    node_b = cluster.nodes["b"]

    async def go():
        async with cluster.client("b") as b:
            assert (await b.post("/api/collections/video/fetch", json={"ref": ref})).status_code == 200
        node_b.set_peers({"a": "http://unreachable"})
        cluster.apps["http://unreachable"] = FastAPI()      # answers 404 to everything
        async with cluster.admin("b") as b:
            return (await b.post("/api/collections/_gc")).json()

    res = run(go())
    assert res["kept"] == [ref] and res["removed"] == []
    assert (node_b.root / "video" / "by-app" / "downloader" / "clip" / ca.META_DIR / ca.MANIFEST_NAME).exists()


def test_replica_cap_evicts_oldest(cluster):
    col_a = cluster.collection("a", "downloader")
    r1 = publish(col_a, "old", data=b"o" * 100)
    r2 = publish(col_a, "new", data=b"n" * 100)
    node_b = cluster.nodes["b"]
    node_b.replica_max_bytes = 150

    async def go():
        async with cluster.client("b") as b:
            assert (await b.post("/api/collections/video/fetch", json={"ref": r1})).status_code == 200
            old_marker = node_b.root / "video" / "by-app" / "downloader" / "old" / ca.META_DIR / ca.REPLICA_NAME
            data = json.loads(old_marker.read_text())
            data["fetched_at"] = "2000-01-01T00:00:00+00:00"
            old_marker.write_text(json.dumps(data))
            assert (await b.post("/api/collections/video/fetch", json={"ref": r2})).status_code == 200

    run(go())
    refs = sorted(e["ref"] for e in node_b.replicas())
    assert refs == [r2]


def test_fetch_errors(cluster):
    async def go():
        async with cluster.client("b") as b:
            assert (await b.post("/api/collections/video/fetch", json={"ref": "video:downloader/nope"})).status_code == 404
            assert (await b.post("/api/collections/video/fetch", json={"ref": "dicom:x/y"})).status_code == 400
            assert (await b.post("/api/collections/video/fetch", json={"ref": "video:../x/y"})).status_code == 400
            assert (await b.post("/api/collections/video/fetch", json={"ref": "video:x/.tmp"})).status_code == 400

    run(go())


def test_fetch_status_while_fetching(cluster):
    node_b = cluster.nodes["b"]
    tmp = node_b.root / "video" / "by-app" / "o" / ca.TMP_DIR / "it.replica.ab12"
    (tmp / ca.META_DIR).mkdir(parents=True)
    (tmp / ca.META_DIR / ca.FETCH_INFO_NAME).write_text(json.dumps({"bytes_total": 100, "home": "a"}))
    (tmp / "f.bin.part").write_bytes(b"x" * 40)
    st = node_b.fetch_status("video:o/it")
    assert st["state"] == "fetching" and st["bytes_total"] == 100 and st["home"] == "a"
    assert 40 <= st["bytes_done"] < 100
    assert node_b.fetch_status("video:o/other")["state"] == "none"


def test_peer_endpoints_need_token_and_reject_traversal(cluster):
    ref = publish(cluster.collection("a", "downloader"), "t")
    base = "/api/collections/video/by-app/downloader/t"

    async def go():
        async with cluster.client("a") as anon, cluster.client("a", TOKEN) as peer:
            assert (await anon.get(f"{base}/manifest.json")).status_code == 401
            assert (await anon.get(f"{base}/files/f0.bin")).status_code == 401
            assert (await peer.get(f"{base}/manifest.json")).json()["kind"] == "video.file"
            assert (await peer.get(f"{base}/files/f0.bin")).content == b"bytes0"
            assert (await peer.get(f"{base}/files/.item/manifest.json")).status_code in (400, 404)
            assert (await peer.get(f"{base}/files/..%2Fmanifest.json")).status_code in (400, 404)
            assert (await peer.get("/api/collections/video/by-app/downloader/.tmp/manifest.json")).status_code == 400
            assert (await peer.get("/api/collections/video/by-app/..%2Fx/t/manifest.json")).status_code in (400, 404)
            assert (await peer.get(f"{base}/files/nope.bin")).status_code == 404
        # a replica is never served on to a third host
        async with cluster.client("b") as b:
            assert (await b.post("/api/collections/video/fetch", json={"ref": ref})).status_code == 200
        async with cluster.client("b", TOKEN) as peer_b:
            assert (await peer_b.get(f"{base}/manifest.json")).status_code == 404

    run(go())


def test_open_node_without_token_serves_peers(tmp_path, monkeypatch):
    monkeypatch.delenv("DDNS_APP_ID", raising=False)
    cl = Cluster(tmp_path, token="")
    ref = publish(cl.collection("a", "downloader"), "t")

    async def go():
        async with cl.client("b") as b:
            return (await b.post("/api/collections/video/fetch", json={"ref": ref})).status_code

    assert run(go()) == 200


# -- lifecycle & mounts ----------------------------------------------------

def test_contributions_and_remove(cluster):
    node = cluster.nodes["a"]
    node.ensure_contribution("video", "downloader")
    publish(cluster.collection("a", "downloader"), "x")
    publish(cluster.collection("a", "downloader", "documents"), "doc")
    assert node.contributions_of("Bad Owner") == []
    contribs = node.contributions_of("downloader")
    assert [c["collection"] for c in contribs] == ["documents", "video"]
    assert contribs[1]["path"] == "video/by-app/downloader"
    assert contribs[1]["host_path"] == "/host/a/video/by-app/downloader"
    assert contribs[1]["items"] == 1 and contribs[1]["replicas"] == 0 and contribs[1]["bytes"] > 6

    async def go():
        async with cluster.client("a") as anon:
            # an app cannot list or delete another app's contribution
            assert (await anon.get("/api/collections/_contributions/downloader")).status_code == 401
            assert (await anon.delete("/api/collections/_contributions/downloader")).status_code == 401
            bad = {ADMIN_HEADER: "wrong"}
            assert (await anon.delete("/api/collections/_contributions/downloader", headers=bad)).status_code == 401
        async with cluster.admin("a") as a:
            got = (await a.get("/api/collections/_contributions/downloader")).json()["contributions"]
            assert [c["collection"] for c in got] == ["documents", "video"]
            r = await a.delete("/api/collections/_contributions/downloader", params={"collection": "video"})
            assert r.json()["removed"] == ["video"]
            assert [c["collection"] for c in (await a.get("/api/collections/_contributions/downloader")).json()["contributions"]] == ["documents"]
            assert (await a.delete("/api/collections/_contributions/downloader")).json()["removed"] == ["documents"]
            assert (await a.get("/api/collections/_contributions/downloader")).json()["contributions"] == []

    run(go())
    assert not (node.root / "video" / "by-app" / "downloader").exists()
    assert (node.root / "video" / "collection.json").exists()      # the collection itself stays


def test_storage_binds(cluster):
    node = cluster.nodes["a"]
    binds, env = storage_binds(node, "dicom-viewer", [StorageSpec(collection="dicom", access="read", env="PUBLIC_DICOM_DIR")])
    assert binds == ["/host/a/dicom:/data/collections/dicom:ro"]
    assert env == [
        "PUBLIC_DICOM_DIR=/data/collections/dicom",
        "DDNS_APP_ID=dicom-viewer",
        "DDNS_NODE_NAME=a",
        "DDNS_COLLECTIONS_ROOT=/data/collections",
        "DDNS_COLLECTIONS_NODE_URL=http://re-ddns:8000",
    ]
    assert not (node.root / "dicom" / "by-app" / "dicom-viewer").exists()   # read access: no contribution

    binds, env = storage_binds(node, "dicom-data-explorer",
                               [StorageSpec(collection="dicom", env="PUBLIC_DICOM_DIR", env_target="own")])
    assert binds == [
        "/host/a/dicom:/data/collections/dicom:ro",
        "/host/a/dicom/by-app/dicom-data-explorer:/data/collections/dicom/by-app/dicom-data-explorer:rw",
    ]
    assert "PUBLIC_DICOM_DIR=/data/collections/dicom/by-app/dicom-data-explorer" in env
    assert (node.root / "dicom" / "by-app" / "dicom-data-explorer" / ca.TMP_DIR).is_dir()
    assert json.loads((node.root / "dicom" / "collection.json").read_text())["name"] == "dicom"

    binds, env = storage_binds(node, "scanner", [StorageSpec(collection="dicom", access="contribute-only")])
    assert binds == ["/host/a/dicom/by-app/scanner:/data/collections/dicom/by-app/scanner:rw"]

    binds, env = storage_binds(node, "plain", [])
    assert binds == [] and env == ["DDNS_APP_ID=plain", "DDNS_NODE_NAME=a"]

    for bad in (StorageSpec(collection="Bad"), StorageSpec(collection="dicom", access="rw"),
                StorageSpec(collection="dicom", env="bad-name")):
        with pytest.raises(ValueError):
            storage_binds(node, "x", [bad])
    with pytest.raises(ValueError):
        storage_binds(node, "Bad Sub", [])


def test_peers_config(tmp_path):
    assert ca.parse_peers("mac-b=http://10.0.0.2/, nas = https://nas:443,,bad") == {
        "mac-b": "http://10.0.0.2", "nas": "https://nas:443",
    }
    n = Node(tmp_path / "r", "me", peers={"env": "http://e"}, peers_file=tmp_path / "p.json")
    assert n.peers == {"env": "http://e"}
    n.set_peers({"f": "http://f/", "me": "http://self"})
    assert n.peers == {"env": "http://e", "f": "http://f"}        # a node never peers with itself
    (tmp_path / "p.json").write_text(json.dumps({"peers": {"g": "http://g"}}))
    time.sleep(0.01)
    os.utime(tmp_path / "p.json", None)
    assert n.peers == {"env": "http://e", "g": "http://g"}         # file edits are picked up


def test_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLECTIONS_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("COLLECTIONS_HOST_ROOT", "/Users/Shared/re-ddns/collections")
    monkeypatch.setenv("RE_DDNS_NODE_NAME", "mac-a")
    monkeypatch.setenv("RE_DDNS_PEERS", "mac-b=http://192.168.1.20")
    monkeypatch.setenv("RE_DDNS_NODE_TOKEN", "t")
    monkeypatch.setenv("HOST_UID", "501")
    monkeypatch.setenv("HOST_GID", "")
    n = Node.from_env()
    assert n.root == tmp_path / "root" and n.host_root == "/Users/Shared/re-ddns/collections"
    assert n.name == "mac-a" and n.peers == {"mac-b": "http://192.168.1.20"} and n.token == "t"
    assert n.host_uid == 501 and n.host_gid is None
    assert n.peer_host_header == "home.reflex-ddns.com"
    client = n.peer_client("http://192.168.1.20")
    assert client.headers["host"] == "home.reflex-ddns.com" and client.headers[ca.TOKEN_HEADER.lower()] == "t"
