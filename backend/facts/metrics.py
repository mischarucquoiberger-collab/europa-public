"""The metrics the report can show and where each one lives in the SEC's XBRL data.

Each metric lists (taxonomy, tag) pairs in fallback order: US GAAP spellings first, the IFRS
taxonomy (20-F filers) after. The tag content is lifted from the original product's SEC tag map
(app/services/sec_facts.py); balance-sheet items, shares and dividends, which that map did not
cover, use the standard us-gaap / ifrs-full / dei concepts.

Tags were left out on purpose where the value is NOT the quantity the label promises, e.g. cash
including restricted cash under "Cash and cash equivalents". One considered exception: capital
expenditure also accepts PaymentsToAcquireProductiveAssets, the single line some large companies
report for property and equipment together with intangible assets. Without it those companies
have no capital expenditure and no free cash flow at all; the report states this basis under its
cash flow block, and the figure links to the filing line it comes from.

Later fallbacks, used only by a company that does not tag the usual concept (the stale-tag rule in
select.py passes over a tag the company stopped using, so a fallback never displaces a current
first choice):
- net income: ProfitLoss (consolidated net income, i.e. with the noncontrolling interests' share,
  which is small where a company files this instead of NetIncomeLoss: Mastercard, Monster), then
  NetIncomeLossAvailableToCommonStockholdersBasic (after preferred dividends: Ford). ProfitLoss
  comes first because it is the closer quantity: Occidental's FY2025 ProfitLoss is 2,369M against
  2,326M attributable to the company, while its amount available to common holders is 1,612M;
- capital expenditure: PaymentsToAcquireOtherPropertyPlantAndEquipment (Eli Lilly's only line);
- NOT taken for cash: CashAndDueFromBanks. It is only a small part of a bank's cash (JPMorgan:
  21.7B of about 343B), so showing it under "Cash and cash equivalents" would be a wrong figure;
  a bank's cash is shown as not available instead;
- long-term debt: LongTermDebtAndCapitalLeaseObligations[IncludingCurrentMaturities] (JPMorgan,
  Chevron, ConocoPhillips) and, last, LineOfCredit, for a company whose only borrowing is its
  credit line (Sprouts);
- revenue: the all-in totals first (Revenues, then RevenuesNetOfInterestExpense, a finance
  company's total net revenue); revenue from contracts with customers is only part of a finance
  company's revenue, so it comes after them.
"""
from __future__ import annotations

from dataclasses import dataclass

UNITS = ("USD", "USD/share", "shares", "ratio")
KINDS = ("duration", "instant")


@dataclass(frozen=True)
class Metric:
    """`unit` is the kind of quantity ("USD" = an amount of money; a 20-F filer's facts keep the
    currency they were filed in). `kind` is "duration" for flows over a period (revenue) and
    "instant" for balances on a date (total assets)."""
    key: str
    label: str
    unit: str
    kind: str
    tags: tuple[tuple[str, str], ...]


def _m(key: str, label: str, unit: str, kind: str, *tags: tuple[str, str]) -> Metric:
    if unit not in UNITS or kind not in KINDS or not tags:
        raise ValueError(f"bad metric definition: {key}")
    return Metric(key, label, unit, kind, tuple(tags))


G, I, D = "us-gaap", "ifrs-full", "dei"

METRICS: dict[str, Metric] = {m.key: m for m in (
    # income statement. The all-in totals (`Revenues`, then a finance company's total revenues net
    # of interest expense) first: a finance company tags only part of its revenue as revenue from
    # contracts with customers. Revenue including assessed taxes is the line some companies
    # report instead (G-III, Performance Food Group); excluding them is preferred when both exist.
    _m("revenue", "Revenue", "USD", "duration",
       (G, "Revenues"), (G, "RevenuesNetOfInterestExpense"),
       (G, "RevenueFromContractWithCustomerExcludingAssessedTax"),
       (G, "RevenueFromContractWithCustomerIncludingAssessedTax"),
       (G, "SalesRevenueNet"), (I, "Revenue"), (I, "RevenueFromContractsWithCustomers")),
    _m("cost_of_revenue", "Cost of revenue", "USD", "duration",
       (G, "CostOfGoodsAndServicesSold"), (G, "CostOfGoodsSold"), (G, "CostOfRevenue"),
       (I, "CostOfSales")),
    _m("gross_profit", "Gross profit", "USD", "duration",
       (G, "GrossProfit"), (I, "GrossProfit")),
    _m("research_and_development", "Research and development", "USD", "duration",
       (G, "ResearchAndDevelopmentExpense"), (I, "ResearchAndDevelopmentExpense")),
    _m("operating_income", "Operating income", "USD", "duration",
       (G, "OperatingIncomeLoss"), (I, "ProfitLossFromOperatingActivities")),
    # the two fallbacks are for companies that do not tag NetIncomeLoss (see the module note)
    _m("net_income", "Net income", "USD", "duration",
       (G, "NetIncomeLoss"), (G, "ProfitLoss"), (G, "NetIncomeLossAvailableToCommonStockholdersBasic"),
       (I, "ProfitLossAttributableToOwnersOfParent")),
    _m("eps_basic", "Earnings per share (basic)", "USD/share", "duration",
       (G, "EarningsPerShareBasic"), (I, "BasicEarningsLossPerShare")),
    _m("eps_diluted", "Earnings per share (diluted)", "USD/share", "duration",
       (G, "EarningsPerShareDiluted"), (I, "DilutedEarningsLossPerShare")),
    _m("dividends_per_share", "Dividends per share", "USD/share", "duration",
       (G, "CommonStockDividendsPerShareDeclared"), (G, "CommonStockDividendsPerShareCashPaid"),
       (I, "DividendsRecognisedAsDistributionsToOwnersPerShare")),
    # cash flow. capex is the cash purchase of property, plant and equipment (see the module note)
    _m("operating_cash_flow", "Operating cash flow", "USD", "duration",
       (G, "NetCashProvidedByUsedInOperatingActivities"),
       (G, "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
       (I, "CashFlowsFromUsedInOperatingActivities")),
    _m("capex", "Capital expenditure", "USD", "duration",
       (G, "PaymentsToAcquirePropertyPlantAndEquipment"),
       # property and equipment together with intangible assets, for a company that reports them
       # on one line (the stale-tag rule picks whichever the company still uses)
       (G, "PaymentsToAcquireProductiveAssets"),
       # the only capital expenditure line of a company such as Eli Lilly
       (G, "PaymentsToAcquireOtherPropertyPlantAndEquipment"),
       (I, "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")),
    # balance sheet
    _m("total_assets", "Total assets", "USD", "instant",
       (G, "Assets"), (I, "Assets")),
    _m("total_liabilities", "Total liabilities", "USD", "instant",
       (G, "Liabilities"), (I, "Liabilities")),
    _m("shareholders_equity", "Shareholders' equity", "USD", "instant",
       (G, "StockholdersEquity"),
       (G, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
       (I, "EquityAttributableToOwnersOfParent"), (I, "Equity")),
    _m("cash", "Cash and cash equivalents", "USD", "instant",
       (G, "CashAndCashEquivalentsAtCarryingValue"), (G, "Cash"),
       (I, "CashAndCashEquivalents")),
    _m("long_term_debt", "Long-term debt", "USD", "instant",
       (G, "LongTermDebt"), (G, "LongTermDebtNoncurrent"),
       (G, "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"),
       (G, "LongTermDebtAndCapitalLeaseObligations"),
       (I, "LongtermBorrowings"), (I, "NoncurrentPortionOfNoncurrentBorrowings"),
       (G, "LineOfCredit")),
    # balance-sheet share count first; the cover-page count (a later date) after it. Both are the
    # same quantity on different dates, so select.py keeps the entries of both (MERGED_METRICS)
    _m("shares_outstanding", "Shares outstanding", "shares", "instant",
       (G, "CommonStockSharesOutstanding"), (D, "EntityCommonStockSharesOutstanding")),
    # inputs of the discount rate (backend/analysis/scenarios.py), tags in the original's order
    # (sec_facts.py 139-149). Interest expense is us-gaap only, as in the original: the IFRS
    # InterestExpense / FinanceCosts concepts can carry a finance arm's funding cost, not the
    # interest on the company's own debt. InterestExpenseNonoperating is the newer us-gaap name.
    _m("interest_expense", "Interest expense", "USD", "duration",
       (G, "InterestExpense"), (G, "InterestExpenseDebt"), (G, "InterestExpenseNonoperating")),
    _m("income_tax_expense", "Income tax expense", "USD", "duration",
       (G, "IncomeTaxExpenseBenefit"), (I, "IncomeTaxExpenseContinuingOperations")),
    _m("pretax_income", "Pre-tax income", "USD", "duration",
       (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
       (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
       (I, "ProfitLossBeforeTax")),
)}

# Labels of the computed facts (backend/analysis/ratios.py and the derived fourth quarter).
COMPUTED_LABELS: dict[str, str] = {
    "gross_margin": "Gross margin",
    "operating_margin": "Operating margin",
    "net_margin": "Net margin",
    "revenue_growth": "Revenue growth",
    "net_income_growth": "Net income growth",
    "return_on_equity": "Return on equity",
    "return_on_assets": "Return on assets",
    "debt_to_equity": "Long-term debt to equity",
    "free_cash_flow": "Free cash flow",
    "cash_conversion": "Cash conversion (operating cash flow to net income)",
    "fcf_margin": "Free cash flow margin",
    # backend/analysis/scenarios.py
    "revenue_cagr_2y": "Revenue CAGR, 2 years",
    "revenue_cagr_4y": "Revenue CAGR, 4 years",
    "revenue_growth_estimate": "Blended historical revenue growth",
    "net_debt": "Net debt",
    "pre_tax_cost_of_debt": "Pre-tax cost of debt",
    "effective_tax_rate": "Effective tax rate",
}


def label(key: str) -> str:
    """Plain-English name of a metric or computed fact; the key itself if unknown."""
    if key in METRICS:
        return METRICS[key].label
    return COMPUTED_LABELS.get(key, key)
