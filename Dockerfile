# Dockerfile — DevPulse backend (updated)
FROM python:3.12-slim

# Metadata
LABEL maintainer="devpulse@example.com"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# Install minimal system deps needed for common Python packages and DB drivers
# Keep list minimal to reduce image size.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential gcc libpq-dev ca-certificates netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest(s) first for caching
COPY requirements.txt /app/requirements.txt
# If you use poetry/pyproject, copy those too (not required by this file)
COPY pyproject.toml poetry.loc[k]* /app/

# Install Python deps
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /app/requirements.txt

# Copy project code
COPY . /app

# Ensure the working directory contains the app package
# Expose port used by Uvicorn
EXPOSE 8000

# Lightweight TCP healthcheck (no external deps).
# It attempts a TCP connect to 127.0.0.1:8000 inside the container.
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import socket,sys; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 8000)); s.close(); print('ok')" || exit 1

# Use a unprivileged user (optional but recommended)
RUN useradd --create-home --shell /bin/bash appuser || true
USER appuser

# Default command: run uvicorn (one worker — tiny VMs don't need many)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
