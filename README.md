# Face Attendance System

A production-grade, face-recognition based attendance system for schools and
classrooms. Teachers register, enroll students' faces, and take attendance by
pointing a camera at the class. Each teacher has an isolated account: their
own students, photos, and attendance records.

Built with **Flask**, **SQLAlchemy**, **face-recognition (dlib)**, and a
responsive dark-themed frontend (Chart.js for weekly trends).

---

## Features

- **Face enrollment** — capture from webcam or upload photos; 3–8 photos per
  student recommended. Automatic quality checks (blur, face size, lighting).
- **Live recognition** — browser-based camera capture sent to `/api/recognize`.
  Multi-face detection with a consistency window (N detections within N
  seconds) to suppress false positives before marking attendance.
- **Attendance tracking** — one record per student per day (atomic de-dupe via
  a unique constraint), with dashboard stats, today's list, and a weekly trend
  chart. Export to CSV.
- **Multi-tenant by design** — every teacher has an isolated data space.
- **Security** — salted password hashing, CSRF protection, per-IP/user rate
  limiting, security headers (CSP, HSTS, nosniff, X-Frame-Options), path
  traversal protection on photo serving, XSS-safe templating, and optional
  admin roles.
- **Responsive UI** — works on desktop, tablets, and phones.

---

## Architecture

```
app/
  __init__.py      App factory: extensions, logging, security headers,
                   error handlers, request IDs
  config.py        Environment-driven configuration
  database.py      SQLAlchemy engine, session, schema, SQLite pragmas
  models.py        Data-access layer (users, students, encodings, attendance)
  recognition.py   Encoding, quality assessment, matching, consistency logic
  auth.py          Flask-Login wiring (user_loader, unauthorized handler)
  utils.py         Validation + safe path helpers
  routes/
    auth.py        Login / register / logout (CSRF + rate limited)
    main.py        Dashboard and enroll pages
    api.py         /api/stats, /api/attendance, /api/recognize, exports
    enroll.py      /api/enroll/* (capture, upload, list, view, delete)
templates/         Jinja2 templates (dashboard, enroll, login, register, error)
tests/             pytest suite (auth, api, enroll, recognition)
Dockerfile         Multi-stage production image (compiles dlib)
render.yaml        Render blueprint (free-tier web + Postgres)
.github/workflows  CI (lint + tests + boot check)
```

### Data model

| Table              | Purpose                                          | Isolation key |
|--------------------|--------------------------------------------------|---------------|
| `users`            | Teacher/admin accounts (password hashes, role)   | —             |
| `students`         | A teacher's students                             | `user_id`     |
| `face_encodings`   | 128-d encodings + photo paths per student        | `user_id`     |
| `attendance_records`| One row per student per day (unique constraint)  | `user_id`     |

SQLite is the default database (with WAL, FK enforcement, busy timeout).
PostgreSQL is supported via `DATABASE_URL` (e.g. on Render).

---

## Quick start (local)

```bash
# 1. Install dependencies (dlib compiles from source; needs cmake + a C++ compiler)
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
#   ... edit SECRET_KEY at minimum

# 3. Run (Waitress - production-grade local server)
python run.py
# or the Flask dev server with auto-reload (development only)
python run.py --debug
```

Open http://localhost:5000, register a teacher account, and enroll students.

> **Windows note:** dlib requires Visual Studio Build Tools with C++ workload.
> See the [face-recognition install guide](https://github.com/ageitgey/face_recognition)
> for platform-specific instructions.

---

## Configuration

All settings are read from environment variables (`.env` is loaded
automatically by `run.py`/`wsgi.py`). See `.env.example` for the full list.

| Variable                  | Default               | Description |
|---------------------------|-----------------------|-------------|
| `SECRET_KEY`              | (dev only)            | Signs session cookies. **Must** be a long random value in production. |
| `DATABASE_URL`            | `sqlite:///database.db` | SQLAlchemy URL; use Postgres in production. |
| `DATA_DIR`                | `data`                | Directory for uploaded enrollment photos. |
| `MAX_PHOTOS_PER_STUDENT`  | `8`                   | Cap on photos per student. |
| `SESSION_COOKIE_SECURE`   | `false` (auto on Render)| Send session cookies over HTTPS only. |
| `SESSION_DAYS`            | `7`                   | Login session lifetime. |
| `WTF_CSRF_TIME_LIMIT`     | `28800`               | CSRF token lifetime (seconds). |
| `ALLOW_REGISTRATION`      | `true`                | Set `false` to disable self-service registration. |
| `ADMIN_USERNAMES`         | ``                    | Comma-separated usernames auto-promoted to `admin`. |
| `RATELIMIT_STORAGE_URI`   | `memory://`           | Use a shared Redis for multi-worker deployments. |
| `FACE_TOLERANCE`          | `0.5`                 | Face match threshold (lower = stricter). |
| `CONSISTENCY_FRAMES`      | `3`                   | Detections required before marking attendance. |
| `CONSISTENCY_WINDOW_SECONDS` | `6`                 | Window for the consistency check. |
| `MIN_FACE_SIZE`           | `110`                 | Min face box width for enrollment photos. |
| `MIN_BLUR_VARIANCE`       | `40.0`                | Min Laplacian variance for enrollment photos. |
| `MAX_IMAGE_DIMENSION`     | `1600`                | Images are downscaled above this on recognition. |
| `LOG_LEVEL`               | `INFO`                | Logging level. |

---

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest          # 38 tests: auth, api, enroll, recognition
python -m ruff check .    # lint
```

CI (`.github/workflows/ci.yml`) runs lint, the full test suite, and a boot
check on every push/PR.

---

## Deployment

### Option A — Render (free, recommended)

`render.yaml` is a blueprint that provisions a free web service + free
PostgreSQL. In the Render dashboard: **New → Blueprint → connect your GitHub
repo** and Render creates both resources automatically.

Manual alternative: create a **Web Service** from the repo, runtime **Docker**,
and set the `DATABASE_URL` to a free Render PostgreSQL instance.

> **Free-tier caveats**
> - Instances spin down after ~15 min of inactivity (first request after a
>   cold start is slower).
> - Enrollment photos are stored on the instance's ephemeral disk and reset on
>   redeploy/restart. Attendance records live in Postgres and are persistent.
>   For permanent photo storage, add a persistent disk or object storage.

### Option B — Docker (any host)

```bash
docker build -t face-attendance .
docker run --rm -p 5000:5000 -e SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')" \
  -v face_data:/app/data face-attendance
# or: docker compose up --build
```

### Option C — Traditional WSGI host

```bash
pip install -r requirements.txt
gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 2 wsgi:app
```

Run behind a reverse proxy (nginx/Caddy) that terminates TLS.

---

## Security notes

- Passwords are hashed with Werkzeug's `scrypt` (or `pbkdf2`) — never stored
  in plaintext.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` when HTTPS is
  detected.
- CSRF protection is enabled globally (Flask-WTF), including for the JSON API
  (`X-CSRFToken` header).
- Rate limits: login `10/min`, register `5/hour`, recognition `120/min`,
  enrollment `30/min`, plus a global default of `120/min`.
- Photo endpoints sanitize and resolve paths so traversal is impossible.
- Face photos and encodings are biometric data: keep the database and `data/`
  directory private, restrict registration (`ALLOW_REGISTRATION=false`), and
  follow your jurisdiction's rules on biometric data handling (e.g. GDPR
  consent for students).

## Known limitations

- Recognition is CPU-bound (dlib HOG). Large classes (~100+ students) work,
  but real-time throughput depends on the host's CPU.
- Recognition cache and rate-limit storage are per-process; run **one worker**
  (the default) so both stay consistent. Multiple workers require
  `RATELIMIT_STORAGE_URI=redis://...`.
- The legacy single-file `app.py` was removed; the package `app/` is the only
  supported application now.

---

## License

For demonstration and educational use.
