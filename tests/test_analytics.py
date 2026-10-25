"""Analytics tests: SQL results vs independent reference, plus rule and edge-case checks."""
from decimal import Decimal

import pytest

from app import analytics as an
from app.config import DEFAULT_CSV_PATH
from app.importer import import_csv
from app.db import connect_readonly
from tests import reference as ref
from tests.helpers import build_database, sale


# ----------------------------------------------------------------- supplied dataset

@pytest.fixture(scope="module")
def supplied_conn(tmp_path_factory):
    folder = tmp_path_factory.mktemp("supplied")
    import_csv(DEFAULT_CSV_PATH, folder / "sales.db", folder / "issues.csv")
    conn = connect_readonly(folder / "sales.db")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def reference():
    return ref.compute(DEFAULT_CSV_PATH)


def test_supplied_total_revenue_matches_reference(supplied_conn, reference):
    result = an.total_revenue(supplied_conn)
    assert reference.eligible_count == 49
    assert result == {
        "total_revenue": float(ref.q2(reference.total)),
        "eligible_transactions": reference.eligible_count,
    }
    assert result["total_revenue"] == 1439200.00


def test_supplied_top_product_matches_reference(supplied_conn, reference):
    expected = [(n, float(ref.q2(r)), t, u) for n, r, t, u in ref.ranking(reference.by_product)]
    result = an.top_product(supplied_conn)
    actual = [(x["name"], x["revenue"], x["transactions"], x["units"]) for x in result["ranking"]]
    assert actual == expected
    assert result["top"]["name"] == "Monitor"
    assert result["top"]["revenue"] == 473000.00


def test_supplied_top_region_matches_reference(supplied_conn, reference):
    expected = [(n, float(ref.q2(r)), t, u) for n, r, t, u in ref.ranking(reference.by_region)]
    result = an.top_region(supplied_conn)
    actual = [(x["name"], x["revenue"], x["transactions"], x["units"]) for x in result["ranking"]]
    assert actual == expected
    assert result["top"]["name"] == "South"
    assert result["top"]["revenue"] == 411200.00


def test_supplied_monthly_trend_matches_reference_and_is_chronological(supplied_conn, reference):
    result = an.monthly_revenue(supplied_conn)
    months = [item["month"] for item in result]
    assert months == sorted(months) == reference.all_months
    for item in result:
        group = reference.by_month.get(item["month"])
        assert item["revenue"] == float(ref.q2(group.revenue if group else Decimal("0")))
        assert item["transactions"] == (group.transactions if group else 0)
    assert [item["revenue"] for item in result] == [
        210250.00, 234600.00, 223900.00, 240700.00, 318500.00, 211250.00
    ]


def test_supplied_every_month_pair_matches_reference(supplied_conn, reference):
    months = reference.all_months
    for a in months:
        for b in months:
            if a == b:
                continue
            result = an.compare_months(supplied_conn, a, b)
            ra = reference.by_month[a].revenue if a in reference.by_month else Decimal("0")
            rb = reference.by_month[b].revenue if b in reference.by_month else Decimal("0")
            change = rb - ra
            pct = ref.percent_change(ra, rb)
            assert result["absolute_change"] == float(ref.q2(change)), (a, b)
            if pct is None:
                assert result["percentage_change"] is None, (a, b)
            else:
                assert result["percentage_change"] == float(ref.q2(pct)), (a, b)


def test_supplied_may_to_june_known_values(supplied_conn):
    result = an.compare_months(supplied_conn, "2026-05", "2026-06")
    assert result["revenue_a"] == 318500.00
    assert result["revenue_b"] == 211250.00
    assert result["absolute_change"] == -107250.00
    assert result["percentage_change"] == -33.67
    assert result["direction"] == "decreased"
    assert result["note"] is None


def test_supplied_jan_to_may_increase(supplied_conn):
    result = an.compare_months(supplied_conn, "2026-01", "2026-05")
    assert result["absolute_change"] == 108250.00
    assert result["percentage_change"] == 51.49
    assert result["direction"] == "increased"


# ----------------------------------------------------------------- hand-checked rules

@pytest.fixture
def rules_conn(tmp_path):
    rows = [
        sale("T1", "05-01-2026", "Alpha", "North", 4, 9500, 500),   # 4*9500-500 = 37500 (discount once)
        sale("T2", "10-01-2026", "Beta", "South", 0, 900, 0),        # zero quantity: valid, 0 revenue
        sale("T3", "15-01-2026", "Alpha", "North", 2, None, 0),      # missing price: excluded
        sale("T4", "20-01-2026", "Beta", "South", 3, 1000, 0, "Returned"),  # returned: excluded
        sale("T5", "03-03-2026", "Gamma", "East", 1, 100, 0),        # March; February has no sales
    ]
    conn = build_database(tmp_path, rows)
    yield conn
    conn.close()


def test_formula_applies_discount_once_per_transaction(rules_conn):
    assert an.total_revenue(rules_conn) == {"total_revenue": 37600.00, "eligible_transactions": 3}


def test_excluded_rows_do_not_affect_totals(rules_conn):
    # T3 (missing price) and T4 (returned) would add revenue if they were included.
    assert an.total_revenue(rules_conn)["eligible_transactions"] == 3
    products = {x["name"]: x for x in an.top_product(rules_conn)["ranking"]}
    assert products["Alpha"]["transactions"] == 1  # T3 excluded
    assert "Beta" in products and products["Beta"]["transactions"] == 1  # T2 kept, T4 excluded


def test_zero_quantity_is_eligible_with_zero_revenue(rules_conn):
    products = {x["name"]: x for x in an.top_product(rules_conn)["ranking"]}
    assert products["Beta"] == {"name": "Beta", "revenue": 0.0, "transactions": 1, "units": 0}


def test_top_product_and_region_on_rules_fixture(rules_conn):
    assert an.top_product(rules_conn)["top"]["name"] == "Alpha"
    assert an.top_region(rules_conn)["top"]["name"] == "North"


def test_monthly_trend_is_chronological_with_zero_filled_gap(rules_conn):
    trend = an.monthly_revenue(rules_conn)
    assert trend == [
        {"month": "2026-01", "revenue": 37500.00, "transactions": 2},
        {"month": "2026-02", "revenue": 0.0, "transactions": 0},
        {"month": "2026-03", "revenue": 100.00, "transactions": 1},
    ]


def test_increase_with_zero_gap_month_reports_percent(rules_conn):
    result = an.compare_months(rules_conn, "2026-01", "2026-03")
    assert result["absolute_change"] == -37400.00
    assert result["percentage_change"] == -99.73
    assert result["direction"] == "decreased"


def test_zero_baseline_gives_undefined_percentage(rules_conn):
    result = an.compare_months(rules_conn, "2026-02", "2026-03")
    assert result["revenue_a"] == 0.0
    assert result["absolute_change"] == 100.00
    assert result["direction"] == "increased"
    assert result["percentage_change"] is None
    assert result["note"] is not None


def test_unchanged_revenue_reports_zero_change(tmp_path):
    rows = [
        sale("U1", "05-01-2026", "Alpha", "North", 2, 500, 0),
        sale("U2", "05-02-2026", "Alpha", "North", 1, 1000, 0),
    ]
    conn = build_database(tmp_path, rows)
    try:
        result = an.compare_months(conn, "2026-01", "2026-02")
        assert result["absolute_change"] == 0.0
        assert result["percentage_change"] == 0.0
        assert result["direction"] == "unchanged"
    finally:
        conn.close()


def test_tie_breaking_is_alphabetical_for_products_and_regions(tmp_path):
    rows = [
        sale("K1", "05-01-2026", "Zeta", "West", 1, 1000, 0),
        sale("K2", "06-01-2026", "Alpha", "Central", 1, 1000, 0),
        sale("K3", "07-01-2026", "Mid", "West", 1, 500, 0),
        sale("K4", "08-01-2026", "Mid", "Central", 1, 500, 0),
    ]
    conn = build_database(tmp_path, rows)
    try:
        products = an.top_product(conn)["ranking"]
        assert [p["name"] for p in products] == ["Alpha", "Mid", "Zeta"]
        assert an.top_product(conn)["top"]["name"] == "Alpha"  # tie at 1000 -> alphabetical
        regions = an.top_region(conn)["ranking"]
        assert [r["name"] for r in regions] == ["Central", "West"]  # tie at 1500 -> alphabetical
    finally:
        conn.close()


# ----------------------------------------------------------------- empty and invalid input

def test_empty_database_results(tmp_path):
    conn = build_database(tmp_path, [])
    try:
        assert an.total_revenue(conn) == {"total_revenue": 0.0, "eligible_transactions": 0}
        assert an.top_product(conn) == {"top": None, "ranking": []}
        assert an.top_region(conn) == {"top": None, "ranking": []}
        assert an.monthly_revenue(conn) == []
        with pytest.raises(an.InvalidMonthError, match="No transactions"):
            an.compare_months(conn, "2026-01", "2026-02")
    finally:
        conn.close()


def test_month_with_only_excluded_rows_is_zero_not_missing(tmp_path):
    rows = [
        sale("E1", "05-01-2026", "Alpha", "North", 1, 100, 0),
        sale("E2", "05-02-2026", "Alpha", "North", 1, 100, 0, "Returned"),
    ]
    conn = build_database(tmp_path, rows)
    try:
        trend = an.monthly_revenue(conn)
        assert trend[1] == {"month": "2026-02", "revenue": 0.0, "transactions": 0}
        result = an.compare_months(conn, "2026-01", "2026-02")
        assert result["revenue_b"] == 0.0
        assert result["percentage_change"] == -100.0
    finally:
        conn.close()


@pytest.mark.parametrize(
    "bad",
    [
        "2026-13", "2026-00", "2026-5", "May", "June 2026", "", "2026-06 ",
        "2026-01' OR '1'='1", "2026-01; DROP TABLE transactions", None, 202601,
    ],
)
def test_malformed_month_is_rejected_before_sql(supplied_conn, bad):
    with pytest.raises(an.InvalidMonthError):
        an.compare_months(supplied_conn, bad, "2026-06")
    with pytest.raises(an.InvalidMonthError):
        an.compare_months(supplied_conn, "2026-05", bad)


@pytest.mark.parametrize("out_of_range", ["2025-12", "2026-07"])
def test_month_outside_data_range_is_rejected(supplied_conn, out_of_range):
    with pytest.raises(an.InvalidMonthError, match="outside the available data range 2026-01 to 2026-06"):
        an.compare_months(supplied_conn, "2026-05", out_of_range)


def test_identical_months_are_rejected(supplied_conn):
    with pytest.raises(an.IdenticalMonthsError):
        an.compare_months(supplied_conn, "2026-05", "2026-05")


def test_database_is_unchanged_by_analytics(supplied_conn):
    before = supplied_conn.execute("SELECT COUNT(*), SUM(quantity) FROM transactions").fetchone()[:]
    an.total_revenue(supplied_conn)
    an.top_product(supplied_conn)
    an.monthly_revenue(supplied_conn)
    an.compare_months(supplied_conn, "2026-01", "2026-02")
    after = supplied_conn.execute("SELECT COUNT(*), SUM(quantity) FROM transactions").fetchone()[:]
    assert before == after


# ----------------------------------------------------------------- negative net revenue

@pytest.fixture
def negative_conn(tmp_path):
    """Discounts larger than the gross amount produce negative net revenue.

    Net per transaction: N1 -400, N2 +600, N3 -200, N4 0, N5 -300.
    Monthly: Jan +200 (2 txns), Feb -200, Mar 0.00 (eligible, zero), Apr -300.
    """
    rows = [
        sale("N1", "05-01-2026", "Alpha", "North", 1, 100, 500),   # 100 - 500 = -400
        sale("N2", "10-01-2026", "Beta", "South", 2, 300, 0),      # 600
        sale("N3", "05-02-2026", "Beta", "East", 1, 100, 300),     # -200
        sale("N4", "05-03-2026", "Gamma", "West", 1, 50, 50),      # 0 (eligible, zero net)
        sale("N5", "05-04-2026", "Alpha", "East", 1, 100, 400),    # -300
    ]
    conn = build_database(tmp_path, rows)
    yield conn
    conn.close()


def test_negative_net_rows_are_kept_and_summed(negative_conn):
    assert an.total_revenue(negative_conn) == {"total_revenue": -300.00, "eligible_transactions": 5}


def test_negative_monthly_values_are_listed_in_order(negative_conn):
    assert an.monthly_revenue(negative_conn) == [
        {"month": "2026-01", "revenue": 200.00, "transactions": 2},
        {"month": "2026-02", "revenue": -200.00, "transactions": 1},
        {"month": "2026-03", "revenue": 0.0, "transactions": 1},
        {"month": "2026-04", "revenue": -300.00, "transactions": 1},
    ]


def test_negative_products_and_regions_rank_below_positive(negative_conn):
    products = an.top_product(negative_conn)
    assert [(p["name"], p["revenue"]) for p in products["ranking"]] == [
        ("Beta", 400.00), ("Gamma", 0.0), ("Alpha", -700.00),
    ]
    assert products["top"]["name"] == "Beta"
    regions = an.top_region(negative_conn)
    assert [(r["name"], r["revenue"]) for r in regions["ranking"]] == [
        ("South", 600.00), ("West", 0.0), ("North", -400.00), ("East", -500.00),
    ]
    assert regions["top"]["name"] == "South"


def test_all_negative_groups_still_rank_by_highest_revenue(tmp_path):
    rows = [
        sale("M1", "05-01-2026", "Alpha", "North", 1, 100, 300),   # -200
        sale("M2", "06-01-2026", "Beta", "North", 1, 100, 150),    # -50
    ]
    conn = build_database(tmp_path, rows)
    try:
        ranking = an.top_product(conn)["ranking"]
        assert [(p["name"], p["revenue"]) for p in ranking] == [("Beta", -50.00), ("Alpha", -200.00)]
        assert an.top_product(conn)["top"]["name"] == "Beta"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "month_a, month_b, change, pct, direction, note_kind",
    [
        # positive baseline: ordinary behaviour
        ("2026-01", "2026-02", -400.00, -200.00, "decreased", None),
        ("2026-01", "2026-03", -200.00, -100.00, "decreased", None),
        # negative baseline: percentage against |baseline|, note returned
        ("2026-02", "2026-01", 400.00, 200.00, "increased", "negative"),
        ("2026-02", "2026-03", 200.00, 100.00, "increased", "negative"),
        ("2026-02", "2026-04", -100.00, -50.00, "decreased", "negative"),
        ("2026-04", "2026-02", 100.00, 33.33, "increased", "negative"),
        # zero baseline: no percentage, note returned
        ("2026-03", "2026-04", -300.00, None, "decreased", "zero"),
    ],
)
def test_percentage_change_for_positive_negative_and_zero_baselines(
    negative_conn, month_a, month_b, change, pct, direction, note_kind
):
    result = an.compare_months(negative_conn, month_a, month_b)
    assert result["absolute_change"] == change
    assert result["percentage_change"] == pct
    assert result["direction"] == direction
    if note_kind is None:
        assert result["note"] is None
    elif note_kind == "negative":
        assert result["note"] == an.NEGATIVE_BASELINE_NOTE
    else:
        assert result["note"] == an.ZERO_BASELINE_NOTE


def test_negative_fixture_agrees_with_independent_reference(negative_conn, tmp_path):
    csv_path = tmp_path / "analytics.db.csv"  # written by build_database next to the database
    reference = ref.compute(csv_path)
    assert float(ref.q2(reference.total)) == an.total_revenue(negative_conn)["total_revenue"]
    for item in an.monthly_revenue(negative_conn):
        group = reference.by_month[item["month"]]
        assert item["revenue"] == float(ref.q2(group.revenue))
    for a in reference.all_months:
        for b in reference.all_months:
            if a == b:
                continue
            result = an.compare_months(negative_conn, a, b)
            ra = reference.by_month[a].revenue
            rb = reference.by_month[b].revenue
            pct = ref.percent_change(ra, rb)
            assert result["absolute_change"] == float(ref.q2(rb - ra)), (a, b)
            expected_pct = None if pct is None else float(ref.q2(pct))
            assert result["percentage_change"] == expected_pct, (a, b)
