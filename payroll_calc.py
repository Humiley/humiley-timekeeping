"""Pure, tested reference implementation of the Vietnam payroll math (HML-CB-001, 3P model).

The authoritative calculation currently lives in the 21k-line frontend (`_payComputed` in
templates/index.html). That is untested, so a one-character PIT-bracket or proration slip would ship
silently onto real payslips. This module is a FAITHFUL, byte-for-byte port of that function — same
constants, same order of operations, same rounding — so it can be unit-tested (see
tests/test_payroll_calc.py) and, later, become the server-side source of truth. It changes no behaviour.

Rounding note: JavaScript's Math.round is floor(x + 0.5) (round-half-UP), NOT Python's round()
(round-half-to-even). `jsround` below reproduces the JS behaviour so results match the frontend exactly.
"""
import math

# ── Constants (must mirror templates/index.html) ─────────────────────────────
SI_CAP = 46_800_000          # SI/HI/UI contribution cap (base = P1 + P2, capped here)
PIT_SELF = 11_000_000        # personal PIT deduction
PIT_DEP = 4_400_000          # per-dependant PIT deduction
LUNCH, PHONE, TRANSPORT = 730_000, 300_000, 500_000
WELFARE = LUNCH + PHONE + TRANSPORT   # 1,530,000

# Employee SI/HI/UI rates (total 10.5%) and employer rates (total 23.5%).
EE_RATES = {"bhxh": 0.08, "bhyt": 0.015, "bhtn": 0.01}
ER_RATES = {"bhxh": 0.175, "bhyt": 0.03, "bhtn": 0.01, "tu": 0.02}

# Progressive monthly PIT brackets: (width, rate). Last width is unbounded.
PIT_BRACKETS = [(5_000_000, 0.05), (5_000_000, 0.10), (8_000_000, 0.15),
                (14_000_000, 0.20), (20_000_000, 0.25), (28_000_000, 0.30), (math.inf, 0.35)]

# Grade table (index 0..9 → G1..G10); `mid` is the default gross when an employee has no explicit salary.
GRADES = [
    ("G1", 5_000_000, 7_000_000, 9_000_000), ("G2", 12_000_000, 15_000_000, 18_000_000),
    ("G3", 18_000_000, 22_000_000, 26_000_000), ("G4", 26_000_000, 32_000_000, 40_000_000),
    ("G5", 38_000_000, 46_000_000, 56_000_000), ("G6", 52_000_000, 62_000_000, 74_000_000),
    ("G7", 70_000_000, 85_000_000, 100_000_000), ("G8", 95_000_000, 115_000_000, 140_000_000),
    ("G9", 130_000_000, 160_000_000, 200_000_000), ("G10", 180_000_000, 240_000_000, 320_000_000),
]


def jsround(x):
    """Reproduce JavaScript Math.round (round half UP): floor(x + 0.5)."""
    return math.floor(x + 0.5)


def pit(taxable):
    """Progressive monthly PIT on `taxable` income (rounded, JS-style). Mirrors _payPit."""
    if taxable <= 0:
        return 0
    tax, rem = 0.0, taxable
    for amt, rate in PIT_BRACKETS:
        x = min(rem, amt)
        tax += x * rate
        rem -= x
        if rem <= 0:
            break
    return jsround(tax)


def perf_factor(rating):
    """KPI performance multiplier by rating (matches the frontend's ladder)."""
    r = rating or 3
    return 1.5 if r >= 5 else 1.25 if r >= 4 else 1.0 if r >= 3 else 0.5 if r >= 2 else 0


def compute(gross, gi=2, yrs=0, rating=3, deps=0, has_cert=False, working_days=22, unpaid_days=0,
            ot_units=0, ot_taxable_units=0, ot_hours=0, ot_night_hours=0):
    """One employee's payslip for a month. Inputs are the already-resolved drivers:
      gross        — monthly gross (employee.salary, else grade mid)
      gi           — grade index 0..9 (position allowance applies at gi >= 4)
      yrs          — years of service (skill/seniority allowance at yrs >= 5)
      rating       — PADR rating 0..5 (drives the P3 KPI factor)
      deps         — number of PIT dependants
      has_cert     — has an English certificate (also triggers the skill allowance)
      working_days — standard working days in the month (unpaid-leave proration base)
      unpaid_days  — approved unpaid-leave days this month
      ot_units     — approved overtime as MULTIPLIER-hours (overtime.month_summary with hourly=1.0):
                     the Art. 98 rates, the night premium and the day types are already inside it
      ot_taxable_units — the same hours at the plain rate; only the premium above it escapes PIT
      ot_hours / ot_night_hours — carried through for the wage statement, not for the arithmetic
    Returns a dict of the rounded payslip fields (same keys as the frontend snapshot)."""
    basic = gross * 0.65
    pos_allow = gross * 0.05 if gi >= 4 else 0
    responsibility = gross * 0.10
    skill_sen = gross * 0.05 if (yrs >= 5 or has_cert) else 0
    P1 = basic + pos_allow
    P2 = responsibility + skill_sen
    kpi_target = gross * 0.10
    P3 = kpi_target * perf_factor(rating)

    si_base = min(P1 + P2, SI_CAP)
    ee = {k: si_base * v for k, v in EE_RATES.items()}
    ee_total = sum(ee.values())
    er = {k: si_base * v for k, v in ER_RATES.items()}
    er_total = sum(er.values())

    unpaid_deduction = (P1 + P2) / working_days * unpaid_days if working_days else 0

    # Overtime (Labour Code Art. 98, Decree 145/2020 Art. 55). The hourly wage is the wage-and-
    # allowance pay over the normal hours in the month — bonuses, welfare and overtime itself are
    # excluded from that base, so P3 and the meal/phone/transport welfare stay out of it.
    # Overtime is NOT in the SI base, and per Circular 111/2013 Art. 3(1)(i) only the ordinary-rate
    # part of it is taxable; the premium above that is exempt.
    ot_hourly = (P1 + P2) / max(1, working_days * 8)
    ot_pay = jsround(ot_hourly * (ot_units or 0))
    ot_taxable = jsround(ot_hourly * (ot_taxable_units or 0))
    ot_exempt = max(0, ot_pay - ot_taxable)

    taxable = max(0, (P1 + P2 + P3 + TRANSPORT + ot_taxable) - ee_total - PIT_SELF - deps * PIT_DEP)
    p = pit(taxable)
    gross_pay = P1 + P2 + P3 + WELFARE + ot_pay
    net = gross_pay - ee_total - p - unpaid_deduction

    return {
        "P1": jsround(P1), "P2": jsround(P2), "P3": jsround(P3), "kpiTarget": jsround(kpi_target),
        "welfare": WELFARE, "siBase": jsround(si_base),
        "otHours": ot_hours, "otNightHours": ot_night_hours, "otHourly": jsround(ot_hourly),
        "otPay": ot_pay, "otTaxable": ot_taxable, "otExempt": ot_exempt,
        "eeBhxh": jsround(ee["bhxh"]), "eeBhyt": jsround(ee["bhyt"]), "eeBhtn": jsround(ee["bhtn"]),
        "si": jsround(ee_total),
        "erBhxh": jsround(er["bhxh"]), "erBhyt": jsround(er["bhyt"]), "erBhtn": jsround(er["bhtn"]),
        "erTu": jsround(er["tu"]), "erTotal": jsround(er_total),
        "pit": jsround(p), "grossPay": jsround(gross_pay),
        "unpaidDeduction": jsround(unpaid_deduction),
        "employerCost": jsround(gross_pay + er_total), "net": jsround(net),
    }
