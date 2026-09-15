"""Versioned provider outputs. All model-generated text is advisory, never a Quant input."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "AIAnalystPolicyV1"
PROMPT_VERSION = "PromptSetV1"
SCHEMA_VERSION = "FeatureSchemaV1"
FeatureName = Literal[
    "demand_momentum",
    "demand_visibility",
    "pricing_power",
    "supply_constraint",
    "product_cycle_strength",
    "customer_adoption",
    "customer_concentration_outlook",
    "inference_demand",
    "training_demand",
    "competition_outlook",
    "custom_asic_outlook",
    "customer_insourcing_outlook",
    "ecosystem_strength",
    "switching_cost_strength",
    "margin_outlook",
    "working_capital_quality",
    "customer_financing_quality",
    "revenue_quality",
    "inventory_quality",
    "china_outlook",
    "export_control_outlook",
    "regulatory_outlook",
    "management_confidence",
    "guidance_visibility",
    "management_credibility_signal",
    "structural_outlook",
    "moat_strength_signal",
    "long_term_demand_durability",
]
SectionName = Literal[
    "Demand",
    "Supply",
    "Product",
    "Margin",
    "Customers",
    "Competition",
    "Regulation / China",
    "Working Capital / Financing",
    "Long-Term Strategy",
    "Risks",
]
Horizon = Literal[
    "current_quarter", "next_1_2_quarters", "next_fiscal_year", "multi_year", "unspecified"
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceDraft(Strict):
    key: str = Field(min_length=1, max_length=80)
    block_id: str
    span: str = Field(min_length=12, max_length=500)
    speaker: str | None
    topic: FeatureName
    implication: Literal["positive", "negative", "neutral", "mixed"]
    certainty: Literal["explicit", "qualified", "ambiguous"]
    statement_type: Literal["reported_fact", "management_statement", "risk_disclosure"]


class Extraction(Strict):
    evidence: list[EvidenceDraft] = Field(max_length=80)


class FeatureDraft(Strict):
    feature_name: FeatureName
    feature_value: float = Field(ge=-1, le=1, allow_inf_nan=False)
    time_horizon: Horizon
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    net_assessment: str = Field(min_length=1, max_length=900)


class SectionDraft(Strict):
    section: SectionName
    summary: str = Field(min_length=1, max_length=900)
    evidence: list[str]


class Synthesis(Strict):
    features: list[FeatureDraft] = Field(max_length=28)
    sections: list[SectionDraft] = Field(max_length=10)


class ChallengeDraft(Strict):
    kind: Literal["upside", "downside", "anomaly", "regime", "adjustment"]
    description: str = Field(min_length=1, max_length=900)
    direction: Literal["up", "down", "mixed", "monitor"]
    affected_model_variable: Literal[
        "revenue",
        "eps",
        "free_cash_flow",
        "gross_margin",
        "operating_margin",
        "diluted_shares",
        "working_capital",
        "regime",
    ]
    time_horizon: Horizon
    evidence: list[str]
    anomaly_code: str | None


class Challenges(Strict):
    challenges: list[ChallengeDraft] = Field(max_length=30)


class ReviewDraft(Strict):
    analysis_run_id: int
    category: Literal[
        "demand",
        "supply",
        "competition",
        "product_cycle",
        "management",
        "anomalies",
        "model_challenge",
    ]
    verdict: Literal["correct", "partially_correct", "unsupported", "missed"]
    reviewer: str = Field(min_length=2)
    notes: str = Field(min_length=5)
    evidence_ids: list[int]
