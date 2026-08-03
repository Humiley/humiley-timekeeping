"""Characterization tests for the payroll money math (payroll_calc.py).

The EXPECTED numbers below were captured from the LIVE frontend `_payComputed` (templates/index.html) for
a spread of cases — MD/default grade, cert + dependants, unpaid-leave proration, an intern at rating 1, an
explicit salary, and a low-rating manager who hits the SI cap and a non-round proration. The Python port
must reproduce them to the cent. If either implementation's math ever changes, this test fails and forces a
conscious, reviewed update — that is exactly the guard the audit asked for (payroll math was untested).
"""
import pytest

import payroll_calc as pc


def _gross(gross, gi):
    """Resolve gross the way the frontend does: explicit salary, else the grade's mid."""
    return gross if gross is not None else pc.GRADES[gi][2]


# (name, drivers, expected-payslip) — expected values are the frontend's exact output.
CASES = [
    ("MD-default-G10", dict(gross=None, gi=9, yrs=0, rating=3, deps=0, has_cert=False, working_days=22, unpaid_days=0),
     {"P1": 168000000, "P2": 24000000, "P3": 24000000, "kpiTarget": 24000000, "welfare": 1530000,
      "siBase": 46800000, "eeBhxh": 3744000, "eeBhyt": 702000, "eeBhtn": 468000, "si": 4914000,
      "erBhxh": 8190000, "erBhyt": 1404000, "erBhtn": 468000, "erTu": 936000, "erTotal": 10998000,
      "pit": 60355100, "grossPay": 217530000, "unpaidDeduction": 0, "employerCost": 228528000, "net": 152260900}),
    ("G3-cert-2dep", dict(gross=None, gi=2, yrs=8, rating=4, deps=2, has_cert=True, working_days=21, unpaid_days=0),
     {"P1": 14300000, "P2": 3300000, "P3": 2750000, "kpiTarget": 2200000, "welfare": 1530000,
      "siBase": 17600000, "eeBhxh": 1408000, "eeBhyt": 264000, "eeBhtn": 176000, "si": 1848000,
      "erBhxh": 3080000, "erBhyt": 528000, "erBhtn": 176000, "erTu": 352000, "erTotal": 4136000,
      "pit": 0, "grossPay": 21880000, "unpaidDeduction": 0, "employerCost": 26016000, "net": 20032000}),
    ("G5-unpaid3", dict(gross=None, gi=4, yrs=2, rating=5, deps=1, has_cert=False, working_days=20, unpaid_days=3),
     {"P1": 32200000, "P2": 4600000, "P3": 6900000, "kpiTarget": 4600000, "welfare": 1530000,
      "siBase": 36800000, "eeBhxh": 2944000, "eeBhyt": 552000, "eeBhtn": 368000, "si": 3864000,
      "erBhxh": 6440000, "erBhyt": 1104000, "erBhtn": 368000, "erTu": 736000, "erTotal": 8648000,
      "pit": 3337200, "grossPay": 45230000, "unpaidDeduction": 5520000, "employerCost": 53878000, "net": 32508800}),
    ("G1-intern-r1", dict(gross=None, gi=0, yrs=0, rating=1, deps=0, has_cert=False, working_days=22, unpaid_days=0),
     {"P1": 4550000, "P2": 700000, "P3": 0, "kpiTarget": 700000, "welfare": 1530000,
      "siBase": 5250000, "eeBhxh": 420000, "eeBhyt": 78750, "eeBhtn": 52500, "si": 551250,
      "erBhxh": 918750, "erBhyt": 157500, "erBhtn": 52500, "erTu": 105000, "erTotal": 1233750,
      "pit": 0, "grossPay": 6780000, "unpaidDeduction": 0, "employerCost": 8013750, "net": 6228750}),
    ("salary-explicit", dict(gross=50000000, gi=2, yrs=6, rating=3, deps=0, has_cert=False, working_days=23, unpaid_days=0),
     {"P1": 32500000, "P2": 7500000, "P3": 5000000, "kpiTarget": 5000000, "welfare": 1530000,
      "siBase": 40000000, "eeBhxh": 3200000, "eeBhyt": 600000, "eeBhtn": 400000, "si": 4200000,
      "erBhxh": 7000000, "erBhyt": 1200000, "erBhtn": 400000, "erTu": 800000, "erTotal": 9400000,
      "pit": 4410000, "grossPay": 46530000, "unpaidDeduction": 0, "employerCost": 55930000, "net": 37920000}),
    ("G7-lowrating-cap-proration", dict(gross=None, gi=6, yrs=11, rating=2, deps=3, has_cert=False, working_days=22, unpaid_days=1),
     {"P1": 59500000, "P2": 12750000, "P3": 4250000, "kpiTarget": 8500000, "welfare": 1530000,
      "siBase": 46800000, "eeBhxh": 3744000, "eeBhyt": 702000, "eeBhtn": 468000, "si": 4914000,
      "erBhxh": 8190000, "erBhyt": 1404000, "erBhtn": 468000, "erTu": 936000, "erTotal": 10998000,
      "pit": 8721500, "grossPay": 78030000, "unpaidDeduction": 3284091, "employerCost": 89028000, "net": 61110409}),
]


@pytest.mark.parametrize("name,d,expect", CASES, ids=[c[0] for c in CASES])
def test_payslip_matches_frontend(name, d, expect):
    got = pc.compute(_gross(d["gross"], d["gi"]), gi=d["gi"], yrs=d["yrs"], rating=d["rating"],
                     deps=d["deps"], has_cert=d["has_cert"], working_days=d["working_days"], unpaid_days=d["unpaid_days"])
    for k, v in expect.items():
        assert got[k] == v, "%s field %s: got %s, expected %s" % (name, k, got.get(k), v)


def test_internal_identities_hold():
    # Structural invariants that must hold for every payslip, on top of the exact numbers above.
    for name, d, _ in CASES:
        c = pc.compute(_gross(d["gross"], d["gi"]), gi=d["gi"], yrs=d["yrs"], rating=d["rating"],
                       deps=d["deps"], has_cert=d["has_cert"], working_days=d["working_days"], unpaid_days=d["unpaid_days"])
        assert c["si"] == c["eeBhxh"] + c["eeBhyt"] + c["eeBhtn"]
        assert c["erTotal"] == c["erBhxh"] + c["erBhyt"] + c["erBhtn"] + c["erTu"]
        assert c["siBase"] <= pc.SI_CAP
        assert c["employerCost"] == c["grossPay"] + c["erTotal"]


def test_pit_brackets():
    assert pc.pit(0) == 0 and pc.pit(-100) == 0
    assert pc.pit(5_000_000) == 250_000                    # whole first bracket @5%
    assert pc.pit(10_000_000) == 250_000 + 500_000         # + second @10%
    # 100M taxable: 5@5 + 5@10 + 8@15 + 14@20 + 20@25 + 28@30 + 20@35
    assert pc.pit(100_000_000) == (250_000 + 500_000 + 1_200_000 + 2_800_000 + 5_000_000 + 8_400_000 + 7_000_000)


def test_jsround_is_half_up_not_bankers():
    assert pc.jsround(0.5) == 1 and pc.jsround(1.5) == 2 and pc.jsround(2.5) == 3   # Python round() would give 0/2/2
    assert pc.jsround(-0.5) == 0
