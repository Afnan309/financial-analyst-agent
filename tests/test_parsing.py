import pytest

from finagent.calculator import CalcError, calculate
from finagent.finance import concept_for, detect_metric
from finagent.ingest import load_bytes
from finagent.numbers import convert, detect_unit, fmt_money, parse_number
from finagent.tables import extract_line_items


@pytest.mark.parametrize("tok,val", [("1,234.5", 1234.5), ("(1,234)", -1234), ("$98", 98), ("—", 0.0), ("12.5%", 12.5),
                                     ("-7", -7), ("abc", None)])
def test_parse_number(tok, val):
    assert parse_number(tok) == val


def test_units():
    assert detect_unit("(In millions, except per share amounts)") == "millions"
    assert detect_unit("Dollars in thousands") == "thousands"
    assert convert(2481230, "thousands", "millions") == pytest.approx(2481.23)
    assert fmt_money(-256.6, "millions") == "-$256.6 million"


def test_calculator_is_safe():
    assert calculate("(4210.0 - 3785.6) / 3785.6 * 100") == pytest.approx(11.2109, rel=1e-4)
    assert calculate("round(2.6789, 2)") == 2.68
    for evil in ["__import__('os').system('ls')", "open('x')", "[1,2]", "2 ** 100", "1/0", "a + 1"]:
        with pytest.raises(CalcError):
            calculate(evil)


def test_concepts_and_metrics():
    assert concept_for("capex") == "capex"
    assert concept_for("Total net sales") == "revenue"
    assert concept_for("Purchases of property, plant and equipment") == "capex"
    assert detect_metric("What is the FY2025 fixed asset turnover ratio?").key == "fixed_asset_turnover"
    assert detect_metric("What is the asset turnover?").key == "asset_turnover"
    assert detect_metric("What is the quick ratio?").key == "quick_ratio"
    assert detect_metric("What was revenue in 2025?") is None


def test_pdf_statements(northwind):
    items = {(it.label, it.statement): it for it in northwind.tools.items}
    ni = items[("Net income", "income_statement")]
    assert ni.values == {"2025": 565.6, "2024": 449.4, "2023": 351.1}
    assert ni.unit == "millions" and ni.page == 6
    assert items[("Purchases of property, plant and equipment", "cash_flow")].values["2025"] == -256.6
    assert items[("Total assets", "balance_sheet")].values["2025"] == pytest.approx(4300.0)
    assert len(northwind.tools.items) >= 55


def test_statements_tie_out(northwind):
    """Sanity: the extracted balance sheet balances, which only happens if every row parsed correctly."""
    get = {it.label: it.values for it in northwind.tools.items}
    for y in ("2025", "2024"):
        assert get["Total assets"][y] == pytest.approx(get["Total liabilities and stockholders' equity"][y])
        assert get["Total liabilities"][y] + get["Total stockholders' equity"][y] == pytest.approx(get["Total assets"][y])


def test_edgar_html(cascade):
    f = cascade.filing
    assert len(f.pages) == 6  # one page per page-break, no phantom splits
    assert f.pages[3].section == "Item 8. Financial Statements"
    rev = next(it for it in cascade.tools.items if it.label == "Total revenues")
    assert rev.values == {"2024": 2481230.0, "2023": 2302118.0} and rev.unit == "thousands"
    interest = next(it for it in cascade.tools.items if it.label == "Interest expense, net")
    assert interest.values["2024"] == -21870.0  # "(" "21,870" ")" split across three <td> cells


def test_toc_pages_excluded_from_search(northwind):
    hits = northwind.tools.index.search("risk factors suppliers", k=5)
    assert all(c.page != 1 for c, _ in hits)  # page 1 is the table of contents


def test_unsupported_and_empty():
    with pytest.raises(ValueError):
        load_bytes(b"x", "filing.xlsx")
    with pytest.raises(ValueError):
        load_bytes(b"   ", "empty.txt")


def test_text_filing_page_breaks():
    f = load_bytes(b"Page one text\fCONSOLIDATED STATEMENTS OF INCOME\n(In millions)\n2025 2024\nRevenue 10.0 8.0", "x.txt")
    assert len(f.pages) == 2
    items = extract_line_items(f)
    assert items[0].values == {"2025": 10.0, "2024": 8.0} and items[0].page == 1
