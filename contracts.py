"""Labour contracts: when they expire, and what the law does about it if nobody notices.

The portal has employee records and start dates. It has never had the contracts themselves — so
nothing knows whose definite-term contract runs out next month, nobody is told, and the consequences
of missing it happen silently and by operation of law rather than by anybody's decision.

Article 20 of the Labour Code 2019 is unusually mechanical, which makes it a good fit for code:

  Art. 20(1)(a)   an indefinite-term contract has no end date.
  Art. 20(1)(b)   a definite-term contract runs for AT MOST 36 months from the day it takes effect.
  Art. 20(2)(a)   when a definite-term contract expires and the employee keeps working, the parties
                  have 30 days to sign a new one; until they do, the old terms continue.
  Art. 20(2)(b)   after those 30 days with nothing signed, the contract BECOMES indefinite-term.
                  Not "should be" — it already has, whatever the file says.
  Art. 20(2)(c)   a replacement may itself be definite-term only ONCE. After that, an employee who
                  keeps working must be on an indefinite-term contract. The exceptions are narrow:
                  a hired director of a state-capital enterprise, an elderly employee (Art. 149(1)),
                  a foreign worker (Art. 151(2)), and a full-time trade-union officer (Art. 177(4)).

So the questions this module answers are the ones that arrive late: whose contract is about to run
out, whose already has, who is now on an indefinite-term contract without anybody deciding it, and
who cannot lawfully be given another fixed term.

Pure — no database, no clock. Every rule is exercised by tests/test_contracts.py.
"""
from datetime import date, timedelta

import datespan

INDEFINITE = "indefinite"
DEFINITE = "definite"
TYPES = (INDEFINITE, DEFINITE)

MAX_DEFINITE_MONTHS = 36        # Art. 20(1)(b)
GRACE_DAYS = 30                 # Art. 20(2)(a): the window to sign a replacement
MAX_DEFINITE_CONTRACTS = 2      # Art. 20(2)(c): the original, then one more
DEFAULT_WARN_DAYS = 45          # how far ahead "expiring soon" reaches; a business choice, not law

# Art. 20(2)(c) exempts these from the two-contract limit — they may be renewed on fixed terms
# indefinitely. Recorded per employee, because it is a legal status, not something to infer.
RENEWAL_EXEMPT = ("elderly", "foreign", "state_director", "union_officer")


def _d(value):
    if isinstance(value, date):
        return value
    try:
        y, m, dd = (int(x) for x in str(value)[:10].split("-"))
        return date(y, m, dd)
    except (ValueError, AttributeError, TypeError):
        return None


def term_months(start, end):
    """Whole months of a contract term, for the Art. 20(1)(b) ceiling. The end date is the last day
    covered, so 1 Jan 2026 → 31 Dec 2028 is 36 months, not 35.

    This used a day-of-month shortcut that over-counted by one for any contract NOT starting on the
    1st: a perfectly lawful 15 Mar 2026 → 14 Mar 2029 read as 37 months and was reported to HR as
    breaching the ceiling. Roughly half of all contracts start mid-month.
    """
    return datespan.whole_months(start, end)


def last_lawful_end(start):
    """The latest date a fixed term starting on `start` may run to: the day before its 36-month
    anniversary (Art. 20(1)(b))."""
    end = datespan.add_months(start, MAX_DEFINITE_MONTHS)
    return (end - timedelta(days=1)) if end else None


def exceeds_max_term(start, end):
    """Art. 20(1)(b). A fixed term longer than 36 months is not a longer contract — it is an unlawful
    one, and the excess is unenforceable.

    Compared as DATES rather than as a month count. Whole months cannot see the difference between a
    term of exactly 36 months and one of 36 months and a day, and the second of those exceeds the
    ceiling while the first does not.
    """
    s, e, limit = _d(start), _d(end), last_lawful_end(start)
    if not s or not e or not limit:
        return False
    return e > limit


def status(contract, as_of):
    """Where one contract stands on a given date.

      'indefinite'   no end date — it does not expire
      'active'       running, with time left
      'expiring'     running, but inside the warning window
      'grace'        expired within the last 30 days: Art. 20(2)(a), sign a replacement NOW
      'lapsed'       expired more than 30 days ago and the employee is still working, so under
                     Art. 20(2)(b) the contract is ALREADY indefinite-term
      'unknown'      no usable end date on a contract that claims to have one
    """
    a = _d(as_of)
    if str(contract.get("type") or DEFINITE) == INDEFINITE:
        return "indefinite"
    e = _d(contract.get("endDate"))
    if not e or not a:
        return "unknown"
    if a <= e:
        warn = int(contract.get("warnDays") or DEFAULT_WARN_DAYS)
        return "expiring" if (e - a).days <= warn else "active"
    return "grace" if (a - e).days <= GRACE_DAYS else "lapsed"


def days_left(contract, as_of):
    """Days until expiry — negative once it has passed. None for an indefinite contract."""
    e, a = _d(contract.get("endDate")), _d(as_of)
    if str(contract.get("type") or DEFINITE) == INDEFINITE or not e or not a:
        return None
    return (e - a).days


def becomes_indefinite_on(contract):
    """The date a lapsed fixed term turned into an indefinite one, under Art. 20(2)(b)."""
    e = _d(contract.get("endDate"))
    if not e or str(contract.get("type") or DEFINITE) == INDEFINITE:
        return None
    return e + timedelta(days=GRACE_DAYS + 1)


def next_contract_must_be_indefinite(history, exempt=None):
    """Art. 20(2)(c): may this employee lawfully be given another fixed term?

    `history` is their contracts, any order. Two definite-term contracts is the limit — the original
    and one replacement — after which an employee who keeps working must go onto an indefinite-term
    contract. An employee already on an indefinite contract is not going backwards either.

    `exempt` is one of RENEWAL_EXEMPT where the employee falls inside one of the article's narrow
    carve-outs, in which case fixed terms may continue.
    """
    if exempt in RENEWAL_EXEMPT:
        return False
    if any(str(c.get("type") or DEFINITE) == INDEFINITE for c in history or ()):
        return True
    return len([c for c in (history or ()) if str(c.get("type") or DEFINITE) == DEFINITE]) \
        >= MAX_DEFINITE_CONTRACTS


def current(history, as_of):
    """The contract in force on a date: the one that has started and whose end has not yet passed,
    latest start first. Failing that, the most recent one to have started — because an employee
    working past an expiry is still working under those terms (Art. 20(2)(a)), and a lapsed contract
    is the thing that needs answering, not something to hide by returning nothing."""
    a = _d(as_of)
    started = [c for c in (history or ()) if _d(c.get("startDate")) and _d(c.get("startDate")) <= a]
    if not started:
        return None
    started.sort(key=lambda c: str(c.get("startDate"))[:10], reverse=True)
    live = [c for c in started
            if str(c.get("type") or DEFINITE) == INDEFINITE
            or (_d(c.get("endDate")) and _d(c.get("endDate")) >= a)]
    return live[0] if live else started[0]


def review(history, as_of, exempt=None):
    """One employee's contract position, and everything about it that needs somebody's attention.

    Returns the contract in force, its status, and `issues` — each one a thing the law says has
    happened or must happen, in the words somebody would need to act on.
    """
    hist = list(history or ())
    cur = current(hist, as_of)
    out = {"contract": cur, "status": "none", "daysLeft": None, "issues": [],
           "definiteCount": len([c for c in hist if str(c.get("type") or DEFINITE) == DEFINITE]),
           "mustBeIndefinite": next_contract_must_be_indefinite(hist, exempt)}
    if not cur:
        out["issues"].append({"kind": "missing", "severity": "high",
                              "message": "No labour contract on file. Art. 13 requires one in "
                                         "writing before work begins."})
        return out

    out["status"] = status(cur, as_of)
    out["daysLeft"] = days_left(cur, as_of)

    if exceeds_max_term(cur.get("startDate"), cur.get("endDate")) \
            and str(cur.get("type") or DEFINITE) == DEFINITE:
        out["issues"].append({"kind": "term_too_long", "severity": "high",
                              "message": "A fixed term may not exceed 36 months (Art. 20(1)(b)); "
                                         "this one runs %d." % term_months(cur.get("startDate"),
                                                                          cur.get("endDate"))})
    if out["status"] == "expiring":
        out["issues"].append({"kind": "expiring", "severity": "medium",
                              "message": "Expires in %d day(s). A replacement must be signed within "
                                         "30 days of expiry (Art. 20(2)(a))." % out["daysLeft"]})
    elif out["status"] == "grace":
        out["issues"].append({"kind": "grace", "severity": "high",
                              "message": "Expired %d day(s) ago. Sign a new contract before %s or it "
                                         "becomes indefinite-term by law (Art. 20(2))."
                                         % (-out["daysLeft"], becomes_indefinite_on(cur))})
    elif out["status"] == "lapsed":
        out["issues"].append({"kind": "lapsed", "severity": "high",
                              "message": "Expired on %s and no replacement was signed within 30 days, "
                                         "so this is ALREADY an indefinite-term contract "
                                         "(Art. 20(2)(b)) — the record should say so."
                                         % str(cur.get("endDate"))[:10]})
    elif out["status"] == "unknown":
        out["issues"].append({"kind": "no_end_date", "severity": "medium",
                              "message": "A fixed-term contract with no end date on record. Either "
                                         "the date is missing or it is indefinite-term."})

    if out["mustBeIndefinite"] and str(cur.get("type") or DEFINITE) == DEFINITE \
            and out["status"] in ("expiring", "grace", "lapsed"):
        out["issues"].append({"kind": "must_be_indefinite", "severity": "high",
                              "message": "This employee has already had %d fixed-term contracts. "
                                         "Under Art. 20(2)(c) the next one must be indefinite-term."
                                         % out["definiteCount"]})
    return out
