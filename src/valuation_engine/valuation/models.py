from decimal import Decimal
from typing import Protocol


class DCFModel(Protocol):
    def value(
        self, cash_flows: tuple[Decimal, ...], discount_rate: Decimal, terminal_growth: Decimal
    ) -> Decimal: ...


class ReverseDCFModel(Protocol):
    def implied_growth(self, enterprise_value: Decimal, base_cash_flow: Decimal) -> Decimal: ...


class ScenarioValuationModel(Protocol):
    def value(self, assumptions: dict[str, Decimal]) -> dict[str, Decimal]: ...


class OpportunityScore(Protocol):
    def score(self, features: dict[str, Decimal]) -> Decimal: ...
