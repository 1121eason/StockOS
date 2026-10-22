"""Collect current, non-model evidence for the NVDA single-quarter experiment.

This is an audit, not a provider or a way to enable the blocked S2 runner.
Native observations and current web captures do not authenticate historical PIT
availability, model identity, or a global absence of interpreter-wrapped agents.
"""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from valuation_engine.ai.codex_pit import VERSION, discovery
from valuation_engine.ai.sources import blocks, chunks

PROTOCOL_HASH = "5aff6b73e6b83a5f159e66dce277eb4412c83d13624bfda6a3ce2dce91d44e1d"
PACKAGE_HASH = "51164d6740f177141db77880f29b79c606651d187402bc8edc6dcf7b2f6cb885"
PROVIDER_NAMES = ("codex", "claude", "gemini", "agy", "antigravity")
INTERPRETERS = ("python", "node", "ruby", "deno", "bun", "java")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_bound(path: Path, field: str, expected: str) -> dict:
    value = json.loads(path.read_bytes())
    body = {k: v for k, v in value.items() if k != field}
    if value.get(field) != expected or sha(canonical(body).encode()) != expected:
        raise ValueError("Input differs from the pinned Q2 experiment")
    return value


def official_url(value: str) -> str:
    url = urlsplit(value)
    valid = (
        url.scheme == "https"
        and url.port in (None, 443)
        and not url.username
        and not url.password
        and not url.query
        and not url.fragment
        and not any(c.isspace() for c in value)
        and (
            (
                url.hostname == "www.sec.gov"
                and re.fullmatch(r"/Archives/edgar/data/1045810/[0-9]{18}/[a-zA-Z0-9.-]+", url.path)
            )
            or (
                url.hostname == "nvidianews.nvidia.com"
                and url.path.startswith("/news/nvidia-announces-financial-results-for-")
            )
        )
    )
    if not valid:
        raise ValueError("URL outside the selected NVIDIA SEC/IR sources")
    return value


def inspect_preparation(preparation: Path, raw_dir: Path) -> tuple[dict, list[dict]]:
    protocol = load_bound(preparation / "protocol.json", "protocol_hash", PROTOCOL_HASH)
    package = load_bound(preparation / "package.json", "package_hash", PACKAGE_HASH)
    prepared = package["prepared"]
    context, sources = prepared["quant_context"], prepared["sources"]
    if context["quarter"] != "FY2023-Q2" or context["company_id"] != 1:
        raise ValueError("Only the pinned NVDA FY2023-Q2 package is accepted")
    derived: list[dict] = []
    excluded: list[dict] = []
    identities = set()
    for doc in sources["documents"]:
        official_url(doc["source_url"])
        identity = doc["source_document_id"]
        if identity in identities or not re.fullmatch(r"[a-f0-9]{64}", doc["source_hash"]):
            raise ValueError("Invalid or duplicate source identity")
        identities.add(identity)
        path = raw_dir / doc["source_hash"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("Source must be a regular content-addressed file")
        content = path.read_bytes()
        if sha(content) != doc["source_hash"]:
            raise ValueError("Selected raw source bytes changed")
        parsed, removed = blocks(
            SimpleNamespace(
                id=identity, content_hash=doc["source_hash"], document_type=doc["document_type"]
            ),
            content,
        )
        derived.extend(
            {**b, **{k: doc[k] for k in ("published_at", "available_at", "tier")}} for b in parsed
        )
        excluded.extend({"source_document_id": identity, **r} for r in removed)
    if canonical(derived) != canonical(sources["blocks"]) or canonical(excluded) != canonical(
        sources["excluded_blocks"]
    ):
        raise ValueError("Full narrative/exclusion replay differs from the pinned package")
    count = len(list(chunks(derived)))
    budget = protocol["shared_budget"]
    within = (
        count + 2 <= budget["attempts_per_method"]
        and 2 * (count + 2) <= budget["attempts_per_pair"]
    )
    return {
        "protocol_hash": PROTOCOL_HASH,
        "package_hash": PACKAGE_HASH,
        "quarter": context["quarter"],
        "information_cutoff": context["information_cutoff"],
        "source_count": len(identities),
        "narrative_blocks": len(derived),
        "excluded_blocks": len(excluded),
        "extraction_chunks": count,
        "planned_attempts_per_method": count + 2,
        "planned_attempts_per_pair": 2 * (count + 2),
        "budget": budget,
        "budget_status": "WITHIN_SINGLE_PAIR_CAP" if within else "BLOCKED_CALL_CAP",
        "complete_cached_source_replay": "PASS",
        "historical_availability": "UNVERIFIED",
    }, sources["documents"]


def parse_census(raw: str, exit_code: int) -> dict:
    if exit_code != 0 or not raw.strip():
        raise ValueError("Failed or empty native process observation")
    rows, candidates, seen = [], [], set()
    for line in raw.splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3:
            raise ValueError("Malformed native process observation")
        pid, ppid = int(fields[0]), int(fields[1])
        if pid <= 0 or ppid < 0 or pid in seen:
            raise ValueError("Invalid or duplicate process identity")
        seen.add(pid)
        row = {"pid": pid, "ppid": ppid, "executable": fields[2]}
        rows.append(row)
        name = Path(fields[2]).name.lower()
        if any(word in name for word in PROVIDER_NAMES) or name.startswith(INTERPRETERS):
            candidates.append(row)
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "collector": "/bin/ps -axo pid=,ppid=,comm=",
        "raw_observation": raw,
        "observation_sha256": sha(raw.encode()),
        "process_count": len(rows),
        "candidates": candidates,
        "classification_status": "UNVERIFIED_NO_REVIEWED_EXEMPTIONS",
        "no_residual_provider_proven": False,
        "note": "Desktop/parent processes are not exempt. Executable names alone cannot exclude custom or interpreter-wrapped providers; arguments and credentials are not collected.",
    }


def collect_census() -> dict:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,comm="],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return parse_census(result.stdout, result.returncode)


def inspect_cli(executable: str) -> dict:
    result = discovery(executable)
    actual = result.get("executable_path")
    result["executable_sha256"] = sha(Path(actual).read_bytes()) if actual else None
    result["required_transport_cli_version"] = VERSION
    result["actual_model"] = None
    result["model_identity_status"] = "NOT_OBSERVED_NO_MODEL_CALL"
    result["native_isolation_status"] = "NOT_ESTABLISHED_BY_DISCOVERY"
    return result


def classify_command_probe(name: str, control: dict, restricted: dict) -> str:
    markers = {
        "outside_read": ("dd:", "outside-canary.txt"),
        "workspace_write": ("/bin/sh:", "probe-write.txt"),
        "network_connect": ("nc:", "127.0.0.1"),
    }
    error = restricted.get("stderr", "")
    denied = (
        control.get("exit_code") == 0
        and restricted.get("exit_code") in (1, 2)
        and all(
            r.get("timeout") is False and r.get("group_absent") is True
            for r in (control, restricted)
        )
        and any(s in error for s in ("Operation not permitted", "Permission denied"))
        and all(s in error for s in markers[name])
        and "execvp()" not in error
    )
    return "DENIED_WITH_SUCCESSFUL_CONTROL" if denied else "UNVERIFIED"


def capture_official(url: str, destination: Path, *, client: httpx.Client) -> dict:
    """At most three allowlisted redirects; explicit bounded body, no env proxies."""
    official_url(url)
    history = []
    for _ in range(4):
        with client.stream("GET", url) as response:
            history.append({"url": url, "http_status": response.status_code})
            if response.is_redirect:
                # Resolve relative locations with httpx, then revalidate before following.
                url = official_url(str(response.url.join(response.headers["location"])))
                continue
            response.raise_for_status()
            data = bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data) > 12_000_000:
                    raise ValueError("Official source exceeds the capture limit")
            content = bytes(data)
            destination.write_bytes(content)
            soup = BeautifulSoup(content, "html.parser")
            timestamps = [
                dict(tag.attrs)
                for tag in soup.find_all("meta")
                if any(word in str(tag).lower() for word in ("published", "date", "modified"))
            ]
            return {
                "retrieved_at": datetime.now(UTC).isoformat(),
                "final_url": str(response.url),
                "history": history,
                "bytes": len(content),
                "sha256": sha(content),
                "captured_file": destination.name,
                "publication_metadata_observed": timestamps,
                "historical_availability": "UNVERIFIED_CURRENT_CAPTURE_ONLY",
            }
    raise ValueError("Too many official-source redirects")


def compare_narrative(content: bytes, selected_blocks: list[dict]) -> dict:
    soup = BeautifulSoup(content, "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    missing = [b["block_id"] for b in selected_blocks if " ".join(b["text"].split()) not in text]
    return {
        "selected_blocks": len(selected_blocks),
        "matching_blocks": len(selected_blocks) - len(missing),
        "missing_block_ids": missing,
        "current_official_narrative": "ALL_SELECTED_TEXT_PRESENT"
        if selected_blocks and not missing
        else "UNVERIFIED_INCOMPLETE_MATCH",
        "historical_availability": "UNVERIFIED_CURRENT_CAPTURE_ONLY",
    }


def capture_sources(
    documents: list[dict], destination: Path, selected_blocks: list[dict]
) -> list[dict]:
    receipts = []
    with httpx.Client(
        timeout=30,
        trust_env=False,
        follow_redirects=False,
        headers={"User-Agent": "StockOS source verification https://github.com/1121eason/StockOS"},
    ) as client:
        for doc in documents:
            receipt = {
                "source_document_id": doc["source_document_id"],
                "cached_sha256": doc["source_hash"],
                "source_url": doc["source_url"],
            }
            try:
                capture = capture_official(
                    doc["source_url"],
                    destination / f"source-{doc['source_document_id']}.html",
                    client=client,
                )
                receipt.update(
                    capture, exact_cached_bytes_match=capture["sha256"] == doc["source_hash"]
                )
                receipt["narrative_check"] = compare_narrative(
                    (destination / capture["captured_file"]).read_bytes(),
                    [
                        b
                        for b in selected_blocks
                        if b["source_document_id"] == doc["source_document_id"]
                    ],
                )
                receipt["source_authenticity_status"] = (
                    "EXACT_OFFICIAL_CURRENT_BYTES"
                    if receipt["exact_cached_bytes_match"]
                    else "UNVERIFIED_CAPTURE_DIFFERS"
                )
            except httpx.HTTPStatusError as error:
                receipt.update(
                    source_authenticity_status="UNVERIFIED_FETCH_FAILED",
                    error_type=type(error).__name__,
                    http_status=error.response.status_code,
                )
            except Exception as error:
                receipt.update(
                    source_authenticity_status="UNVERIFIED_FETCH_FAILED",
                    error_type=type(error).__name__,
                )
            receipts.append(receipt)
    return receipts


def summarize(prepared: dict, cli: dict, census: dict, sources: list[dict]) -> dict:
    blockers = []
    if prepared["budget_status"] != "WITHIN_SINGLE_PAIR_CAP":
        blockers.append("CALL_CAP")
    if cli.get("cli_version") != VERSION:
        blockers.append("CLI_VERSION_CHANGED_REQUALIFICATION_REQUIRED")
    if cli.get("authenticated") is not True:
        blockers.append("SUBSCRIPTION_AUTH_NOT_CONFIRMED")
    if cli.get("features_verified") is not True:
        blockers.append("FEATURE_CONFIGURATION_NOT_CONFIRMED")
    blockers.extend(
        [
            "NATIVE_ISOLATION_AND_LIFECYCLE_NOT_APPROVED",
            "GLOBAL_PROCESS_CLASSIFICATION_NOT_APPROVED",
            "ACTUAL_MODEL_IDENTITY_NOT_OBSERVED",
            "HISTORICAL_SOURCE_AVAILABILITY_NOT_AUTHENTICATED",
        ]
    )
    if len(sources) != prepared["source_count"] or not all(
        s.get("exact_cached_bytes_match") is True for s in sources
    ):
        blockers.append("OFFICIAL_SOURCE_BYTES_NOT_ALL_RECONFIRMED")
    return {
        "audit_version": "NVDASingleQuarterNativePreflightV1",
        "created_at": datetime.now(UTC).isoformat(),
        "quarter": "FY2023-Q2",
        "role": "research_supplement_only",
        "prepared": prepared,
        "cli": cli,
        "native_process_observation_collected": bool(census.get("observation_sha256")),
        "process_candidates": len(census.get("candidates", [])),
        "source_captures": sources,
        "blockers": blockers,
        "ready_for_live": False,
        "live_model_attempts": 0,
        "formal_db_writes": 0,
        "human_reviews_completed": 0,
        "quality_verdict": "UNSCORED",
        "winner": None,
        "promotion_ready": False,
    }
