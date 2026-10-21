"""Cloud packaging invariants, with synthetic local data and no uploads."""

import hashlib
import json

import pytest

from valuation_engine.research import deployment


@pytest.fixture
def seed(tmp_path):
    folder = tmp_path / "seed"
    (folder / "raw").mkdir(parents=True)
    (folder / "qve.db").write_bytes(b"synthetic database bytes")
    raw = b"synthetic official source bytes"
    identity = hashlib.sha256(raw).hexdigest()
    (folder / "raw" / identity).write_bytes(raw)
    manifest = {
        "version": deployment.VERSION,
        "ticker": "NVDA",
        "database_sha256": deployment.file_hash(folder / "qve.db"),
        "source_hashes": [identity],
    }
    (folder / "seed-manifest.json").write_text(json.dumps(manifest))
    return folder, manifest


def test_seed_verification_rejects_modified_database_and_pending_writes(seed):
    folder, manifest = seed
    assert deployment.verify_seed(folder) == manifest
    (folder / "qve.db-wal").write_bytes(b"pending write")
    with pytest.raises(ValueError):
        deployment.verify_seed(folder)
    (folder / "qve.db-wal").unlink()
    (folder / "qve.db").write_bytes(b"changed")
    with pytest.raises(ValueError, match="database_hash"):
        deployment.verify_seed(folder)


def test_seed_source_hashes_cannot_escape_raw_directory(seed):
    folder, manifest = seed
    manifest["source_hashes"] = ["../../outside"]
    (folder / "seed-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="invalid_source_hash"):
        deployment.verify_seed(folder)


def test_seed_source_must_match_bytes_and_not_be_a_link(seed, tmp_path):
    folder, manifest = seed
    source = folder / "raw" / manifest["source_hashes"][0]
    source.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="source_hash"):
        deployment.verify_seed(folder)
    source.unlink()
    source.symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="source_hash"):
        deployment.verify_seed(folder)


def test_prepare_seed_never_replaces_an_existing_destination(seed):
    folder, _ = seed
    with pytest.raises(ValueError, match="already_exists"):
        deployment.prepare_seed(folder / "qve.db", folder / "raw", folder)


def test_seed_copy_publishes_only_after_same_research_reconciles(seed, tmp_path, monkeypatch):
    folder, manifest = seed
    research = {
        "sources": [{"sha256": manifest["source_hashes"][0]}],
        "source_database_sha256": manifest["database_sha256"],
        "current": {"quarter": "FY2027-Q2"},
        "previous": {"quarter": "FY2027-Q1"},
        "revisions": [],
    }
    monkeypatch.setattr(deployment, "build_research", lambda *a: research)
    output = tmp_path / "copy"
    result = deployment.prepare_seed(folder / "qve.db", folder / "raw", output)
    assert deployment.verify_seed(output) == result
    assert deployment.file_hash(folder / "qve.db") == manifest["database_sha256"]
    assert sorted(p.name for p in output.iterdir()) == ["qve.db", "raw", "seed-manifest.json"]


def test_failed_reconciliation_never_publishes_seed(seed, tmp_path, monkeypatch):
    folder, manifest = seed
    calls = []

    def build(*args):
        calls.append(True)
        return {
            "sources": [{"sha256": manifest["source_hashes"][0]}],
            "source_database_sha256": manifest["database_sha256"],
            "current": {"quarter": "FY2027-Q2" if len(calls) == 1 else "FY2027-Q3"},
            "previous": {"quarter": "FY2027-Q1"},
            "revisions": [],
        }

    monkeypatch.setattr(deployment, "build_research", build)
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match="research_mismatch"):
        deployment.prepare_seed(folder / "qve.db", folder / "raw", output)
    assert not output.exists()
