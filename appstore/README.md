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
| **Install**  | Installs the app **in-page** with a live progress bar — no host commands. |
| **Uninstall**| Stops the container and removes its DNS + nginx records.                  |

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
- **Uninstall** — `DELETE {RE_DDNS_API_URL}/api/service/<sub>` stops the
  container and removes the registry + DNS + nginx records.
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

## Notes / limitations

- **Docker socket access** grants broad control over the host's containers.
  This is acceptable for a local/dev control plane; do not expose this app to
  untrusted networks.
- In a browser that does **not** trust the local CA (e.g. a fresh automation
  browser), the page shows `Connection Error` because the Reflex websocket is
  `wss://`. Install the local CA first (see `RUN_FROM_ZERO.md`).
