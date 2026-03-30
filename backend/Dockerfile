FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim

# Firefox/Camoufox system dependencies + Xvfb virtual display
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgtk-3-0 \
    libasound2 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libnss3 \
    libxss1 \
    libdbus-1-3 \
    libxt6 \
    xvfb \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser . .

# Install runner Python deps, fetch Camoufox (Firefox binary + GeoIP db),
# then copy the binary cache into appuser's home so it's found at runtime.
# Full fetch runs as root so it can write GeoIP into site-packages.
# The Firefox binary lands in /root/.cache/camoufox — we copy it to
# /home/appuser/.cache/camoufox so appuser finds it without re-downloading.
RUN pip install --no-cache-dir -r runner/requirements.txt \
 && chmod +x /app/entrypoint.sh \
 && python -m camoufox fetch \
 && mkdir -p /home/appuser/.cache \
 && cp -r /root/.cache/camoufox /home/appuser/.cache/camoufox \
 && chown -R appuser:appuser /home/appuser/.cache/camoufox

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"

CMD ["/app/entrypoint.sh"]
