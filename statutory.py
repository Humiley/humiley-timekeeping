"""The returns a Vietnamese employer has to file, built from what was actually paid.

Three outputs, all sourced from a SIGNED pay run rather than recomputed — a declaration that
disagrees with the payslips it came from is worse than a late one.

  · the social-insurance contribution schedule (BHXH / BHYT / BHTN, employee and employer)
  · the PIT withholding summary behind the monthly declaration
  · the labour-usage report, Decree 145/2020 Art. 4, filed twice a year

**The variance this module exists to surface.** The portal caps all three funds at one figure. The
law does not:

  · **BHXH and BHYT** cap at 20 × the base salary (*mức lương cơ sở*) — ₫2,340,000 since
    1 July 2024 under Decree 73/2024, so ₫46,800,000.
  · **BHTN** caps at 20 × the REGIONAL minimum wage (*mức lương tối thiểu vùng*) — ₫4,960,000 in
    Region I since 1 July 2024 under Decree 74/2024, so ₫99,200,000.

Anybody whose contribution base sits between those two figures has had unemployment insurance
withheld on the lower one. This module does NOT change what was withheld — a number already filed
should not move underneath the person who filed it. It computes both, reports the difference per
person, and leaves the decision where it belongs. The figures are parameters, not literals, because
both are revised by decree and a hardcoded cap becomes wrong silently.
"""
BASE_SALARY = 2_340_000                # mức lương cơ sở — Decree 73/2024, from 1 July 2024
REGION_MIN_WAGE = {                    # mức lương tối thiểu vùng — Decree 74/2024, from 1 July 2024
    "I": 4_960_000, "II": 4_410_000, "III": 3_860_000, "IV": 3_450_000,
}
CAP_MULTIPLE = 20

EE_RATES = {"bhxh": 0.08, "bhyt": 0.015, "bhtn": 0.01}
ER_RATES = {"bhxh": 0.175, "bhyt": 0.03, "bhtn": 0.01}
UNION_RATE = 0.02                      # kinh phí công đoàn — employer only, not an insurance fund

FUND_NAMES = {"bhxh": "Social insurance (BHXH)", "bhyt": "Health insurance (BHYT)",
              "bhtn": "Unemployment insurance (BHTN)"}


def si_hi_cap(base_salary=BASE_SALARY):
    return CAP_MULTIPLE * int(base_salary or 0)


def ui_cap(region="I", region_min=None):
    mw = region_min if region_min else REGION_MIN_WAGE.get(str(region or "I").upper(), 0)
    return CAP_MULTIPLE * int(mw or 0)


def _n(v, d=0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return x if x == x else d


def _line_calc(line):
    return (line or {}).get("calc") or {}


def contributions(lines, region="I", base_salary=BASE_SALARY, region_min=None):
    """The contribution schedule, and where it differs from what the caps require.

    `withheld` is what the signed run actually took. `required` is what the statutory caps imply.
    They are reported side by side rather than reconciled, because only one of them has already been
    paid to the authority and this module is not entitled to rewrite that.
    """
    cap_si = si_hi_cap(base_salary)
    cap_ui = ui_cap(region, region_min)
    rows, tot = [], {"eeBhxh": 0, "eeBhyt": 0, "eeBhtn": 0, "erBhxh": 0, "erBhyt": 0,
                     "erBhtn": 0, "union": 0, "base": 0, "variance": 0}

    for ln in (lines or []):
        c = _line_calc(ln)
        # The UNCAPPED contribution base is P1 + P2; the run stores the already-capped siBase, so the
        # true base has to come from the components or it cannot be re-capped differently.
        raw = _n(c.get("P1")) + _n(c.get("P2"))
        if not raw:
            raw = _n(c.get("siBase"))
        base_si = min(raw, cap_si) if cap_si else raw
        base_ui = min(raw, cap_ui) if cap_ui else raw

        withheld = {
            "eeBhxh": int(round(_n(c.get("eeBhxh")))), "eeBhyt": int(round(_n(c.get("eeBhyt")))),
            "eeBhtn": int(round(_n(c.get("eeBhtn")))),
            "erBhxh": int(round(_n(c.get("erBhxh")))), "erBhyt": int(round(_n(c.get("erBhyt")))),
            "erBhtn": int(round(_n(c.get("erBhtn")))), "union": int(round(_n(c.get("erTu")))),
        }
        required = {
            "eeBhxh": int(round(base_si * EE_RATES["bhxh"])),
            "eeBhyt": int(round(base_si * EE_RATES["bhyt"])),
            "eeBhtn": int(round(base_ui * EE_RATES["bhtn"])),
            "erBhxh": int(round(base_si * ER_RATES["bhxh"])),
            "erBhyt": int(round(base_si * ER_RATES["bhyt"])),
            "erBhtn": int(round(base_ui * ER_RATES["bhtn"])),
            "union": int(round(base_si * UNION_RATE)),
        }
        var = sum(required[k] - withheld[k] for k in required)
        rows.append({
            "empId": ln.get("empId") or "", "name": ln.get("name") or "",
            "dept": ln.get("dept") or "",
            "contributionBase": int(round(raw)),
            "baseSiHi": int(round(base_si)), "baseUi": int(round(base_ui)),
            "withheld": withheld, "required": required, "variance": var,
            # Which cap actually bound them — the sentence that explains a variance without anybody
            # having to reverse-engineer it.
            "capNote": _cap_note(raw, cap_si, cap_ui),
        })
        for k in ("eeBhxh", "eeBhyt", "eeBhtn", "erBhxh", "erBhyt", "erBhtn", "union"):
            tot[k] += withheld[k]
        tot["base"] += int(round(raw))
        tot["variance"] += var

    tot["employee"] = tot["eeBhxh"] + tot["eeBhyt"] + tot["eeBhtn"]
    tot["employer"] = tot["erBhxh"] + tot["erBhyt"] + tot["erBhtn"]
    affected = [r for r in rows if r["variance"]]
    return {
        "rows": sorted(rows, key=lambda r: (-abs(r["variance"]), r["name"])),
        "totals": tot,
        "capSiHi": cap_si, "capUi": cap_ui, "region": str(region or "I").upper(),
        "baseSalary": int(base_salary or 0),
        "capBasis": ("BHXH and BHYT cap at 20 × the base salary (%s); BHTN caps at 20 × the Region "
                     "%s minimum wage (%s)." % (f"{int(base_salary or 0):,}",
                                                str(region or "I").upper(),
                                                f"{ui_cap(region, region_min) // CAP_MULTIPLE:,}")),
        "variance": tot["variance"],
        "affected": [{"empId": r["empId"], "name": r["name"], "variance": r["variance"],
                      "capNote": r["capNote"]} for r in affected],
    }


def _cap_note(raw, cap_si, cap_ui):
    if cap_si and raw > cap_si and cap_ui and raw <= cap_ui:
        return ("Their base is above the BHXH/BHYT cap but below the BHTN one, so unemployment "
                "insurance is due on the full base rather than on the capped figure.")
    if cap_ui and raw > cap_ui:
        return "Their base is above both caps."
    return ""


# ── PIT ──────────────────────────────────────────────────────────────────────────────────────────

def pit_summary(lines):
    """What was withheld from whom — the schedule behind the monthly PIT declaration."""
    rows, total, taxed = [], 0, 0
    for ln in (lines or []):
        c = _line_calc(ln)
        pit = int(round(_n(c.get("pit"), _n(ln.get("pit")))))
        gross = int(round(_n(c.get("grossPay"), _n(ln.get("gross")))))
        rows.append({"empId": ln.get("empId") or "", "name": ln.get("name") or "",
                     "gross": gross, "si": int(round(_n(c.get("si")))),
                     "pit": pit, "net": int(round(_n(c.get("net"), _n(ln.get("net")))))})
        total += pit
        if pit:
            taxed += 1
    return {"rows": sorted(rows, key=lambda r: (-r["pit"], r["name"])),
            "total": total, "people": len(rows), "taxed": taxed,
            # Somebody with no PIT is not an error — below the personal deduction plus dependants,
            # the liability really is nil, and a declaration listing them at zero is correct.
            "note": "Employees showing nil PIT fall below the personal and dependant deductions."}


# ── Labour usage report (Decree 145/2020 Art. 4) ─────────────────────────────────────────────────

REPORT_DEADLINES = (("06-05", "the first-half report, due 5 June"),
                    ("12-05", "the second-half report, due 5 December"))


def labour_report(employees, as_of):
    """The headcount breakdown filed with the local labour authority twice a year.

    Counted at the reporting DATE, from dated facts, so re-running it later reproduces the same
    return rather than today's roster.
    """
    import workforce
    total = fem = 0
    by_type, by_dept, unusable = {}, {}, []
    for e in (employees or []):
        if not workforce.employed_on(e, as_of):
            if not (e or {}).get("startDate"):
                unusable.append({"empId": e.get("id") or "", "name": e.get("name") or "",
                                 "why": "No start date, so they cannot be counted at a date."})
            continue
        total += 1
        g = str(e.get("gender") or "").strip().lower()
        if g.startswith("f") or g.startswith("nữ") or g.startswith("nu"):
            fem += 1
        t = str(e.get("employmentType") or "Full Time").strip() or "Full Time"
        by_type[t] = by_type.get(t, 0) + 1
        d = str(e.get("dept") or "—").strip() or "—"
        by_dept[d] = by_dept.get(d, 0) + 1
    return {
        "asOf": str(as_of), "total": total, "female": fem, "male": total - fem,
        "byType": sorted(({"type": k, "count": v} for k, v in by_type.items()),
                         key=lambda r: (-r["count"], r["type"])),
        "byDept": sorted(({"dept": k, "count": v} for k, v in by_dept.items()),
                         key=lambda r: (-r["count"], r["dept"])),
        "unusable": unusable,
        "basis": ("Decree 145/2020 Art. 4 — employers report labour usage to the local labour "
                  "authority before 5 June and 5 December each year."),
    }
