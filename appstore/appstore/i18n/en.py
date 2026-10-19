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
    "st_starting": "Starting…",
    "st_stopped": "Stopped",
    "badge_platform": "platform",
    "restarts": "{count} restarts",
    "cpu": "CPU",
    "no_limit": "no limit",
    "act_limit": "Limit",
    "act_stop": "Stop",

    # ── dev / non-dev menu ──
    "menu_title": "Actions",
    "menu_open": "Open app link",
    "menu_restart": "Restart",
    "menu_restart_hint": "Stop and start the container",
    "menu_to_dev": "Switch to Dev",
    "menu_to_dev_hint": "Hot reload; Vite dev server, more memory",
    "menu_to_prod": "Switch to Non-Dev",
    "menu_to_prod_hint": "Prebuilt frontend, no hot reload, less memory",
    "mode_dev": "Dev",
    "mode_prod": "Non-Dev",
    "switch_confirm": "Switch {name} to {mode}? The container is recreated with the same settings and the app reinstalls, which takes about 1–2 minutes. Data in volumes and mounted folders is kept.",
    "switch_go": "Switch",
    "switch_cancel": "Cancel",
    "switching": "Recreating the container…",
    "msg_switch_working": "Switching {name} to {mode}…",
    "msg_switch_started": "{name} now runs as {mode}; it is reinstalling and will be back in about 1–2 minutes.",
    "msg_switch_failed": "Switching {name} failed; the old container was restored: {error}",
    "msg_switch_busy": "Another switch is still running.",

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

    # ── shared ──
    "cancel": "Cancel",
    "list_sep": ", ",

    # ══ App Store page (appstore.py) ══
    "store_subtitle": "Browse, install, and manage Reflex apps deployed behind re-ddns.",
    "store_memory": "Memory",
    "store_empty": "No apps in the catalog yet.",
    "store_empty_hint": "Add entries to data/appstore_catalog.json.",

    # ── app card (st_running / st_stopped above are shared) ──
    "st_not_installed": "Not installed",
    "st_unknown": "Unknown",
    "store_open": "Open",
    "store_start": "Start",
    "store_stop": "Stop",
    "store_install": "Install",
    "store_uninstall": "Uninstall",
    "store_dev": "Dev",
    "store_installing": "Installing",
    "store_uninstalling": "Uninstalling",
    "store_view_progress": "View progress",
    "store_install_failed": "Install failed",
    "store_uninstall_failed": "Uninstall failed",

    # ── banner ({name} is the container in started/stopped/not_installed_yet,
    #    the app in installed/uninstalled) ──
    "store_started": "Started {name}.",
    "store_stopped": "Stopped {name}.",
    "store_no_socket_start": "Docker socket unavailable — cannot start the container.",
    "store_no_socket_stop": "Docker socket unavailable — cannot stop the container.",
    "store_not_installed_yet": "{name} is not installed yet. Use Install first.",
    "store_start_failed": "Start failed (HTTP {code}).",
    "store_stop_failed": "Stop failed (HTTP {code}).",
    "store_installed": "{name} is installed!",
    "store_uninstalled": "{name} was removed: its container, DNS record, nginx config and TLS certificate are gone.",

    # ── settings form (apps whose catalog entry has an env_schema) ──
    "env_title": "Set up {name}",
    "env_intro": (
        "This app needs a few settings to work. They are passed to its container "
        "as environment variables at install time and written to its .env."
    ),
    "env_missing": "Please fill in the required fields: {fields}",

    # ── Dev form ──
    "dev_title": "Dev mode — {name}",
    "dev_intro": (
        "Enter the absolute path of a local project. The container bind-mounts that "
        "folder instead of cloning it from git, and runs your app in the right Linux "
        "environment. Reflex hot-reloads when you change the code."
    ),
    "dev_path_label": "Local project path",
    "dev_path_placeholder": "Type / or ~/ and press Tab",
    "dev_path_hint": "Absolute path on the Docker host (the folder with pyproject.toml)",
    "dev_path_keys": " · Tab completes · ↑↓ select · Esc hides the list",
    "dev_path_no_browse": " · host folders are not visible, so there is no completion",
    "dev_more": "…{count} more; type a few more letters to narrow it down",
    "dev_install": "Dev Install",
    "dev_err_empty": "Enter the local project path.",
    "dev_err_missing": "Folder not found: {path}",
    "dev_st_relative": "Enter an absolute path (starting with / or ~/)",
    "dev_st_outside": "No completion here (only folders under {root} are visible); the path is used as typed",
    "dev_st_not_found": "No such folder",
    "dev_st_reflex": "✓ Reflex project: rxconfig.py found",
    "dev_st_reflex_sub": "✓ Reflex project (subfolder {sub}): rxconfig.py found",
    "dev_st_python": "✓ pyproject.toml found",
    "dev_st_python_sub": "✓ pyproject.toml found (subfolder {sub})",
    "dev_st_none": "No pyproject.toml in this folder; keep going down",
    "dev_st_none_sub": "No pyproject.toml in this folder (subfolder {sub}); keep going down",

    # ── uninstall confirmation ({container} is shown as code) ──
    "un_title": "Uninstall {name}",
    "un_body": (
        "Stops and deletes the container {container}, then removes its DNS record, "
        "nginx config and TLS certificate. Once removed it no longer uses memory; "
        "you can install it again at any time."
    ),
    "un_running": "This app is running now; it is stopped first, then removed.",
    "un_remove_data": "Also delete its data (volumes and shared-collection folders)",
    "un_keep_hint": (
        "Left unticked, they are kept and a reinstall uses the data again. Local "
        "folders mounted in Dev mode are never touched."
    ),
    "un_confirm": "Uninstall",

    # ── progress panel ──
    "job_title_install": "Install {name}",
    "job_title_uninstall": "Uninstall {name}",
    "job_busy_install": "Installing… (you can close this window; the install carries on in the background)",
    "job_busy_uninstall": "Uninstalling… (you can close this window; the removal carries on in the background)",
    "job_done": "Done",
    # said by the App Store itself
    "job_sending_install": "Sending the install request…",
    "job_sending_dev_install": "Sending the dev-mode install request…",
    "job_sending_uninstall": "Sending the uninstall request…",
    "job_install_refused": "Could not start the install (HTTP {code}): {detail}",
    "job_dev_install_refused": "Could not start the dev-mode install (HTTP {code}): {detail}",
    "job_uninstall_refused": "Could not start the uninstall (HTTP {code}): {detail}",
    "job_unreachable": "Cannot reach re-ddns: {error}",
    # said by re-ddns: job_<msg> for each key of _MESSAGES in
    # re_ddns/api/install_manager.py
    "job_queued": "Queued…",
    "job_queued_dev": "Queued (dev mode)…",
    "job_building_image": "First install: building the launcher image (this takes a few minutes)…",
    "job_image_context_missing": "Launcher build files not found: {path}",
    "job_image_build_http": "Building the launcher image failed (HTTP {code})",
    "job_image_build_failed": "Building the launcher image failed: {error}",
    "job_image_build_exception": "Building the launcher image raised an error: {error}",
    "job_image_missing": "The launcher image is still missing after the build.",
    "job_creating": "Creating the {name} container…",
    "job_creating_dev": "Creating the {name} dev container…",
    "job_create_failed": "Creating the container failed (HTTP {code})",
    "job_start_failed": "Starting the container failed (HTTP {code}): {error}",
    "job_installing": "Installing {name}…",
    "job_installing_dev": "Installing {name} in dev mode…",
    "job_phase": "{name}: {phase}",
    "job_installed": "{name} is installed and running!",
    "job_container_exited": "The {name} container exited (exit code {code}).",
    "job_install_start_failed": "The install could not start: {error}",
    "job_dev_install_start_failed": "The dev-mode install could not start: {error}",
    "job_storage_invalid": "Invalid shared-storage declaration: {error}",
    "job_stop_waiting": "{name}: waiting for the container to exit… ({seconds} s)",
    "job_uninstalled": "{name} was removed.",
    "job_uninstall_failed": "Removing {name} failed: {error}",
    # the {phase} of job_phase
    "phase_queued": "Queued",
    "phase_preparing_image": "Preparing the launcher image",
    "phase_building_image": "Building the launcher image",
    "phase_creating": "Creating the container",
    "phase_starting_container": "Starting the container",
    "phase_dev_mount": "Using the locally mounted source",
    "phase_apt_packages": "Installing system packages",
    "phase_cloning": "Downloading the code",
    "phase_cloning_deps": "Downloading dependency repos",
    "phase_installing_deps": "Installing dependencies",
    "phase_initializing": "Initializing Reflex",
    "phase_registering": "Registering DNS / nginx",
    "phase_starting_app": "Starting the app",
    "phase_running": "Done; the app is running",
    "phase_stopping": "Stopping the container",
    "phase_removing_container": "Deleting the container",
    "phase_unregistering": "Removing the registration and DNS record",
    "phase_nginx": "Updating the nginx config",
    "phase_cert": "Removing the TLS certificate",
    "phase_data": "Deleting the data volumes",
    "phase_done": "Done; removed",
}
