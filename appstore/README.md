# App Store (`aapps.reflex-ddns.com`)

A Reflex app that acts as a small **App Store / control panel** for every
Reflex app deployed behind `re-ddns`. It runs as an independent container
(`app-store`) and registers itself as `aapps.reflex-ddns.com`, exactly like
the other apps.

Open it at: **https://aapps.reflex-ddns.com/**

## What it does

For every app declared in the catalog you can:

| Action       | Behaviour                                                                 |
|--------------|---------------------------------------------------------------------------|
| **Status**   | Shows `Running` / `Stopped` / `Not installed` (live, from Docker).        |
| **Open**     | Opens `https://<subdomain>.reflex-ddns.com` in a new tab.                 |
| **Start**    | Starts the app's container (`smart-app-<subdomain>`).                     |
| **Stop**     | Stops the app's container.                                                |
| **Install**  | Installs the app **in-page** with a live progress bar — no host commands. Several apps can be installed (or removed) at once; each card shows its own bar. |
| **Uninstall**| Confirms, then removes the app **in-page with live progress**: container, registry, DNS, nginx, TLS cert. Data volumes are kept unless ticked. |
| **Language** | English, 繁體中文, 简体中文, Español, 日本語 — one choice for this page, `/monitor` and `/storage` (kept in the browser, synced across tabs). |

The **Storage** page (`/storage`, linked from the header) manages the data the
apps share through collections: items (search, details with lineage, preview,
*Open with*, fetch a copy from another host, delete), space (per app and
collection, quotas, data of apps no longer installed), hosts (peers, the cap
on copies, clean-up), and importing your own files as items. See
[docs/collections.md](../docs/collections.md#managing-it-the-storage-page).

The **Memory** page (`/monitor`, linked from the header) shows the Docker VM's
memory and every container's share of it, sampled every 4 s, with per-container
limits, restart, and the Dev / Non-Dev switch. **Resize** on the VM card
changes the VM's own memory. Docker Desktop keeps that setting on the Mac,
where this container cannot reach it, so a small helper on the Mac makes the
change (`../macos_docker_vm_helper.sh --install`, once; see the main README).
The page reads the helper's port and token from
`<HOST_FS_PREFIX><HOST_HOME>/.re_ddns/docker-vm-helper.json` and calls it at
`http://host.docker.internal:<port>/vm`. Applying a size restarts the VM, this
container included, so the page disconnects; when it reconnects, its on_load
asks the helper again and reports the outcome.

> **Real, in-page install (no host shell needed):** every smart app is just the
> generic `re-ddns/smart-launcher` image started with different environment
> variables. The App Store asks **re-ddns** (which owns the Docker socket and an
> install/progress manager) to create + start the app's container, then polls
> for progress and renders a live bar: clone → install deps → reflex init →
> register DNS/nginx → app running.

## How it works

- **Catalog** — `data/appstore_catalog.json` is the source of truth (the
  `smart_launch.sh` parameter table). It is bind-mounted read-only at
  `/app/data/appstore_catalog.json` (`CATALOG_PATH`).
- **Status & control** — uses the Docker Engine API over the bind-mounted
  Unix socket `/var/run/docker.sock`:
  - `GET /containers/smart-app-<sub>/json` → running / stopped / 404 (not installed)
  - `POST /containers/smart-app-<sub>/start|stop`
- **Install** — `POST {RE_DDNS_API_URL}/api/appstore/install` with the catalog
  entry. re-ddns creates + starts `smart-app-<sub>` from the generic
  `re-ddns/smart-launcher` image via the Docker Engine API. The App Store then
  polls `GET /api/appstore/status/<sub>`; each poll advances re-ddns's scan of
  the container logs and returns `{percent, phase, message, log}`.
- **Uninstall** — `POST {RE_DDNS_API_URL}/api/appstore/uninstall` with
  `{subdomain, name, zone, remove_data}`. re-ddns runs it as a job that the
  same `GET /api/appstore/status/<sub>` polls advance, one short step per
  poll: stop the container (its StopSignal, SIGKILL after the grace period)
  → remove it → drop the registry entry + DNS record → `nginx` sync → delete
  the TLS cert → optionally delete the app's named volumes. Every step is
  idempotent and recorded in `data/install_jobs.json`, so a backend reload
  half-way through (the dev-mode hot reloader restarts re-ddns when the
  registry file changes) cannot leave a container behind. The App Store
  shows the steps in the same progress panel as Install; closing the panel
  does not stop the job.
- **Several at once** — every install / uninstall is its own job in re-ddns
  (`install_jobs.json` is keyed by subdomain) and gets its own poller in the
  App Store, so two apps can be installed, or one installed while another is
  removed, at the same time. Each card shows its own progress bar; the panel
  shows one job and grows tabs to switch between them when several are in
  flight. A job that fails while the panel shows another one stays marked on
  its card until its own panel has been opened.
- **Admin token** — install, dev-install, uninstall and every call of the
  Storage page carry re-ddns's admin token (`X-Re-DDNS-Admin-Token`), which
  `appstore/admin.py` takes from `RE_DDNS_ADMIN_TOKEN`, or else reads from
  `/app/data/admin_token` inside the `re-ddns` container through the Docker
  socket (`GET /containers/re-ddns/archive`). A 401 makes it read the token
  again once (re-ddns recreated with a new volume).
- **Storage** — `appstore/storage.py`: the page calls the re-ddns node API
  (`/api/collections/_usage`, `_index`, `_item`, `_settings`, `_import`, ...)
  and the intent registry (`/api/intent/openers?kind=`, for *Open with*).
  Previews go through this app's own backend, `GET /api/storage/thumb?ref=`,
  which fetches them with the token, so the browser never sees it. Imports
  stream each uploaded file to re-ddns in 1 MB chunks.
- **Routing** — registers `aapps` with `re-ddns` on startup (`register_dns.py`);
  nginx terminates TLS and proxies `aapps.reflex-ddns.com` → `app-store:3000`.

## Catalog format (`data/appstore_catalog.json`)

```json
{
  "apps": [
    {
      "id": "md",
      "name": "Markdown CoDoc",
      "description": "Collaborative markdown editor.",
      "icon": "file-text",
      "subdomain": "md",
      "github_repo": "https://github.com/milochen0418/codoc_in_md.git",
      "app_name": "codoc_in_md",
      "branch": "main",
      "commit": "",
      "subdir": "",
      "env_file": "",
      "volumes": []
    }
  ]
}
```

Each entry maps directly to a `smart_launch.sh` invocation. `icon` is any
[Lucide](https://lucide.dev/icons/) icon name.

Optional: `env_schema` (settings asked for before install) and `ports`
(host-published ports such as `["7881:7881", "7882:7882/udp"]`, for traffic
nginx cannot proxy, e.g. WebRTC media; `smart_launch.sh -p`).

`i18n` (optional) holds the entry's texts in other languages. The base fields
are English and are used for any language or field it leaves out:

```json
"i18n": {
  "zh-Hant": {"description": "多人協作編輯文件，以 Markdown 呈現。"},
  "ja": {
    "description": "…",
    "env": {"ADMIN_PASSCODE": {"label": "…", "placeholder": "…", "help": "…"}}
  }
}
```

## Languages

The UI text of this page and of `/monitor` lives in `appstore/i18n/` (one
table per language; `en.py` is the reference). Both pages inherit the chosen
language from `LocaleState` in `appstore/lang.py`, so switching on either page
switches both. Install and uninstall progress from re-ddns arrives as a
message key plus arguments (`msg`, `msg_args`), which the App Store renders
from the same tables. To add a language, follow the steps in
`appstore/i18n/__init__.py`, and add the language to the catalog's `i18n`
blocks if the app descriptions should follow.

## Run it

It is part of the full test stack and starts with everything else:

```bash
./docker_restart.sh
```

Or build/start just this service:

```bash
docker compose -f docker-compose.test.yml up -d --build app-store
docker logs -f app-store
```

## Configuration (environment)

| Variable             | Default                               | Purpose                                  |
|----------------------|---------------------------------------|------------------------------------------|
| `RE_DDNS_API_URL`    | `http://re-ddns:8000`                 | re-ddns registration API.                |
| `SERVICE_SUBDOMAIN`  | `aapps`                               | Subdomain to register.                   |
| `SERVICE_ZONE`       | `reflex-ddns.com`                     | DNS zone.                                |
| `CATALOG_PATH`       | `/app/data/appstore_catalog.json`     | App catalog location.                    |
| `DOCKER_SOCK`        | `/var/run/docker.sock`                | Docker Engine socket for status/control. |
| `RE_DDNS_ADMIN_TOKEN` | *(empty)*                            | re-ddns's admin token; empty = read it from the re-ddns container. |
| `RE_DDNS_CONTAINER`  | `re-ddns`                             | The container the token is read from.    |
| `RE_DDNS_ADMIN_TOKEN_PATH` | `/app/data/admin_token`         | Where the token file is in that container. |
| `APPSTORE_DEV_MODE`  | `0`                                   | `1` shows the **Dev** button (bind-mount a local checkout). |
| `HOST_HOME`          | *(empty)*                             | Host home folder; the Dev form autocompletes paths under it, and the Memory page finds the VM helper's token there. |
| `HOST_FS_PREFIX`     | `/hostfs`                             | Where the host home is mounted read-only (`${HOME}:/hostfs${HOME}:ro`). |
| `VM_HELPER_HOST`     | `host.docker.internal`                | Where the Mac-side Docker VM helper answers (port from its config file). |

### Dev form path autocomplete

The Dev form's path field works like a shell: type `/` or `~/` and press
**Tab** to complete (a unique folder completes; several extend to their
common prefix, and a second Tab takes the highlighted one). **↑/↓** move
through the folder list, **Enter** takes the highlighted folder, **Esc**
hides the list. No prefix match falls back to a substring match
(`gits/dd` → `re_ddns`). Folders with `rxconfig.py` / `pyproject.toml` are
tagged, and the line under the field says whether the path is a project.
Only folders under `HOST_HOME` can be listed; `/` and its ancestors show
just the way down to it.

## Notes / limitations

- **Docker socket access** grants broad control over the host's containers.
  This is acceptable for a local/dev control plane; do not expose this app to
  untrusted networks.
- In a browser that does **not** trust the local CA (e.g. a fresh automation
  browser), the page shows `Connection Error` because the Reflex websocket is
  `wss://`. Install the local CA first (see `RUN_FROM_ZERO.md`).
