"""A money figure written out in Vietnamese words.

Every Vietnamese contract, payment voucher and receipt states the amount twice: in figures and then
"bằng chữ" — in words. It is not decoration. The words are what a reader checks the figures against,
and on a signed document they are what settles an argument about a transposed digit.

The reading rules are fixed but full of small irregularities, and each one is a way to produce a
document that a Vietnamese reader can see is machine-written:

  · 15 is "mười lăm", never "mười năm" — five becomes `lăm` after a tens word.
  · 21 is "hai mươi mốt", never "hai mươi một" — one becomes `mốt` after `mươi`.
  · 24 is "hai mươi tư". `bốn` is also correct and both are used in practice; `tư` is the form the
    model contract and bank documents use, so that is the one here.
  · 105 is "một trăm linh năm" — a zero in the tens column is spoken as `linh`, not skipped.
  · Inside a larger number, a group with no hundreds still says "không trăm": 1,005 is "một nghìn
    không trăm linh năm", because "một nghìn năm" is how 1,500 is said.
  · A wholly empty group is dropped instead, and the scale word carries the meaning: 1,000,105 is
    "một triệu một trăm linh năm" — no "nghìn" is spoken, which is exactly what distinguishes it
    from 1,100,000, "một triệu một trăm nghìn".

Pure. Exercised by tests/test_vn_amount.py.
"""
UNITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")
# Vietnamese has no word above `tỷ`; larger numbers are read as multiples of it — 10^12 is "một
# nghìn tỷ", handled by recursion in words(). Before that, words(10**12) put 1000 into _group and
# raised IndexError out of UNITS[10] — reachable from any contract wage box, so an unhandled 500 on
# /api/hr/contract.
SCALES = ((10 ** 9, "tỷ"), (10 ** 6, "triệu"), (10 ** 3, "nghìn"), (1, ""))
BILLION = 10 ** 9

CURRENCY = "đồng"


def _group(n, full):
    """One group of three digits. `full` means it sits inside a larger number, so a missing
    hundreds digit must still be spoken — otherwise 1,000,105 reads as 1,000,5."""
    h, t, u = n // 100, (n // 10) % 10, n % 10
    parts = []
    if h or full:
        parts += [UNITS[h], "trăm"]
    if t == 0:
        if u:
            # `linh` (northern) / `lẻ` (southern) — both standard; the model form uses `linh`.
            if h or full:
                parts.append("linh")
            parts.append(UNITS[u])
    elif t == 1:
        parts.append("mười")
        if u == 5:
            parts.append("lăm")
        elif u:
            parts.append(UNITS[u])
    else:
        parts += [UNITS[t], "mươi"]
        if u == 1:
            parts.append("mốt")
        elif u == 4:
            parts.append("tư")
        elif u == 5:
            parts.append("lăm")
        elif u:
            parts.append(UNITS[u])
    return " ".join(parts)


def words(amount):
    """The whole-đồng part of `amount` in Vietnamese words, with no currency noun.

    Fractions of a đồng do not exist in practice and are not silently dropped: the value is rounded
    to the nearest đồng, which is what payroll already does, rather than truncated.
    """
    try:
        n = int(round(float(amount)))
    except (TypeError, ValueError):
        return ""
    if n == 0:
        return "không"
    sign = "âm " if n < 0 else ""
    n = abs(n)
    said = []
    started = False                 # has a higher group already been spoken?
    # Anything at or above 10^12 is spoken as "<that many> tỷ": 2,500,000,000,000 is
    # "hai nghìn năm trăm tỷ". Recursing keeps one implementation of the reading rules.
    if n >= 1000 * BILLION:
        head, n = divmod(n, BILLION)
        said.append(words(head))
        said.append("tỷ")
        started = True
        if not n:
            return sign + " ".join(w for w in said if w)
    for value, name in SCALES:
        part, n = divmod(n, value)
        if not part:
            # A wholly empty group is skipped. The next non-empty one still says "không trăm",
            # because `started` is already true by then.
            continue
        said.append(_group(part, started))
        if name:
            said.append(name)
        started = True
    return sign + " ".join(w for w in said if w)


def in_words(amount, currency=CURRENCY):
    """The full "bằng chữ" line: capitalised, with the currency noun, as it prints on a document."""
    w = words(amount)
    if not w:
        return ""
    if currency:
        w = "%s %s" % (w, currency)
    return w[0].upper() + w[1:]
