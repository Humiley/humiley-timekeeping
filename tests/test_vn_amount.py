"""A money figure in Vietnamese words.

The words are what a reader checks the figures against on a signed document, so every irregularity
in the reading rules is a way to produce something a Vietnamese reader can see is machine-written —
and a wage stated wrongly in words is a wage that can be argued about.
"""
import vn_amount as v


# ── the irregular forms, which are the whole difficulty ──────────────────────────────────────────

def test_five_becomes_lam_after_a_tens_word():
    """15 is "mười lăm". "mười năm" means five years."""
    assert v.words(15) == "mười lăm"
    assert v.words(25) == "hai mươi lăm"
    assert v.words(5) == "năm", "on its own it stays năm"


def test_one_becomes_mot_after_muoi():
    assert v.words(21) == "hai mươi mốt"
    assert v.words(11) == "mười một", "but not after mười"
    assert v.words(1) == "một"


def test_four_becomes_tu_after_muoi():
    """bốn is also correct and both are used; tư is the form the model contract uses."""
    assert v.words(24) == "hai mươi tư"
    assert v.words(14) == "mười bốn", "not after mười"
    assert v.words(4) == "bốn"


def test_a_zero_in_the_tens_column_is_spoken_as_linh():
    assert v.words(105) == "một trăm linh năm"
    assert v.words(101) == "một trăm linh một"


def test_a_group_with_no_hundreds_still_says_khong_tram():
    """"một nghìn năm" is how 1,500 is said, so 1,005 must not collapse to it."""
    assert v.words(1005) == "một nghìn không trăm linh năm"
    assert v.words(1500) == "một nghìn năm trăm"


def test_a_wholly_empty_group_is_dropped_and_the_scale_word_carries_the_meaning():
    """1,000,105 says no "nghìn" at all — which is exactly what distinguishes it from 1,100,000."""
    assert v.words(1_000_105) == "một triệu một trăm linh năm"
    assert v.words(1_100_000) == "một triệu một trăm nghìn"


# ── the figures this system actually prints ──────────────────────────────────────────────────────

def test_the_wages_and_statutory_figures_the_portal_deals_in():
    assert v.words(20_000_000) == "hai mươi triệu"
    assert v.words(2_340_000) == "hai triệu ba trăm bốn mươi nghìn"      # the base salary
    assert v.words(4_960_000) == "bốn triệu chín trăm sáu mươi nghìn"    # Region I minimum wage
    assert v.words(46_800_000) == "bốn mươi sáu triệu tám trăm nghìn"    # the BHXH/BHYT cap


def test_the_scales_go_up_to_billions():
    assert v.words(1_000_000_000) == "một tỷ"
    assert v.words(1_234_567_890) == ("một tỷ hai trăm ba mươi tư triệu năm trăm sáu mươi bảy "
                                      "nghìn tám trăm chín mươi")


# ── the printed line ─────────────────────────────────────────────────────────────────────────────

def test_the_line_that_prints_is_capitalised_and_carries_the_currency():
    assert v.in_words(20_000_000) == "Hai mươi triệu đồng"
    assert v.in_words(12_750_000) == "Mười hai triệu bảy trăm năm mươi nghìn đồng"


def test_the_currency_noun_can_be_dropped_without_losing_the_capital():
    assert v.in_words(1000, currency="") == "Một nghìn"


# ── the edges, which must not print something embarrassing ───────────────────────────────────────

def test_zero_is_a_word_not_an_empty_line():
    assert v.words(0) == "không"
    assert v.in_words(0) == "Không đồng"


def test_something_that_is_not_a_number_produces_nothing_rather_than_nonsense():
    """A blank line on a contract is recoverable. "Nan đồng" on a signed one is not."""
    for bad in (None, "", "banana", [], {}):
        assert v.words(bad) == ""
        assert v.in_words(bad) == ""


def test_a_fraction_is_rounded_to_the_dong_rather_than_truncated():
    """Payroll already rounds; truncating here would make the words disagree with the figures."""
    assert v.words(1000.4) == "một nghìn"
    assert v.words(1000.6) == "một nghìn không trăm linh một"


def test_a_negative_is_said_as_negative_rather_than_silently_flipped():
    assert v.words(-5000) == "âm năm nghìn"


def test_amounts_at_and_above_a_thousand_billion_do_not_crash():
    """words(10**12) put 1000 into the hundreds group and raised IndexError out of UNITS[10] —
    reachable from any contract wage box, so an unhandled 500 on /api/hr/contract."""
    assert v.words(10 ** 12) == "một nghìn tỷ"
    assert v.words(2_500_000_000_000) == "hai nghìn năm trăm tỷ"
    assert v.words(-(10 ** 12)) == "âm một nghìn tỷ"
    assert v.words(10 ** 15) == "một triệu tỷ"


def test_the_boundary_below_it_still_reads_the_old_way():
    assert v.words(999_999_999_999).startswith("chín trăm chín mươi chín tỷ")


def test_a_remainder_after_the_billions_head_is_still_spoken():
    assert v.words(1_000_000_000_001) == "một nghìn tỷ không trăm linh một"
