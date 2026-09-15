from enum import StrEnum
from typing import Protocol


class Archetype(StrEnum):
    AI_COMPUTE = "AI Compute / Fabless"
    FOUNDRY = "Semiconductor Manufacturing / Foundry"
    MEMORY = "Memory / Commodity Semiconductor"
    EQUIPMENT = "Semiconductor Equipment"
    CLOUD = "AI Cloud / Hyperscaler"
    SOFTWARE = "AI Software / SaaS"
    NETWORKING = "AI Networking / Systems"
    CLASS_X = "Class X / Unsuitable for Systematic Valuation"


class Regime(StrEnum):
    HYPERGROWTH = "Hypergrowth"
    GROWTH = "Growth"
    MATURE = "Mature Growth"
    CYCLICAL = "Cyclical Downturn"
    DETERIORATION = "Structural Deterioration"


class RegimeClassifier(Protocol):
    def classify(self, features: dict[str, float]) -> dict[Regime, float]: ...
