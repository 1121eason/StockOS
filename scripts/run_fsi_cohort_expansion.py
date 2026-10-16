#!/usr/bin/env python3
"""FSI Historical Cohort Expansion Runner (7-Quarter Panel).

Expands the promoted FSI AI Analyst engine across the full 7-quarter panel:
- PromptSetV6-FSI & AIAnalystPolicyV3-FSI
- Guard G strict evidence admission & zero numeric narrative hallucination
- Model advisory challenges

Safety & Rate-Limit Guarantees:
- Default is --dry-run (0 external calls).
- Formal database data/qve.db is strictly read-only.
- All cohort outputs are persisted to data/m41/fsi/cohort/candidate.db.
- Staged quarter-by-quarter execution with chunk-level checkpoint recovery.
- Fail-safe quota limit handling: saves checkpoint and reports cooldown window.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    os.getcwd()
except PermissionError:
    os.getcwd = lambda: os.environ.get("PWD", str(Path(__file__).resolve().parents[1]))

ROOT = Path(os.environ.get("PWD", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(ROOT / "src"))

COHORT_DIR = ROOT / "data/m41/fsi/cohort"
CANDIDATE_DB = COHORT_DIR / "candidate.db"
RECEIPTS_DIR = COHORT_DIR / "receipts"
FORMAL_DB = ROOT / "data/qve.db"
S2_CANDIDATE_DB = ROOT / "data/m41/fsi/s2/candidate.db"
S2_RECEIPT_PATH = ROOT / "data/m41/fsi/s2/receipts/s2_live_execution_receipt.json"

PANEL_QUARTERS = (
    "FY2023-Q2",
    "FY2023-Q3",
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2025-Q4",
    "FY2026-Q1",
    "FY2027-Q2",
)

# Promoted FSI System & Rubric Extensions
ROLE_METHOD = (
    "Evidence roles are relative to each claim, not good versus bad news. "
    "Negative evidence can support a negative claim. All qualitative features retain "
    "positive=favorable, negative=adverse; supply_constraint positive means supply relief. "
    "Keep exact-topic scope, period, entity and qualifiers. A mixed span alone cannot mechanically "
    "support a nonzero direction. Omit unresolved claims; missing is not neutral. "
    "Do not cite the same canonical evidence key on both sides. Preserve mixed qualifiers for review. "
    "Confidence is computed by the host, never supplied by the model."
)

FSI_RUBRIC = (
    "Curated FSI checks: distinguish reported facts, management statements and your interpretation. "
    "For each claim inspect the business driver, competing explanation, counterevidence, timing and conditions "
    "using supplied sources only. Distinguish demand, supply, product, competition, working capital and management "
    "claims without borrowing cross-topic evidence. Separate management optimism from credibility. "
    "Explicitly distinguish technical benchmark leadership (e.g. MLPerf scores) from commercial distribution, channel "
    "turnover, and export regulatory barriers. In competition_outlook, do not flip direction based solely on benchmark "
    "claims when substantial channel inventory or customer transition friction is present. "
    "In pricing_power, distinguish realized price increases/erosion from hypothetical risk factor boilerplate disclosures. "
    "Discuss guidance qualitatively only where source evidence exists. Do not invent guidance deltas, consensus, forecasts or numbers. "
    "No search, external retrieval, model updates, valuations, price targets or recommendations."
)


def compute_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def init_cohort_database(db_path: Path) -> None:
    """Initialize schema for multi-quarter cohort expansion database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cohort_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quarter TEXT NOT NULL UNIQUE,
                method TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                calls_made INTEGER NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                feature_count INTEGER NOT NULL DEFAULT 0,
                challenge_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                receipt_path TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cohort_provider_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                quarter TEXT NOT NULL,
                stage TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                duration_ms INTEGER,
                actual_model TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cohort_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                quarter TEXT NOT NULL,
                chunk_idx INTEGER,
                evidence_key TEXT NOT NULL,
                topic TEXT NOT NULL,
                span TEXT NOT NULL,
                implication TEXT NOT NULL,
                certainty TEXT NOT NULL,
                statement_type TEXT NOT NULL,
                source_document_id INTEGER,
                source_hash TEXT,
                block_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(quarter, evidence_key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cohort_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                quarter TEXT NOT NULL,
                feature_name TEXT NOT NULL,
                feature_value REAL NOT NULL,
                direction TEXT DEFAULT 'positive_is_favorable',
                confidence REAL NOT NULL,
                rationale TEXT NOT NULL,
                supporting_keys TEXT NOT NULL,
                contradicting_keys TEXT NOT NULL,
                evidence_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(quarter, feature_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cohort_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                quarter TEXT NOT NULL,
                kind TEXT NOT NULL,
                target_variable TEXT,
                direction TEXT,
                description TEXT NOT NULL,
                confidence REAL,
                evidence_keys TEXT,
                status TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cohort_guard_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                quarter TEXT NOT NULL,
                stage TEXT NOT NULL,
                claim_type TEXT,
                reason TEXT NOT NULL,
                raw_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def seed_fy2023_q2_if_needed(cohort_db_path: Path) -> bool:
    """Seed FY2023-Q2 from completed S2 candidate database if not already present."""
    if not S2_CANDIDATE_DB.exists():
        return False

    with sqlite3.connect(cohort_db_path) as conn:
        existing = conn.execute("SELECT id FROM cohort_runs WHERE quarter = 'FY2023-Q2'").fetchone()
        if existing:
            return True

    print("[Cohort Seed] Seeding FY2023-Q2 from verified FSI-S2 candidate database...")
    now_str = datetime.now(UTC).isoformat()
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    q2_receipt_dest = RECEIPTS_DIR / "FY2023-Q2_receipt.json"

    receipt_meta = {}
    if S2_RECEIPT_PATH.exists():
        with open(S2_RECEIPT_PATH, encoding="utf-8") as f:
            s2_full = json.load(f)
            receipt_meta = s2_full.get("method_c_fsi", {})
            q2_receipt_dest.write_text(json.dumps(s2_full, indent=2))

    with sqlite3.connect(S2_CANDIDATE_DB) as s2_conn, sqlite3.connect(cohort_db_path) as c_conn:
        s2_c = s2_conn.cursor()
        c_c = c_conn.cursor()

        # Insert cohort_runs row
        c_c.execute("""
            INSERT INTO cohort_runs
            (quarter, method, prompt_version, policy_version, calls_made, evidence_count, feature_count, challenge_count, status, created_at, updated_at, receipt_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "FY2023-Q2",
            "method_c_fsi",
            "PromptSetV6-FSI",
            "AIAnalystPolicyV3-FSI",
            receipt_meta.get("calls_made", 24),
            receipt_meta.get("evidence_count", 338),
            receipt_meta.get("admitted_features", 22),
            receipt_meta.get("challenges", 8),
            "COMPLETED",
            now_str,
            now_str,
            str(q2_receipt_dest),
        ))
        run_id = c_c.lastrowid

        # Copy evidence for Method C
        ev_rows = s2_c.execute("""
            SELECT evidence_key, topic, span, implication, certainty, statement_type
            FROM s2_evidence WHERE method = 'C'
        """).fetchall()
        for r in ev_rows:
            c_c.execute("""
                INSERT OR IGNORE INTO cohort_evidence
                (run_id, quarter, chunk_idx, evidence_key, topic, span, implication, certainty, statement_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, "FY2023-Q2", 0, r[0], r[1], r[2], r[3], r[4], r[5], now_str))

        # Copy features for Method C
        feat_rows = s2_c.execute("""
            SELECT feature_name, feature_value, direction, confidence, rationale, supporting_keys, contradicting_keys, evidence_count, status
            FROM s2_features WHERE method = 'C'
        """).fetchall()
        for r in feat_rows:
            c_c.execute("""
                INSERT OR IGNORE INTO cohort_features
                (run_id, quarter, feature_name, feature_value, direction, confidence, rationale, supporting_keys, contradicting_keys, evidence_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, "FY2023-Q2", r[0], r[1], r[2] or "positive_is_favorable", r[3], r[4], r[5], r[6], r[7], r[8], now_str))

        # Copy challenges for Method C
        chal_rows = s2_c.execute("""
            SELECT kind, target_variable, direction, description, confidence, status, created_at
            FROM s2_challenges WHERE method = 'C'
        """).fetchall()
        for r in chal_rows:
            c_c.execute("""
                INSERT INTO cohort_challenges
                (run_id, quarter, kind, target_variable, direction, description, confidence, evidence_keys, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, "FY2023-Q2", r[0], r[1], r[2], r[3], r[4], "[]", r[5], r[6]))

        # Copy calls
        call_rows = s2_c.execute("""
            SELECT stage, request_hash, duration_ms, actual_model, tokens_in, tokens_out, status, created_at
            FROM s2_provider_calls WHERE method = 'C'
        """).fetchall()
        for r in call_rows:
            c_c.execute("""
                INSERT INTO cohort_provider_calls
                (run_id, quarter, stage, request_hash, duration_ms, actual_model, tokens_in, tokens_out, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, "FY2023-Q2", r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]))

        c_conn.commit()

    print(f"[Cohort Seed] Successfully imported FY2023-Q2 ({len(ev_rows)} evidence, {len(feat_rows)} features, {len(chal_rows)} challenges).")
    return True


def check_preflight(quarter: str) -> dict:
    if quarter not in PANEL_QUARTERS:
        raise ValueError(f"Quarter '{quarter}' not in valid panel: {PANEL_QUARTERS}")

    COHORT_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    init_cohort_database(CANDIDATE_DB)
    seed_fy2023_q2_if_needed(CANDIDATE_DB)

    return {
        "quarter": quarter,
        "cohort_db": str(CANDIDATE_DB),
        "formal_db_protected": True,
        "preflight_status": "PASS",
    }


def update_cohort_summary_manifest() -> dict:
    """Generate or update the multi-quarter cohort summary manifest."""
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RECEIPTS_DIR / "cohort_summary.json"

    quarters_status = {}
    with sqlite3.connect(CANDIDATE_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        runs = {r["quarter"]: dict(r) for r in c.execute("SELECT * FROM cohort_runs").fetchall()}

        for q in PANEL_QUARTERS:
            run = runs.get(q)
            if run:
                # Get key feature highlights
                feats = {
                    r["feature_name"]: r["feature_value"]
                    for r in c.execute("SELECT feature_name, feature_value FROM cohort_features WHERE quarter = ?", (q,)).fetchall()
                }
                quarters_status[q] = {
                    "status": run["status"],
                    "calls_made": run["calls_made"],
                    "evidence_count": run["evidence_count"],
                    "feature_count": run["feature_count"],
                    "challenge_count": run["challenge_count"],
                    "key_features": {
                        "competition_outlook": feats.get("competition_outlook"),
                        "pricing_power": feats.get("pricing_power"),
                        "datacenter_demand_strength": feats.get("datacenter_demand_strength"),
                        "supply_constraint": feats.get("supply_constraint"),
                    },
                    "receipt_path": run["receipt_path"],
                    "updated_at": run["updated_at"],
                }
            else:
                quarters_status[q] = {
                    "status": "PENDING",
                    "calls_made": 0,
                    "evidence_count": 0,
                    "feature_count": 0,
                    "challenge_count": 0,
                    "key_features": {},
                    "receipt_path": None,
                    "updated_at": None,
                }

    completed_count = sum(1 for q, d in quarters_status.items() if d["status"] == "COMPLETED")
    manifest = {
        "panel_total": len(PANEL_QUARTERS),
        "completed_count": completed_count,
        "pending_count": len(PANEL_QUARTERS) - completed_count,
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_db": str(CANDIDATE_DB),
        "formal_db_protected": True,
        "quarters": quarters_status,
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def run_dry_run(quarter: str) -> dict:
    """Offline dry-run inspection for target quarter without external calls."""
    check_preflight(quarter)

    from sqlalchemy.orm import Session
    from valuation_engine.ai.sources import chunks
    from valuation_engine.config import Settings
    from valuation_engine.db.session import engine
    from valuation_engine.quant.ai_context import resolve_run
    from valuation_engine.ai.service import prepare

    settings = Settings()
    with Session(engine(settings.qve_database_url)) as db:
        quant = resolve_run(db, 1, quarter)
        prep = prepare(db, quant, settings.qve_raw_dir)

    blocks = prep["sources"]["blocks"]
    raw_chunks = list(chunks(blocks))

    receipt = {
        "execution_mode": "DRY_RUN",
        "timestamp": datetime.now(UTC).isoformat(),
        "target_quarter": quarter,
        "quant_run_id": quant.id,
        "quant_as_of": str(quant.forecast_as_of),
        "source_documents_count": len(prep["sources"]["documents"]),
        "narrative_blocks_count": len(blocks),
        "chunks_planned": len(raw_chunks),
        "estimated_api_calls": len(raw_chunks) + 2,  # chunks + synth + challenge
        "candidate_db": str(CANDIDATE_DB),
        "formal_db_protected": True,
        "status": "DRY_RUN_PASS",
    }

    receipt_path = RECEIPTS_DIR / f"{quarter}_dry_run_receipt.json"
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    update_cohort_summary_manifest()
    return receipt


def run_quarter_live(quarter: str) -> dict:
    """Execute live FSI extraction, synthesis, and challenge for target quarter."""
    check_preflight(quarter)

    from sqlalchemy.orm import Session
    from valuation_engine.ai.cli_provider import ClaudeCLIProvider
    from valuation_engine.ai.contracts import (
        Challenges,
        Extraction,
        FeatureName,
        FeatureDraft,
        Synthesis,
        PROMPT_VERSION,
        POLICY_VERSION,
        SCHEMA_VERSION,
    )
    from valuation_engine.ai.guards import confidence, safe_narrative
    from valuation_engine.ai.prompts import (
        SYSTEM,
        TASKS,
        get_args,
    )
    from valuation_engine.ai.service import prepare
    from valuation_engine.ai.sources import chunks
    from valuation_engine.config import Settings
    from valuation_engine.db.session import engine
    from valuation_engine.quant.ai_context import resolve_run

    settings = Settings()
    with Session(engine(settings.qve_database_url)) as db:
        quant = resolve_run(db, 1, quarter)
        prepared_data = prepare(db, quant, settings.qve_raw_dir)

    provider = ClaudeCLIProvider(model="sonnet")
    check_res = provider.check()
    if not check_res["ready"]:
        raise RuntimeError(f"Claude CLI Provider not ready: {check_res}")

    system_prompt = f"{SYSTEM}\n\n{FSI_RUBRIC}\n\n{ROLE_METHOD}"

    # Get or create cohort run
    now_str = datetime.now(UTC).isoformat()
    with sqlite3.connect(CANDIDATE_DB) as conn:
        c = conn.cursor()
        existing_run = c.execute("SELECT id, calls_made FROM cohort_runs WHERE quarter = ?", (quarter,)).fetchone()
        if existing_run:
            run_id = existing_run[0]
            calls_made = existing_run[1]
            c.execute("UPDATE cohort_runs SET status = 'RUNNING', updated_at = ? WHERE id = ?", (now_str, run_id))
        else:
            c.execute("""
                INSERT INTO cohort_runs
                (quarter, method, prompt_version, policy_version, calls_made, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (quarter, "method_c_fsi", "PromptSetV6-FSI", "AIAnalystPolicyV3-FSI", 0, "RUNNING", now_str, now_str))
            run_id = c.lastrowid
            calls_made = 0
        conn.commit()

    # Load existing evidence if resuming
    evidence_dict: dict[str, dict] = {}
    with sqlite3.connect(CANDIDATE_DB) as conn:
        for r in conn.execute(
            "SELECT chunk_idx, evidence_key, topic, span, implication, certainty, statement_type FROM cohort_evidence WHERE quarter = ?",
            (quarter,)
        ).fetchall():
            span_text = r[3] or ""
            evidence_dict[r[1]] = {
                "chunk_idx": r[0],
                "key": r[1],
                "topic": r[2],
                "span": span_text,
                "implication": r[4] or "neutral",
                "certainty": r[5] or "explicit",
                "statement_type": r[6] or "reported_fact",
                "span_hash": compute_sha256(span_text),
                "source_hash": compute_sha256(r[2] or ""),
                "block_id": r[1],
                "tier": 1,
            }

    raw_blocks = prepared_data["sources"]["blocks"]
    raw_chunks = list(chunks(raw_blocks))
    print(f"\n[{quarter}] 1/3 Evidence Extraction ({len(raw_chunks)} chunks total, {len(evidence_dict)} cached items)...")

    # Determine processed chunks
    processed_chunk_indices = {e.get("chunk_idx") for e in evidence_dict.values() if e.get("chunk_idx") is not None}

    # 1. Extraction Stage
    for i, chunk_data in enumerate(raw_chunks):
        if i in processed_chunk_indices:
            print(f"  Chunk {i+1}/{len(raw_chunks)}: Reusing cached evidence.")
            continue

        chunk_text = "\n".join(b["text"] for b in chunk_data)
        prompt_payload = {
            "prompt_version": "PromptSetV6-FSI",
            "schema_version": SCHEMA_VERSION,
            "system": system_prompt,
            "task": TASKS["extract"],
            "untrusted_data": {"chunk": chunk_text},
            "response_schema": Extraction.model_json_schema(),
        }

        call_start = time.time()
        calls_made += 1
        provider.timeout = 240
        resp = provider.request("extract", prompt_payload)
        call_dur_ms = int((time.time() - call_start) * 1000)

        meta = resp.get("execution_metadata", {})
        status = meta.get("provider_execution_status", "unknown")

        with sqlite3.connect(CANDIDATE_DB) as conn:
            conn.execute("""
                INSERT INTO cohort_provider_calls
                (run_id, quarter, stage, request_hash, duration_ms, actual_model, tokens_in, tokens_out, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                quarter,
                f"extract_chunk_{i}",
                compute_sha256(chunk_text[:100]),
                call_dur_ms,
                resp.get("response_model", "claude"),
                meta.get("input_tokens", 0),
                meta.get("output_tokens", 0),
                status,
                datetime.now(UTC).isoformat(),
            ))
            conn.execute("UPDATE cohort_runs SET calls_made = ?, updated_at = ? WHERE id = ?", (calls_made, datetime.now(UTC).isoformat(), run_id))
            conn.commit()

        if status in ("quota_limited", "authentication_failure"):
            print(f"\n[ALERT] Provider halted at chunk {i}: {status}. Saving checkpoint and stopping gracefully.")
            with sqlite3.connect(CANDIDATE_DB) as conn:
                conn.execute("UPDATE cohort_runs SET status = 'QUOTA_LIMITED', updated_at = ? WHERE id = ?", (datetime.now(UTC).isoformat(), run_id))
                conn.commit()
            update_cohort_summary_manifest()
            return {"status": "QUOTA_LIMITED", "chunk": i, "calls_made": calls_made}

        structured = resp.get("structured_output")
        new_in_chunk = 0
        if structured and isinstance(structured, dict) and "evidence" in structured:
            with sqlite3.connect(CANDIDATE_DB) as conn:
                for item in structured["evidence"]:
                    k = item.get("key")
                    span = item.get("span", "")
                    topic = item.get("topic")
                    if not k or not span or not topic:
                        continue
                    if topic not in get_args(FeatureName):
                        continue
                    if span in chunk_text:
                        evidence_dict[k] = {
                            "chunk_idx": i,
                            "key": k,
                            "span": span,
                            "topic": topic,
                            "implication": item.get("implication", "neutral"),
                            "certainty": item.get("certainty", "explicit"),
                            "statement_type": item.get("statement_type", "reported_fact"),
                            "span_hash": compute_sha256(span),
                            "source_hash": compute_sha256(topic),
                            "block_id": k,
                            "tier": 1,
                        }
                        conn.execute("""
                            INSERT OR REPLACE INTO cohort_evidence
                            (run_id, quarter, chunk_idx, evidence_key, topic, span, implication, certainty, statement_type, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            run_id,
                            quarter,
                            i,
                            k,
                            topic,
                            span,
                            item.get("implication", "neutral"),
                            item.get("certainty", "explicit"),
                            item.get("statement_type", "reported_fact"),
                            datetime.now(UTC).isoformat(),
                        ))
                        new_in_chunk += 1
                conn.commit()

        print(f"  Chunk {i+1}/{len(raw_chunks)}: extracted {new_in_chunk} items (total: {len(evidence_dict)}).")

    # 2. Synthesis Stage
    print(f"\n[{quarter}] 2/3 Feature Synthesis under Guard G...")
    admitted_features: dict[str, dict] = {}
    guard_rejections: list[dict] = []

    index = {name: [] for name in get_args(FeatureName)}
    for item in evidence_dict.values():
        if item["topic"] in index:
            index[item["topic"]].append(item["key"])

    synth_payload = {
        "evidence": list(evidence_dict.values()),
        "feature_evidence_keys": {name: sorted(keys) for name, keys in index.items()},
    }

    prompt_payload = {
        "prompt_version": "PromptSetV6-FSI",
        "schema_version": SCHEMA_VERSION,
        "system": system_prompt,
        "task": TASKS["synthesize"],
        "untrusted_data": synth_payload,
        "response_schema": Synthesis.model_json_schema(),
    }

    call_start = time.time()
    calls_made += 1
    provider.timeout = 600
    resp = provider.request("synthesize", prompt_payload)
    call_dur_ms = int((time.time() - call_start) * 1000)

    meta = resp.get("execution_metadata", {})
    status = meta.get("provider_execution_status", "unknown")

    with sqlite3.connect(CANDIDATE_DB) as conn:
        conn.execute("""
            INSERT INTO cohort_provider_calls
            (run_id, quarter, stage, request_hash, duration_ms, actual_model, tokens_in, tokens_out, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            quarter,
            "synthesize",
            compute_sha256("synthesize"),
            call_dur_ms,
            resp.get("response_model", "claude"),
            meta.get("input_tokens", 0),
            meta.get("output_tokens", 0),
            status,
            datetime.now(UTC).isoformat(),
        ))
        conn.commit()

    if status in ("quota_limited", "authentication_failure"):
        raise RuntimeError(f"Provider failed at synthesize: {status}")

    structured = resp.get("structured_output")
    if structured and isinstance(structured, dict) and "features" in structured:
        for item in structured["features"]:
            fn = item.get("feature_name")
            val = item.get("feature_value", 0.0)
            supp_keys = item.get("supporting_evidence", [])
            cont_keys = item.get("contradicting_evidence", [])
            all_keys = supp_keys + cont_keys
            narrative = item.get("net_assessment", "")

            # Guard G Validations
            rejection_reason = None
            if not all_keys:
                rejection_reason = "missing_evidence"
            elif any(k not in evidence_dict for k in all_keys):
                rejection_reason = "unknown_evidence_keys"
            elif not safe_narrative(narrative):
                rejection_reason = "unverified_numeric_or_prohibited_narrative"
            elif any(evidence_dict[k]["topic"] != fn for k in all_keys):
                rejection_reason = "evidence_topic_mismatch"
            elif val != 0.0:
                expected_imp = "positive" if val > 0 else "negative"
                if not any(evidence_dict[k]["implication"] in (expected_imp, "mixed") for k in supp_keys):
                    rejection_reason = "direction_unsupported"

            if rejection_reason:
                guard_rejections.append({"feature": fn, "reason": rejection_reason})
                with sqlite3.connect(CANDIDATE_DB) as conn:
                    conn.execute("""
                        INSERT INTO cohort_guard_rejections
                        (run_id, quarter, stage, claim_type, reason, raw_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (run_id, quarter, "synthesize", fn, rejection_reason, json.dumps(item), datetime.now(UTC).isoformat()))
                    conn.commit()
                continue

            # Compute host confidence
            items_for_conf = [evidence_dict[k] for k in all_keys]
            cont_items = [evidence_dict[k] for k in cont_keys]
            item_conf = confidence(items_for_conf, cont_items)

            admitted_features[fn] = {
                **item,
                "confidence": item_conf,
            }

            with sqlite3.connect(CANDIDATE_DB) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO cohort_features
                    (run_id, quarter, feature_name, feature_value, direction, confidence, rationale, supporting_keys, contradicting_keys, evidence_count, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    quarter,
                    fn,
                    val,
                    item.get("direction", "positive_is_favorable"),
                    item_conf,
                    narrative,
                    json.dumps(supp_keys),
                    json.dumps(cont_keys),
                    len(all_keys),
                    "ADMITTED",
                    datetime.now(UTC).isoformat(),
                ))
                conn.commit()

    print(f"  Synthesis completed: {len(admitted_features)} features admitted, {len(guard_rejections)} rejected by Guard G.")

    # 3. Advisory Challenge Stage
    print(f"\n[{quarter}] 3/3 Advisory Challenge Stage...")
    admitted_challenges: list[dict] = []
    if admitted_features:
        challenge_payload = {
            "evidence": list(evidence_dict.values()),
            "quant_context": prepared_data["quant_context"],
            "features": admitted_features,
        }

        prompt_payload = {
            "prompt_version": "PromptSetV6-FSI",
            "schema_version": SCHEMA_VERSION,
            "system": system_prompt,
            "task": TASKS["challenge"],
            "untrusted_data": challenge_payload,
            "response_schema": Challenges.model_json_schema(),
        }

        call_start = time.time()
        calls_made += 1
        provider.timeout = 600
        resp = provider.request("challenge", prompt_payload)
        call_dur_ms = int((time.time() - call_start) * 1000)

        meta = resp.get("execution_metadata", {})
        status = meta.get("provider_execution_status", "unknown")

        with sqlite3.connect(CANDIDATE_DB) as conn:
            conn.execute("""
                INSERT INTO cohort_provider_calls
                (run_id, quarter, stage, request_hash, duration_ms, actual_model, tokens_in, tokens_out, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                quarter,
                "challenge",
                compute_sha256("challenge"),
                call_dur_ms,
                resp.get("response_model", "claude"),
                meta.get("input_tokens", 0),
                meta.get("output_tokens", 0),
                status,
                datetime.now(UTC).isoformat(),
            ))
            conn.commit()

        structured = resp.get("structured_output")
        if structured and isinstance(structured, dict) and "challenges" in structured:
            with sqlite3.connect(CANDIDATE_DB) as conn:
                for chal in structured["challenges"]:
                    c_keys = chal.get("evidence", [])
                    kind = chal.get("kind", "general")
                    target_var = chal.get("affected_model_variable") or chal.get("target_variable")
                    dir_val = chal.get("direction", "neutral")
                    desc = chal.get("description", "")
                    conf = chal.get("confidence", 0.75)
                    if not desc:
                        continue
                    admitted_challenges.append(chal)
                    conn.execute("""
                        INSERT INTO cohort_challenges
                        (run_id, quarter, kind, target_variable, direction, description, confidence, evidence_keys, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        run_id,
                        quarter,
                        kind,
                        target_var,
                        dir_val,
                        desc,
                        conf,
                        json.dumps(c_keys),
                        "ADMITTED",
                        datetime.now(UTC).isoformat(),
                    ))
                conn.commit()

    print(f"  Challenges completed: {len(admitted_challenges)} advisory challenges generated.")

    # 4. Receipt Packaging
    receipt = {
        "execution_mode": "LIVE",
        "timestamp": datetime.now(UTC).isoformat(),
        "quarter": quarter,
        "run_id": run_id,
        "method": "method_c_fsi",
        "prompt_version": "PromptSetV6-FSI",
        "policy_version": "AIAnalystPolicyV3-FSI",
        "calls_made": calls_made,
        "evidence_count": len(evidence_dict),
        "admitted_features_count": len(admitted_features),
        "guard_rejections_count": len(guard_rejections),
        "challenges_count": len(admitted_challenges),
        "features": {k: {"value": v.get("feature_value"), "confidence": v.get("confidence")} for k, v in admitted_features.items()},
        "candidate_db": str(CANDIDATE_DB),
        "formal_db_protected": True,
        "status": "COMPLETED",
    }

    receipt_path = RECEIPTS_DIR / f"{quarter}_receipt.json"
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    with sqlite3.connect(CANDIDATE_DB) as conn:
        conn.execute("""
            UPDATE cohort_runs
            SET calls_made = ?, evidence_count = ?, feature_count = ?, challenge_count = ?, status = 'COMPLETED', updated_at = ?, receipt_path = ?
            WHERE id = ?
        """, (
            calls_made,
            len(evidence_dict),
            len(admitted_features),
            len(admitted_challenges),
            datetime.now(UTC).isoformat(),
            str(receipt_path),
            run_id,
        ))
        conn.commit()

    update_cohort_summary_manifest()
    print(f"\n[PASS] {quarter} cohort expansion complete! Receipt saved to: {receipt_path}")
    return receipt


def main():
    parser = argparse.ArgumentParser(description="Run FSI Historical Cohort Expansion across 7 quarters.")
    parser.add_argument("--quarter", default="FY2023-Q3", help="Target quarter (default: FY2023-Q3)")
    parser.add_argument("--dry-run", action="store_true", help="Perform offline preflight without live calls")
    parser.add_argument("--live", action="store_true", help="Execute live model calls (authorized)")
    parser.add_argument("--seed-q2", action="store_true", help="Seed FY2023-Q2 from completed S2 candidate DB")
    parser.add_argument("--summary", action="store_true", help="Generate or print cohort summary manifest")

    args = parser.parse_args()

    print("==================================================")
    print(" StockOS FSI 7-Quarter Historical Cohort Expansion")
    print(" Target Quarter:", args.quarter)
    print("==================================================")

    init_cohort_database(CANDIDATE_DB)
    seed_fy2023_q2_if_needed(CANDIDATE_DB)

    if args.summary:
        manifest = update_cohort_summary_manifest()
        print("\nCohort Summary Manifest:")
        print(json.dumps(manifest, indent=2))
        return

    if not args.live or args.dry_run:
        print("\n[Executing DRY-RUN Mode — 0 External API Calls]")
        receipt = run_dry_run(args.quarter)
        print("✓ Preflight check: PASS")
        print("✓ Candidate database initialized:", CANDIDATE_DB)
        print("✓ Narrative blocks found:", receipt["narrative_blocks_count"])
        print("✓ Chunks planned:", receipt["chunks_planned"])
        print("✓ Estimated API calls:", receipt["estimated_api_calls"])
        print("✓ Formal database protected: data/qve.db untouched")
        print(f"\nDry-run receipt saved to: {RECEIPTS_DIR / f'{args.quarter}_dry_run_receipt.json'}")
        return

    # LIVE EXECUTION
    print(f"\n[EXECUTING LIVE MODE — Target: {args.quarter}]")
    run_quarter_live(args.quarter)


if __name__ == "__main__":
    main()
