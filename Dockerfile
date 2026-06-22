# Portable container for the Humiley People & Workplace Portal.
# Works on any Docker host — Render, Fly.io, or a Mat Bao VPS / Cloud Server.
FROM python:3.11-slim

WORKDIR /app
COPY . /app

# Bind on all interfaces; persist the SQLite DB on a mounted volume so data
# survives container restarts/redeploys.
ENV TK_HOST=0.0.0.0 \
    PORT=8000 \
    TK_DB_PATH=/data/timekeeping.db

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "app.py"]
