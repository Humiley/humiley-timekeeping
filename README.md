# Humiley Timekeeping & Leave Management

A standalone web app for Humiley / Cowork — employees check in/out (with GPS),
request leave, and managers track everyone from a back-office dashboard.

It reuses the design of the original **Humiley Timekeeping & Leave Management**
platform (sidebar, modules, branding) but replaces the Microsoft 365 /
SharePoint backend with a **self-contained Python + SQLite** backend so the data
**persists** and the app runs anywhere — **no dependencies to install**.

> Built on the Python standard library only (`http.server` + `sqlite3`). If you
> have Python 3.8+, you can run it.

---

## Features

The full platform UI, served from a real database:

- **Dashboard** — KPIs, attendance charts, today's activity, pending approvals
- **Check In / Out** — GPS-aware check-in/out; on-time vs late detection
- **Attendance** — every record, filterable; staff see only their own
- **GPS Locations** — approved geofence zones (HQ, Factory, …)
- **Work Schedules** — shift configuration
- **Leave Management** — request annual/sick/etc. leave with working-day calc
- **Manager Approval** — approve / reject leave requests
- **HR Admin** — add / edit employees, departments, leave balances, roles
- **Reports & Analytics** — department, leave, payroll, trend charts
- **Settings / Integration** — Microsoft 365 connection guide

**Roles:** *Manager* (full access) and *Staff* (personal workspace) — enforced
both in the UI and the API.

---

## Quick start

```bash
cd "TimeKeeping Web App"
python3 app.py
```

Open **http://localhost:8000/**.

On first run the database is seeded with the platform's 15 demo employees, GPS
zones, and sample attendance/leave so every screen has realistic data.

### Logging in

**Demo mode (default — no Microsoft account needed):**
Click **Sign in with Microsoft 365**, then choose **Manager** or **Staff**.
- *Manager* signs in as the Managing Director (full access).
- *Staff* signs in as an engineer (personal workspace).

**Live Microsoft 365 mode:** see [Microsoft 365 setup](#microsoft-365-setup-live-mode).

---

## Configuration

Environment variables (all optional):

| Variable             | Default            | Purpose                                  |
| -------------------- | ------------------ | ---------------------------------------- |
| `TK_PORT` / `PORT`   | `8000`             | Port to listen on                        |
| `TK_HOST`            | `0.0.0.0`          | Bind address                             |
| `TK_DB_PATH`         | `./timekeeping.db` | SQLite database file                     |
| `TK_M365_CLIENT_ID`  | *(empty)*          | Azure AD app (client) ID — enables live mode |
| `TK_M365_TENANT_ID`  | *(empty)*          | Azure AD directory (tenant) ID           |
| `TK_MAPS_KEY`        | *(empty)*          | Google Maps API key (optional, for maps) |

If `TK_M365_CLIENT_ID` **and** `TK_M365_TENANT_ID` are set, the app switches to
**live Microsoft 365** login automatically; otherwise it runs in **demo mode**.

---

## Microsoft 365 setup (live mode)

1. In the **Azure Portal → App registrations**, register a Single-Page App.
   - Redirect URI (SPA): the URL where you host this app (e.g. `http://localhost:8000/`).
   - API permissions: **Microsoft Graph → User.Read** (delegated).
2. Copy the **Application (client) ID** and **Directory (tenant) ID**.
3. Run with them set:

   ```bash
   TK_M365_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
   TK_M365_TENANT_ID=yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy \
   python3 app.py
   ```

4. Add each person as an employee (HR Admin) with their **work email**. On
   sign-in, the backend verifies their Microsoft token via Microsoft Graph,
   matches the email to their employee record, and applies their role.

> Users without a matching employee record are refused — add them in HR Admin first.

---

## How it works

| File             | Role                                                          |
| ---------------- | ------------------------------------------------------------ |
| `app.py`         | HTTP server, routing, REST API, Microsoft 365 token verify   |
| `db.py`          | SQLite schema + data access (employees, attendance, leave, zones) |
| `seed_data.py`   | First-run seed data (employees, zones, attendance, leave)    |
| `templates/index.html` | The full single-page platform UI (design preserved)    |
| `static/brand/`  | Humiley logos                                                |

- The frontend authenticates to the backend, then **loads all data from the
  database** — every screen reflects real, persisted records.
- **Check-in/out, leave requests, approvals, and employee edits persist** to
  SQLite via the REST API (`/api/*`).
- The database file (`timekeeping.db`) is **git-ignored** so real data is never
  committed.

### REST API (selected)

| Method | Path | Notes |
| ------ | ---- | ----- |
| `POST` | `/api/auth/demo` | Demo login (`{role}`) |
| `POST` | `/api/auth/m365` | Live login (`{accessToken}`) |
| `GET`  | `/api/employees` · `POST` · `PATCH /:id` · `DELETE /:id` | manager-only writes |
| `GET`  | `/api/attendance` · `POST /checkin` · `POST /checkout` | staff see own only |
| `GET`  | `/api/leave` · `POST` · `PATCH /:id` | approve/reject = manager |
| `GET`  | `/api/zones` · `POST` · `PATCH /:id` · `DELETE /:id` | manager-only writes |

---

## Notes & next steps

- Admin sessions are kept in memory, so restarting the server signs users out.
- Times/dates are stored as written; production deployments should run behind HTTPS.
- The original SharePoint integration guide is preserved in the project history
  if you ever want to connect Power Automate / Graph instead of SQLite.

---

*Humiley Engineering & Solutions · Timekeeping & Leave Management*
