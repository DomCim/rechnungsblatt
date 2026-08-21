# Rechnungsblatt — Web-Schicht + Kern in einem Container.
# Build-Kontext ist die Repo-Wurzel:  docker build -f deploy/Dockerfile .
#
# Lizenzhinweis: Ghostscript ist AGPL. Für den internen Betrieb unkritisch,
# vor kommerziellem Angebot die Artifex-Lizenzfrage klären (README, Risiko 1).

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ghostscript fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY kern/ kern/
COPY web/ web/

RUN pip install --no-cache-dir ./kern \
    && pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart

# App läuft aus dem Quellbaum (Seiten und Zonen-Editor liegen neben dem Paket)
ENV PYTHONPATH=/srv/web/src \
    DATEN_VERZEICHNIS=/daten \
    PYTHONUNBUFFERED=1

RUN useradd --system --create-home rechnungsblatt \
    && mkdir -p /daten \
    && chown rechnungsblatt:rechnungsblatt /daten
USER rechnungsblatt
VOLUME /daten

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=4)"]

CMD ["uvicorn", "rechnungsblatt_web.main:app", "--host", "0.0.0.0", "--port", "8000"]
