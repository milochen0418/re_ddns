FROM python:3.11-slim-bookworm

# aiohttp is the only dependency: HTTP server and upstream client in one.
RUN pip install --no-cache-dir "aiohttp==3.14.5"

WORKDIR /app
COPY server.py /app/server.py

# The cached files live in /data, bind-mounted from ./pkg_cache/data on the host.
ENV PKG_CACHE_DIR=/data \
    PKG_CACHE_PORT=3142 \
    PYTHONUNBUFFERED=1

EXPOSE 3142

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3142/_health', timeout=3)"

CMD ["python", "/app/server.py"]
