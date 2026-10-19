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
    "st_starting": "Arrancando…",
    "st_stopped": "Detenido",
    "badge_platform": "plataforma",
    "restarts": "{count} reinicios",
    "cpu": "CPU",
    "no_limit": "sin límite",
    "act_limit": "Límite",
    "act_stop": "Detener",

    # ── menú Dev / Non-Dev ──
    "menu_title": "Acciones",
    "menu_open": "Abrir enlace de la app",
    "menu_restart": "Reiniciar",
    "menu_restart_hint": "Detiene y vuelve a arrancar el contenedor",
    "menu_to_dev": "Cambiar a Dev",
    "menu_to_dev_hint": "Recarga en caliente; servidor Vite, más memoria",
    "menu_to_prod": "Cambiar a Non-Dev",
    "menu_to_prod_hint": "Frontend precompilado, sin recarga en caliente, menos memoria",
    "mode_dev": "Dev",
    "mode_prod": "Non-Dev",
    "switch_confirm": "¿Cambiar {name} a {mode}? El contenedor se recrea con la misma configuración y la app se reinstala, lo que tarda 1–2 minutos. Se conservan los datos de los volúmenes y de las carpetas montadas.",
    "switch_go": "Cambiar",
    "switch_cancel": "Cancelar",
    "switching": "Recreando el contenedor…",
    "msg_switch_working": "Cambiando {name} a {mode}…",
    "msg_switch_started": "{name} ahora funciona en {mode}; se está reinstalando y volverá en 1–2 minutos.",
    "msg_switch_failed": "No se pudo cambiar {name}; se restauró el contenedor anterior: {error}",
    "msg_switch_busy": "Ya hay otro cambio en curso.",

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

    # ── compartido ──
    "cancel": "Cancelar",
    "list_sep": ", ",

    # ══ página del App Store ══
    "store_subtitle": "Explora, instala y gestiona las apps de Reflex desplegadas detrás de re-ddns.",
    "store_memory": "Memoria",
    "store_empty": "Todavía no hay apps en el catálogo.",
    "store_empty_hint": "Añade entradas a data/appstore_catalog.json.",

    # ── tarjeta de cada app ──
    "st_not_installed": "No instalado",
    "st_unknown": "Desconocido",
    "store_open": "Abrir",
    "store_start": "Iniciar",
    "store_stop": "Detener",
    "store_install": "Instalar",
    "store_uninstall": "Desinstalar",
    "store_dev": "Dev",
    "store_installing": "Instalando",
    "store_uninstalling": "Desinstalando",
    "store_view_progress": "Ver progreso",
    "store_install_failed": "La instalación falló",
    "store_uninstall_failed": "La desinstalación falló",

    # ── mensajes ──
    "store_started": "{name} iniciado.",
    "store_stopped": "{name} detenido.",
    "store_no_socket_start": "No se puede acceder al socket de Docker: no se puede iniciar el contenedor.",
    "store_no_socket_stop": "No se puede acceder al socket de Docker: no se puede detener el contenedor.",
    "store_not_installed_yet": "{name} todavía no está instalado. Usa Instalar primero.",
    "store_start_failed": "No se pudo iniciar (HTTP {code}).",
    "store_stop_failed": "No se pudo detener (HTTP {code}).",
    "store_installed": "¡Instalación de {name} completada!",
    "store_uninstalled": "Se desinstaló {name}: ya no están su contenedor, su registro DNS, su configuración de nginx ni su certificado TLS.",

    # ── formulario de ajustes ──
    "env_title": "Configurar {name}",
    "env_intro": (
        "Esta app necesita algunos ajustes para funcionar. Se pasan a su contenedor "
        "como variables de entorno al instalarla y se escriben en su .env."
    ),
    "env_missing": "Rellena los campos obligatorios: {fields}",

    # ── formulario Dev ──
    "dev_title": "Modo Dev — {name}",
    "dev_intro": (
        "Escribe la ruta absoluta de un proyecto local. El contenedor monta esa carpeta "
        "(bind mount) en vez de clonarla con git y ejecuta tu app en el entorno Linux "
        "adecuado. Reflex recarga en caliente cuando cambias el código."
    ),
    "dev_path_label": "Ruta del proyecto local",
    "dev_path_placeholder": "Escribe / o ~/ y pulsa Tab",
    "dev_path_hint": "Ruta absoluta en el host de Docker (la carpeta con pyproject.toml)",
    "dev_path_keys": " · Tab completa · ↑↓ elige · Esc oculta la lista",
    "dev_path_no_browse": " · no se ven las carpetas del host, así que no hay autocompletado",
    "dev_more": "…{count} más; escribe unas letras más para acotar",
    "dev_install": "Instalar en Dev",
    "dev_err_empty": "Escribe la ruta del proyecto local.",
    "dev_err_missing": "No se encuentra la carpeta: {path}",
    "dev_st_relative": "Escribe una ruta absoluta (que empiece por / o ~/)",
    "dev_st_outside": "Aquí no hay autocompletado (solo se ven las carpetas bajo {root}); se usa la ruta tal cual",
    "dev_st_not_found": "No existe esa carpeta",
    "dev_st_reflex": "✓ Proyecto Reflex: se encontró rxconfig.py",
    "dev_st_reflex_sub": "✓ Proyecto Reflex (subcarpeta {sub}): se encontró rxconfig.py",
    "dev_st_python": "✓ Se encontró pyproject.toml",
    "dev_st_python_sub": "✓ Se encontró pyproject.toml (subcarpeta {sub})",
    "dev_st_none": "Esta carpeta no tiene pyproject.toml; sigue bajando",
    "dev_st_none_sub": "Esta carpeta (subcarpeta {sub}) no tiene pyproject.toml; sigue bajando",

    # ── confirmación de desinstalación ──
    "un_title": "Desinstalar {name}",
    "un_body": (
        "Detiene y borra el contenedor {container}, y después elimina su registro DNS, "
        "su configuración de nginx y su certificado TLS. Después ya no ocupa memoria; "
        "puedes volver a instalarla cuando quieras."
    ),
    "un_running": "Esta app está en ejecución; primero se detiene y después se desinstala.",
    "un_remove_data": "Borrar también sus datos (volúmenes y carpetas de colecciones compartidas)",
    "un_keep_hint": (
        "Si no lo marcas, se conservan y al reinstalar se vuelven a usar esos datos. "
        "Las carpetas locales montadas en modo Dev nunca se tocan."
    ),
    "un_confirm": "Desinstalar",

    # ── ventana de progreso ──
    "job_title_install": "Instalar {name}",
    "job_title_uninstall": "Desinstalar {name}",
    "job_busy_install": "Instalando… (puedes cerrar esta ventana; la instalación sigue en segundo plano)",
    "job_busy_uninstall": "Desinstalando… (puedes cerrar esta ventana; la desinstalación sigue en segundo plano)",
    "job_done": "Listo",
    "job_sending_install": "Enviando la solicitud de instalación…",
    "job_sending_dev_install": "Enviando la solicitud de instalación en modo Dev…",
    "job_sending_uninstall": "Enviando la solicitud de desinstalación…",
    "job_install_refused": "No se pudo iniciar la instalación (HTTP {code}): {detail}",
    "job_dev_install_refused": "No se pudo iniciar la instalación en modo Dev (HTTP {code}): {detail}",
    "job_uninstall_refused": "No se pudo iniciar la desinstalación (HTTP {code}): {detail}",
    "job_unreachable": "No se puede conectar con re-ddns: {error}",
    "job_queued": "En cola…",
    "job_queued_dev": "En cola (modo Dev)…",
    "job_building_image": "Primera instalación: construyendo la imagen del lanzador (tarda unos minutos)…",
    "job_image_context_missing": "No se encuentran los archivos para construir el lanzador: {path}",
    "job_image_build_http": "No se pudo construir la imagen del lanzador (HTTP {code})",
    "job_image_build_failed": "No se pudo construir la imagen del lanzador: {error}",
    "job_image_build_exception": "Error al construir la imagen del lanzador: {error}",
    "job_image_missing": "La imagen del lanzador sigue sin aparecer después de construirla.",
    "job_creating": "Creando el contenedor de {name}…",
    "job_creating_dev": "Creando el contenedor Dev de {name}…",
    "job_create_failed": "No se pudo crear el contenedor (HTTP {code})",
    "job_start_failed": "No se pudo iniciar el contenedor (HTTP {code}): {error}",
    "job_installing": "Instalando {name}…",
    "job_installing_dev": "Instalando {name} en modo Dev…",
    "job_phase": "{name}: {phase}",
    "job_installed": "¡Instalación de {name} completada; ya está en marcha!",
    "job_container_exited": "El contenedor de {name} terminó (exit code {code}).",
    "job_install_start_failed": "No se pudo iniciar la instalación: {error}",
    "job_dev_install_start_failed": "No se pudo iniciar la instalación en modo Dev: {error}",
    "job_storage_invalid": "Declaración de almacenamiento compartido no válida: {error}",
    "job_stop_waiting": "{name}: esperando a que termine el contenedor… ({seconds} s)",
    "job_uninstalled": "Se desinstaló {name}.",
    "job_uninstall_failed": "No se pudo desinstalar {name}: {error}",
    "phase_queued": "En cola",
    "phase_preparing_image": "Preparando la imagen del lanzador",
    "phase_building_image": "Construyendo la imagen del lanzador",
    "phase_creating": "Creando el contenedor",
    "phase_starting_container": "Iniciando el contenedor",
    "phase_dev_mount": "Usando el código fuente montado localmente",
    "phase_apt_packages": "Instalando paquetes del sistema",
    "phase_cloning": "Descargando el código",
    "phase_cloning_deps": "Descargando repositorios de dependencias",
    "phase_installing_deps": "Instalando dependencias",
    "phase_initializing": "Inicializando Reflex",
    "phase_registering": "Registrando DNS / nginx",
    "phase_starting_app": "Iniciando la app",
    "phase_running": "Listo; la app está en marcha",
    "phase_stopping": "Deteniendo el contenedor",
    "phase_removing_container": "Borrando el contenedor",
    "phase_unregistering": "Dando de baja el servicio y borrando su registro DNS",
    "phase_nginx": "Actualizando la configuración de nginx",
    "phase_cert": "Quitando el certificado TLS",
    "phase_data": "Borrando los volúmenes de datos",
    "phase_done": "Listo; se desinstaló",
}
