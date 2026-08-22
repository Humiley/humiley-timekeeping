# -*- coding: utf-8 -*-
"""The identification, tested against the cases that would lose real data.

Every assertion here is about something NOT being deleted. That is the point: a sweep that removes
the sample is easy, and a sweep that removes the sample and nothing else is the whole job.
"""
import demo_data
import seed_data


def _readers(att=0, lv=0):
    """plan() takes ROWS now, not counts — it has to look at each attendance row's date to tell a
    sample punch from a real one. Sample-shaped rows by default, so a test that wants "in use"
    behaviour has to ask for it."""
    day = sorted(demo_data.seed_attendance_dates())[0]
    rows = [{"emp_id": "x", "date": day} for _ in range(att)]
    lv_key = list(demo_data.seed_leave_keys())[0] if lv else None
    lvs = [{"emp_id": lv_key[0], "type": lv_key[1],
            "startDate": lv_key[2], "endDate": lv_key[3]} for _ in range(lv)] if lv else []
    return (lambda _id: rows), (lambda _id: lvs)


def _seed_emp(i=0):
    return dict(seed_data.EMPLOYEES[i])


# ── the happy path, so the rest of the file is not vacuous ──────────────────────────────────────
def test_an_untouched_sample_employee_is_identified():
    e = _seed_emp(1)                      # EMP002, not a protected address
    v, why = demo_data.classify_employee(e)
    assert v == "demo", why


def test_a_real_employee_is_not():
    v, why = demo_data.classify_employee(
        {"id": "HML-042", "name": "Nguyen Van Thanh", "email": "thanh@humiley.com"})
    assert v == "keep" and "not in the shipped sample" in why


# ── the trap that motivates the whole module ────────────────────────────────────────────────────
def test_the_sample_record_that_carries_an_administrators_address_is_never_removed():
    """EMP001 in the shipped seed is huy.nguyen@humiley.com, which is a REAL super-admin. The
    obvious "delete employees EMP001..EMP015" sweep takes out an administrator."""
    e = _seed_emp(0)
    assert e["email"] == "huy.nguyen@humiley.com", "if the seed changes, this test must be re-read"
    v, why = demo_data.classify_employee(e)
    assert v == "keep" and "protected administrator" in why


def test_the_other_protected_address_too():
    e = dict(_seed_emp(1), email="tony.nguyen@humiley.com")
    assert demo_data.classify_employee(e)[0] == "keep"


# ── somebody has been working in the record ─────────────────────────────────────────────────────
def test_a_sample_id_with_a_changed_name_is_treated_as_real():
    e = dict(_seed_emp(1), name="Someone Real")
    v, why = demo_data.classify_employee(e)
    assert v == "edited" and "changed since" in why


def test_a_sample_id_with_a_changed_email_is_treated_as_real():
    e = dict(_seed_emp(1), email="real.person@humiley.com")
    assert demo_data.classify_employee(e)[0] == "edited"


def test_matching_is_case_and_space_insensitive():
    e = dict(_seed_emp(1))
    e["name"] = "  " + e["name"].upper() + " "
    assert demo_data.classify_employee(e)[0] == "demo", \
        "a stray space must not turn a sample row into a real one, or nothing is ever removable"


# ── the plan ────────────────────────────────────────────────────────────────────────────────────
def test_the_plan_counts_only_what_it_may_remove():
    att, lv = _readers(att=4, lv=1)
    p = demo_data.plan([_seed_emp(0), _seed_emp(1),
                        {"id": "HML-9", "name": "Real", "email": "real@humiley.com"}], [], att, lv)
    ids = [x["id"] for x in p["employees"]["demo"]]
    assert ids == ["EMP002"], ids                       # EMP001 protected, HML-9 real
    assert p["totals"]["employees"] == 1
    assert p["totals"]["attendance"] == 4 and p["totals"]["leave"] == 1, \
        "attendance and leave are counted for the removable employee ONLY"


def test_a_real_employees_attendance_is_never_counted():
    seen = []

    def att(emp_id):
        seen.append(emp_id)
        return 10
    p = demo_data.plan([{"id": "HML-9", "name": "Real", "email": "real@humiley.com"}], [],
                       att, lambda _i: 0)
    assert seen == [], "the counter must not even be ASKED about a real employee"
    assert p["totals"]["attendance"] == 0
    assert p["anything"] is False


def test_an_edited_sample_row_contributes_nothing():
    p = demo_data.plan([dict(_seed_emp(1), name="Real Person")], [], *_readers(att=99, lv=99))
    assert p["totals"] == {"employees": 0, "attendance": 0, "leave": 0, "zones": 0}
    assert p["employees"]["edited"] and p["anything"] is False


# ── zones: a geofence decides whether a punch is on site ────────────────────────────────────────
def test_a_zone_must_match_on_name_AND_position():
    z = seed_data.ZONES[0]
    same = {"id": 1, "name": z["name"], "lat": z["lat"], "lon": z["lon"], "radius": z["radius"]}
    moved = {"id": 2, "name": z["name"], "lat": z["lat"] + 0.02, "lon": z["lon"], "radius": z["radius"]}
    p = demo_data.plan([], [same, moved], *_readers())
    assert [x["id"] for x in p["zones"]["demo"]] == [1]
    assert [x["id"] for x in p["zones"]["keep"]] == [2], \
        "a site renamed to match the sample but sited elsewhere is a REAL geofence"


def test_a_real_zone_is_kept():
    p = demo_data.plan([], [{"id": 7, "name": "Mega Lifesciences Site", "lat": 10.9,
                             "lon": 106.7, "radius": 200}], *_readers())
    assert p["zones"]["keep"] and not p["zones"]["demo"]


# ── the module cannot delete anything ───────────────────────────────────────────────────────────
def test_this_module_has_no_write_path():
    """It takes readers, not a database. A future edit that hands it a connection should fail here
    rather than in production."""
    import inspect
    src = inspect.getsource(demo_data)
    for forbidden in ("DELETE", "get_conn", "commit(", "execute("):
        assert forbidden not in src, "demo_data must describe, never write: found %r" % forbidden


def test_the_hr_sample_caveat_is_always_stated():
    p = demo_data.plan([], [], *_readers())
    assert any("belong to REAL people" in n for n in p["notes"]), \
        "the one thing this cannot identify has to be said every time, not only when it is convenient"


# ── the two properties the adversarial review added ─────────────────────────────────────────────
def test_a_sample_record_with_activity_on_it_is_in_use():
    """An EDIT already makes a sample row real. Accrued ACTIVITY is the stronger signal, and the
    single-employee delete path has always refused on it."""
    att = lambda _i: [{"emp_id": "EMP002", "date": "2026-08-19"}]      # not a seed date
    p = demo_data.plan([_seed_emp(1)], [], att, lambda _i: [])
    assert p["totals"]["employees"] == 0
    assert p["employees"]["inUse"] and "punching in" in p["employees"]["inUse"][0]["why"]


def test_a_reference_elsewhere_also_means_in_use():
    p = demo_data.plan([_seed_emp(1)], [], lambda _i: [], lambda _i: [],
                       lambda _i: {"payruns": 1})
    assert p["totals"]["employees"] == 0 and p["employees"]["inUse"]


def test_a_zone_whose_radius_was_changed_is_an_edit():
    z = seed_data.ZONES[0]
    widened = {"id": 9, "name": z["name"], "lat": z["lat"], "lon": z["lon"],
               "radius": int(z["radius"]) + 150}
    p = demo_data.plan([], [widened], *_readers())
    assert not p["zones"]["demo"], "a geofence somebody widened is theirs, not the sample's"
    assert [x["id"] for x in p["zones"]["edited"]] == [9]
