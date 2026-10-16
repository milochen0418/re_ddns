"""Container memory monitor (``/monitor``).

The Docker VM that runs every app has a fixed amount of memory (8 GiB by
default), and the apps share it.  When it runs out, the kernel's **global** OOM
killer frees memory by killing the largest process it can find — which is
usually not the app that asked for the memory, and often a child of a container
that keeps running without it.  ``docker ps`` still says ``Up``, so the damage
is invisible: a half-dead app answers HTTP 502, or loads but dies on first use.

This page makes that visible and manageable:

  • **VM total** — how much of the Docker VM's memory and swap is in use, and
    how much is actually available for the next allocation.
  • **Per container** — working set, share of the VM, CPU, a short history,
    and the container's own memory limit.
  • **Half-dead detection** — ``State.OOMKilled`` is true while the container
    is still running, i.e. the OOM killer took a child process since the last
    start.  ``docker restart`` is the fix.
  • **Limits** — set a memory limit per container, live, without recreating it.
    A container with a limit is killed alone when it runs away, instead of the
    kernel picking the biggest innocent process in the VM.

Everything is read through the Docker Engine API over the socket bind-mounted
at ``/var/run/docker.sock`` (the same socket the app cards already use), plus
``/proc/meminfo``, which inside a container describes the whole Docker VM.

The page is translated: it starts in English and the picker in its header
switches language without a reload, remembering the choice in the browser.
All the text lives in the ``i18n`` package next door — see its ``__init__`` for
how to add a language.  Strings with ``{placeholders}`` are formatted on the
server (a Reflex Var cannot be ``.format()``-ed in a component), so anything
the UI shows ready-made is composed in ``collect()`` or in a computed var.

This module is self-contained apart from ``i18n``: ``appstore.py`` imports it,
so it must not import ``appstore.py`` back.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path

import httpx
import reflex as rx

from . import i18n

CATALOG_PATH = os.environ.get("CATALOG_PATH", "/app/data/appstore_catalog.json")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
SERVICE_ZONE = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")
# Platform containers that serve a page but carry no SERVICE_SUBDOMAIN.
PLATFORM_SUBDOMAINS = {"re-ddns": "home"}

# Seconds between samples while the page is open.
POLL_SECONDS = 4.0
# Samples kept per container for the sparklines (backend only).
HISTORY = 60
MIB = 1024 * 1024

# Stopping these breaks the page itself: app-store serves it, re-ddns proxies
# it.  Restarting re-ddns is allowed — it is the documented fix when its own
# frontend was OOM-killed — but app-store cannot restart itself from its page.
NO_STOP = {"app-store", "re-ddns"}
NO_RESTART = {"app-store"}

# MemAvailable thresholds for the warning line.
CRITICAL_MB = 800
TIGHT_MB = 1536
# Docker itself refuses anything under 6 MB; keep a workable floor.
MIN_LIMIT_MB = 128


# ---------------------------------------------------------------------------
# Docker + /proc helpers
# ---------------------------------------------------------------------------

def _catalog_meta() -> dict[str, dict[str, str]]:
    """``subdomain`` → display name + icon, for ``smart-app-<subdomain>``."""
    try:
        apps = json.loads(Path(CATALOG_PATH).read_text()).get("apps", [])
    except Exception:  # noqa: BLE001 - an unreadable catalog only costs labels
        return {}
    return {
        str(a["subdomain"]): {
            "name": str(a.get("name", a["subdomain"])),
            "icon": str(a.get("icon", "box")),
        }
        for a in apps
        if a.get("subdomain")
    }


def _read_meminfo() -> dict[str, int]:
    """``/proc/meminfo`` in kB.

    Inside a container this is the Docker VM's own memory, not the container's,
    which is exactly the number this page is about.  The Docker API's ``/info``
    reports only MemTotal, with no available or swap figure.
    """
    out: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                out[key] = int(parts[0])
    except OSError:
        pass
    return out


def _client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=20.0)


async def _get(client: httpx.AsyncClient, path: str):
    """GET a Docker API path, returning the parsed body or ``None``."""
    try:
        r = await client.get(path)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:  # noqa: BLE001 - a container may vanish mid-poll
        return None


async def _port_open(host: str, port: int) -> bool:
    """Whether something accepts TCP connections on host:port right now."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 0.8)
    except Exception:  # noqa: BLE001 - refused, unreachable, timeout: all "no"
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001
        pass
    return True


def _frontend_port(env: dict[str, str], name: str) -> int:
    """The port the container's web UI answers on (what nginx proxies to)."""
    if name == "pkg-cache":
        return int(env.get("PKG_CACHE_PORT") or 3142)
    return int(env.get("FRONTEND_PORT") or 3000)


async def _probe(client: httpx.AsyncClient, name: str) -> tuple[str, dict | None, dict | None]:
    """One container's stats + inspect, fetched together.

    ``one-shot=true`` is what keeps a poll fast: without it the API samples
    twice, a second apart, to compute CPU itself (1.02 s vs 0.01 s per
    container here).  The price is that ``precpu_stats`` comes back empty, so
    CPU is computed from the difference between our own polls instead.
    """
    stats, insp = await asyncio.gather(
        _get(client, f"/containers/{name}/stats?stream=false&one-shot=true"),
        _get(client, f"/containers/{name}/json"),
    )
    return name, stats, insp


def _working_set(stats: dict | None) -> int:
    """Bytes of memory that cannot be reclaimed, as ``docker stats`` shows.

    ``memory_stats.usage`` includes the page cache, which the kernel drops
    under pressure; subtracting ``inactive_file`` is the same correction the
    docker CLI makes, and keeps the number comparable to it.
    """
    if not stats:
        return 0
    mem = stats.get("memory_stats") or {}
    usage = int(mem.get("usage") or 0)
    inactive = int((mem.get("stats") or {}).get("inactive_file") or 0)
    return max(0, usage - inactive)


def _cpu_percent(stats: dict | None, prev: list[int] | None) -> tuple[float, list[int] | None]:
    """CPU use since the previous poll, plus the sample to keep for the next."""
    if not stats:
        return 0.0, None
    cpu = stats.get("cpu_stats") or {}
    total = int((cpu.get("cpu_usage") or {}).get("total_usage") or 0)
    system = int(cpu.get("system_cpu_usage") or 0)
    cpus = int(cpu.get("online_cpus") or 0) or 1
    sample = [total, system, cpus]
    if not prev or not total or not system:
        return 0.0, sample
    d_total, d_system = total - prev[0], system - prev[1]
    if d_total <= 0 or d_system <= 0:
        return 0.0, sample
    return min(100.0 * cpus, d_total / d_system * cpus * 100.0), sample


def _spark(samples: list[int]) -> str:
    """Working-set history as polyline points for a 100×24 SVG.

    Scaled to each container's own maximum, so a row shows its trend rather
    than its size (the bar next to it already shows the size).
    """
    if len(samples) < 2:
        return ""
    top = max(samples) or 1
    step = 100.0 / (len(samples) - 1)
    return " ".join(
        f"{i * step:.1f},{23.0 - (v / top) * 21.0:.1f}" for i, v in enumerate(samples)
    )


def _env_of(insp: dict | None) -> dict[str, str]:
    """A container's environment as a dict."""
    return dict(
        e.split("=", 1) for e in ((insp or {}).get("Config") or {}).get("Env") or [] if "=" in e
    )


# Config keys a container is created with, copied from its inspect output when
# it is recreated.
_CREATE_KEYS = (
    "Hostname", "Domainname", "User", "Tty", "OpenStdin", "StdinOnce",
    "AttachStdin", "AttachStdout", "AttachStderr", "ExposedPorts", "Labels",
    "Volumes", "StopSignal", "StopTimeout", "Healthcheck",
)
# Keys an image supplies; copied only where the container overrode them, so a
# rebuilt image's own defaults (PATH, entrypoint, …) take effect.
_IMAGE_KEYS = ("Cmd", "Entrypoint", "WorkingDir")


#: Env vars every smart-launcher app should carry; ``recreate`` adds the ones
#: a container made before they existed is missing.
PLATFORM_ENV_DEFAULTS = {
    # Hide the fixed "Built with Reflex" badge Reflex adds in prod mode.
    "REFLEX_SHOW_BUILT_WITH_REFLEX": "false",
}


async def recreate(
    name: str, env_set: dict[str, str], env_default: dict[str, str] | None = None
) -> None:
    """Recreate a container with the same settings and some env vars changed.

    ``env_set`` entries replace the container's values; ``env_default`` entries
    are added only when the container has no value for that key.

    Docker cannot change an existing container's environment, so switching an
    app between dev and prod means a new container.  Everything else is taken
    from ``inspect``: image, mounts and named volumes (so app data survives),
    published ports, network, restart policy, memory limit.  Env entries that
    merely repeat the old image's defaults are dropped, so the image's current
    defaults apply.

    The old container is stopped and parked under another name until the new
    one has started; if anything fails it is renamed back and started again,
    and the error is raised.
    """
    async with _client() as c:
        r = await c.get(f"/containers/{name}/json")
        r.raise_for_status()
        insp = r.json()
        cfg, host = insp["Config"], insp["HostConfig"]
        img = await _get(c, f"/images/{insp['Image']}/json") or {}
        img_cfg = img.get("Config") or {}

        base_env = set(img_cfg.get("Env") or [])
        env = [
            e for e in cfg.get("Env") or []
            if e not in base_env and e.split("=", 1)[0] not in env_set
        ]
        env += [f"{k}={v}" for k, v in env_set.items()]
        present = {e.split("=", 1)[0] for e in env}
        env += [f"{k}={v}" for k, v in (env_default or {}).items() if k not in present]

        body: dict = {"Image": cfg["Image"], "Env": env, "HostConfig": host}
        body.update({k: cfg[k] for k in _CREATE_KEYS if cfg.get(k) is not None})
        body.update({
            k: cfg[k] for k in _IMAGE_KEYS
            if cfg.get(k) is not None and cfg.get(k) != img_cfg.get(k)
        })
        endpoints = {}
        for net, ep in ((insp.get("NetworkSettings") or {}).get("Networks") or {}).items():
            entry: dict = {}
            # Docker adds the container's short id as an alias; drop the old one.
            aliases = [a for a in ep.get("Aliases") or [] if a != insp["Id"][:12]]
            if aliases:
                entry["Aliases"] = aliases
            if ep.get("IPAMConfig"):
                entry["IPAMConfig"] = ep["IPAMConfig"]
            endpoints[net] = entry
        body["NetworkingConfig"] = {"EndpointsConfig": endpoints}

        parked = f"{name}-switching"
        await c.post(f"/containers/{name}/stop?t=10", timeout=60.0)
        r = await c.post(f"/containers/{name}/rename?name={parked}")
        if r.status_code != 204:
            await c.post(f"/containers/{name}/start")
            raise RuntimeError(f"rename failed (HTTP {r.status_code})")
        try:
            r = await c.post(f"/containers/create?name={name}", json=body)
            if r.status_code != 201:
                raise RuntimeError(f"create: HTTP {r.status_code} {r.text[:160]}")
            r = await c.post(f"/containers/{r.json()['Id']}/start")
            if r.status_code not in (204, 304):
                raise RuntimeError(f"start: HTTP {r.status_code} {r.text[:160]}")
        except Exception:
            await c.delete(f"/containers/{name}?force=true")
            await c.post(f"/containers/{parked}/rename?name={name}")
            await c.post(f"/containers/{name}/start")
            raise
        await c.delete(f"/containers/{parked}?force=true")


def _app_url(name: str, insp: dict | None) -> str:
    """The ``https://<subdomain>.<zone>`` a container answers on, or "".

    Read from the container's own ``SERVICE_SUBDOMAIN`` / ``SERVICE_ZONE``
    (what it registered with re-ddns), so a dev install under another
    subdomain still links correctly.  re-ddns serves its control panel as
    ``home`` without that variable; pkg-cache has no domain at all.
    """
    env = _env_of(insp)
    sub = env.get("SERVICE_SUBDOMAIN") or PLATFORM_SUBDOMAINS.get(name, "")
    if not sub:
        return ""
    return f"https://{sub}.{env.get('SERVICE_ZONE') or SERVICE_ZONE}"


def _status_of(insp: dict | None, listed_state: str, t: Mapping[str, str]) -> tuple[str, str]:
    """``(status, translated label)``, including the half-dead case.

    ``OOMKilled`` stays true from the moment the OOM killer took a process in
    the container until it is started again, so ``running`` + ``OOMKilled``
    means "something inside was killed and never came back".
    """
    state = (insp or {}).get("State") or {}
    status = str(state.get("Status") or listed_state or "unknown")
    if status == "restarting":
        return "restarting", t["st_restarting"]
    if status == "running":
        if state.get("OOMKilled"):
            return "half_dead", t["st_half_dead"]
        return "running", t["st_running"]
    if status in ("exited", "created", "dead", "paused", "removing"):
        return "stopped", t["st_stopped"]
    return "unknown", status


async def collect(
    prev_cpu: dict[str, list[int]],
    hist: dict[str, list[int]],
    meta: dict[str, dict[str, str]],
    t: Mapping[str, str],
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, list[int]]]:
    """Sample the VM and every container once.

    Returns the table rows (largest first), the VM summary, and the CPU
    samples to compare against on the next poll.  ``hist`` is updated in place.
    """
    mem = _read_meminfo()
    total_kb = mem.get("MemTotal", 0)
    avail_kb = mem.get("MemAvailable", 0)
    free_kb = mem.get("MemFree", 0)
    cache_kb = mem.get("Buffers", 0) + mem.get("Cached", 0) + mem.get("SReclaimable", 0)
    used_kb = max(0, total_kb - free_kb - cache_kb)
    swap_total_kb = mem.get("SwapTotal", 0)
    swap_used_kb = max(0, swap_total_kb - mem.get("SwapFree", 0))

    rows: list[dict[str, str]] = []
    next_cpu: dict[str, list[int]] = {}
    if not os.path.exists(DOCKER_SOCK):
        return rows, {"error": t["socket_error"]}, next_cpu

    async with _client() as client:
        listed = await _get(client, "/containers/json?all=1") or []
        names: list[str] = []
        listed_by_name: dict[str, dict] = {}
        for item in listed:
            raw = (item.get("Names") or ["/?"])[0]
            name = raw.lstrip("/")
            names.append(name)
            listed_by_name[name] = item
        probes = await asyncio.gather(*(_probe(client, n) for n in names))

    # A recreated container runs long before its app serves anything: the
    # launcher is still reinstalling, and nginx answers 502 meanwhile.  A TCP
    # check on the UI port separates "running" from "still starting", so the
    # page explains the 502 instead of showing a healthy green badge.
    ports = {
        name: _frontend_port(_env_of(insp), name)
        for name, _stats, insp in probes
        if ((insp or {}).get("State") or {}).get("Running")
    }
    answering = dict(zip(
        ports,
        await asyncio.gather(*(_port_open(n, p) for n, p in ports.items())),
    ))

    total_bytes = total_kb * 1024
    for name, stats, insp in probes:
        item = listed_by_name.get(name, {})
        status, label = _status_of(insp, str(item.get("State") or ""), t)
        if status == "running" and not answering.get(name, True):
            status, label = "starting", t["st_starting"]
        ws = _working_set(stats) if status != "stopped" else 0
        cpu, sample = _cpu_percent(stats, prev_cpu.get(name))
        if sample:
            next_cpu[name] = sample

        series = hist.setdefault(name, [])
        series.append(ws)
        del series[:-HISTORY]

        limit = int(((insp or {}).get("HostConfig") or {}).get("Memory") or 0)
        sub = name[len("smart-app-"):] if name.startswith("smart-app-") else ""
        info = meta.get(sub, {})
        url = _app_url(name, insp)
        env = _env_of(insp)
        # Only smart-launcher apps understand REFLEX_ENV; re-ddns and app-store
        # have their own entrypoints and are managed by docker compose.
        switchable = bool(sub) and "APP_NAME" in env
        mode = (env.get("REFLEX_ENV") or "dev") if switchable else ""
        rows.append(
            {
                "name": name,
                "label": info.get("name") or name,
                "icon": info.get("icon") or ("server" if not sub else "box"),
                "kind": "app" if sub else "platform",
                "status": status,
                "status_label": label,
                "ws_mb": f"{ws // MIB}",
                "ws_label": f"{ws / MIB:,.0f} MB" if ws else "—",
                "pct": f"{(ws / total_bytes * 100) if total_bytes else 0:.1f}",
                "bar": f"{min(100.0, (ws / total_bytes * 100) if total_bytes else 0):.2f}%",
                "cpu": f"{cpu:.1f}",
                "restarts": str((insp or {}).get("RestartCount") or 0),
                "restarts_label": t["restarts"].format(
                    count=(insp or {}).get("RestartCount") or 0
                ),
                "uptime": str(item.get("Status") or ""),
                "limit_mb": str(limit // MIB),
                "limit_label": f"{limit // MIB:,} MB" if limit else t["no_limit"],
                "spark": _spark(series),
                "url": url,
                "host": url.removeprefix("https://"),
                "mode": mode,
                "mode_label": t["mode_prod"] if mode == "prod" else t["mode_dev"] if mode else "",
                "can_stop": "" if name in NO_STOP or status == "stopped" else "1",
                "can_restart": "" if name in NO_RESTART else "1",
                "_sort": f"{ws:020d}",
            }
        )

    rows.sort(key=lambda r: r["_sort"], reverse=True)
    for r in rows:
        del r["_sort"]

    avail_mb = avail_kb // 1024
    level = "ok"
    note = t["note_ok"]
    if avail_mb < CRITICAL_MB:
        level = "critical"
        note = t["note_critical"].format(avail=f"{avail_mb:,}")
    elif avail_mb < TIGHT_MB:
        level = "tight"
        note = t["note_tight"].format(avail=f"{avail_mb:,}")
    summary = {
        "error": "",
        "total": f"{total_kb / 1048576:.1f} GB",
        "used": f"{used_kb / 1048576:.1f} GB",
        "cache": f"{cache_kb / 1048576:.1f} GB",
        "avail": f"{avail_kb / 1048576:.2f} GB",
        "avail_mb": str(avail_mb),
        "used_bar": f"{(used_kb / total_kb * 100) if total_kb else 0:.2f}%",
        "cache_bar": f"{(cache_kb / total_kb * 100) if total_kb else 0:.2f}%",
        "swap": f"{swap_used_kb / 1048576:.2f} / {swap_total_kb / 1048576:.1f} GB",
        "swap_bar": f"{(swap_used_kb / swap_total_kb * 100) if swap_total_kb else 0:.2f}%",
        "containers": t["vm_containers"].format(count=len(rows)),
        "level": level,
        "note": note,
    }
    return rows, summary, next_cpu


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class MonitorState(rx.State):
    """Live container memory table, polled while the page is open."""

    rows: list[dict[str, str]] = []
    vm: dict[str, str] = {}
    loading: bool = False
    auto: bool = True
    message: str = ""
    message_kind: str = "info"  # info | success | error

    # The chosen language, kept in the browser so it survives a reload. New
    # visitors start in English (i18n.DEFAULT).
    locale: str = rx.LocalStorage(i18n.DEFAULT, name="appstore_monitor_locale")
    show_langs: bool = False

    # Memory-limit editor (one row at a time).
    edit_name: str = ""
    edit_value: str = ""
    edit_current: str = ""
    edit_hint: str = ""

    # The ☰ menu that is open (container name, "" = none), and the dev/prod
    # switch waiting for confirmation.
    menu_name: str = ""
    switch_name: str = ""
    switch_to: str = ""        # "dev" | "prod"
    switch_text: str = ""      # the confirmation question, in the current language
    switching: str = ""        # container being recreated right now

    # Backend-only: CPU samples to diff against, and the sparkline history.
    _cpu: dict[str, list[int]] = {}
    _hist: dict[str, list[int]] = {}

    @rx.var
    def t(self) -> dict[str, str]:
        """The string table the components read, e.g. ``MonitorState.t["refresh"]``."""
        return dict(i18n.strings(self.locale))

    @rx.var
    def subtitle(self) -> str:
        """Composed here because a Var cannot be ``.format()``-ed in a component."""
        return i18n.strings(self.locale)["subtitle"].format(seconds=int(POLL_SECONDS))

    @rx.var
    def lang_label(self) -> str:
        return i18n.label(self.locale)

    def _strings(self):
        return i18n.strings(self.locale)

    async def _sample(self):
        rows, vm, cpu = await collect(
            self._cpu, self._hist, _catalog_meta(), self._strings()
        )
        self.rows = rows
        self.vm = vm
        self._cpu = cpu

    @rx.event
    async def refresh(self):
        """Take one sample now, with the spinner (also the page's on_load)."""
        self.loading = True
        yield
        try:
            await self._sample()
        except Exception as exc:  # noqa: BLE001
            self.message = self._strings()["msg_read_failed"].format(error=exc)
            self.message_kind = "error"
        self.loading = False

    @rx.event
    async def set_locale(self, code: str):
        """Switch language, and re-sample so the server-built text follows.

        Status labels, the VM note and "N containers" are composed while
        sampling, so they would otherwise keep the old language until the next
        tick.
        """
        self.locale = code if code in i18n.CODES else i18n.DEFAULT
        self.show_langs = False
        self.message = ""
        if self.edit_name:
            self.edit_hint = self._strings()["limit_hint"].format(mb=self.edit_current)
        try:
            await self._sample()
        except Exception:  # noqa: BLE001 - the language still changed
            pass

    @rx.event
    def toggle_langs(self):
        self.show_langs = not self.show_langs
        self.menu_name = ""

    # ── ☰ menu ──

    @rx.event
    def toggle_menu(self, name: str):
        self.menu_name = "" if self.menu_name == name else name
        self.show_langs = False

    @rx.event
    def close_menus(self):
        """Click outside any open menu."""
        self.menu_name = ""
        self.show_langs = False

    @rx.event
    def menu_restart(self, name: str):
        self.menu_name = ""
        return MonitorState.restart_container(name)

    @rx.event
    def ask_switch(self, name: str, to: str):
        """Show the confirmation for a dev ↔ prod switch (it recreates the container)."""
        t = self._strings()
        self.menu_name = ""
        self.edit_name = ""
        self.switch_name = name
        self.switch_to = "prod" if to == "prod" else "dev"
        mode = t["mode_prod"] if self.switch_to == "prod" else t["mode_dev"]
        self.switch_text = t["switch_confirm"].format(name=name, mode=mode)
        self.message = ""

    @rx.event
    def cancel_switch(self):
        self.switch_name = ""
        self.switch_to = ""

    @rx.event(background=True)
    async def confirm_switch(self):
        """Recreate the container with REFLEX_ENV changed.

        Runs in the background: stopping the old container alone can take ten
        seconds, and the page keeps updating meanwhile.
        """
        async with self:
            name, to = self.switch_name, self.switch_to
            t = self._strings()
            if not name or self.switching:
                if self.switching:
                    self.message = t["msg_switch_busy"]
                    self.message_kind = "error"
                return
            self.switching = name
            self.switch_name = ""
            mode = t["mode_prod"] if to == "prod" else t["mode_dev"]
            self.message = t["msg_switch_working"].format(name=name, mode=mode)
            self.message_kind = "info"
        try:
            await recreate(name, {"REFLEX_ENV": to}, env_default=PLATFORM_ENV_DEFAULTS)
        except Exception as exc:  # noqa: BLE001 - recreate() restored the old one
            async with self:
                self.switching = ""
                self.message = t["msg_switch_failed"].format(name=name, error=exc)
                self.message_kind = "error"
            return
        async with self:
            self.switching = ""
            self.message = t["msg_switch_started"].format(name=name, mode=mode)
            self.message_kind = "success"
            try:
                await self._sample()
            except Exception:  # noqa: BLE001
                pass

    @rx.event
    async def tick(self):
        """One silent sample, driven by the timer in the page.

        The timer lives in the browser, so polling stops by itself when the
        page is closed — unlike a server-side loop, which would keep sampling
        for every session that ever opened this page.
        """
        if not self.auto:
            return
        try:
            await self._sample()
        except Exception:  # noqa: BLE001 - keep the timer alive through a blip
            pass

    @rx.event
    def toggle_auto(self):
        self.auto = not self.auto

    # ── container actions ──

    async def _act(self, name: str, path: str, keys: tuple[str, str, str]):
        """POST a container action; ``keys`` are the ok / HTTP / error messages."""
        ok_key, http_key, err_key = keys
        t = self._strings()
        try:
            async with _client() as client:
                r = await client.post(f"/containers/{name}/{path}", timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            self.message = t[err_key].format(name=name, error=exc)
            self.message_kind = "error"
            return
        if r.status_code in (204, 304):
            self.message = t[ok_key].format(name=name)
            self.message_kind = "success"
        else:
            self.message = t[http_key].format(name=name, code=r.status_code)
            self.message_kind = "error"

    @rx.event
    async def stop_container(self, name: str):
        if name in NO_STOP:
            self.message = self._strings()["msg_stop_protected"].format(name=name)
            self.message_kind = "error"
            return
        await self._act(name, "stop?t=10", ("msg_stop_ok", "msg_stop_http", "msg_stop_err"))
        yield MonitorState.refresh

    @rx.event
    async def restart_container(self, name: str):
        if name in NO_RESTART:
            self.message = self._strings()["msg_restart_protected"].format(name=name)
            self.message_kind = "error"
            return
        await self._act(
            name, "restart?t=10",
            ("msg_restart_ok", "msg_restart_http", "msg_restart_err"),
        )
        yield MonitorState.refresh

    # ── memory limit ──

    @rx.event
    def begin_edit(self, name: str, current_limit: str, ws_mb: str):
        self.menu_name = ""
        self.switch_name = ""
        self.edit_name = name
        self.edit_value = current_limit if current_limit != "0" else ""
        self.edit_current = ws_mb
        self.edit_hint = self._strings()["limit_hint"].format(mb=ws_mb)
        self.message = ""

    @rx.event
    def cancel_edit(self):
        self.edit_name = ""
        self.edit_value = ""
        self.edit_hint = ""

    @rx.event
    async def apply_limit(self, form_data: dict):
        """Set a container's memory limit without recreating it.

        ``POST /containers/<id>/update`` takes effect immediately.  Docker
        requires ``MemorySwap >= Memory``; they are set equal here, so a
        limited container cannot push the VM's shared 1 GB of swap either.

        A limit cannot actually be *removed* this way: the API reads ``0`` as
        "leave unchanged" (HTTP 200, nothing happens) and rejects ``-1`` with
        "Minimum memory limit allowed is 6MB".  Only recreating the container
        clears it, so an empty value sets the limit to the whole VM instead,
        which no container can exceed anyway.
        """
        name = self.edit_name
        raw = str(form_data.get("limit_mb", "")).strip()
        if not name:
            return
        t = self._strings()
        release = raw in ("", "0")
        if release:
            mb = (_read_meminfo().get("MemTotal", 0) // 1024) or 0
            if not mb:
                self.message = t["msg_no_memtotal"]
                self.message_kind = "error"
                return
        elif raw.isdigit():
            mb = int(raw)
        else:
            self.message = t["msg_not_number"]
            self.message_kind = "error"
            return
        if not release and mb < MIN_LIMIT_MB:
            self.message = t["msg_min_limit"].format(min=MIN_LIMIT_MB)
            self.message_kind = "error"
            return
        current = int(self.edit_current or 0)
        if not release and mb < current * 1.1:
            self.message = t["msg_below_usage"].format(
                name=name, current=f"{current:,}", wanted=f"{mb:,}",
                suggested=f"{int(current * 1.1):,}",
            )
            self.message_kind = "error"
            return
        body = {"Memory": mb * MIB, "MemorySwap": mb * MIB}
        try:
            async with _client() as client:
                r = await client.post(f"/containers/{name}/update", json=body, timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            self.message = t["msg_limit_err"].format(name=name, error=exc)
            self.message_kind = "error"
            return
        if r.status_code == 200:
            key = "msg_released" if release else "msg_limit_set"
            self.message = t[key].format(name=name, mb=f"{mb:,}")
            self.message_kind = "success"
            self.edit_name = ""
            self.edit_value = ""
            self.edit_hint = ""
        else:
            detail = ""
            try:
                detail = str(r.json().get("message", ""))[:160]
            except Exception:  # noqa: BLE001
                detail = r.text[:160]
            self.message = t["msg_limit_http"].format(
                name=name, code=r.status_code, detail=detail
            )
            self.message_kind = "error"
        yield MonitorState.refresh


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_LEVEL_BAR = {
    "ok": "bg-green-500",
    "tight": "bg-amber-500",
    "critical": "bg-red-500",
}


def language_picker() -> rx.Component:
    """Switches language without a reload; the options come from i18n.LOCALES.

    The list is built from a plain Python loop because the available languages
    are fixed when the app compiles — only the *choice* is state.
    """
    return rx.el.div(
        rx.el.button(
            rx.icon("languages", class_name="h-4 w-4"),
            rx.el.span(MonitorState.lang_label),
            rx.icon("chevron-down", class_name="h-3.5 w-3.5 opacity-60"),
            on_click=MonitorState.toggle_langs,
            title=MonitorState.t["language"],
            class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all",
        ),
        rx.cond(
            MonitorState.show_langs,
            rx.el.div(
                *[
                    rx.el.button(
                        rx.el.span(loc["label"], class_name="flex-1 text-left"),
                        rx.cond(
                            MonitorState.locale == loc["code"],
                            rx.icon("check", class_name="h-4 w-4 text-blue-600"),
                            None,
                        ),
                        on_click=MonitorState.set_locale(loc["code"]),
                        class_name="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg",
                    )
                    for loc in i18n.LOCALES
                ],
                class_name="absolute right-0 z-20 mt-2 w-44 p-1 bg-white border border-gray-200 rounded-xl shadow-lg",
            ),
            None,
        ),
        class_name="relative",
    )


def vm_card() -> rx.Component:
    """Docker VM totals: a used / cache / free bar plus the warning line."""
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.icon("server", class_name="h-5 w-5 text-blue-600"),
                rx.el.h2(
                    MonitorState.t["vm_title"],
                    class_name="text-lg font-bold text-gray-900",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.span(
                MonitorState.vm["containers"],
                class_name="text-sm text-gray-500",
            ),
            class_name="flex items-center justify-between mb-4",
        ),
        # used | cache | free
        rx.el.div(
            rx.el.div(
                class_name=rx.match(
                    MonitorState.vm["level"],
                    ("critical", "h-full bg-red-500"),
                    ("tight", "h-full bg-amber-500"),
                    "h-full bg-green-500",
                ),
                style={"width": MonitorState.vm["used_bar"]},
            ),
            rx.el.div(
                class_name="h-full bg-gray-300",
                style={"width": MonitorState.vm["cache_bar"]},
            ),
            class_name="flex h-4 w-full overflow-hidden rounded-full bg-gray-100",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.p(MonitorState.t["vm_used"], class_name="text-xs text-gray-500"),
                rx.el.p(MonitorState.vm["used"], class_name="text-xl font-bold text-gray-900"),
                class_name="",
            ),
            rx.el.div(
                rx.el.p(MonitorState.t["vm_cache"], class_name="text-xs text-gray-500"),
                rx.el.p(MonitorState.vm["cache"], class_name="text-xl font-bold text-gray-500"),
            ),
            rx.el.div(
                rx.el.p(MonitorState.t["vm_avail"], class_name="text-xs text-gray-500"),
                rx.el.p(
                    MonitorState.vm["avail"],
                    class_name=rx.match(
                        MonitorState.vm["level"],
                        ("critical", "text-xl font-bold text-red-600"),
                        ("tight", "text-xl font-bold text-amber-600"),
                        "text-xl font-bold text-green-600",
                    ),
                ),
            ),
            rx.el.div(
                rx.el.p(MonitorState.t["vm_swap"], class_name="text-xs text-gray-500"),
                rx.el.p(MonitorState.vm["swap"], class_name="text-xl font-bold text-gray-700"),
            ),
            rx.el.div(
                rx.el.p(MonitorState.t["vm_total"], class_name="text-xs text-gray-500"),
                rx.el.p(MonitorState.vm["total"], class_name="text-xl font-bold text-gray-700"),
            ),
            class_name="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mt-4",
        ),
        rx.el.div(
            rx.icon(
                rx.match(
                    MonitorState.vm["level"],
                    ("critical", "triangle-alert"),
                    ("tight", "triangle-alert"),
                    "check-circle-2",
                ),
                class_name="h-4 w-4 shrink-0 mt-0.5",
            ),
            rx.el.span(MonitorState.vm["note"], class_name="text-sm"),
            class_name=rx.match(
                MonitorState.vm["level"],
                ("critical", "flex items-start gap-2 mt-4 p-3 rounded-xl bg-red-50 text-red-700"),
                ("tight", "flex items-start gap-2 mt-4 p-3 rounded-xl bg-amber-50 text-amber-800"),
                "flex items-start gap-2 mt-4 p-3 rounded-xl bg-green-50 text-green-700",
            ),
        ),
        class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm mb-6",
    )


def row_badge(row: rx.Var[dict]) -> rx.Component:
    return rx.el.span(
        rx.el.span(
            class_name=rx.match(
                row["status"],
                ("running", "h-2 w-2 rounded-full bg-green-500"),
                ("half_dead", "h-2 w-2 rounded-full bg-red-500 animate-pulse"),
                ("starting", "h-2 w-2 rounded-full bg-amber-500 animate-pulse"),
                ("restarting", "h-2 w-2 rounded-full bg-amber-500 animate-pulse"),
                ("stopped", "h-2 w-2 rounded-full bg-gray-300"),
                "h-2 w-2 rounded-full bg-gray-300",
            ),
        ),
        rx.el.span(row["status_label"], class_name="text-xs font-bold"),
        class_name=rx.match(
            row["status"],
            ("running", "flex items-center gap-2 px-2.5 py-1 rounded-full bg-green-50 text-green-700"),
            ("half_dead", "flex items-center gap-2 px-2.5 py-1 rounded-full bg-red-50 text-red-700"),
            ("starting", "flex items-center gap-2 px-2.5 py-1 rounded-full bg-amber-50 text-amber-800"),
            ("restarting", "flex items-center gap-2 px-2.5 py-1 rounded-full bg-amber-50 text-amber-800"),
            ("stopped", "flex items-center gap-2 px-2.5 py-1 rounded-full bg-gray-100 text-gray-500"),
            "flex items-center gap-2 px-2.5 py-1 rounded-full bg-gray-100 text-gray-500",
        ),
    )


def sparkline(row: rx.Var[dict]) -> rx.Component:
    """Working-set trend, scaled to this container's own maximum."""
    return rx.cond(
        row["spark"] != "",
        rx.el.svg(
            rx.el.svg.polyline(
                points=row["spark"],
                fill="none",
                stroke="currentColor",
                stroke_width="1.5",
                stroke_linejoin="round",
            ),
            view_box="0 0 100 24",
            preserve_aspect_ratio="none",
            class_name=rx.cond(
                row["status"] == "half_dead",
                "h-6 w-24 text-red-400",
                "h-6 w-24 text-blue-400",
            ),
        ),
        rx.el.span("—", class_name="text-xs text-gray-300"),
    )


def _row_btn(label: str, icon: str, on_click, color: str) -> rx.Component:
    return rx.el.button(
        rx.icon(icon, class_name="h-3.5 w-3.5"),
        rx.el.span(label, class_name="hidden sm:inline"),
        on_click=on_click,
        class_name=f"flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all {color}",
    )


_MENU_ITEM = "flex items-start gap-2.5 w-full px-3 py-2 rounded-lg text-sm text-left"


def _menu_item(icon: str, label, hint, on_click, active=False):
    """One row of the ☰ menu: icon, label and a grey line under it."""
    return rx.el.button(
        rx.icon(icon, class_name="h-4 w-4 mt-0.5 shrink-0"),
        rx.el.div(
            rx.el.div(label, class_name="font-medium"),
            rx.el.div(hint, class_name="text-xs text-gray-400"),
            class_name="flex-1 min-w-0",
        ),
        rx.cond(active, rx.icon("check", class_name="h-4 w-4 mt-0.5 text-blue-600"), None),
        on_click=on_click,
        disabled=active,
        class_name=rx.cond(
            active,
            f"{_MENU_ITEM} text-gray-700 opacity-60 cursor-default",
            f"{_MENU_ITEM} text-gray-700 hover:bg-gray-50",
        ),
    )


def row_menu(row: rx.Var[dict]) -> rx.Component:
    """☰ menu: open the app's link, restart, switch between Dev and Non-Dev.

    The link shows its full URL on hover.  The switch items appear only for
    smart-launcher apps (``row["mode"]`` set); the current mode is ticked.
    """
    return rx.el.div(
        rx.el.button(
            rx.icon("menu", class_name="h-4 w-4"),
            on_click=MonitorState.toggle_menu(row["name"]),
            title=MonitorState.t["menu_title"],
            class_name=rx.cond(
                MonitorState.menu_name == row["name"],
                "flex items-center px-2.5 py-1.5 rounded-lg bg-gray-900 text-white",
                "flex items-center px-2.5 py-1.5 rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200",
            ),
        ),
        rx.cond(
            MonitorState.menu_name == row["name"],
            rx.el.div(
                rx.cond(
                    (row["url"] != "")
                    & (row["status"] != "stopped")
                    & (row["status"] != "starting"),
                    rx.el.a(
                        rx.icon("external-link", class_name="h-4 w-4 mt-0.5 shrink-0"),
                        rx.el.div(
                            rx.el.div(MonitorState.t["menu_open"], class_name="font-medium"),
                            rx.el.div(row["host"], class_name="text-xs text-blue-500 truncate"),
                            class_name="flex-1 min-w-0",
                        ),
                        href=row["url"],
                        target="_blank",
                        rel="noopener noreferrer",
                        title=row["url"],
                        on_click=MonitorState.close_menus,
                        class_name=f"{_MENU_ITEM} text-gray-700 hover:bg-gray-50",
                    ),
                    None,
                ),
                rx.cond(
                    row["can_restart"] != "",
                    _menu_item(
                        "rotate-cw",
                        MonitorState.t["menu_restart"],
                        MonitorState.t["menu_restart_hint"],
                        MonitorState.menu_restart(row["name"]),
                    ),
                    None,
                ),
                rx.cond(
                    row["mode"] != "",
                    rx.el.div(
                        rx.el.div(class_name="my-1 border-t border-gray-100"),
                        _menu_item(
                            "code",
                            MonitorState.t["menu_to_dev"],
                            MonitorState.t["menu_to_dev_hint"],
                            MonitorState.ask_switch(row["name"], "dev"),
                            active=row["mode"] == "dev",
                        ),
                        _menu_item(
                            "leaf",
                            MonitorState.t["menu_to_prod"],
                            MonitorState.t["menu_to_prod_hint"],
                            MonitorState.ask_switch(row["name"], "prod"),
                            active=row["mode"] == "prod",
                        ),
                    ),
                    None,
                ),
                class_name="absolute right-0 top-full mt-2 z-30 w-72 p-1 bg-white border border-gray-200 rounded-xl shadow-lg",
            ),
            None,
        ),
        class_name="relative",
    )


def switch_confirm() -> rx.Component:
    """Confirmation for a Dev ↔ Non-Dev switch, which recreates the container."""
    return rx.el.div(
        rx.el.p(MonitorState.switch_text, class_name="text-sm text-gray-700"),
        rx.el.div(
            rx.el.button(
                MonitorState.t["switch_go"],
                on_click=MonitorState.confirm_switch,
                class_name="px-3 py-1.5 rounded-lg bg-gray-900 text-white text-xs font-semibold hover:bg-black",
            ),
            rx.el.button(
                MonitorState.t["switch_cancel"],
                on_click=MonitorState.cancel_switch,
                class_name="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-xs font-semibold hover:bg-gray-200",
            ),
            class_name="flex items-center gap-2 mt-2",
        ),
        class_name="mt-3 p-3 rounded-xl bg-blue-50/60 border border-blue-100",
    )


def menu_backdrop() -> rx.Component:
    """Invisible layer behind an open menu: a click anywhere else closes it."""
    return rx.cond(
        (MonitorState.menu_name != "") | MonitorState.show_langs,
        rx.el.div(on_click=MonitorState.close_menus, class_name="fixed inset-0 z-10"),
        None,
    )


def limit_editor() -> rx.Component:
    """Inline form for the container in ``edit_name``."""
    return rx.el.form(
        rx.el.div(
            rx.el.input(
                name="limit_mb",
                default_value=MonitorState.edit_value,
                placeholder=MonitorState.t["limit_placeholder"],
                input_mode="numeric",
                auto_focus=True,
                class_name="w-40 px-3 py-1.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
            ),
            rx.el.button(
                MonitorState.t["limit_apply"],
                type="submit",
                class_name="px-3 py-1.5 rounded-lg bg-gray-900 text-white text-xs font-semibold hover:bg-black",
            ),
            rx.el.button(
                MonitorState.t["limit_cancel"],
                type="button",
                on_click=MonitorState.cancel_edit,
                class_name="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-xs font-semibold hover:bg-gray-200",
            ),
            class_name="flex items-center gap-2",
        ),
        rx.el.p(MonitorState.edit_hint, class_name="text-xs text-gray-400 mt-1"),
        on_submit=MonitorState.apply_limit,
        reset_on_submit=False,
        class_name="mt-2",
    )


def container_row(row: rx.Var[dict]) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            # name + status
            rx.el.div(
                rx.el.div(
                    rx.icon(row["icon"], class_name="h-4 w-4 text-gray-400 shrink-0"),
                    rx.el.span(row["label"], class_name="font-semibold text-gray-900 truncate"),
                    rx.cond(
                        row["kind"] == "platform",
                        rx.el.span(
                            MonitorState.t["badge_platform"],
                            class_name="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-[10px] font-bold shrink-0",
                        ),
                        None,
                    ),
                    class_name="flex items-center gap-2 min-w-0",
                ),
                rx.el.div(
                    rx.el.span(row["name"], class_name="text-xs text-gray-400 truncate"),
                    rx.cond(
                        row["host"] != "",
                        rx.el.span(
                            "→ " + row["host"],
                            class_name="text-xs text-blue-500 truncate",
                        ),
                        None,
                    ),
                    rx.cond(
                        row["restarts"] != "0",
                        rx.el.span(
                            row["restarts_label"],
                            class_name="text-xs text-amber-600 font-medium shrink-0",
                        ),
                        None,
                    ),
                    class_name="flex items-center gap-2 min-w-0",
                ),
                class_name="flex flex-col gap-0.5 min-w-0 flex-1",
            ),
            rx.el.div(
                rx.cond(
                    row["mode"] != "",
                    rx.el.span(
                        row["mode_label"],
                        title=rx.cond(
                            row["mode"] == "prod",
                            MonitorState.t["menu_to_prod_hint"],
                            MonitorState.t["menu_to_dev_hint"],
                        ),
                        class_name=rx.cond(
                            row["mode"] == "prod",
                            "px-2 py-1 rounded-full bg-teal-50 text-teal-700 text-xs font-bold",
                            "px-2 py-1 rounded-full bg-purple-50 text-purple-700 text-xs font-bold",
                        ),
                    ),
                    None,
                ),
                row_badge(row),
                class_name="flex items-center gap-2 shrink-0",
            ),
            class_name="flex items-start justify-between gap-3",
        ),
        # memory bar + numbers
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    class_name=rx.match(
                        row["status"],
                        ("half_dead", "h-full rounded-full bg-red-500"),
                        ("running", "h-full rounded-full bg-blue-500"),
                        "h-full rounded-full bg-gray-300",
                    ),
                    style={"width": row["bar"]},
                ),
                class_name="h-2 flex-1 rounded-full bg-gray-100 overflow-hidden",
            ),
            rx.el.span(
                row["ws_label"],
                class_name="w-20 text-right text-sm font-bold text-gray-900 tabular-nums",
            ),
            rx.el.span(
                row["pct"] + "%",
                class_name="w-14 text-right text-xs text-gray-400 tabular-nums",
            ),
            sparkline(row),
            class_name="flex items-center gap-3 mt-3",
        ),
        # footer: cpu / limit / uptime / actions
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    rx.icon("cpu", class_name="h-3.5 w-3.5 inline mr-1 -mt-0.5"),
                    MonitorState.t["cpu"] + " " + row["cpu"] + "%",
                    class_name="text-xs text-gray-500",
                ),
                rx.el.span(
                    rx.icon("gauge", class_name="h-3.5 w-3.5 inline mr-1 -mt-0.5"),
                    row["limit_label"],
                    class_name=rx.cond(
                        row["limit_mb"] == "0",
                        "text-xs text-gray-400",
                        "text-xs text-blue-600 font-semibold",
                    ),
                ),
                rx.el.span(row["uptime"], class_name="text-xs text-gray-400 truncate"),
                class_name="flex items-center gap-3 min-w-0",
            ),
            rx.el.div(
                _row_btn(
                    MonitorState.t["act_limit"],
                    "sliders-horizontal",
                    lambda: MonitorState.begin_edit(row["name"], row["limit_mb"], row["ws_mb"]),
                    "bg-gray-50 text-gray-600 hover:bg-gray-100",
                ),
                rx.cond(
                    row["can_stop"] != "",
                    _row_btn(
                        MonitorState.t["act_stop"],
                        "square",
                        lambda: MonitorState.stop_container(row["name"]),
                        "bg-yellow-50 text-yellow-700 hover:bg-yellow-100",
                    ),
                    None,
                ),
                row_menu(row),
                class_name="flex items-center gap-2 shrink-0",
            ),
            class_name="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-gray-50",
        ),
        rx.cond(MonitorState.edit_name == row["name"], limit_editor(), None),
        rx.cond(MonitorState.switch_name == row["name"], switch_confirm(), None),
        rx.cond(
            MonitorState.switching == row["name"],
            rx.el.div(
                rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                rx.el.span(MonitorState.t["switching"]),
                class_name="flex items-center gap-2 mt-3 text-sm text-blue-700",
            ),
            None,
        ),
        class_name=rx.match(
            row["status"],
            ("half_dead", "p-4 bg-white rounded-2xl border-2 border-red-200 shadow-sm"),
            "p-4 bg-white rounded-2xl border border-gray-100 shadow-sm",
        ),
    )


def monitor_banner() -> rx.Component:
    return rx.cond(
        MonitorState.message != "",
        rx.el.div(
            rx.icon(
                rx.match(
                    MonitorState.message_kind,
                    ("success", "check-circle-2"),
                    ("error", "circle-alert"),
                    "info",
                ),
                class_name="h-5 w-5 mr-2 shrink-0",
            ),
            rx.el.span(MonitorState.message, class_name="font-medium"),
            class_name=rx.match(
                MonitorState.message_kind,
                ("success", "flex items-center p-4 bg-green-50 text-green-800 rounded-xl border border-green-100 mb-6"),
                ("error", "flex items-center p-4 bg-red-50 text-red-800 rounded-xl border border-red-100 mb-6"),
                "flex items-center p-4 bg-blue-50 text-blue-800 rounded-xl border border-blue-100 mb-6",
            ),
        ),
        None,
    )


def poll_timer() -> rx.Component:
    """Invisible clock that asks for a new sample every POLL_SECONDS."""
    return rx.cond(
        MonitorState.auto,
        rx.moment(
            interval=int(POLL_SECONDS * 1000),
            on_change=lambda _date: MonitorState.tick(),
            class_name="hidden",
        ),
        None,
    )


def monitor() -> rx.Component:
    return rx.el.main(
        poll_timer(),
        menu_backdrop(),
        rx.el.div(
            # header
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.icon("activity", class_name="h-8 w-8 text-blue-600"),
                        rx.el.h1(
                            MonitorState.t["page_title"],
                            class_name="text-3xl font-black text-gray-900",
                        ),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.div(
                        language_picker(),
                        rx.el.button(
                            rx.cond(
                                MonitorState.auto,
                                rx.icon("zap", class_name="h-4 w-4 text-green-600"),
                                rx.icon("zap-off", class_name="h-4 w-4"),
                            ),
                            rx.el.span(
                                rx.cond(
                                    MonitorState.auto,
                                    MonitorState.t["auto_on"],
                                    MonitorState.t["auto_off"],
                                ),
                            ),
                            on_click=MonitorState.toggle_auto,
                            class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all",
                        ),
                        rx.el.button(
                            rx.cond(
                                MonitorState.loading,
                                rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                                rx.icon("refresh-cw", class_name="h-4 w-4"),
                            ),
                            rx.el.span(MonitorState.t["refresh"]),
                            on_click=MonitorState.refresh,
                            disabled=MonitorState.loading,
                            class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all disabled:opacity-50",
                        ),
                        rx.link(
                            rx.el.div(
                                rx.icon("arrow-left", class_name="h-4 w-4"),
                                rx.el.span(MonitorState.t["back_to_store"]),
                                class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all",
                            ),
                            href="/",
                        ),
                        class_name="flex flex-wrap items-center gap-2",
                    ),
                    class_name="flex flex-wrap items-center justify-between gap-3 mb-2",
                ),
                rx.el.p(MonitorState.subtitle, class_name="text-gray-500"),
                class_name="mb-8",
            ),
            monitor_banner(),
            rx.cond(
                MonitorState.vm["error"] != "",
                rx.el.div(
                    rx.icon("triangle-alert", class_name="h-5 w-5 mr-2"),
                    rx.el.span(MonitorState.vm["error"], class_name="font-medium"),
                    class_name="flex items-center p-4 bg-red-50 text-red-800 rounded-xl border border-red-100 mb-6",
                ),
                vm_card(),
            ),
            rx.cond(
                MonitorState.rows.length() > 0,
                rx.el.div(
                    rx.foreach(MonitorState.rows, container_row),
                    class_name="grid grid-cols-1 xl:grid-cols-2 gap-4",
                ),
                rx.el.div(
                    rx.icon("loader-circle", class_name="h-10 w-10 text-gray-300 animate-spin mb-4"),
                    rx.el.p(
                        MonitorState.t["loading_rows"],
                        class_name="text-gray-400 font-medium",
                    ),
                    class_name="flex flex-col items-center justify-center h-64 border-2 border-dashed border-gray-100 rounded-3xl",
                ),
            ),
            class_name="max-w-6xl mx-auto py-12 px-6",
        ),
        class_name="min-h-screen bg-gray-50 font-['Inter']",
    )
