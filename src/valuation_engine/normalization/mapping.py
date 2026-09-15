"""Ordered explicit US-GAAP aliases; USD amounts, shares, USD/share, ratio."""

CONCEPTS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "operating_expenses": ["OperatingExpenses"],
    "research_and_development": ["ResearchAndDevelopmentExpense"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "marketable_securities": ["ShortTermInvestments", "MarketableSecuritiesCurrent"],
    "accounts_receivable": ["AccountsReceivableNetCurrent"],
    "inventory": ["InventoryNet"],
    "total_assets": ["Assets"],
    "accounts_payable": ["AccountsPayableCurrent"],
    "debt_current": ["LongTermDebtCurrent", "ShortTermBorrowings"],
    "debt_noncurrent": ["LongTermDebtNoncurrent"],
    "equity": ["StockholdersEquity"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "sbc": ["ShareBasedCompensation"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "period_end_shares": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
        "DepreciationAmortizationAndAccretionNet",
    ],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
    ],
    "tax_expense": ["IncomeTaxExpenseBenefit"],
}
INSTANT = {
    "cash",
    "marketable_securities",
    "accounts_receivable",
    "inventory",
    "total_assets",
    "accounts_payable",
    "debt_current",
    "debt_noncurrent",
    "equity",
    "period_end_shares",
}
NON_ADDITIVE = {"eps_diluted", "diluted_shares", "gross_margin_reported"}
REQUIRED = set(CONCEPTS) - {"depreciation_amortization", "pretax_income", "tax_expense"}
VERSION = "normalization-1.1"
