#!/usr/bin/env python3
"""Isolated S2 engineering harness. Quality remains unscored until human blind review.

No formal database is opened. Live execution is blocked until reviewed process
isolation and frozen methodology contracts exist; CLI opt-ins cannot unlock it.
The candidate format is versioned; legacy databases are never auto-migrated.
"""

import argparse
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from valuation_engine.ai.contracts import Challenges, Extraction, Synthesis
from valuation_engine.ai.experiment_prompts import FSI_RUBRIC, SYSTEM, prompt
from valuation_engine.ai.guards import admit_feature, confidence, safe_narrative, validate_evidence
from valuation_engine.ai.sources import blocks as source_blocks
from valuation_engine.ai.sources import chunks
from valuation_engine.db.store import digest

MAX_CALLS_PER_METHOD = 22
ALLOWED_QUARTERS = ("FY2023-Q2",)
FORMAT_VERSION = 2
LIVE_BLOCK_REASON = (
    "Live execution is blocked: frozen comparison methodology and global single-process/"
    "no-residual-provider isolation are not implemented and reviewed. Explicit opt-ins "
    "alone cannot authorize this unverified runtime. Offline synthetic execution remains available."
)


def now():
    return datetime.now(UTC).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def compute_sha256(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def init_candidate_database(db_path):
    """Create a new candidate only. No upgrades or writes to existing databases."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db_path.open("xb"):
        pass
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            PRAGMA user_version=2;
            CREATE TABLE s2_experiment_runs (
                id INTEGER PRIMARY KEY, method TEXT NOT NULL, quarter TEXT NOT NULL,
                prompt_version TEXT NOT NULL, guard_version TEXT NOT NULL,
                calls_made INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                receipt_json TEXT NOT NULL, context_json TEXT NOT NULL, context_hash TEXT NOT NULL,
                config_json TEXT NOT NULL);
            CREATE TABLE s2_provider_calls (
                id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, method TEXT NOT NULL,
                stage TEXT NOT NULL, request_hash TEXT NOT NULL, duration_ms INTEGER,
                actual_model TEXT, tokens_in INTEGER, tokens_out INTEGER,
                status TEXT NOT NULL, created_at TEXT NOT NULL, raw_response TEXT,
                exact_request TEXT NOT NULL, response_hash TEXT, error_type TEXT);
            CREATE TABLE s2_source_documents (
                run_id INTEGER NOT NULL, source_document_id INTEGER NOT NULL,
                source_hash TEXT NOT NULL, metadata_json TEXT NOT NULL, content BLOB NOT NULL,
                PRIMARY KEY(run_id, source_document_id));
            CREATE TABLE s2_source_blocks (
                run_id INTEGER NOT NULL, block_id TEXT NOT NULL, block_json TEXT NOT NULL,
                PRIMARY KEY(run_id, block_id));
            CREATE TABLE s2_evidence (
                id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, method TEXT NOT NULL,
                evidence_key TEXT NOT NULL, topic TEXT NOT NULL, span TEXT NOT NULL,
                implication TEXT NOT NULL, certainty TEXT NOT NULL, statement_type TEXT NOT NULL,
                created_at TEXT NOT NULL, call_id INTEGER NOT NULL, draft_key TEXT NOT NULL,
                source_document_id INTEGER NOT NULL, source_hash TEXT NOT NULL,
                block_id TEXT NOT NULL, span_hash TEXT NOT NULL, metadata_json TEXT NOT NULL,
                UNIQUE(run_id, evidence_key));
            CREATE TABLE s2_features (
                id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, method TEXT NOT NULL,
                feature_name TEXT NOT NULL, feature_value REAL NOT NULL, direction TEXT NOT NULL,
                confidence REAL NOT NULL, evidence_count INTEGER NOT NULL, rationale TEXT NOT NULL,
                supporting_keys TEXT NOT NULL, contradicting_keys TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, call_id INTEGER NOT NULL,
                metadata_json TEXT NOT NULL, UNIQUE(run_id, feature_name));
            CREATE TABLE s2_challenges (
                id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, method TEXT NOT NULL,
                kind TEXT NOT NULL, target_variable TEXT NOT NULL, direction TEXT NOT NULL,
                description TEXT NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, call_id INTEGER NOT NULL, evidence_keys TEXT NOT NULL,
                metadata_json TEXT NOT NULL);
            CREATE TABLE s2_guard_rejections (
                id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, method TEXT NOT NULL,
                stage TEXT NOT NULL, claim_type TEXT NOT NULL, reason TEXT NOT NULL,
                raw_json TEXT NOT NULL, created_at TEXT NOT NULL, call_id INTEGER NOT NULL);
        """)


@contextmanager
def candidate_connection(path):
    """Require our explicit version and an existing database; never create on typo."""
    path = Path(path).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT_VERSION:
            raise ValueError("Unsupported candidate format; use a fresh output directory")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def build_method_payloads(quarter):
    result = {}
    for method in ("B", "C"):
        config = {
            "method": method,
            "quarter": quarter,
            "prompt_version": "S2ExperimentalPromptV1-" + method,
            "intended_workorder_prompt": "PromptSetV6" + ("-FSI" if method == "C" else ""),
            "policy_version": "AIAnalystPolicyV1",
            "schema_version": "FeatureSchemaV1",
            "comparison_design_status": "UNVERIFIED_FROZEN_BASELINE_MISSING",
            "guard_version": "Guard_G_Strict",
            "max_calls": MAX_CALLS_PER_METHOD,
        }
        config["config_hash"] = digest(config)
        result["method_" + method.lower()] = config
    return result


def verify_prepared(prepared, source_contents, quarter):
    """Bind supplied blocks to re-parsed, hash-checked source bytes, never topic labels.

    This proves byte/block consistency, not authenticity of source ownership,
    historical availability metadata, or model semantic correctness.
    """
    context = prepared["quant_context"]
    if context["quarter"] != quarter:
        raise ValueError("Prepared quarter mismatch")
    cutoff = datetime.fromisoformat(context["information_cutoff"])
    if cutoff.tzinfo is None:
        raise ValueError("An aware information cutoff is required")
    documents, blocks = prepared["sources"]["documents"], prepared["sources"]["blocks"]
    if not documents or not blocks:
        raise ValueError("Source documents and blocks are required")
    ids, parsed = set(), {}
    for doc in documents:
        source_id, sha = doc["source_document_id"], doc["source_hash"]
        if type(source_id) is not int or source_id in ids:
            raise ValueError("Duplicate or malformed source identity")
        ids.add(source_id)
        content = source_contents[sha]
        if not isinstance(content, bytes) or compute_sha256(content) != sha:
            raise ValueError("Source bytes hash mismatch")
        available = datetime.fromisoformat(doc["available_at"])
        if available.tzinfo is None or available > cutoff or doc["tier"] not in (1, 2):
            raise ValueError("Invalid source availability or tier")
        derived, _ = source_blocks(
            SimpleNamespace(id=source_id, content_hash=sha, document_type=doc["document_type"]),
            content,
        )
        for block in derived:
            parsed[block["block_id"]] = {
                **block,
                "published_at": doc["published_at"],
                "available_at": doc["available_at"],
                "tier": doc["tier"],
            }
    seen = set()
    for block in blocks:
        block_id = block["block_id"]
        if block_id in seen or block != parsed.get(block_id):
            raise ValueError("Source block does not match re-parsed source bytes")
        seen.add(block_id)
    if seen != set(parsed):
        raise ValueError("Prepared package omits parsed narrative blocks")
    if len(list(chunks(blocks))) + 2 > MAX_CALLS_PER_METHOD:
        raise ValueError("Full source package exceeds call cap; truncation is not allowed")
    return digest(prepared)


def method_prompt(stage, payload, response_type, config):
    exact = prompt(stage, payload, response_type)
    # Shared strict roles stay common; the FSI extension is the controlled difference.
    baseline = SYSTEM.replace(FSI_RUBRIC, "").strip()
    exact["system"] = baseline + ("\n\n" + FSI_RUBRIC if config["method"] == "C" else "")
    exact["prompt_version"] = config["prompt_version"]
    exact["schema_version"] = config["schema_version"]
    return exact


def compute_item_confidence(item_evidence, cont_items=()):
    """No synthetic source identity, default weights, or success fallback."""
    return confidence(item_evidence, cont_items)


def guard_g_invariant(feature, evidence):
    support, counter = (
        feature.get("supporting_evidence", []),
        feature.get("contradicting_evidence", []),
    )
    if any(key not in evidence for key in support + counter):
        return "FSI.EVIDENCE_REFERENCE_INVALID"
    if set(support) & set(counter):
        return "FSI.EVIDENCE_ROLE_OVERLAP"
    if any(evidence[key]["topic"] != feature["feature_name"] for key in support + counter):
        return "evidence_topic_mismatch"
    value = feature.get("feature_value")
    if value:
        if not support:
            return "FSI.FINAL_SUPPORT_EMPTY"
        expected = "positive" if value > 0 else "negative"
        if not any(evidence[key]["implication"] == expected for key in support):
            return "direction_unsupported"
    return None


def run_single_method(
    method_key,
    method_config,
    provider,
    prepared_data,
    candidate_db_path,
    *,
    source_contents,
    execution_mode,
):
    """Fresh run only, zero outer retries. Synthetic adapters use OFFLINE_SYNTHETIC."""
    if execution_mode == "LIVE_EXECUTION":
        raise ValueError(LIVE_BLOCK_REASON)
    if execution_mode != "OFFLINE_SYNTHETIC":
        raise ValueError("Explicit OFFLINE_SYNTHETIC execution mode required")
    method = method_config["method"]
    if method not in {"B", "C"} or method_key != "method_" + method.lower():
        raise ValueError("Method identity mismatch")
    if method_config != build_method_payloads(method_config["quarter"])[method_key]:
        raise ValueError("Method configuration mismatch")
    # Isolate the approved input from accidental provider mutation.
    prepared = json.loads(encode(prepared_data))
    context_hash = verify_prepared(prepared, source_contents, method_config["quarter"])
    started = now()
    with candidate_connection(candidate_db_path) as conn:
        run_id = conn.execute(
            "INSERT INTO s2_experiment_runs VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)",
            (
                method,
                method_config["quarter"],
                method_config["prompt_version"],
                method_config["guard_version"],
                0,
                "RUNNING",
                started,
                "{}",
                encode(prepared),
                context_hash,
                encode(method_config),
            ),
        ).lastrowid
        for doc in prepared["sources"]["documents"]:
            conn.execute(
                "INSERT INTO s2_source_documents VALUES(?,?,?,?,?)",
                (
                    run_id,
                    doc["source_document_id"],
                    doc["source_hash"],
                    encode(doc),
                    source_contents[doc["source_hash"]],
                ),
            )
        for block in prepared["sources"]["blocks"]:
            conn.execute(
                "INSERT INTO s2_source_blocks VALUES(?,?,?)",
                (run_id, block["block_id"], encode(block)),
            )
        conn.commit()
        evidence, features, challenges, rejections = {}, {}, [], []
        calls_made = 0

        def reject(stage, kind, reason, draft, call_id):
            value = {"stage": stage, "claim_type": kind, "reason": reason, "raw": draft}
            rejections.append(value)
            conn.execute(
                "INSERT INTO s2_guard_rejections VALUES(NULL,?,?,?,?,?,?,?,?)",
                (run_id, method, stage, kind, reason, encode(draft), now(), call_id),
            )
            conn.commit()

        def invoke(stage, payload, response_type):
            nonlocal calls_made
            if calls_made >= MAX_CALLS_PER_METHOD:
                raise RuntimeError("Call cap reached")
            exact = method_prompt(stage, payload, response_type, method_config)
            # Persist BEFORE execution: crashes remain pending, never hidden retries.
            call_id = conn.execute(
                "INSERT INTO s2_provider_calls (run_id,method,stage,request_hash,status,created_at,exact_request) VALUES(?,?,?,?,?,?,?)",
                (run_id, method, stage, digest([stage, exact]), "pending", now(), encode(exact)),
            ).lastrowid
            calls_made += 1
            conn.execute(
                "UPDATE s2_experiment_runs SET calls_made=? WHERE id=?", (calls_made, run_id)
            )
            conn.commit()
            start = time.monotonic()
            raw_text, response_hash, model, tokens_in, tokens_out, error_type = (
                None,
                None,
                None,
                None,
                None,
                None,
            )
            status = "invalid_or_unavailable"
            try:
                provider.timeout = 180 if stage == "extract" else 600
                raw = provider.request(stage, json.loads(encode(exact)))
                raw_text = encode(raw)
                response_hash = digest(raw)
                if not isinstance(raw, dict):
                    raise ValueError("Provider response must be an object")
                metadata = raw.get("execution_metadata", {})
                model = raw.get("response_model")
                tokens_in, tokens_out = metadata.get("input_tokens"), metadata.get("output_tokens")
                if metadata.get("provider_execution_status") != "completed":
                    raise ValueError("Provider did not complete")
                result = response_type.model_validate(raw.get("structured_output"))
                status = "completed"
            except Exception as error:
                error_type = type(error).__name__
                raise RuntimeError("Provider stage failed; see persisted attempt status") from None
            finally:
                conn.execute(
                    "UPDATE s2_provider_calls SET duration_ms=?,actual_model=?,tokens_in=?,tokens_out=?,status=?,raw_response=?,response_hash=?,error_type=? WHERE id=?",
                    (
                        int((time.monotonic() - start) * 1000),
                        model,
                        tokens_in,
                        tokens_out,
                        status,
                        raw_text,
                        response_hash,
                        error_type,
                        call_id,
                    ),
                )
                conn.commit()
            return result, call_id

        status, failure = "INCOMPLETE", None
        try:
            for index, batch in enumerate(chunks(prepared["sources"]["blocks"])):
                extracted, call_id = invoke(
                    "extract",
                    {"cutoff": prepared["quant_context"]["information_cutoff"], "blocks": batch},
                    Extraction,
                )
                block_map = {block["block_id"]: block for block in batch}
                for item in extracted.evidence:
                    valid, reason = validate_evidence(item, block_map)
                    if item.speaker is not None and item.speaker != block_map.get(
                        item.block_id, {}
                    ).get("speaker"):
                        valid, reason = None, "unsupported_speaker"
                    key = f"{index}:{item.key}"
                    if key in evidence:
                        valid, reason = None, "duplicate_evidence_key"
                    if valid is None:
                        reject("extract", "evidence", reason, item.model_dump(), call_id)
                        continue
                    valid["key"] = key
                    evidence[key] = valid
                    conn.execute(
                        "INSERT INTO s2_evidence VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            run_id,
                            method,
                            key,
                            valid["topic"],
                            valid["span"],
                            valid["implication"],
                            valid["certainty"],
                            valid["statement_type"],
                            now(),
                            call_id,
                            item.key,
                            valid["source_document_id"],
                            valid["source_hash"],
                            valid["block_id"],
                            valid["span_hash"],
                            encode(valid),
                        ),
                    )
                conn.commit()
            if evidence:
                synthesized, call_id = invoke(
                    "synthesize", {"evidence": list(evidence.values())}, Synthesis
                )
                for item in synthesized.features:
                    valid, reason = admit_feature(item, evidence)
                    if item.feature_name in features:
                        valid, reason = None, "duplicate_feature"
                    if valid is not None:
                        reason = guard_g_invariant(valid, evidence)
                        if reason:
                            valid = None
                    if valid is None:
                        reject("synthesize", "feature", reason, item.model_dump(), call_id)
                        continue
                    features[item.feature_name] = valid
                    conn.execute(
                        "INSERT INTO s2_features VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            run_id,
                            method,
                            item.feature_name,
                            valid["feature_value"],
                            valid["direction"],
                            valid["confidence"],
                            valid["evidence_count"],
                            valid["net_assessment"],
                            encode(valid["supporting_evidence"]),
                            encode(valid["contradicting_evidence"]),
                            "ADMITTED",
                            now(),
                            call_id,
                            encode(valid),
                        ),
                    )
                conn.commit()
            if features:
                response, call_id = invoke(
                    "challenge",
                    {
                        "evidence": list(evidence.values()),
                        "quant_context": prepared["quant_context"],
                        "features": features,
                    },
                    Challenges,
                )
                for item in response.challenges:
                    reason = None
                    if (
                        not item.evidence
                        or any(key not in evidence for key in item.evidence)
                        or not safe_narrative(item.description)
                    ):
                        reason = "unsupported_challenge"
                    elif (
                        item.kind == "anomaly"
                        and item.anomaly_code not in prepared["quant_context"]["anomaly_codes"]
                    ):
                        reason = "unknown_quant_anomaly"
                    elif (item.kind == "regime") != (item.affected_model_variable == "regime"):
                        reason = "inconsistent_regime_target"
                    if reason:
                        reject("challenge", "challenge", reason, item.model_dump(), call_id)
                        continue
                    valid = {
                        **item.model_dump(),
                        "confidence": confidence([evidence[key] for key in item.evidence]),
                    }
                    challenges.append(valid)
                    conn.execute(
                        "INSERT INTO s2_challenges VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            run_id,
                            method,
                            item.kind,
                            item.affected_model_variable,
                            item.direction,
                            item.description,
                            valid["confidence"],
                            "ADMITTED",
                            now(),
                            call_id,
                            encode(item.evidence),
                            encode(valid),
                        ),
                    )
                conn.commit()
                if {"upside", "downside", "regime"} <= {item["kind"] for item in challenges}:
                    status = "COMPLETED"
        except Exception as error:
            status, failure = "FAILED", type(error).__name__
        summary = {
            "format_version": FORMAT_VERSION,
            "execution_mode": execution_mode,
            "run_id": run_id,
            "method": method,
            "quarter": method_config["quarter"],
            "status": status,
            "failure_type": failure,
            "context_hash": context_hash,
            "calls_made": calls_made,
            "evidence_count": len(evidence),
            "admitted_features_count": len(features),
            "rejections_count": len(rejections),
            "challenges_count": len(challenges),
            "features": features,
            "rejections": rejections,
            "challenges": challenges,
            "started_at": started,
            "completed_at": now(),
            "quality_verdict": "UNSCORED",
            "actual_model_identity": "UNVERIFIED",
            "source_authenticity_and_pit_metadata": "UNVERIFIED",
            "promotion_ready": False,
            "comparison_design_status": method_config["comparison_design_status"],
        }
        conn.execute(
            "UPDATE s2_experiment_runs SET calls_made=?,status=?,receipt_json=? WHERE id=?",
            (calls_made, status, encode(summary), run_id),
        )
        conn.commit()
        return summary


def compare_and_evaluate(b_res, c_res):
    """Report mechanical counts only. The frozen five-dimension rubric is human-scored."""
    return {
        "timestamp": now(),
        "target_quarter": b_res.get("quarter"),
        "same_context": bool(b_res.get("context_hash"))
        and b_res.get("context_hash") == c_res.get("context_hash"),
        "method_b_baseline": {**b_res, "score": None},
        "method_c_fsi": {**c_res, "score": None},
        "rubric_assessment": {
            key: "UNASSESSED_REQUIRES_HUMAN_BLIND_REVIEW"
            for key in (
                "rubric_1_evidence_fidelity",
                "rubric_2_guard_g_adherence",
                "rubric_3_core_dispute_stability",
                "rubric_4_qualitative_depth",
                "rubric_5_model_challenges",
            )
        },
        "verdict": "UNSCORED",
        "winner": None,
        "promotion_ready": False,
        "recommendation": "Obtain run-bound human blind review; no numerical scoring or promotion decision is defined.",
    }


def check_preflight(quarter, prepared=None, source_contents=None):
    if quarter not in ALLOWED_QUARTERS:
        raise ValueError("Quarter not supported by the frozen S2 workorder")
    result = {
        "quarter": quarter,
        "live_api_calls_made": 0,
        "max_calls_per_method": 22,
        "max_total_calls": 44,
        "preflight_status": "UNVERIFIED_MISSING_INPUTS",
        "quality_verdict": "UNSCORED",
        "live_authorization": "NOT_GRANTED",
        "live_execution_status": "BLOCKED_UNVERIFIED_RUNTIME_AND_METHODOLOGY",
    }
    if prepared is not None:
        result["context_hash"] = verify_prepared(prepared, source_contents, quarter)
        result["preflight_status"] = "INPUT_BYTES_AND_BLOCKS_VERIFIED"
    return result


def run_dry_run(quarter, prepared=None, source_contents=None):
    return {
        "mode": "DRY_RUN",
        "timestamp": now(),
        "preflight": check_preflight(quarter, prepared, source_contents),
        "methods": build_method_payloads(quarter),
        "live_api_calls_made": 0,
        "dry_run_verdict": "UNSCORED_NOT_LIVE_VERIFIED",
    }


def load_inputs(context_path, source_dir):
    prepared = json.loads(Path(context_path).read_text(encoding="utf-8"))
    contents = {}
    for doc in prepared["sources"]["documents"]:
        sha = doc["source_hash"]
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            raise ValueError("Invalid source hash filename")
        contents[sha] = (Path(source_dir) / sha).read_bytes()
    return prepared, contents


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarter", default="FY2023-Q2")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument(
        "--authorize-live", action="store_true", help="Separate explicit live-call authorization"
    )
    parser.add_argument("--prepared-context", type=Path)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--model", help="Explicit requested provider model; no inferred default")
    args = parser.parse_args(argv)
    if args.live:
        parser.error(LIVE_BLOCK_REASON)
    prepared, contents = None, None
    if args.prepared_context or args.source_dir:
        if not (args.prepared_context and args.source_dir):
            parser.error("Both --prepared-context and --source-dir are required")
        prepared, contents = load_inputs(args.prepared_context, args.source_dir)
    print(encode(run_dry_run(args.quarter, prepared, contents)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
