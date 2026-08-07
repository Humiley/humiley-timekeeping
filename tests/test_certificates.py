"""Certificates, licences and health checks.

The value of this register is not the list of what people hold — it is the two answers a list cannot
give: whose certificate lapsed while they kept working, and who never had one at all.
"""
import certificates as C


def _c(kind, issued, expiry=None, title=None):
    return {"kind": kind, "issuedDate": issued, "expiryDate": expiry, "title": title}


# ── month arithmetic that must not drift ─────────────────────────────────────────────────────────

def test_a_year_later_is_the_same_day():
    assert str(C.add_months("2026-03-15", 12)) == "2027-03-15"


def test_six_months_later_is_the_same_day():
    assert str(C.add_months("2026-03-15", 6)) == "2026-09-15"


def test_the_end_of_a_long_month_clamps_rather_than_spilling_over():
    """31 Jan plus one month is 28 Feb. Spilling into 3 March would quietly extend the validity."""
    assert str(C.add_months("2026-01-31", 1)) == "2026-02-28"


def test_a_leap_year_is_handled():
    assert str(C.add_months("2028-01-31", 1)) == "2028-02-29"


# ── Law on OSH 2015 Art. 21(1): how often a health check is due ──────────────────────────────────

def test_ordinary_work_is_once_a_year():
    assert C.health_check_months("normal") == 12


def test_hazardous_work_is_twice_a_year():
    assert C.health_check_months("heavy") == 6
    assert C.health_check_months("especially_heavy") == 6


def test_a_minor_an_elderly_or_a_disabled_worker_is_twice_a_year_whatever_the_job():
    assert C.health_check_months("normal", minor=True) == 6
    assert C.health_check_months("normal", elderly=True) == 6
    assert C.health_check_months("normal", disabled=True) == 6


# ── when a certificate stops covering somebody ───────────────────────────────────────────────────

def test_a_printed_expiry_date_wins_over_any_interval():
    """It is what an inspector reads. A computed date that disagrees with the document is worse than
    no computed date at all."""
    cert = _c(C.KIND_OSH, "2026-01-01", expiry="2026-06-30")
    assert str(C.due_date(cert, 24)) == "2026-06-30"


def test_without_a_printed_date_the_statutory_interval_applies():
    assert str(C.due_date(_c(C.KIND_HEALTH, "2026-03-01"), 12)) == "2027-03-01"


def test_a_certificate_with_neither_is_treated_as_not_lapsing():
    assert C.due_date(_c(C.KIND_OTHER, "2020-05-01")) is None
    assert C.status(_c(C.KIND_OTHER, "2020-05-01"), "2026-06-01") == "permanent"


def test_a_current_certificate_is_valid():
    assert C.status(_c(C.KIND_HEALTH, "2026-03-01"), "2026-06-01", 12) == "valid"


def test_a_certificate_inside_the_warning_window_is_expiring():
    assert C.status(_c(C.KIND_HEALTH, "2026-03-01"), "2027-02-01", 12) == "expiring"


def test_the_due_date_itself_is_still_covered():
    assert C.status(_c(C.KIND_HEALTH, "2026-03-01"), "2027-03-01", 12) == "expiring"
    assert C.days_left(_c(C.KIND_HEALTH, "2026-03-01"), "2027-03-01", 12) == 0


def test_the_day_after_is_not():
    assert C.status(_c(C.KIND_HEALTH, "2026-03-01"), "2027-03-02", 12) == "expired"


# ── a refresher supersedes what it renews ────────────────────────────────────────────────────────

def test_the_most_recently_issued_certificate_is_the_one_that_counts():
    certs = [_c(C.KIND_OSH, "2022-01-01"), _c(C.KIND_OSH, "2025-06-01")]
    assert C.latest(certs, C.KIND_OSH)["issuedDate"] == "2025-06-01"


def test_an_old_certificate_on_file_does_not_make_somebody_covered():
    """The trap a plain list falls into: the register shows a safety certificate, so it looks fine,
    and the certificate is four years old."""
    certs = [_c(C.KIND_OSH, "2022-01-01")]
    r = C.review(certs, "2026-06-01", osh_group="3")
    assert any(i["state"] == "expired" for i in r["issues"])


def test_a_kind_nobody_holds_returns_nothing_rather_than_the_wrong_one():
    certs = [_c(C.KIND_OSH, "2025-06-01")]
    assert C.latest(certs, C.KIND_HEALTH) is None


# ── the review ───────────────────────────────────────────────────────────────────────────────────

def test_a_person_with_no_health_check_at_all_is_a_finding():
    """The answer a list of what people hold cannot give."""
    r = C.review([], "2026-06-01")
    kinds = [(i["kind"], i["state"]) for i in r["issues"]]
    assert (C.KIND_HEALTH, "missing") in kinds


def test_a_current_health_check_raises_nothing():
    r = C.review([_c(C.KIND_HEALTH, "2026-03-01")], "2026-06-01")
    assert r["issues"] == []
    assert r["items"][0]["status"] == "valid"


def test_a_site_worker_on_hazardous_duty_is_overdue_at_seven_months():
    """The same certificate that keeps an office worker covered for a year covers a site crew for
    six months. Applying one cadence to everybody is how the exposure goes unnoticed."""
    certs = [_c(C.KIND_HEALTH, "2025-11-01")]
    assert C.review(certs, "2026-06-01", conditions="normal")["issues"] == []
    hazard = C.review(certs, "2026-06-01", conditions="heavy")
    assert any(i["state"] == "expired" for i in hazard["issues"])


def test_safety_training_is_only_required_where_the_company_has_classified_somebody():
    """Asserting a requirement for everybody would bury the people who genuinely have one."""
    assert C.review([], "2026-06-01")["issues"] == [
        i for i in C.review([], "2026-06-01")["issues"] if i["kind"] == C.KIND_HEALTH]
    with_group = C.review([], "2026-06-01", osh_group="3")
    assert any(i["kind"] == C.KIND_OSH and i["state"] == "missing" for i in with_group["issues"])


def test_safety_training_lapses_after_two_years():
    r = C.review([_c(C.KIND_OSH, "2024-01-01"), _c(C.KIND_HEALTH, "2026-05-01")],
                 "2026-06-01", osh_group="3")
    assert any(i["kind"] == C.KIND_OSH and i["state"] == "expired" for i in r["issues"])


def test_a_trade_certificate_with_its_own_expiry_is_tracked_on_that_date():
    certs = [_c(C.KIND_HEALTH, "2026-05-01"),
             _c("welding", "2024-02-01", expiry="2026-02-01", title="6G welding qualification")]
    r = C.review(certs, "2026-06-01")
    assert any("6G welding" in i["message"] and i["state"] == "expired" for i in r["issues"])


def test_a_qualification_that_does_not_expire_is_listed_but_never_flagged():
    certs = [_c(C.KIND_HEALTH, "2026-05-01"),
             _c("degree", "2015-06-01", title="BEng Mechanical Engineering")]
    r = C.review(certs, "2026-06-01")
    assert r["issues"] == []
    assert any(x["label"] == "BEng Mechanical Engineering" and x["status"] == "permanent"
               for x in r["items"])


def test_the_reason_the_law_gives_travels_with_the_finding():
    """Somebody has to act on this, and "expired" alone does not say why it matters."""
    r = C.review([], "2026-06-01", conditions="heavy")
    msg = " ".join(i["message"] for i in r["issues"])
    assert "Art. 21(1)" in msg and "6 months" in msg


def test_whether_the_certificate_itself_is_attached_is_part_of_the_answer():
    r = C.review([_c(C.KIND_HEALTH, "2026-05-01")], "2026-06-01")
    assert r["items"][0]["hasFile"] is False
    certs = [dict(_c(C.KIND_HEALTH, "2026-05-01"), file="data:application/pdf;base64,AAA")]
    assert C.review(certs, "2026-06-01")["items"][0]["hasFile"] is True
