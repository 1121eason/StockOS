"""Build a hash-pinned, single-quarter PIT package for isolated inference."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from valuation_engine.db.store import digest

VERSION = "PITQuarterPackageV1"


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("PIT package timestamps must include a timezone")
    return result


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def build_package(prepared: dict) -> dict:
    """Return deterministic package files and a manifest after enforcing the PIT boundary."""
    context = prepared["quant_context"]
    sources = prepared["sources"]
    cutoff_text = context["information_cutoff"]
    cutoff = _timestamp(cutoff_text)
    quarter = context["quarter"]
    if _timestamp(context["as_of_timestamp"]) > cutoff:
        raise ValueError("Quant context became available after PIT cutoff")
    if context["regime"]["forecast_run_id"] != context["forecast_run_id"]:
        raise ValueError("Regime output does not match the PIT forecast run")
    if _timestamp(context["regime"]["as_of"]) > cutoff:
        raise ValueError("Regime output became available after PIT cutoff")
    docs = sources["documents"]
    blocks = sources["blocks"]
    by_id = {}
    for doc in docs:
        source_id = doc["source_document_id"]
        if source_id in by_id:
            raise ValueError("Duplicate source document in PIT package")
        if _timestamp(doc["available_at"]) > cutoff:
            raise ValueError("Source became available after PIT cutoff")
        by_id[source_id] = doc

    grouped: dict[int, list[dict]] = {source_id: [] for source_id in by_id}
    block_ids = set()
    for block in blocks:
        source_id = block["source_document_id"]
        doc = by_id.get(source_id)
        if doc is None or block["source_hash"] != doc["source_hash"]:
            raise ValueError("PIT block does not match a manifest source")
        if block["block_id"] in block_ids:
            raise ValueError("Duplicate block identifier in PIT package")
        if _timestamp(block["available_at"]) > cutoff:
            raise ValueError("Narrative block became available after PIT cutoff")
        if _timestamp(block["available_at"]) != _timestamp(doc["available_at"]):
            raise ValueError("Narrative block availability differs from its source")
        block_ids.add(block["block_id"])
        grouped[source_id].append(block)

    files: dict[str, str] = {
        "input/financials.json": _json(
            {
                "quarter": quarter,
                "as_of_timestamp": context["as_of_timestamp"],
                "forecast_run_id": context["forecast_run_id"],
                "quant_forecasts": context["quant_forecasts"],
                "fundamental_features": context["fundamental_features"],
            }
        ),
        "input/guidance.json": _json(
            {
                "quarter": quarter,
                "information_cutoff": cutoff_text,
                "quant_guidance_accuracy": context["quant_guidance_accuracy"],
            }
        ),
        "input/regime.json": _json(context["regime"]),
    }
    source_manifest = []
    for source_id in sorted(by_id):
        doc = by_id[source_id]
        name = f"input/source_{source_id}_{doc['source_hash'][:12]}.txt"
        rendered = []
        block_manifest = []
        for block in grouped[source_id]:
            text = block["text"]
            rendered.append(f"[{block['block_id']}] {block.get('section', 'narrative')}\n{text}")
            block_manifest.append(
                {
                    "block_id": block["block_id"],
                    "block_hash": hashlib.sha256(text.encode()).hexdigest(),
                    "section": block.get("section"),
                    "speaker": block.get("speaker"),
                    "speaker_role": block.get("speaker_role"),
                }
            )
        files[name] = "\n\n".join(rendered) + ("\n" if rendered else "")
        source_manifest.append(
            {
                "source_document_id": source_id,
                "source_hash": doc["source_hash"],
                "document_type": doc["document_type"],
                "source_url": doc["source_url"],
                "published_at": doc["published_at"],
                "available_at": doc["available_at"],
                "timestamp_precision": doc["timestamp_precision"],
                "availability_evidence_id": doc["availability_evidence_id"],
                "block_count": len(block_manifest),
                "blocks": block_manifest,
                "package_path": name,
            }
        )
    files["input/source_manifest.json"] = _json(
        {
            "quarter": quarter,
            "information_cutoff": cutoff_text,
            "sources": source_manifest,
            "excluded_blocks": sources["excluded_blocks"],
        }
    )
    entries = [
        {"path": name, "sha256": hashlib.sha256(body.encode()).hexdigest()}
        for name, body in sorted(files.items())
    ]
    manifest = {
        "package_version": VERSION,
        "quarter": quarter,
        "information_cutoff": cutoff_text,
        "as_of_timestamp": context["as_of_timestamp"],
        "forecast_run_id": context["forecast_run_id"],
        "source_count": len(docs),
        "block_count": len(blocks),
        "files": entries,
        "package_hash": digest(entries),
        "excluded_block_count": len(sources["excluded_blocks"]),
    }
    files["package_manifest.json"] = _json(manifest)
    return {"manifest": manifest, "files": files}
