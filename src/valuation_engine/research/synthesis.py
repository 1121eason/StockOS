"""Read-only research conclusions and strictly bound, unapproved AI explanations.

This module never invokes a provider, promotes a candidate, or changes a number in
the Quant baseline. Citation checks establish traceability, not semantic quality.
"""

import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

VERSION = "StockOSResearchSynthesisV1"
AI_VERSION = "StockOSAIExplanationV1"
SECTION_KINDS = ("drivers", "risks", "uncertainties", "invalidation_conditions")
LABELS = {
    "revenue": "營收",
    "operating_income": "營業利益",
    "net_income": "淨利",
    "eps_diluted": "稀釋每股盈餘",
    "ocf": "營業現金流",
    "capex": "資本支出",
    "fcf": "自由現金流",
}


def canonical_sha(value: Any) -> str:
    content = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(content).hexdigest()


def research_binding(research: dict) -> str:
    """Exclude live quotes and verification clocks; include every research input."""
    source_keys = ("id", "sha256", "url", "published_at", "availability_records")
    return canonical_sha(
        {
            **{
                key: research.get(key)
                for key in (
                    "version",
                    "ticker",
                    "currency",
                    "current",
                    "previous",
                    "revisions",
                    "source_database_sha256",
                    "financial_refresh",
                )
            },
            "sources": sorted(
                ({key: row.get(key) for key in source_keys} for row in research.get("sources", [])),
                key=lambda row: row["id"],
            ),
        }
    )


def _shape(value: Any, fields: set[str], name: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"AI {name} 欄位不完整或含未核准的額外欄位。")
    return value


def _text(value: Any, name: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"AI {name} 文字無效。")
    return value


def validate_candidate(research: dict, request: dict, candidate: dict) -> list[dict]:
    """Return an allowlisted display projection; never import scores or approval."""
    _shape(
        candidate,
        {
            "version",
            "request_sha256",
            "research_binding",
            "ticker",
            "quarter",
            "checkpoint",
            "information_cutoff",
            "sections",
        },
        "候選",
    )
    current = research["current"]
    binding = research_binding(research)
    if (
        candidate["version"] != AI_VERSION
        or request.get("version") != "StockOSAIExplanationRequestV1"
        or candidate["request_sha256"] != canonical_sha(request)
        or candidate["research_binding"] != binding
        or request.get("research_binding") != binding
    ):
        raise ValueError("AI 候選與研究或請求包版本不符，需重做本季分析。")
    for key, expected in (
        ("ticker", research.get("ticker")),
        ("quarter", current["quarter"]),
        ("checkpoint", current["checkpoint"]),
        ("information_cutoff", current.get("information_cutoff", current["checkpoint"])),
    ):
        if candidate[key] != expected or request.get(key) != expected:
            raise ValueError("AI 公司、季度或研究截止時間不符，不能沿用其他研究。")
    sources = {row["id"]: row["sha256"] for row in research.get("sources", [])}
    blocks = {}
    for block in request.get("source_blocks", []):
        identity = block["paragraph_id"]
        if identity in blocks or sources.get(block["source_id"]) != block["source_sha256"]:
            raise ValueError("AI 原文段落來源不符或重複。")
        blocks[identity] = block
    sections = candidate["sections"]
    if not isinstance(sections, list) or len(sections) != len(SECTION_KINDS):
        raise ValueError("AI 需包含營運驅動、風險、不確定性與失效條件四部分。")
    seen = set()
    displayed = []
    for section in sections:
        _shape(section, {"kind", "title", "claims"}, "段落")
        kind = section["kind"]
        if not isinstance(kind, str) or kind not in SECTION_KINDS or kind in seen:
            raise ValueError("AI 分析部分不完整或重複。")
        seen.add(kind)
        title = _text(section["title"], "標題", 120)
        claims = section["claims"]
        if not isinstance(claims, list) or not 1 <= len(claims) <= 12:
            raise ValueError("AI 每部分需有可引用的觀點；無證據時保留待補。")
        checked = []
        for claim in claims:
            _shape(claim, {"kind", "text", "citations"}, "觀點")
            if claim["kind"] not in ("fact", "management_outlook", "inference"):
                raise ValueError("AI 需區分事實、管理層預期及研究推論。")
            text = _text(claim["text"], "觀點")
            citations = claim["citations"]
            if not isinstance(citations, list) or not 1 <= len(citations) <= 8:
                raise ValueError("AI 觀點缺少原文證據。")
            evidence = []
            for citation in citations:
                _shape(citation, {"paragraph_id", "quote"}, "引用")
                paragraph_id = _text(citation["paragraph_id"], "段落識別", 150)
                quote = _text(citation["quote"], "引文", 2000)
                block = blocks.get(paragraph_id)
                if (
                    block is None
                    or quote not in block["text"]
                    or len(re.findall(r"\S+", quote)) > 55
                    or len(quote) > 550
                ):
                    raise ValueError("AI 引文無法逐字核對或超過長度限制。")
                evidence.append(
                    {
                        "source_id": block["source_id"],
                        "paragraph_id": paragraph_id,
                        "quote": quote,
                        "paragraph": block["text"],
                    }
                )
            checked.append({"kind": claim["kind"], "text": text, "citations": evidence})
        displayed.append({"kind": kind, "title": title, "claims": checked})
    return displayed


def _number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def summarize(research: dict, *, ai: dict | None = None) -> dict:
    """Describe baseline facts, with no invented trading or valuation adjustments."""
    current = research["current"]
    previous = research.get("previous", {})
    financials = []
    for metric, label in LABELS.items():
        observation = current.get("metrics", {}).get(metric, {})
        now = _number(observation.get("value"))
        prior = _number(previous.get("metrics", {}).get(metric, {}).get("value"))
        # Percentage change against a non-positive denominator is not interpretable.
        change = (now / prior - 1) if now is not None and prior is not None and prior > 0 else None
        financials.append(
            {
                "metric": metric,
                "label": label,
                "current": str(now) if now is not None else None,
                "previous": str(prior) if prior is not None else None,
                "change_ratio": str(change) if change is not None else None,
                "source_ids": deepcopy(observation.get("source_ids", [])),
            }
        )
    explanation = ai or {
        "status": "not_generated",
        "sections": [],
        "reason": "尚無與本季、來源及研究版本相符的 AI 解釋。",
    }
    candidate = explanation["status"] == "candidate_pending_review"
    valuation = current.get("valuation", {})
    return {
        "version": VERSION,
        "research_binding": research_binding(research),
        "quarter": current.get("quarter"),
        "status": "candidate_pending_review" if candidate else "quant_only",
        "headline": "量化研究已整理；AI 解釋待驗收"
        if candidate
        else "量化研究已整理；本季 AI 解釋尚未完成",
        "conclusion": "以下為已核對數字與研究條件。AI 內容仍待獨立審查，完整綜合判斷尚未發布。",
        "financial_summary": financials,
        "forecast_revisions": [
            {key: deepcopy(row.get(key)) for key in ("target", "status", "metrics")}
            for row in research.get("revisions", [])
        ],
        "regime_summary": {
            key: current.get("regime", {}).get(key)
            for key in ("confirmed_regime", "candidate_regime", "transition_status")
        },
        "valuation_summary": {
            **{
                key: deepcopy(valuation.get(key))
                for key in ("status", "base", "low", "high", "basis_date")
            },
            "label": "研究日合理價值（非 12 個月目標價）",
        },
        "ai": explanation,
        "blockers": [
            *([] if candidate else [explanation["reason"]]),
            "本季 AI 內容尚未完成兩位獨立審查者驗收。",
            "逐字引用核對不代表因果解釋或推論已正確。",
        ],
        "decision_ready": False,
        "promotion_ready": False,
        "affects_valuation": False,
    }


def attach_synthesis(
    research: dict,
    *,
    candidate_path: Path | None = None,
    raw_dir: Path | None = None,
    supplemental_raw_dir: Path | None = None,
) -> dict:
    """A bad candidate blocks only AI; the last verified Quant remains readable."""
    ai = None
    if candidate_path is not None:
        try:
            if candidate_path.is_symlink() or not candidate_path.is_file():
                raise ValueError("AI 候選檔案不存在或為連結。")
            if candidate_path.stat().st_size > 2_000_000 or raw_dir is None:
                raise ValueError("AI 候選過大或缺少原文目錄。")
            from valuation_engine.research.ai_request import build_request

            request = build_request(research, raw_dir, supplemental_raw_dir=supplemental_raw_dir)
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            sections = validate_candidate(research, request, candidate)
            ai = {
                "status": "candidate_pending_review",
                "sections": sections,
                "reason": "引文與本季研究已對齊；事實分類、推論及完整性仍待獨立內容審查。",
                "request_sha256": canonical_sha(request),
            }
        except (
            ValueError,
            OSError,
            KeyError,
            TypeError,
            AttributeError,
            ArithmeticError,
            RecursionError,
        ):
            ai = {
                "status": "blocked",
                "sections": [],
                "reason": "AI 候選未通過季度、版本、來源或引文核對；保留已核對的量化研究。",
            }
    result = deepcopy(research)
    result["synthesis"] = summarize(research, ai=ai)
    return result
