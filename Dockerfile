# syntax=docker/dockerfile:1
#
# Multi-stage build:
#   * builder  - installs all deps (dlib-bin = pre-compiled, no cmake needed)
#   * runtime  - slim image with only the installed packages + app source
#
# Build:  docker build -t face-attendance .
# Run:    docker run --rm -p 5000:5000 -v face_data:/app/data face-attendance

FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/requirements.txt

# Install dlib-bin first (pre-compiled, no cmake needed), then face-recognition
# with --no-deps to avoid pip re-compiling dlib from source.  Then install
# face-recognition-models (its actual dep), then the rest of requirements.
RUN pip install --no-cache-dir --target=/opt/pydeps dlib-bin==20.0.1
RUN pip install --no-cache-dir --target=/opt/pydeps face-recognition==1.3.0 --no-deps
RUN pip install --no-cache-dir --target=/opt/pydeps face-recognition-models==0.1.0
RUN pip install --no-cache-dir --target=/opt/pydeps \
    $(grep -v -E '^(dlib-bin|face-recognition)' /tmp/requirements.txt | tr '\n' ' ')

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/pydeps

# Shared libraries required by dlib-bin and OpenCV wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libopenblas0 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /opt/pydeps /opt/pydeps
COPY . /app

# Run as a non-root user; keep uploaded photos + SQLite in a writable dir.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/enrollments \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4).status==200 else 1)"]

# Single worker: the in-process recognition cache and rate-limit storage are
# per-process, and face matching is CPU-bound.
CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:5000", \
     "--workers", "1", "--threads", "2", "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
