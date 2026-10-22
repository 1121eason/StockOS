import hashlib
from datetime import UTC, datetime

import pytest

from valuation_engine.db.store import digest
from valuation_engine.research import financial_refresh as refresh
from valuation_engine.research.numbers import canonical


@pytest.mark.parametrize("changed", [False, True])
def test_same_quarter_never_skips_integrity_or_silently_accepts_changed_inputs(
    tmp_path, monkeypatch, changed
):
    root = tmp_path / "product"
    (root / "raw").mkdir(parents=True)
    raw = b"synthetic new capture"
    key = hashlib.sha256(raw).hexdigest()
    (root / "raw" / key).write_bytes(raw)
    parsed = {"facts": ["synthetic revision" if changed else "synthetic"]}
    monkeypatch.setattr(refresh, "parse_release", lambda *a: parsed)
    saved = {
        "database_ref": "c" * 64,
        "current": {"quarter": "FY2027-Q2"},
        "financial_refresh": {"financial_fingerprint": digest(canonical({"facts": ["synthetic"]}))},
    }
    checks = []
    monkeypatch.setattr(refresh, "verify_publication", lambda *a: checks.append(True))
    article = {
        "url": "https://nvidianews.nvidia.com/news/synthetic",
        "source_hash": key,
        "quarter": "FY2027-Q2",
        "received_at": datetime.now(UTC).isoformat(),
    }
    if changed:
        with pytest.raises(refresh.RefreshBlocked, match="source_revision_requires_review"):
            refresh.rebuild(tmp_path / "unused", tmp_path / "unused-raw", root, article, saved)
    else:
        assert (
            refresh.rebuild(tmp_path / "unused", tmp_path / "unused-raw", root, article, saved)
            is None
        )
    assert checks == [True]

    def corrupt(*a):
        raise refresh.RefreshBlocked("source_integrity")

    monkeypatch.setattr(refresh, "verify_publication", corrupt)
    with pytest.raises(refresh.RefreshBlocked, match="source_integrity"):
        refresh.rebuild(tmp_path / "unused", tmp_path / "unused-raw", root, article, saved)
