# syntax=docker/dockerfile:1
#
# Multi-stage build:
#   * builder  - compiles dlib (source-only on PyPI) and installs all deps
#   * runtime  - slim image with only the compiled packages + app source
#
# Build:  docker build -t face-attendance .
# Run:    docker run --rm -p 5000:5000 -v face_data:/app/data face-attendance

FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build tools required to compile dlib from source.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libopenblas-dev \
        liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

# Compile dlib with limited parallelism to keep peak build memory bounded.
ARG MAKEFLAGS=-j2
RUN pip install --no-cache-dir --target=/opt/pydeps -r /tmp/requirements.txt

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/pydeps

# Shared libraries required by the compiled dlib and OpenCV wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libopenblas0 \
        liblapack3 \
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
