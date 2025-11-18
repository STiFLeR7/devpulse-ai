# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# system deps (if any); add git if you need to fetch submodules
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev ca-certificates netcat-openbsd \
  && rm -rf /var/lib/apt/lists/*

# copy pyproject + install
COPY pyproject.toml poetry.lock* /app/
# fallback: if you use requirements.txt, copy that instead
COPY requirements.txt /app/

# Use pip install to simplify (works with requirements.txt)
RUN pip install --no-cache-dir -r requirements.txt

# copy code
COPY . /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# expose port
EXPOSE 8000

# healthcheck (simple)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import sys,requests; print('ok')" || exit 1

# run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
