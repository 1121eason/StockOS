"""Prepare an offline AI request/schema only. No models, DB writes or service startup."""

import argparse
import hashlib
import json
from pathlib import Path

from valuation_engine.research.ai_request import build_request, canonical_bytes, canonical_sha


def candidate_schema(request):
    citation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["paragraph_id", "quote"],
        "properties": {
            "paragraph_id": {"type": "string", "minLength": 1, "maxLength": 150},
            "quote": {"type": "string", "minLength": 1, "maxLength": 550},
        },
    }
    claim = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "text", "citations"],
        "properties": {
            "kind": {"enum": ["fact", "management_outlook", "inference"]},
            "text": {"type": "string", "minLength": 1, "maxLength": 2000},
            "citations": {"type": "array", "minItems": 1, "maxItems": 8, "items": citation},
        },
    }
    kinds = ["drivers", "risks", "uncertainties", "invalidation_conditions"]
    section = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "title", "claims"],
        "properties": {
            "kind": {"enum": kinds},
            "title": {"type": "string", "minLength": 1, "maxLength": 120},
            "claims": {"type": "array", "minItems": 1, "maxItems": 12, "items": claim},
        },
    }
    constants = {
        key: request[key]
        for key in ["research_binding", "ticker", "quarter", "checkpoint", "information_cutoff"]
    }
    constants.update(version="StockOSAIExplanationV1", request_sha256=canonical_sha(request))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [*constants, "sections"],
        "properties": {
            **{key: {"const": value} for key, value in constants.items()},
            "sections": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": section,
                "allOf": [
                    {
                        "contains": {
                            "type": "object",
                            "required": ["kind"],
                            "properties": {"kind": {"const": kind}},
                        },
                        "minContains": 1,
                        "maxContains": 1,
                    }
                    for kind in kinds
                ],
            },
        },
        "$comment": "Passing schema does not establish citation semantics, human approval or eligibility for publication.",
    }


def prepare(
    research_path: Path,
    raw_dir: Path,
    output_dir: Path,
    *,
    supplemental_raw_dir=None,
    source_scope="current_previous",
):
    if research_path.is_symlink():
        raise ValueError("research_file_symlink")
    payload = json.loads(research_path.read_text())
    research = payload.get("research", payload)
    request = build_request(
        research, raw_dir, supplemental_raw_dir=supplemental_raw_dir, source_scope=source_scope
    )
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output_directory_must_be_new")
    if any(parent.is_symlink() for parent in output_dir.absolute().parents):
        raise ValueError("output_directory_symlink")
    output_dir.mkdir(parents=True)
    files = {
        "request.json": canonical_bytes(request),
        "candidate.schema.json": canonical_bytes(candidate_schema(request)),
    }
    for name, data in files.items():
        (output_dir / name).write_bytes(data + b"\n")
    readme = (
        "# 本季 AI 解釋待執行包\n\n"
        f"{request['ticker']} {request['quarter']}，研究截止 {request['information_cutoff']}。\n\n"
        f"來源範圍：{request['source_scope']}。current_previous 僅納入明確對應本季／前季的完整文件；"
        "其他歷史與未知期間文件明列 out_of_explanation_scope。all_research 供全量研究來源稽核，"
        "不代表已核准模型執行。兩種範圍均不截短文件，不修改既有 W1／S2 協定或額度。\n\n"
        "current_previous 對相同官方 URL 只保留截止時間前最後一個可核對版本；"
        "可用時間相同而內容雜湊不同則停止，不用較晚下載時間假裝較早已可使用。"
        "舊版本仍保留原件與數值來源追溯，排除紀錄指向選定版本，不重複提供給 AI。\n\n"
        "本包僅離線準備，沒有呼叫模型、啟動服務或寫入資料庫。沒有產生或核准 AI 候選。\n\n"
        "request.json 包含已核對財務、前季對照、修訂、Regime、DCF 與官方文件可用原文，保留表格。"
        "價格上下文與疑似提示注入另列排除清單，內容不截斷；原件雜湊與時間保留。\n\n"
        "後續經既有執行授權後才可將 request 交給受控模型；輸出需符合 candidate.schema.json。"
        "四類為成長原因、風險、不確定性、判斷失效條件；每個主張有逐字引用。"
        "回覆始終是 candidate_pending_review，仍需內容複核，不能宣稱真人核准或改寫估值。\n"
    )
    (output_dir / "README.md").write_text(readme)
    text_characters = sum(len(block["text"]) for block in request["source_blocks"])
    receipt = {
        "version": "StockOSAIExplanationPreparationV1",
        "status": "PREPARED_NOT_EXECUTED",
        "request_sha256": canonical_sha(request),
        "research_binding": request["research_binding"],
        "ticker": request["ticker"],
        "quarter": request["quarter"],
        "source_scope": request["source_scope"],
        "sources": len(request["sources"]),
        "source_blocks": len(request["source_blocks"]),
        "table_rows": sum(
            block["content_kind"] == "table_row" for block in request["source_blocks"]
        ),
        "excluded_sources": len(request["excluded_sources"]),
        "excluded_blocks": sum(len(source["excluded_blocks"]) for source in request["sources"]),
        "source_text_characters": text_characters,
        "minimum_18000_character_text_chunks": (text_characters + 17999) // 18000,
        "text_chunk_lower_bound_note": "Pure admitted text only; excludes JSON, prompts, metadata and paragraph boundaries. Not an execution or provider call plan.",
        "files": {
            name: hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
            for name in [*files, "README.md"]
        },
        "provider_calls": 0,
        "database_writes": 0,
        "promotion_ready": False,
    }
    (output_dir / "receipt.json").write_bytes(canonical_bytes(receipt) + b"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", required=True, type=Path)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--supplemental-raw-dir", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--source-scope", choices=["current_previous", "all_research"], default="current_previous"
    )
    args = parser.parse_args()
    receipt = prepare(
        args.research,
        args.raw_dir,
        args.output_dir,
        supplemental_raw_dir=args.supplemental_raw_dir,
        source_scope=args.source_scope,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
