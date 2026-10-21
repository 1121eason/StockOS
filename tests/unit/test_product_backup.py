import hashlib

import pytest

from valuation_engine.research.product_store import ProductStore
from valuation_engine.research.state_archive import backup_state, restore_state


@pytest.fixture
def state(tmp_path):
    store = ProductStore(tmp_path / "state")
    raw = b"synthetic source for recovery contract"
    identity = hashlib.sha256(raw).hexdigest()
    (store.root / "raw").mkdir()
    (store.root / "raw" / identity).write_bytes(raw)
    store.publish("source_document", identity, {"source_hash": identity}, 1, pointer="source")
    store.publish(
        "research", "synthetic", {"synthetic_only": True}, 2, pointer="research", message="saved"
    )
    store.enqueue("COLLECT_QUOTES", "synthetic-quote", {}, 3)
    store.claim(3)
    return store


def test_live_backup_preserves_research_and_resumes_interrupted_job(state, tmp_path):
    backup, restored = tmp_path / "backup", tmp_path / "restored"
    manifest = backup_state(state.root, backup)
    assert restore_state(backup, restored) == manifest
    recovered = ProductStore(restored)
    assert recovered.latest("research") == state.latest("research")
    assert recovered.alerts() == state.alerts()
    assert recovered.jobs()[0]["attempts"] == 1
    recovered.recover(4)
    assert recovered.claim(4)["attempts"] == 2
    assert state.jobs()[0]["status"] == "Running"


def test_restore_refuses_to_overwrite_existing_state(state, tmp_path):
    backup = tmp_path / "backup"
    backup_state(state.root, backup)
    with pytest.raises(ValueError, match="destination_exists"):
        restore_state(backup, state.root)


def test_corrupt_archive_never_becomes_a_restore(state, tmp_path):
    backup, output = tmp_path / "backup", tmp_path / "restored"
    backup_state(state.root, backup)
    (backup / "operations.sqlite").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="database_hash"):
        restore_state(backup, output)
    assert not output.exists()


def test_missing_raw_evidence_prevents_backup_publication(state, tmp_path):
    for raw in (state.root / "raw").iterdir():
        raw.unlink()
    output = tmp_path / "backup"
    with pytest.raises(FileNotFoundError):
        backup_state(state.root, output)
    assert not output.exists()


def test_tampered_product_artifact_prevents_backup(state, tmp_path):
    with state.connect() as db:
        db.execute("UPDATE artifacts SET payload='{}' WHERE kind='research'")
    with pytest.raises(ValueError, match="artifact_hash"):
        backup_state(state.root, tmp_path / "backup")
