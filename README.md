# Humiley TimeKeeping

A lightweight time-tracking web app for Humiley / Cowork. Employees clock in
and out with their **work email + PIN**, and admins manage everyone and track
hours from a back-office dashboard.

Built entirely on the **Python standard library** (`http.server` + `sqlite3`) —
**no dependencies to install**. If you have Python 3.8+, you can run it.

---

## Features

**Employee kiosk** (`/`)
- Clock in / out with email + 4-digit PIN (one button toggles in/out)
- Live clock and date
- "Recent activity" view of your own entries and hours

**Admin dashboard** (`/admin`)
- Secure admin sign-in (email + PIN)
- **Overview** — headcount, who's clocked in now, total hours, hours-per-employee with date range
- **Time Entries** — every clock in/out with hours, filter by date, **export to CSV**
- **Employees** — add / edit staff, set admin role, activate / deactivate, reset PINs

---

## Quick start

```bash
cd "TimeKeeping Web App"
python3 app.py
```

Then open:
- Employee kiosk → http://localhost:8000/
- Admin dashboard → http://localhost:8000/admin

On the **first run** a default admin account is created and its credentials are
printed in the terminal:

```
Email: admin@humiley.com
PIN:   2468
```

> **Sign in at `/admin` and change this PIN immediately** (Employees tab → Edit).

### Load sample data (optional)

To explore the dashboard with example employees and entries:

```bash
python3 seed_sample.py
```

---

## Configuration

Set these environment variables before starting if you want to override defaults:

| Variable          | Default              | Purpose                          |
| ----------------- | -------------------- | -------------------------------- |
| `TK_PORT`         | `8000`               | Port to listen on                |
| `TK_HOST`         | `0.0.0.0`            | Bind address                     |
| `TK_DB_PATH`      | `./timekeeping.db`   | SQLite database file location    |
| `TK_ADMIN_EMAIL`  | `admin@humiley.com`  | Default admin email (first run)  |
| `TK_ADMIN_PIN`    | `2468`               | Default admin PIN (first run)    |

Example:

```bash
TK_PORT=9000 TK_ADMIN_EMAIL=you@humiley.com TK_ADMIN_PIN=7531 python3 app.py
```

---

## How it works

| File              | Role                                                        |
| ----------------- | ---------------------------------------------------------- |
| `app.py`          | HTTP server, routing, and the JSON/CSV API                 |
| `db.py`           | SQLite schema + all data access; PINs hashed with PBKDF2   |
| `templates/`      | `index.html` (kiosk) and `admin.html` (dashboard)          |
| `static/`         | `style.css`, `app.js` (kiosk), `admin.js` (dashboard)      |
| `seed_sample.py`  | Optional demo data                                          |

- **PINs are never stored in plain text** — they are salted and hashed with
  PBKDF2-HMAC-SHA256.
- Each clock-in opens a `time_entries` row; the matching clock-out closes it.
  Hours are computed from the in/out timestamps.
- The database file (`timekeeping.db`) is **git-ignored** so real time data is
  never committed.

---

## Notes & next steps

- Admin sessions are kept in memory, so restarting the server signs admins out.
- Times are stored in UTC and shown in the viewer's local timezone.
- Possible enhancements: weekly/monthly reports, edit/delete individual
  entries, email notifications, deploy behind HTTPS.

---

*Humiley Engineering & Solutions · TimeKeeping*
