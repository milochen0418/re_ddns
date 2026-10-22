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

Every item also has a **kind** (`dicom.series`, `video.file`, ...): what it
holds, so that a reader knows what it gets and the storage page knows which
apps open it. See [Kinds](#kinds).

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

A producer may attach a **preview** while publishing; the storage page shows
it next to the item:

```python
with video.publish(vid, kind="video.file") as item:
    ...
    item.set_thumbnail(png_bytes)        # PNG, JPEG, WebP or GIF, 512 KB at most
```

It is kept in `.item/thumbnail.<ext>` with the bookkeeping (not part of the
payload), named by the manifest's `thumbnail`, and copied along with a
replica. An item whose `primary` file is a small image (up to 2 MB) needs no
thumbnail: the page shows that file.

### Items an app keeps editing

Most items never change once published. An item that is a document an app
keeps editing, such as a ReflexGrid workbook saved while people type, is
published once and from then on **revised** in place by its owner:

```python
with sheets.revise(book_id, title=title, meta=meta) as rev:
    with rev.open("book.xlsx") as fh:       # staged in .tmp until the block ends
        fh.write(data)
    rev.remove("book.xlsm")                 # left out of the item from now on
```

- Nothing changes until the block ends. Then each file is replaced with one
  rename (a reader opens the old or the new file, never half of one) and the
  manifest is rewritten last, with `revision` one higher (a manifest without
  one is revision 1) and `updated_at`. `Item.revision` and `Item.updated_at`
  show them, so a reader that caches an item can key it on `(ref, revision)`.
- Only the owner revises, on the host that holds the original; a copy fetched
  from another host is refused. A revision that makes the item bigger is
  checked against the quota like a publish.
- The owner's folder is touched at the end, so the storage page shows the new
  size and title at once.
- Copies other hosts fetched earlier are **not** refreshed: they keep the
  revision they were fetched at, and fetching an item while its home host is
  revising it can fail with a size mismatch (try again).

## Kinds

A kind is `<domain>.<type>`: two or more dot-separated segments of lowercase
letters and digits, single hyphens inside a segment, at most 64 characters
(`dicom.series`, `image.slide-deck`). The domain comes first so related kinds
sort together. `publish()` refuses any other spelling (`InvalidKind`), and so
do `@intent(accepts=...)` and the import of the storage page.

A kind is a promise about the payload. Before an app publishes a new kind,
add its row here, so that two apps never name one thing twice (`video.mp4`
next to `media.video`) and readers know which files and `meta` keys to expect:

| Kind | Payload | `meta` | Published by |
|---|---|---|---|
| `audio.file` | one audio file, the `primary`; from youtube-to-mp3 an MP3 named after the video, item id = `yt-<YouTube video id>`, `source` = the video's address, the video's thumbnail as the preview | `duration` (s); from youtube-to-mp3 also `format`, `youtube_id`, `channel`, `channel_url`, `license` (YouTube's licence text, e.g. Creative Commons), `upload_date` | youtube-to-mp3 |
| `dicom.series` | the `.dcm` files of one DICOM series; item id = SeriesInstanceUID (imports: a generated id) | `Collection`, `Modality`, `BodyPartExamined`, `ImageCount`, `SeriesDescription`, `SeriesDate`, each when known | dicom-data-explorer, imports |
| `document.markdown` | one Markdown document, the `primary`: `doc.md` (UTF-8); item id = the document's id in its link; revised in place while it is edited | `created_by_email`, `created_by_name` | md |
| `file.generic` | any files; promises nothing about them | free | imports |
| `spreadsheet.workbook` | one workbook, the `primary`: `book.xlsx`, or `book.xlsm` when it has macros; item id = the workbook's id in its link; revised in place while it is edited | `sheets`, `created_by_email`, `created_by_name`, `last_editor` | reflex-grid |

Planned for the apps that join next; the first one to publish a kind settles its row:

| Kind | Payload | `meta` |
|---|---|---|
| `video.file` | one video file, the `primary` | `duration` (s), `width`, `height` when known |
| `image.file` | one image file, the `primary` (its own preview) | `width`, `height` |
| `document.pdf` | one PDF, the `primary` | `pages` |

## Quotas

The storage page can give a contribution (one app in one collection, on this
host) a quota. Apps write straight to disk, so the node cannot stop a write
half-way; the library checks instead, when it can reach the node
(`GET /api/collections/<c>/quota/<app>` → `{"limit", "used"}`, open to apps):

- `publish()` does not start when the app's items already fill the quota;
- it does not finish when the new item would go over it: `QuotaExceeded`,
  and the `.tmp` copy stays, so `resume=True` can finish once there is room.

`used` counts the app's published items on this host; copies fetched from
other hosts and unfinished `.tmp` work do not count (copies have their own
cap, see [Several hosts](#several-hosts)). Without a node (a laptop run)
there is no quota. Imports into `_user` are checked by the node itself.

## Several hosts

Writes never cross hosts: an app writes on the host it runs on, at local
disk speed. Readers on another host pull an item once, then read it from
local disk. Each re-ddns is a **node**:

| Setting (re-ddns environment) | Meaning |
|---|---|
| `RE_DDNS_NODE_NAME` | this host's name; `docker_restart.sh` uses the Mac's hostname |
| `RE_DDNS_PEERS` | `name=url,name=url` of the other hosts' re-ddns, e.g. `mac-b=http://192.168.1.20` |
| `RE_DDNS_NODE_TOKEN` | shared secret all nodes present to each other (header `X-Re-DDNS-Node-Token`) |
| `COLLECTIONS_REPLICA_MAX_BYTES` | cap on fetched copies per host; the oldest are evicted (0 = unlimited). The storage page can override it |
| `COLLECTIONS_ROOT` | the host folder (default `/Users/Shared/re-ddns/collections`) |

Peers can also be set at runtime, on the storage page or with
`PUT /api/collections/_peers {"peers": {...}}` (kept in `collections_peers.json`
in the data volume; peers from `RE_DDNS_PEERS` stay). Requests to a peer carry
`Host: home.<zone>`, so the peer's nginx routes them to its re-ddns on port 80.

What apps and peers use (the storage page's endpoints are listed under
[Managing it](#managing-it-the-storage-page)):

| Endpoint | Who | Role |
|---|---|---|
| `GET /api/collections` | anyone | node name, peers (reachable?), collections and their contributions |
| `GET /api/collections/<c>/items?scope=all\|local\|remote&kind=` | apps | the items; `remote` ones carry their `home` |
| `POST /api/collections/<c>/fetch {"ref"}` | apps | copy an item from its home host into the local tree (a replica); idempotent |
| `GET /api/collections/<c>/fetch-status?ref=` | apps | bytes done / total while a fetch runs |
| `GET /api/collections/<c>/quota/<app>` | apps | `{"limit", "used"}` for `publish()` |
| `GET /api/collections/_peers` | anyone | this node's name and peers, used by peers to probe it |
| `GET /api/collections/<c>/items?scope=authoritative` | peers (node token) | the items whose home is this host |
| `GET /api/collections/<c>/by-app/<app>/<item>/manifest.json`, `.../files/<path>`, `.../thumbnail` | peers (node token) | what a home host serves to peers (replicas are never served on); the manifest and the thumbnail are read from the item's `.item/` |

Speeds, by construction:

| Situation | Speed |
|---|---|
| another container on the same host reads | local disk |
| another host opens an item the first time | one LAN connection |
| that host opens it again | local disk |
| any app writes | local disk |

## Managing it: the storage page

The App Store's **Storage** page (`https://aapps.<zone>/storage`) manages every
collection the way a file manager manages files, but item by item, within
the rules above:

| Tab | What it does |
|---|---|
| **Items** | Every item on this host and on its peers, filtered by collection, kind, app, place (made here, copies, only elsewhere) and words, sorted and paged. Details show the manifest, the files, `meta`, and the lineage both ways: what an item was made from (`derived_from`) and what was made from it. A preview, **Open with** (see below), **Fetch a copy** for an item on another host, and **Delete** for one on this host. Items are never renamed or edited: a ref must keep working for the apps that hold it. |
| **Space** | The disk, and per collection what each contribution takes (items, copies, unfinished `.tmp` work), with its quota. A contribution whose app is no longer installed is marked; its data can be deleted here (uninstall only offers that while the app is still there). |
| **Hosts** | This node, its peers (reachable, name as expected), adding and removing peers, the copies fetched from them, the cap on copies, and **Clean up now** (`_gc`). It warns when `RE_DDNS_NODE_TOKEN` is not set. |
| **Import** | A person's own files (dropped as files or as a folder) become **one item** of the reserved owner `_user`, in a collection and kind of their choice. Every app that reads the collection sees it, e.g. the DICOM Viewer shows imported series; this is how files from before a collection existed (or from a CD) join it. |

Deleting an item is one rename out of sight and then the delete, so readers
never see half an item. A ref held by an app may then point nowhere, like a
shortcut to a deleted file: apps must handle `ItemNotFound`. The details
dialog warns how many items were made from the one being deleted; refs kept
inside an app's own database are invisible to it.

**Open with.** An app that opens items declares the kinds an intent action
accepts; the action then gets the item's ref as its `ref` param:

```python
from reflex_ddns_auth.intent import intent

@intent(app, action="dicom.open-series", on_open=ViewerState.open_ref,
        accepts=("dicom.series",))
def open_series_intent():
    return viewer_page()
```

`GET /api/intent/openers?kind=dicom.series` lists such actions over every
installed app (`resolve_openers(kind)` in the library). The storage page opens
`https://<app>.<zone>/intent/<action>?ref=<ref>` in a new tab, where
`IntentPage.is_active` is false; another app can open the same action as a
dialog with `Intent.start(app, action, ref=ref)`. The provider resolves the
ref itself (`Collection(...).resolve(ref)`), so an item on another host is
fetched on the way.

**The index.** Searching and totals come from a SQLite index the node keeps
in its data volume (`collections_index.sqlite`). The tree stays the truth:
apps never use the index, and deleting the file only costs a rebuild from the
manifests. It follows the tree by the mtimes of the `by-app/<app>/` folders
(publishing, fetching, importing and deleting all change them), re-reading
only manifests whose size or mtime changed, with a full pass every five
minutes and on the page's **Refresh**.

**The page's endpoints** all need the admin token (next section):

| Endpoint | Role |
|---|---|
| `GET /api/collections/_usage` | per collection and contribution: items, bytes, copies, unfinished bytes, quota; the replica cap; the disk |
| `GET /api/collections/_index?collection=&kind=&owner=&q=&location=all\|here\|own\|replica\|remote&sort=newest\|oldest\|largest\|smallest\|title&limit=&offset=&refresh=` | search; `remote` = on peers, not copied here |
| `GET /api/collections/_item?ref=` | one item: entry, manifest, `derived_from_items`, `derived_into`, path on the host |
| `GET /api/collections/_thumb?ref=` | its preview (from a peer when the item lives there) |
| `DELETE /api/collections/<c>/by-app/<app>/<item>` | delete one local item or copy, whoever owns it |
| `GET / PUT /api/collections/_settings` | `{"replica_max_bytes": n \| null}`, `{"quota": {"collection", "owner", "bytes"}}` (0 removes it) |
| `POST /api/collections/_import {"collection", "kind", "title", "meta"}`, then `PUT .../_import/<upload>/files/<path>` (raw body) per file, then `POST .../_import/<upload>/finish` (or `DELETE .../_import/<upload>`) | publish files as an item of `_user`: staged in `by-app/_user/.tmp/`, manifest last, one rename; an upload nobody finishes is dropped by `_gc` after a day |
| `PUT /api/collections/_peers`, `GET/DELETE /api/collections/_contributions/<app>`, `POST /api/collections/_gc` | peers, an app's folders (uninstall's "also delete data"), clean-up |

## The admin token

Every app container reaches re-ddns over the Docker network, and every
machine on the LAN reaches it through nginx. So everything that changes the
platform needs the header `X-Re-DDNS-Admin-Token`: the storage page's
endpoints above, and install, dev-install and uninstall in
`/api/appstore` (an install request names its own bind mounts and storage,
and an uninstall can delete data). Without it, "write mine" would hold on
disk but not over HTTP: any app could ask re-ddns to delete another app's
contribution, or install a container that mounts the whole tree read-write.

The token is `RE_DDNS_ADMIN_TOKEN` when set; otherwise re-ddns creates one on
first start in `/app/data/admin_token` (mode 0600, in the registry-data
volume). The App Store reads it through the Docker socket it already holds,
so nothing needs configuring, and apps, which have no Docker socket, cannot
read it. From a shell on the host:

```bash
TOKEN=$(docker exec re-ddns cat /app/data/admin_token)
curl -H "X-Re-DDNS-Admin-Token: $TOKEN" -X POST http://home.reflex-ddns.com/api/collections/_gc
```

Not covered: the DNS / service registry endpoints (`/api/service/*`,
`/api/dns/*`), which every app uses to register itself, stay open.

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

An app that keeps editing its files changes where it saves, not how it works.
**ReflexGrid** declares `{"collection": "spreadsheets", "access": "contribute"}`;
when re-ddns gives it the collection (`DDNS_COLLECTIONS_ROOT` is set), its book
store (`reflex_grid/books.py`, about 150 lines more) keeps each workbook as an
item: `publish()` when the workbook is created, `revise()` on every save,
`remove()` when it is deleted. Links, live co-editing and the workbook list
work as before, because editing happens in memory and only the save moved;
a workbook deleted on the storage page while people are on it is shown to
them as deleted. Run on its own, it keeps its files in `REFLEX_GRID_HOME`.

**CoDoc in MD** (`md`) does the same with `{"collection": "documents", "access": "contribute"}`:
each document is an item holding one `doc.md` (`codoc_in_md/state.py`, about
190 lines more). Its editor saves on every keystroke, so the store keeps a
change in memory and writes it 1.5 s later, at most once per 1.5 s while
people type, and what is unwritten at exit is written then; live co-editing
goes through its Yjs relay and never waits for the disk. Run on its own, it
keeps its documents in its database.

**YouTube to MP3** and **Video Audio Mixer** share the `audio` collection the
same way, one writing and one reading: the converter declares
`{"collection": "audio", "access": "contribute"}` and publishes every song it
converts as an `audio.file` item (`youtube_to_mp3_tool/jobs.py`; ffmpeg writes
the MP3 straight into the item being published); the mixer declares
`{"collection": "audio", "access": "read"}` and lists those items as its audio
library (`video_audio_mixer/media.py`). They also talk while the user works: the
mixer opens the converter's DDNS Intent `audio.find` as a dialog that keeps
running when minimized (or shown as a small picture-in-picture window), and the
converter reports every finished song with an intent `update` (`{"event":
"ready", "ref": ...}`), so it appears in the mixer's library at once.

Everything beyond that (a list of the collection's items in the viewer, a
"Open in Viewer" button through DDNS Intent, fetching from another host with
a progress bar) is optional product work on top, not part of joining.

Downloads made before the collection existed (`/Users/Shared/DICOM`) are not
items; download them again with the explorer, or import them on the storage
page (they become items of `_user`).

An app joining a collection should check three things: its kind has a row in
[Kinds](#kinds) (add one for a new kind), it lets a failed `publish()` fail
visibly (`QuotaExceeded` is a `PublishError`), and it copes with a ref that no
longer resolves (`ItemNotFound`), since items can be deleted on the storage
page.

## Limits worth knowing

- Items are immutable, except that their owner may revise them in place ([Items an app keeps editing](#items-an-app-keeps-editing)). To make something else from an item, publish a new item (`derived_from` keeps the lineage).
- Another app's contribution is untrusted input. The library never follows symlinks out of an item and validates every ref segment; the node checks a preview's bytes before serving it as an image.
- The node serves only items whose home it is; a copy is never passed on to a third host.
- Quotas are checked by the library, not by the kernel: an app that writes without the library, or while the node is unreachable, is not stopped. The storage page still shows it over its quota.
- On Linux hosts set `HOST_UID`/`HOST_GID` (the restart script does) so folders the node creates belong to you.
- Without `RE_DDNS_NODE_TOKEN` the peer endpoints are open on the LAN; set one on every node.
- Apps may read item metadata of any collection through `GET /api/collections/<c>/items`, even one their catalog entry does not grant; the bytes stay out of reach (no mount). The node cannot tell apps apart yet.
