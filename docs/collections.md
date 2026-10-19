# Owned Collections — shared storage between apps

Apps on re-ddns run in their own containers. When one app produces files that
another app uses (the DICOM explorer downloads a series, the DICOM viewer
shows it), they share a **collection**: one directory tree every app with
access sees at the same path, on one host or across several hosts.

Three rules make it safe without any API on the data path:

| Rule | What it means |
|---|---|
| **write mine** | An app writes only inside its own *contribution*, `by-app/<app>/`. The kernel enforces it: the collection is mounted read-only, the app's folder read-write. |
| **read all** | Every app with access reads the union of all contributions. Isolation is per collection: need separation, use another collection. |
| **publish whole** | An *item* (one directory of files, with its bookkeeping hidden in `.item/`) appears only when complete. Files are written as `.part` and renamed; the item lives in `.tmp/` until `.item/manifest.json` is written last and the directory is renamed into place. |

```
<root>/<collection>/                     e.g. /Users/Shared/re-ddns/collections/dicom
  collection.json
  by-app/
    <app>/                               owner = the app's subdomain
      .tmp/                              publishes in progress (readers ignore it)
      <item-id>/<files...>               a published item: the payload, nothing else
      <item-id>/.item/manifest.json      its bookkeeping, hidden like .git/ (written last)
      <item-id>/.item/replica.json       present only on a copy fetched from another host
```

An app that opens an item directory as "a folder of files" sees only the
payload: a directory listing that keeps files (`is_file()`), a shell `*`
or Python's `glob` all skip the hidden `.item/`. Payload paths may not
start with `.item/`.

An item's identity is its **ref**, `<collection>:<owner>/<item-id>`, which
never contains a path. Apps hand refs to each other (DDNS Intent) and
resolve them locally.

## Declaring storage in the catalog

```json
"storage": [
  {"collection": "dicom", "access": "contribute", "env": "PUBLIC_DICOM_DIR", "env_target": "own"}
]
```

| Field | Values | Effect |
|---|---|---|
| `collection` | `a-z 0-9 -` | Created on first use under the collections root. |
| `access` | `read` / `contribute` (default) / `contribute-only` | `read`: the collection mounted read-only. `contribute`: plus the app's own folder read-write. `contribute-only`: only the own folder (the app cannot see other apps' items). |
| `env` | an env var name | Optional. Set for apps that predate the library: `env_target: root` points it at the collection, `env_target: own` at the app's own folder. |

Every app gets `DDNS_APP_ID=<subdomain>`; apps with storage also get
`DDNS_COLLECTIONS_ROOT=/data/collections` and `DDNS_COLLECTIONS_NODE_URL`.
Dev and Prod installs get the same mounts, and the Dev ↔ Prod switch keeps them.

## Using it from an app

```python
from reflex_ddns_auth.collections import Collection

video = Collection("video")                     # root and owner from the environment
if not video.has(vid):
    with video.publish(vid, kind="video.file", title=title, source=url,
                       meta={"duration": 212}) as item:
        with item.open("clip.webm") as fh:      # .part until closed
            download_into(fh)

for it in video.items(kind="video.file"):       # local items + items on other hosts
    it.ref, it.owner, it.local, it.home, it.meta

path = video.resolve(ref, progress=lambda done, total: ...)   # fetches from its home host if needed
```

Resolution order, identical in Docker and on a laptop: root from
`DDNS_COLLECTIONS_ROOT`, then `~/.re-ddns/config.json` (`collections_root`),
then `/Users/Shared/re-ddns/collections` on macOS or
`$XDG_DATA_HOME/re-ddns/collections` elsewhere. Owner from `DDNS_APP_ID`,
then `Collection(app_id=...)`, then the Reflex `app_name` with `_` → `-`.
An app run with `poetry run` on the Mac therefore shares the tree with the
containers, as the same owner, without configuration.

The library has no Reflex dependency; `reflex_ddns_auth.collections` imports
without Reflex installed.

## Several hosts

Writes never cross hosts: an app writes on the host it runs on, at local
disk speed. Readers on another host pull an item once, then read it from
local disk. Each re-ddns is a **node**:

| Setting (re-ddns environment) | Meaning |
|---|---|
| `RE_DDNS_NODE_NAME` | this host's name; `docker_restart.sh` uses the Mac's hostname |
| `RE_DDNS_PEERS` | `name=url,name=url` of the other hosts' re-ddns, e.g. `mac-b=http://192.168.1.20` |
| `RE_DDNS_NODE_TOKEN` | shared secret all nodes present to each other (header `X-Re-DDNS-Node-Token`) |
| `COLLECTIONS_REPLICA_MAX_BYTES` | cap on fetched copies per host; the oldest are evicted (0 = unlimited) |
| `COLLECTIONS_ROOT` | the host folder (default `/Users/Shared/re-ddns/collections`) |

Peers can also be set at runtime: `PUT /api/collections/_peers {"peers": {...}}`
(kept in `collections_peers.json` in the data volume). Requests to a peer carry
`Host: home.<zone>`, so the peer's nginx routes them to its re-ddns on port 80.

| Endpoint | Role |
|---|---|
| `GET /api/collections` | node name, peers (reachable?), collections and their contributions |
| `GET /api/collections/<c>/items?scope=all\|local\|remote&kind=` | the index; `remote` items carry their `home` |
| `POST /api/collections/<c>/fetch {"ref"}` | copy an item from its home host into the local tree (a replica); idempotent |
| `GET /api/collections/<c>/fetch-status?ref=` | bytes done / total while a fetch runs |
| `GET /api/collections/<c>/by-app/<app>/<item>/manifest.json`, `.../files/<path>` | what a home host serves to peers (token required; replicas are never served on); the manifest is read from the item's `.item/` |
| `GET/DELETE /api/collections/_contributions/<app>` | an app's folders, for uninstall ("also delete data") |
| `POST /api/collections/_gc` | drop replicas their home no longer publishes, then enforce the cap |

Speeds, by construction:

| Situation | Speed |
|---|---|
| another container on the same host reads | local disk |
| another host opens an item the first time | one LAN connection |
| that host opens it again | local disk |
| any app writes | local disk |

## What joining a collection costs an app

The two DICOM apps show the real size of the change:

- **A reader (DICOM Viewer): no code.** The catalog entry declares
  `{"collection": "dicom", "access": "read", "env": "PUBLIC_DICOM_DIR"}`; the
  app gets the collection mounted read-only at `/data/collections/dicom` and
  its existing folder browser starts there. Items are plain folders:
  `by-app/dicom-data-explorer/<SeriesInstanceUID>/*.dcm`; the viewer's scan
  never meets the bookkeeping because it lives in the hidden `.item/`.
- **A writer (DICOM Data Explorer): one dependency and one block.**
  `reflex-ddns-auth = {path = "../reflex_ddns_auth", develop = true}` in
  `pyproject.toml`, and the download loop writes into
  `with Collection("dicom").publish(uid, kind="dicom.series", ...) as series:`
  (`series.path` instead of a hand-made directory, `dicom.has(uid)` to skip a
  series already there, `dicom.ref(uid)` kept in the history). About thirty
  lines changed in one file. In return the series is invisible to other apps
  until every file is in place, and it can be found on other hosts by its ref.

Everything beyond that (a list of the collection's items in the viewer, a
"Open in Viewer" button through DDNS Intent, fetching from another host with
a progress bar) is optional product work on top, not part of joining.

Downloads made before the collection existed (`/Users/Shared/DICOM`) are not
items; download them again with the explorer, or publish them with the
library under the explorer's owner.

## Limits worth knowing

- Items are immutable. To change one, publish a new item (`derived_from` keeps the lineage).
- Another app's contribution is untrusted input. The library never follows symlinks out of an item and validates every ref segment.
- The node serves only items whose home it is; a copy is never passed on to a third host.
- On Linux hosts set `HOST_UID`/`HOST_GID` (the restart script does) so folders the node creates belong to you.
- Without `RE_DDNS_NODE_TOKEN` the peer endpoints are open on the LAN; set one on every node.
