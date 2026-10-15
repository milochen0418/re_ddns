"""Español."""

STRINGS: dict[str, str] = {
    # ── marco de la página ──
    "page_title": "Memoria de contenedores",
    "subtitle": (
        "Se mide cada {seconds} s. La memoria es el working set — lo que no se puede "
        "liberar — la misma cifra que da docker stats."
    ),
    "auto_on": "En vivo",
    "auto_off": "En pausa",
    "refresh": "Actualizar",
    "back_to_store": "App Store",
    "loading_rows": "Leyendo contenedores…",
    "language": "Idioma",

    # ── tarjeta de la VM ──
    "vm_title": "Memoria de la VM de Docker",
    "vm_containers": "{count} contenedores",
    "vm_used": "En uso",
    "vm_cache": "Caché (liberable)",
    "vm_avail": "Disponible",
    "vm_swap": "Swap",
    "vm_total": "Total",
    "note_ok": "Hay memoria de sobra.",
    "note_tight": (
        "Solo quedan {avail} MB disponibles: abrir otra app que consuma memoria "
        "arriesga un OOM."
    ),
    "note_critical": (
        "Solo quedan {avail} MB disponibles: la próxima llamada o la carga de Whisper "
        "(unos 1,7 GB) puede provocar un OOM de toda la VM, que mata el proceso más "
        "grande en ese momento, no necesariamente el culpable."
    ),
    "socket_error": "No se puede acceder al socket de Docker",

    # ── fila de cada contenedor ──
    "st_running": "En ejecución",
    "st_half_dead": "Medio caído (OOM)",
    "st_restarting": "Reiniciando",
    "st_stopped": "Detenido",
    "badge_platform": "plataforma",
    "restarts": "{count} reinicios",
    "cpu": "CPU",
    "no_limit": "sin límite",
    "act_limit": "Límite",
    "act_restart": "Reiniciar",
    "act_stop": "Detener",

    # ── editor del límite de memoria ──
    "limit_placeholder": "MB (vacío = ampliar al total de la VM)",
    "limit_apply": "Aplicar",
    "limit_cancel": "Cancelar",
    "limit_hint": (
        "Ahora usa {mb} MB. Con un límite, es este contenedor el que muere cuando se "
        "desborda, en vez de que el kernel elija el proceso más grande de la VM."
    ),

    # ── mensajes ──
    "msg_read_failed": "No se pudieron leer los datos: {error}",
    "msg_stop_protected": "{name} es un contenedor de plataforma; detenerlo rompería esta página.",
    "msg_restart_protected": "{name} no puede reiniciarse desde su propia página (sirve esta conexión).",
    "msg_stop_ok": "{name} detenido.",
    "msg_stop_http": "No se pudo detener {name} (HTTP {code}).",
    "msg_stop_err": "No se pudo detener {name}: {error}",
    "msg_restart_ok": "{name} reiniciado.",
    "msg_restart_http": "No se pudo reiniciar {name} (HTTP {code}).",
    "msg_restart_err": "No se pudo reiniciar {name}: {error}",
    "msg_no_memtotal": "No se puede leer la memoria total de la VM, así que no se puede liberar el límite.",
    "msg_not_number": "Escribe un número de MB, o déjalo vacío para liberar el límite.",
    "msg_min_limit": "El límite debe ser de al menos {min} MB.",
    "msg_below_usage": (
        "{name} está usando {current} MB ahora mismo; un límite de {wanted} MB lo "
        "mataría de inmediato por OOM. Usa {suggested} MB o más."
    ),
    "msg_released": (
        "El límite de {name} se amplió al total de la VM, {mb} MB (en la práctica es "
        "como no tener límite: Docker no puede quitarlo de verdad sin recrear el "
        "contenedor; para eso reinstala la app)."
    ),
    "msg_limit_set": "{name} queda limitado a {mb} MB; si se pasa, solo muere él.",
    "msg_limit_err": "No se pudo fijar el límite de {name}: {error}",
    "msg_limit_http": "No se pudo fijar el límite de {name} (HTTP {code}): {detail}",
}
