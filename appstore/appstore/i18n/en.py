"""English — the reference locale.

Every other locale is merged over this one, so this file defines the full set
of keys and is the only one that must be complete.  Keys ending in a template
are formatted with ``str.format(**kwargs)``; the placeholder names are part of
the contract and must survive translation (the text around them need not).
"""

STRINGS: dict[str, str] = {
    # ── page chrome ──
    "page_title": "Container Memory",
    "subtitle": (
        "Sampled every {seconds} s. Memory is the working set — what cannot be "
        "reclaimed — the same figure docker stats reports."
    ),
    "auto_on": "Live",
    "auto_off": "Paused",
    "refresh": "Refresh",
    "back_to_store": "App Store",
    "loading_rows": "Reading containers…",
    "language": "Language",

    # ── Docker VM card ──
    "vm_title": "Docker VM memory",
    "vm_containers": "{count} containers",
    "vm_used": "Used",
    "vm_cache": "Cache (reclaimable)",
    "vm_avail": "Available",
    "vm_swap": "Swap",
    "vm_total": "Total",
    "note_ok": "Plenty of memory free.",
    "note_tight": (
        "Only {avail} MB available: opening one more memory-hungry app risks an OOM."
    ),
    "note_critical": (
        "Only {avail} MB available: the next call or Whisper load (about 1.7 GB) "
        "is likely to trigger a VM-wide OOM, which kills the largest process at "
        "that moment — not necessarily the one at fault."
    ),
    "socket_error": "Cannot reach the Docker socket",

    # ── per-container row ──
    "st_running": "Running",
    "st_half_dead": "OOM half-dead",
    "st_restarting": "Restarting",
    "st_stopped": "Stopped",
    "badge_platform": "platform",
    "restarts": "{count} restarts",
    "cpu": "CPU",
    "no_limit": "no limit",
    "act_limit": "Limit",
    "act_restart": "Restart",
    "act_stop": "Stop",

    # ── memory-limit editor ──
    "limit_placeholder": "MB (empty = widen to VM total)",
    "limit_apply": "Apply",
    "limit_cancel": "Cancel",
    "limit_hint": (
        "Using {mb} MB now. With a limit, this container is the one killed when it "
        "runs away, instead of the kernel picking the largest process in the VM."
    ),

    # ── messages ──
    "msg_read_failed": "Could not read the data: {error}",
    "msg_stop_protected": "{name} is a platform container; stopping it would break this page.",
    "msg_restart_protected": "{name} cannot restart itself from its own page (it serves this connection).",
    "msg_stop_ok": "{name} stopped.",
    "msg_stop_http": "Stopping {name} failed (HTTP {code}).",
    "msg_stop_err": "Stopping {name} failed: {error}",
    "msg_restart_ok": "{name} restarted.",
    "msg_restart_http": "Restarting {name} failed (HTTP {code}).",
    "msg_restart_err": "Restarting {name} failed: {error}",
    "msg_no_memtotal": "Cannot read the VM's total memory, so the limit cannot be released.",
    "msg_not_number": "Enter a number of MB, or leave it empty to release the limit.",
    "msg_min_limit": "A limit must be at least {min} MB.",
    "msg_below_usage": (
        "{name} is using {current} MB right now; a {wanted} MB limit would get it "
        "OOM-killed immediately. Use {suggested} MB or more."
    ),
    "msg_released": (
        "{name}'s limit widened to the VM total of {mb} MB (the same as none in "
        "practice: Docker cannot truly remove a limit without recreating the "
        "container — reinstall the app for that)."
    ),
    "msg_limit_set": "{name} is now limited to {mb} MB; going over kills only itself.",
    "msg_limit_err": "Setting {name}'s limit failed: {error}",
    "msg_limit_http": "Setting {name}'s limit failed (HTTP {code}): {detail}",
}
