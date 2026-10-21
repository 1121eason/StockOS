import pytest

from valuation_engine.ai.q2_source_evidence import filing_bound, release_bound, verify_text

URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581022000036/nvda-20220130.htm"
INDEX = "0001045810 Form 10-K 0001045810-22-000036 nvda-20220130.htm Filing Date\n2022-03-18\nAccepted\n2022-03-17 20:33:34"


def test_acceptance_is_not_silently_treated_as_exact_publication():
    result = filing_bound(INDEX, URL)
    assert result["accepted_at"] == "2022-03-18T00:33:34+00:00"
    assert result["available_upper_bound"] == "2022-03-19T04:00:00+00:00"


@pytest.mark.parametrize(
    "removed", ["0001045810-22-000036", "nvda-20220130.htm", "Accepted", "Filing Date"]
)
def test_missing_or_cross_document_index_fails(removed):
    with pytest.raises(ValueError):
        filing_bound(INDEX.replace(removed, ""), URL)


def test_visible_day_bound_does_not_invent_a_minute():
    result = release_bound(b"<html>August 24, 2022</html>", "2022-08-24T20:20:00+00:00")
    assert result["available_upper_bound"] == "2022-08-25T04:00:00+00:00"
    assert "UNVERIFIED" in result["precision"]


def test_missing_release_day_is_not_filled_from_cached_metadata():
    with pytest.raises(ValueError):
        release_bound(b"<html>No published day</html>", "2022-08-24T20:20:00+00:00")


def test_word_changes_or_missing_blocks_fail():
    doc = {
        "source_document_id": 107,
        "source_hash": "a" * 64,
        "document_type": "SEC primary filing",
    }
    source = b"<body><p>Demand declined while inventory increased across several distribution channels.</p></body>"
    expected = [
        {
            "block_id": "x",
            "text": "Demand increased while inventory increased across several distribution channels.",
        }
    ]
    with pytest.raises(ValueError):
        verify_text(doc, source, expected)
