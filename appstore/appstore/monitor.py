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

This module is self-contained on purpose: ``appstore.py`` imports it, so it
must not import ``appstore.py`` back.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import reflex as rx

CATALOG_PATH = os.environ.get("CATALOG_PATH", "/app/data/appstore_catalog.json")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")

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


def _status_of(insp: dict | None, listed_state: str) -> tuple[str, str]:
    """``(status, label)``, including the half-dead case.

    ``OOMKilled`` stays true from the moment the OOM killer took a process in
    the container until it is started again, so ``running`` + ``OOMKilled``
    means "something inside was killed and never came back".
    """
    state = (insp or {}).get("State") or {}
    status = str(state.get("Status") or listed_state or "unknown")
    if status == "restarting":
        return "restarting", "重啟中"
    if status == "running":
        if state.get("OOMKilled"):
            return "half_dead", "OOM 半死"
        return "running", "執行中"
    if status in ("exited", "created", "dead", "paused", "removing"):
        return "stopped", "已停止"
    return "unknown", status


async def collect(
    prev_cpu: dict[str, list[int]],
    hist: dict[str, list[int]],
    meta: dict[str, dict[str, str]],
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
        return rows, {"error": "Docker socket 無法存取"}, next_cpu

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

    total_bytes = total_kb * 1024
    for name, stats, insp in probes:
        item = listed_by_name.get(name, {})
        status, label = _status_of(insp, str(item.get("State") or ""))
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
                "uptime": str(item.get("Status") or ""),
                "limit_mb": str(limit // MIB),
                "limit_label": f"{limit // MIB:,} MB" if limit else "無上限",
                "spark": _spark(series),
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
    note = "記憶體充足。"
    if avail_mb < CRITICAL_MB:
        level = "critical"
        note = (
            f"只剩 {avail_mb:,} MB 可用：下一次通話或 Whisper 載入（約 1.7 GB）"
            "很可能觸發全域 OOM，殺掉當下最肥的行程（不一定是兇手）。"
        )
    elif avail_mb < TIGHT_MB:
        level = "tight"
        note = (
            f"可用記憶體只有 {avail_mb:,} MB：再開一個吃記憶體的 app 就有 OOM 風險。"
        )
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
        "containers": str(len(rows)),
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

    # Memory-limit editor (one row at a time).
    edit_name: str = ""
    edit_value: str = ""
    edit_current: str = ""

    # Backend-only: CPU samples to diff against, and the sparkline history.
    _cpu: dict[str, list[int]] = {}
    _hist: dict[str, list[int]] = {}

    async def _sample(self):
        rows, vm, cpu = await collect(self._cpu, self._hist, _catalog_meta())
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
            self.message = f"讀取失敗：{exc}"
            self.message_kind = "error"
        self.loading = False

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

    async def _act(self, name: str, verb: str, path: str, ok_label: str):
        try:
            async with _client() as client:
                r = await client.post(f"/containers/{name}/{path}", timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            self.message = f"{verb} {name} 失敗：{exc}"
            self.message_kind = "error"
            return
        if r.status_code in (204, 304):
            self.message = f"{name} {ok_label}。"
            self.message_kind = "success"
        else:
            self.message = f"{verb} {name} 失敗（HTTP {r.status_code}）。"
            self.message_kind = "error"

    @rx.event
    async def stop_container(self, name: str):
        if name in NO_STOP:
            self.message = f"{name} 是平台容器，停掉會讓這個頁面無法使用。"
            self.message_kind = "error"
            return
        await self._act(name, "停止", "stop?t=10", "已停止")
        yield MonitorState.refresh

    @rx.event
    async def restart_container(self, name: str):
        if name in NO_RESTART:
            self.message = f"{name} 無法從自己的頁面重啟（會中斷這個連線）。"
            self.message_kind = "error"
            return
        await self._act(name, "重啟", "restart?t=10", "已重啟")
        yield MonitorState.refresh

    # ── memory limit ──

    @rx.event
    def begin_edit(self, name: str, current_limit: str, ws_mb: str):
        self.edit_name = name
        self.edit_value = current_limit if current_limit != "0" else ""
        self.edit_current = ws_mb
        self.message = ""

    @rx.event
    def cancel_edit(self):
        self.edit_name = ""
        self.edit_value = ""

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
        release = raw in ("", "0")
        if release:
            mb = (_read_meminfo().get("MemTotal", 0) // 1024) or 0
            if not mb:
                self.message = "讀不到 VM 總記憶體，無法解除上限。"
                self.message_kind = "error"
                return
        elif raw.isdigit():
            mb = int(raw)
        else:
            self.message = "請輸入 MB 數字，或留空代表解除上限。"
            self.message_kind = "error"
            return
        if not release and mb < 128:
            self.message = "上限至少 128 MB。"
            self.message_kind = "error"
            return
        current = int(self.edit_current or 0)
        if not release and mb < current * 1.1:
            self.message = (
                f"{name} 目前就用了 {current:,} MB，上限設 {mb:,} MB 會立刻被 OOM 殺掉。"
                f"請設在 {int(current * 1.1):,} MB 以上。"
            )
            self.message_kind = "error"
            return
        body = {"Memory": mb * MIB, "MemorySwap": mb * MIB}
        try:
            async with _client() as client:
                r = await client.post(f"/containers/{name}/update", json=body, timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            self.message = f"設定 {name} 上限失敗：{exc}"
            self.message_kind = "error"
            return
        if r.status_code == 200:
            self.message = (
                f"{name} 上限放寬到 VM 總量 {mb:,} MB（等同解除；Docker 無法在不重建容器的"
                "情況下真正移除上限，要完全移除請重新安裝這個 app）。" if release
                else f"{name} 記憶體上限設為 {mb:,} MB（超過就只殺它自己）。"
            )
            self.message_kind = "success"
            self.edit_name = ""
            self.edit_value = ""
        else:
            detail = ""
            try:
                detail = str(r.json().get("message", ""))[:160]
            except Exception:  # noqa: BLE001
                detail = r.text[:160]
            self.message = f"設定 {name} 上限失敗（HTTP {r.status_code}）：{detail}"
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


def vm_card() -> rx.Component:
    """Docker VM totals: a used / cache / free bar plus the warning line."""
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.icon("server", class_name="h-5 w-5 text-blue-600"),
                rx.el.h2("Docker VM 記憶體", class_name="text-lg font-bold text-gray-900"),
                class_name="flex items-center gap-2",
            ),
            rx.el.span(
                MonitorState.vm["containers"] + " 個容器",
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
                rx.el.p("已用", class_name="text-xs text-gray-500"),
                rx.el.p(MonitorState.vm["used"], class_name="text-xl font-bold text-gray-900"),
                class_name="",
            ),
            rx.el.div(
                rx.el.p("快取（可回收）", class_name="text-xs text-gray-500"),
                rx.el.p(MonitorState.vm["cache"], class_name="text-xl font-bold text-gray-500"),
            ),
            rx.el.div(
                rx.el.p("可用", class_name="text-xs text-gray-500"),
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
                rx.el.p("Swap", class_name="text-xs text-gray-500"),
                rx.el.p(MonitorState.vm["swap"], class_name="text-xl font-bold text-gray-700"),
            ),
            rx.el.div(
                rx.el.p("總量", class_name="text-xs text-gray-500"),
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


def limit_editor(row: rx.Var[dict]) -> rx.Component:
    """Inline form for one container's memory limit."""
    return rx.el.form(
        rx.el.div(
            rx.el.input(
                name="limit_mb",
                default_value=MonitorState.edit_value,
                placeholder="MB（留空 = 放寬到 VM 總量）",
                input_mode="numeric",
                auto_focus=True,
                class_name="w-40 px-3 py-1.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
            ),
            rx.el.button(
                "套用",
                type="submit",
                class_name="px-3 py-1.5 rounded-lg bg-gray-900 text-white text-xs font-semibold hover:bg-black",
            ),
            rx.el.button(
                "取消",
                type="button",
                on_click=MonitorState.cancel_edit,
                class_name="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-xs font-semibold hover:bg-gray-200",
            ),
            class_name="flex items-center gap-2",
        ),
        rx.el.p(
            "目前用量 " + row["ws_mb"] + " MB。有上限時，超量的是這個容器自己被殺，"
            "不會讓 kernel 挑整台 VM 最肥的行程下手。",
            class_name="text-xs text-gray-400 mt-1",
        ),
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
                            "平台",
                            class_name="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-[10px] font-bold shrink-0",
                        ),
                        None,
                    ),
                    class_name="flex items-center gap-2 min-w-0",
                ),
                rx.el.div(
                    rx.el.span(row["name"], class_name="text-xs text-gray-400 truncate"),
                    rx.cond(
                        row["restarts"] != "0",
                        rx.el.span(
                            "重啟 " + row["restarts"] + " 次",
                            class_name="text-xs text-amber-600 font-medium shrink-0",
                        ),
                        None,
                    ),
                    class_name="flex items-center gap-2 min-w-0",
                ),
                class_name="flex flex-col gap-0.5 min-w-0 flex-1",
            ),
            row_badge(row),
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
                    "CPU " + row["cpu"] + "%",
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
                    "上限",
                    "sliders-horizontal",
                    lambda: MonitorState.begin_edit(row["name"], row["limit_mb"], row["ws_mb"]),
                    "bg-gray-50 text-gray-600 hover:bg-gray-100",
                ),
                rx.cond(
                    row["can_restart"] != "",
                    _row_btn(
                        "重啟",
                        "rotate-cw",
                        lambda: MonitorState.restart_container(row["name"]),
                        rx.cond(
                            row["status"] == "half_dead",
                            "bg-red-600 text-white hover:bg-red-700",
                            "bg-blue-50 text-blue-700 hover:bg-blue-100",
                        ),
                    ),
                    None,
                ),
                rx.cond(
                    row["can_stop"] != "",
                    _row_btn(
                        "停止",
                        "square",
                        lambda: MonitorState.stop_container(row["name"]),
                        "bg-yellow-50 text-yellow-700 hover:bg-yellow-100",
                    ),
                    None,
                ),
                class_name="flex items-center gap-2 shrink-0",
            ),
            class_name="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-gray-50",
        ),
        rx.cond(MonitorState.edit_name == row["name"], limit_editor(row), None),
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
        rx.el.div(
            # header
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.icon("activity", class_name="h-8 w-8 text-blue-600"),
                        rx.el.h1(
                            "容器記憶體監控",
                            class_name="text-3xl font-black text-gray-900",
                        ),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.div(
                        rx.el.button(
                            rx.cond(
                                MonitorState.auto,
                                rx.icon("zap", class_name="h-4 w-4 text-green-600"),
                                rx.icon("zap-off", class_name="h-4 w-4"),
                            ),
                            rx.el.span(
                                rx.cond(MonitorState.auto, "自動更新中", "已暫停"),
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
                            rx.el.span("更新"),
                            on_click=MonitorState.refresh,
                            disabled=MonitorState.loading,
                            class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all disabled:opacity-50",
                        ),
                        rx.link(
                            rx.el.div(
                                rx.icon("arrow-left", class_name="h-4 w-4"),
                                rx.el.span("App Store"),
                                class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all",
                            ),
                            href="/",
                        ),
                        class_name="flex flex-wrap items-center gap-2",
                    ),
                    class_name="flex flex-wrap items-center justify-between gap-3 mb-2",
                ),
                rx.el.p(
                    "每 4 秒取樣一次。記憶體用的是 working set（扣掉可回收的檔案快取），"
                    "與 docker stats 相同。",
                    class_name="text-gray-500",
                ),
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
                    rx.el.p("讀取容器資料…", class_name="text-gray-400 font-medium"),
                    class_name="flex flex-col items-center justify-center h-64 border-2 border-dashed border-gray-100 rounded-3xl",
                ),
            ),
            class_name="max-w-6xl mx-auto py-12 px-6",
        ),
        class_name="min-h-screen bg-gray-50 font-['Inter']",
    )
