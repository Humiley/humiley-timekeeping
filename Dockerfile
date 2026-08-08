# Portable container for the Humiley People & Workplace Portal.
# Works on any Docker host — Render, Fly.io, or a Mat Bao VPS / Cloud Server.
FROM python:3.11-slim

WORKDIR /app
COPY . /app

# Install the one optional dependency (Web Push OS notifications). Pure-wheel install,
# no build tools needed. If it ever fails the app still runs (push auto-disables).
RUN pip install --no-cache-dir -r requirements.txt

# Bind on all interfaces; persist the SQLite DB on a mounted volume so data
# survives container restarts/redeploys.
ENV TK_HOST=0.0.0.0 \
    PORT=8000 \
    TK_DB_PATH=/data/timekeeping.db

# Clean production start: on an empty DB, bootstrap exactly ONE admin and disable
# demo seeding (TK_ALLOW_SEED is intentionally NOT set → no demo data ever).
# Override TK_ADMIN_EMAIL/NAME via the platform's env settings if available.
ENV TK_BOOTSTRAP_ADMIN=1 \
    TK_ADMIN_EMAIL=tony.nguyen@humiley.com \
    TK_ADMIN_NAME="Tony Nguyen"

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "app.py"]
