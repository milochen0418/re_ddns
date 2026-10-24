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

    # ── tamaño de la VM de Docker (Cambiar tamaño) ──
    "vm_resize": "Cambiar tamaño",
    "vm_size_loading": "Consultando al asistente del Mac…",
    "vm_size_missing": "Para cambiar el tamaño desde esta página, ejecuta esto una vez en el Mac, en la carpeta re_ddns:",
    "vm_size_offline": "El asistente del Mac está instalado pero no responde. Compruébalo con:",
    "vm_size_error": "El asistente del Mac no pudo comunicarse con Docker Desktop:",
    "vm_size_manual": "También puedes cambiarlo en Docker Desktop: Settings → Resources → Memory → Apply & restart.",
    "vm_size_now": "VM de Docker ahora:",
    "vm_size_host": "este Mac:",
    "vm_size_same": "Es el tamaño actual.",
    "vm_size_low": (
        "Demasiado poco: las apps usan {used} ahora mismo y todas vuelven a "
        "arrancar tras el reinicio. Detén algunas antes, o elige al menos {need}."
    ),
    "vm_size_high": (
        "Más de lo recomendado ({rec}): solo quedan {left} para macOS, el "
        "navegador y el editor, y el Mac puede ir más lento."
    ),
    "vm_size_ok": "Quedan {left} para el propio Mac.",
    "vm_size_impact": (
        "Un tamaño nuevo requiere reiniciar Docker: todas las apps se detienen "
        "1–2 minutos y luego arrancan solas (las que detuviste siguen detenidas). "
        "Mientras tanto esta página se desconecta y vuelve sola."
    ),
    "vm_size_apply": "Aplicar y reiniciar Docker",
    "vm_size_restarting": "Docker se está reiniciando con el nuevo tamaño:",
    "msg_vm_restarting": (
        "Docker se está reiniciando para cambiar la VM de {old} a {new}. Las apps "
        "vuelven en 1–2 minutos; esta página se reconecta sola."
    ),
    "msg_vm_done": "La VM de Docker tiene ahora {new} (antes {old}).",
    "msg_vm_failed": "El tamaño de la VM de Docker no cambió: {error}",
    "msg_vm_apply_failed": "No se pudo cambiar el tamaño: {error}",
    "msg_vm_unchanged": "Docker ya tiene {size}.",

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
    "store_storage": "Almacenamiento",
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

    # ── storage page (/storage); placeholders as in en.py ──
    "st_page_title": "Almacenamiento",
    "st_subtitle": "Los datos que las apps comparten mediante colecciones en este host: encuéntralos, mira de dónde vienen, ábrelos con otra app y libera espacio.",
    "st_tab_items": "Elementos",
    "st_tab_space": "Espacio",
    "st_tab_hosts": "Hosts",
    "st_load_failed": "No se pudo leer el almacenamiento: {error}",
    "st_action_failed": "No funcionó: {error}",
    "st_search": "Buscar títulos, ids, kinds, apps…",
    "st_import": "Importar archivos",
    "st_all_collections": "Todas las colecciones",
    "st_all_kinds": "Todos los kinds",
    "st_all_owners": "Todas las apps",
    "st_loc_all": "En todas partes",
    "st_loc_here": "En este host",
    "st_loc_own": "Creados en este host",
    "st_loc_replica": "Copias de otros hosts",
    "st_loc_remote": "Solo en otros hosts",
    "st_sort_newest": "Más recientes primero",
    "st_sort_oldest": "Más antiguos primero",
    "st_sort_largest": "Más grandes primero",
    "st_sort_smallest": "Más pequeños primero",
    "st_sort_title": "Por título",
    "st_clear": "Quitar filtros",
    "st_no_items": "No hay elementos",
    "st_no_items_hint": "Las apps que participan en una colección publican aquí sus elementos; también puedes importar tus propios archivos.",
    "st_range": "{first}–{last} de {total}",
    "st_files": "{count} archivo(s)",
    "st_here": "Este host",
    "st_copy_from": "Copia de {host}",
    "st_on_host": "En {host}",
    "st_owner_user": "Tú (importado)",
    "st_open_with": "Abrir con {app}",
    "st_fetch_here": "Traer una copia",
    "st_details": "Detalles",
    "st_delete": "Eliminar",
    "st_fetch_start": "Trayendo una copia…",
    "st_fetch_progress": "Trayendo una copia: {done} de {total}",
    "st_fetched": "Copiado a este host: {ref}",
    "st_size": "Tamaño",
    "st_created": "Publicado",
    "st_source": "Origen",
    "st_on_disk": "En el disco",
    "st_meta": "Datos de la app",
    "st_made_from": "Hecho a partir de",
    "st_made_into": "Usado para hacer",
    "st_files_title": "Archivos",
    "st_more_files": "… y {count} más",
    "st_none": "Nada",
    "st_not_here": "no está en este host",
    "st_no_openers": "Ninguna app instalada dice que abre este kind todavía.",
    "st_delete_item_title": "¿Eliminar este elemento?",
    "st_delete_item_body": "«{title}» ({size}) se eliminará de este host. Las apps que guardan su ref ya no lo encontrarán aquí; una copia en otro host se conserva.",
    "st_delete_lineage": "{count} elemento(s) se hicieron a partir de él. Se conservan, pero su enlace de vuelta no llevará a ninguna parte.",
    "st_delete_contrib_title": "¿Eliminar estos datos?",
    "st_delete_contrib_body": "Se eliminará todo lo que {owner} guarda en la colección «{collection}» de este host: {usage}.",
    "st_delete_contrib_installed": "La app sigue instalada: seguirá funcionando y puede escribir elementos nuevos.",
    "st_deleted": "Eliminado: {what}",
    "st_disk": "{free} libres de {total} en el disco que guarda las colecciones ({path})",
    "st_space_hint": "Cada app escribe solo en su propia parte de una colección. Una cuota limita esa parte en este host; las apps la comprueban al publicar.",
    "st_no_collections": "Aún no hay colecciones. Se crea una al instalar una app que declara almacenamiento.",
    "st_collection_summary": "{items} elementos · {size}",
    "st_collection_copies": "copias: {items} · {size}",
    "st_staging": "sin terminar: {size}",
    "st_contrib_usage": "{items} elementos · {size}",
    "st_status_installed": "Instalada",
    "st_status_orphan": "App no instalada",
    "st_status_copies": "Solo copias",
    "st_status_user": "Tus importaciones",
    "st_no_quota": "sin cuota",
    "st_quota_of": "cuota {limit} ({percent}% usado)",
    "st_set_quota": "Cuota",
    "st_no_limit": "Sin cuota",
    "st_save": "Guardar",
    "st_show_items": "Ver elementos",
    "st_delete_data": "Eliminar datos",
    "st_bad_number": "Escribe un número de GB.",
    "st_this_host": "Este host",
    "st_node_open": "Los otros hosts pueden leer los elementos de este host sin token. Define RE_DDNS_NODE_TOKEN en cada host de re-ddns.",
    "st_peers": "Otros hosts",
    "st_peers_hint": "Hosts de re-ddns cuyos elementos aparecen aquí; una copia se trae una vez y luego se lee del disco local.",
    "st_no_peers": "No hay otros hosts.",
    "st_peer_ok": "accesible",
    "st_peer_down": "inaccesible",
    "st_peer_other_name": "responde como {name}",
    "st_peer_env": "definido por RE_DDNS_PEERS",
    "st_peer_name": "Nombre",
    "st_add_peer": "Añadir host",
    "st_remove": "Quitar",
    "st_copies": "Copias de otros hosts",
    "st_copies_total": "{size} de copias en este host · límite {cap}",
    "st_copies_hint": "Cuando las copias superan el límite, se eliminan las más antiguas; su host de origen conserva el original.",
    "st_cap": "Límite",
    "st_no_cap": "sin límite",
    "st_cap_default": "Usar el valor predeterminado",
    "st_gc": "Limpiar ahora",
    "st_gc_done": "Limpieza hecha: se quitaron {removed} copias y {staging} subidas sin terminar.",
    "st_evicted": "Se eliminaron {count} copias antiguas para no superar el límite.",
    "st_import_title": "Importar tus archivos",
    "st_import_hint": "Los archivos se convierten en un elemento de la colección, y tú eres su dueño. Todas las apps que leen la colección lo ven.",
    "st_collection": "Colección",
    "st_new_collection": "Colección nueva…",
    "st_kind": "Kind",
    "st_other_kind": "Otro kind…",
    "st_kind_hint": "<dominio>.<tipo>, p. ej. dicom.series; file.generic no promete nada sobre los archivos.",
    "st_title": "Título",
    "st_title_placeholder": "¿Qué es?",
    "st_drop": "Suelta archivos o una carpeta aquí, o haz clic para elegir",
    "st_import_go": "Importar",
    "st_import_nothing": "Elige algunos archivos primero.",
    "st_import_uploading": "Subiendo… {percent}%",
    "st_import_saving": "Guardando {n} de {total}: {name}",
    "st_imported": "Importado «{title}» como {ref}",
}
