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
person, and leaves the decision where it belongs.

**Both caps are EFFECTIVE-DATED, and neither is a constant.** They were, and both were wrong.

  · The base salary sat here as one literal used as a default argument, evaluated at import. A
    return for June 2024 was therefore measured against the figure that took effect in July, and
    would be measured against a future revision the day one is added.
  · The regional minimum wage sat here as a SECOND COPY of a table `min_wage.py` already owns and
    already effective-dates. The copy went stale exactly as a copy does: min_wage carried Decree
    293/2025 from 1 January 2026 (Region I ₫5,310,000) while this file still said ₫4,960,000, so
    every 2026 return capped unemployment insurance at ₫99,200,000 instead of ₫106,200,000 —
    confidently, and with nothing to notice it. The table is gone; `min_wage.at()` is asked.

A cap now needs the DAY the return is for, and says which decree it used. Where the day is not
given, the cap is None and the contribution is reported as uncapped-and-unknown rather than
computed against whichever decree happened to be newest when the file was written. A pure module
has no clock, and inventing one here is how a 2025 payslip gets measured by a 2026 decree.

**WHAT THIS MODULE DOES NOT DECIDE.** The Social Insurance Law 2024 (Luật BHXH 41/2024/QH15, in
force 1 July 2025) moves the BHXH/BHYT ceiling off *mức lương cơ sở* and onto a reference level,
*mức tham chiếu*. Until the operative figure and the transition are confirmed by the company's
accountant, the schedule below continues on the base salary and SAYS SO on every answer. Encoding a
reference level nobody here has verified would move real money on a filed return — the same reason
min_wage.py declines to assert the 7% vocational uplift as law.
"""
import min_wage
# mức lương cơ sở, by the decree that set it. (in force from, decree, amount) — `_at` sorts, so
# the order here is for readers.
BASE_SALARY_SCHEDULE = (
    ("2024-07-01", "Decree 73/2024/NĐ-CP", 2_340_000),
    ("2023-07-01", "Decree 24/2023/NĐ-CP", 1_800_000),
    ("2019-07-01", "Decree 38/2019/NĐ-CP", 1_490_000),
)

# The reference-level change this module does not encode. Carried as text so it reaches the screen
# and the return rather than living only in the docstring above.
TAM_CHIEU_NOTE = (
    "From 1 July 2025 the Social Insurance Law 2024 moves the BHXH/BHYT ceiling off the base "
    "salary (mức lương cơ sở) and onto a reference level (mức tham chiếu). This return is still "
    "computed on the base salary. Confirm the reference level with your accountant before filing "
    "a period from July 2025 onwards.")
TAM_CHIEU_FROM = "2025-07-01"

CAP_MULTIPLE = 20

EE_RATES = {"bhxh": 0.08, "bhyt": 0.015, "bhtn": 0.01}
ER_RATES = {"bhxh": 0.175, "bhyt": 0.03, "bhtn": 0.01}
UNION_RATE = 0.02                      # kinh phí công đoàn — employer only, not an insurance fund

FUND_NAMES = {"bhxh": "Social insurance (BHXH)", "bhyt": "Health insurance (BHYT)",
              "bhtn": "Unemployment insurance (BHTN)"}


def base_salary_at(on_date):
    """The base salary in force on that day, with the decree that set it, or None.

    None where the day is missing or falls before the earliest decree recorded here. Refusing is the
    point: a return for a month this module cannot place must not be measured against whichever
    figure happened to be newest when the file was written.
    """
    d = str(on_date or "")[:10]
    if len(d) != 10 or d[4] != "-" or d[7] != "-":
        return None
    for frm, decree, amount in sorted(BASE_SALARY_SCHEDULE, reverse=True):
        if d >= frm:
            return {"amount": amount, "decree": decree, "inForceFrom": frm,
                    "basis": "%s — base salary (mức lương cơ sở) ₫%s, in force from %s."
                             % (decree, "{:,.0f}".format(amount), frm)}
    return None


def si_hi_cap(base_salary=None, on_date=None):
    """The BHXH/BHYT ceiling: 20 × the base salary.

    An explicit `base_salary` wins — a company that has been told a different figure by its social
    insurance office uses it, and this module is not the authority on that. Otherwise the day
    decides. Neither given, the answer is None and not a number: a cap computed from nothing is
    indistinguishable on screen from a cap somebody chose.
    """
    if base_salary:
        return CAP_MULTIPLE * int(base_salary)
    b = base_salary_at(on_date)
    return CAP_MULTIPLE * int(b["amount"]) if b else None


def ui_cap(region="I", on_date=None, region_min=None):
    """The BHTN ceiling: 20 × the REGIONAL minimum wage, read from the module that owns it.

    `min_wage.at()` is asked rather than a copy kept here. The copy that used to live in this file
    is the reason every 2026 return capped unemployment insurance ₫7,000,000 of base too low.
    """
    if region_min:
        return CAP_MULTIPLE * int(region_min)
    floor = min_wage.at(region, on_date)
    return CAP_MULTIPLE * int(floor["monthly"]) if floor else None


def _n(v, d=0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return x if x == x else d


def _line_calc(line):
    return (line or {}).get("calc") or {}


def contributions(lines, region="I", on_date=None, base_salary=None, region_min=None):
    """The contribution schedule, and where it differs from what the caps require.

    `withheld` is what the signed run actually took. `required` is what the statutory caps imply.
    They are reported side by side rather than reconciled, because only one of them has already been
    paid to the authority and this module is not entitled to rewrite that.
    """
    cap_si = si_hi_cap(base_salary, on_date)
    cap_ui = ui_cap(region, on_date, region_min)
    # Named rather than left to be inferred from a null. An uncapped contribution is not the same
    # fact as a contribution capped at a figure somebody chose, and on a filed return the
    # difference is money.
    notes = []
    if cap_si is None:
        notes.append("The BHXH/BHYT ceiling could not be established for this period — no base "
                     "salary is recorded for it and none was supplied — so those contributions are "
                     "shown UNCAPPED. They are not a filing figure until a base salary is set.")
    if cap_ui is None:
        notes.append("The BHTN ceiling could not be established for this period: region '%s' has "
                     "no minimum wage in force on that day. Unemployment insurance is shown "
                     "uncapped." % (region or "(none)"))
    if on_date and str(on_date)[:10] >= TAM_CHIEU_FROM:
        notes.append(TAM_CHIEU_NOTE)
    basis_si = base_salary_at(on_date)
    basis_ui = min_wage.at(region, on_date)
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
        # The figure each cap was built from, and the DECREE that set it. A cap on a filed return
        # with no decree beside it is a number nobody can check a year later.
        "baseSalary": (int(base_salary) if base_salary
                       else (basis_si["amount"] if basis_si else None)),
        "baseSalaryBasis": ("supplied by the company" if base_salary
                            else (basis_si["basis"] if basis_si else "")),
        "regionMinWage": (int(region_min) if region_min
                          else (basis_ui["monthly"] if basis_ui else None)),
        "regionMinWageBasis": ("supplied by the company" if region_min
                               else (basis_ui["basis"] if basis_ui else "")),
        "onDate": str(on_date or "")[:10],
        "capBasis": ("BHXH and BHYT cap at 20 × the base salary (%s); BHTN caps at 20 × the Region "
                     "%s minimum wage (%s)."
                     % ("{:,}".format(cap_si // CAP_MULTIPLE) if cap_si else "not established",
                        str(region or "I").upper(),
                        "{:,}".format(cap_ui // CAP_MULTIPLE) if cap_ui else "not established")),
        # Empty on a period this module could place. Never absent, so a caller that forgets to
        # render it is a caller that renders an empty list rather than one that hides a refusal.
        "notes": notes,
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
