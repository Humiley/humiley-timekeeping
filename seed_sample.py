"""
Optional: load a few sample employees and time entries so you can see the
dashboard with data. Safe to run once on a fresh database.

    python3 seed_sample.py
"""

from datetime import datetime, timezone, timedelta
import db


def iso(dt):
    return dt.replace(microsecond=0, tzinfo=timezone.utc).isoformat()


def main():
    db.init_db()
    db.seed_default_admin()

    samples = [
        ("An Nguyen", "an@humiley.com", "1111"),
        ("Binh Tran", "binh@humiley.com", "2222"),
        ("Chi Le", "chi@humiley.com", "3333"),
    ]
    ids = []
    for name, email, pin in samples:
        if db.get_employee_by_email(email):
            ids.append(db.get_employee_by_email(email)["id"])
            continue
        ids.append(db.create_employee(name, email, pin))

    conn = db.get_conn()
    now = datetime.utcnow()
    for i, emp_id in enumerate(ids):
        for d in range(1, 4):
            day = now - timedelta(days=d)
            start = day.replace(hour=9, minute=0, second=0)
            end = day.replace(hour=17, minute=30, second=0)
            conn.execute(
                "INSERT INTO time_entries (employee_id, clock_in, clock_out) VALUES (?,?,?)",
                (emp_id, iso(start), iso(end)),
            )
    # leave one person currently clocked in
    conn.execute(
        "INSERT INTO time_entries (employee_id, clock_in) VALUES (?,?)",
        (ids[0], iso(now - timedelta(hours=2))),
    )
    conn.commit()
    conn.close()
    print("Sample data loaded:")
    for name, email, pin in samples:
        print("  %-12s %-22s PIN %s" % (name, email, pin))


if __name__ == "__main__":
    main()
