FROM python:3.11-slim-bookworm

# ── System deps: Node.js, Chromium, Xvfb, VNC, noVNC, window manager ──
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl unzip git gcc libffi-dev procps \
        # Chromium browser
        chromium chromium-sandbox \
        # Virtual display + VNC
        xvfb x11vnc xdotool \
        # Lightweight window manager
        fluxbox \
        # noVNC (web-based VNC client)
        novnc websockify \
        # Process manager
        supervisor \
        # Misc X11 utilities
        xterm dbus-x11 \
        # NSS tools (certutil) for Chromium CA install
        libnss3-tools \
        # Zenity for GUI dialogs in CA install script
        zenity \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g bun \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Poetry ──
ENV POETRY_VERSION=1.8.4 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_NO_INTERACTION=1
RUN curl -sSL https://install.python-poetry.org | python - \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

# ── Display environment ──
ENV DISPLAY=:99 \
    SCREEN_WIDTH=1280 \
    SCREEN_HEIGHT=800 \
    SCREEN_DEPTH=24 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080

# ── App workdir ──
WORKDIR /app

# ── Install Python deps (cached layer) ──
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root || (poetry lock && poetry install --no-root)

# ── Copy application source ──
COPY . .

# ── Reflex init (pre-build frontend skeleton) ──
RUN poetry run reflex init || true

# Patch Reflex Vite config to allow any hostname
RUN sed -i 's/port: process.env.PORT,/port: process.env.PORT,\n    allowedHosts: true,/' \
    /app/.venv/lib/python3.11/site-packages/reflex/compiler/templates.py 2>/dev/null || true

# ── Copy config files ──
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY fluxbox-menu /root/.fluxbox/menu
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ports:
#   3000 - Reflex frontend
#   8000 - Reflex backend
#   6080 - noVNC (web-based VNC, access from Mac browser)
EXPOSE 3000 8000 6080

ENTRYPOINT ["/entrypoint.sh"]
